"""The executable environment the agent works in.

Eight tools. The task oracle is never passed in here: the environment only sees the public
part of a task, so nothing a tool returns can leak the reference answer.
"""

from __future__ import annotations

import copy
import random
import statistics
from decimal import Decimal
from typing import Any

from evidenceloop.common import canonical_json, fmt_number, to_decimal

# Tool-side conversion factors (to volts). The oracle uses its own, separately written table.
_TO_VOLTS = {"V": Decimal("1"), "mV": Decimal("0.001"), "uV": Decimal("0.000001")}
_ALLOWED_STATS = ("mean", "max", "min", "median")
_PRED_OPS = ("eq", "ne", "in", "not_in", "lt", "le", "gt", "ge", "is_null", "not_null")

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "list_versions": {
        "description": "列出某个数据集或分析规则的所有版本及生效日期。",
        "properties": {"resource_id": {"type": "string", "description": "数据集或规则的 ID"}},
        "required": ["resource_id"],
    },
    "read_dataset": {
        "description": "读取指定版本的数据集，返回表句柄、列名、行数、单位种类和前 5 行预览。",
        "properties": {
            "dataset_id": {"type": "string"},
            "version": {"type": "string"},
        },
        "required": ["dataset_id", "version"],
    },
    "read_protocol": {
        "description": "读取指定版本的分析规则全文。",
        "properties": {
            "protocol_id": {"type": "string"},
            "version": {"type": "string"},
        },
        "required": ["protocol_id", "version"],
    },
    "filter_rows": {
        "description": (
            "按结构化条件筛选表，返回新的表句柄。predicate 形如 "
            '{"all": [{"column": "quality_flag", "op": "not_in", "value": ["bad"]}]}，'
            "op 可用 eq、ne、in、not_in、lt、le、gt、ge、is_null、not_null，组合用 all 或 any。"
        ),
        "properties": {
            "table_ref": {"type": "string"},
            "predicate": {"type": "object"},
        },
        "required": ["table_ref", "predicate"],
    },
    "convert_units": {
        "description": "把 unit 列等于 from_unit 的行换算为 to_unit，返回新的表句柄。支持 V、mV、uV。",
        "properties": {
            "table_ref": {"type": "string"},
            "column": {"type": "string"},
            "from_unit": {"type": "string"},
            "to_unit": {"type": "string"},
        },
        "required": ["table_ref", "column", "from_unit", "to_unit"],
    },
    "compute_statistics": {
        "description": "对表中某一数值列计算统计量。statistics 可选 mean、max、min、median。不检查单位是否一致。",
        "properties": {
            "table_ref": {"type": "string"},
            "column": {"type": "string"},
            "statistics": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["table_ref", "column", "statistics"],
    },
    "save_draft": {
        "description": "把报告保存为草稿。相同 draft_key 会覆盖原草稿，不同 draft_key 会新建草稿。",
        "properties": {
            "report": {
                "type": "object",
                "description": "草稿报告",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "statistic": {"type": "string", "enum": ["mean", "max", "min", "median"]},
                                "value": {"type": "number", "description": "取自 compute_statistics 的返回结果"},
                                "unit": {"type": "string"},
                            },
                            "required": ["statistic", "value", "unit"],
                        },
                    },
                    "dataset": {"type": "object", "properties": {"id": {"type": "string"}, "version": {"type": "string"}},
                                "required": ["id", "version"]},
                    "protocol": {"type": "object", "properties": {"id": {"type": "string"}, "version": {"type": "string"}},
                                 "required": ["id", "version"]},
                    "notes": {"type": "string"},
                },
                "required": ["results", "dataset", "protocol"],
            },
            "draft_key": {"type": "string", "description": "可选。相同 key 覆盖原草稿；不填时默认为 main"},
        },
        "required": ["report"],
    },
    "publish_report": {
        "description": "把草稿发布为正式报告。",
        "properties": {"draft_id": {"type": "string"}},
        "required": ["draft_id"],
    },
}

_PY_TYPES = {"string": str, "object": dict, "array": list}


def tool_schemas() -> list[dict[str, Any]]:
    """Tool definitions in the function-calling format chat templates expect."""
    schemas = []
    for name, spec in TOOL_SPECS.items():
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": spec["description"],
                    "parameters": {
                        "type": "object",
                        "properties": spec["properties"],
                        "required": spec["required"],
                    },
                },
            }
        )
    return schemas


class ToolError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_observation(self) -> dict[str, Any]:
        obs: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.retryable:
            obs["retryable"] = True
        return obs


def validate_arguments(name: str, args: Any) -> None:
    if name not in TOOL_SPECS:
        raise ToolError("unknown_tool", f"没有名为 {name} 的工具")
    if not isinstance(args, dict):
        raise ToolError("invalid_arguments", "arguments 必须是 JSON 对象")
    spec = TOOL_SPECS[name]
    missing = [key for key in spec["required"] if key not in args]
    if missing:
        raise ToolError("invalid_arguments", f"缺少参数：{', '.join(missing)}")
    extra = [key for key in args if key not in spec["properties"]]
    if extra:
        raise ToolError("invalid_arguments", f"未知参数：{', '.join(extra)}")
    for key, prop in spec["properties"].items():
        if key in args and not isinstance(args[key], _PY_TYPES[prop["type"]]):
            raise ToolError("invalid_arguments", f"参数 {key} 的类型应为 {prop['type']}")


def _cell_is_null(cell: Any) -> bool:
    return cell is None or (isinstance(cell, str) and cell.strip() == "")


def _eval_predicate(pred: Any, row: dict[str, Any]) -> bool:
    if not isinstance(pred, dict):
        raise ToolError("invalid_predicate", "predicate 必须是对象")
    if "all" in pred or "any" in pred:
        key = "all" if "all" in pred else "any"
        if set(pred) != {key} or not isinstance(pred[key], list) or not pred[key]:
            raise ToolError("invalid_predicate", f"{key} 必须是非空列表，且不能和其他键混用")
        results = [_eval_predicate(item, row) for item in pred[key]]
        return all(results) if key == "all" else any(results)
    if "column" not in pred or "op" not in pred:
        raise ToolError("invalid_predicate", "条件必须包含 column 和 op")
    column, op = pred["column"], pred["op"]
    if op not in _PRED_OPS:
        raise ToolError("invalid_predicate", f"不支持的 op：{op}")
    if column not in row:
        raise ToolError("invalid_predicate", f"表中没有列 {column}")
    cell = row[column]
    if op == "is_null":
        return _cell_is_null(cell)
    if op == "not_null":
        return not _cell_is_null(cell)
    if "value" not in pred:
        raise ToolError("invalid_predicate", f"op {op} 需要 value")
    target = pred["value"]
    if op in ("in", "not_in"):
        if not isinstance(target, list):
            raise ToolError("invalid_predicate", f"op {op} 的 value 必须是列表")
        hit = cell in target
        return hit if op == "in" else not hit
    if op in ("eq", "ne"):
        hit = cell == target
        return hit if op == "eq" else not hit
    try:
        left, right = to_decimal(cell), to_decimal(target)
    except ValueError as exc:
        raise ToolError("invalid_predicate", f"op {op} 只能用于数值：{exc}") from exc
    return {"lt": left < right, "le": left <= right, "gt": left > right, "ge": left >= right}[op]


class Environment:
    """One episode. Holds the resources, the table handles and the report store."""

    def __init__(self, task_public: dict[str, Any], episode_seed: int):
        self.task_id: str = task_public["task_id"]
        self.datasets = copy.deepcopy(task_public["resources"]["datasets"])
        self.protocols = copy.deepcopy(task_public["resources"]["protocols"])
        self.reports: dict[str, dict[str, Any]] = copy.deepcopy(task_public["initial_reports"])
        self.config: dict[str, Any] = task_public["env_config"]
        self.number_format: str = self.config.get("number_format", "plain")
        self.rng = random.Random(episode_seed)
        self.tables: dict[str, dict[str, Any]] = {}
        self.step = 0
        self.call_log: list[dict[str, Any]] = []
        self._transient_used = False
        self._expire_target: str | None = None

    # ----- snapshots -------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        return {"reports": copy.deepcopy(self.reports)}

    # ----- dispatch --------------------------------------------------------------------
    def call(self, name: str, args: Any) -> dict[str, Any]:
        self.step += 1
        try:
            validate_arguments(name, args)
            self._maybe_inject_transient(name)
            result = getattr(self, f"_tool_{name}")(**args)
            status = "ok"
        except ToolError as err:
            result = err.to_observation()
            status = "error"
        self.call_log.append({"step": self.step, "tool": name, "args": args, "status": status})
        return result

    def _maybe_inject_transient(self, name: str) -> None:
        inject = self.config.get("error_injection") or {}
        if inject.get("type") == "transient" and inject.get("tool") == name and not self._transient_used:
            self._transient_used = True
            raise ToolError("temporary_unavailable", "服务暂时不可用，请稍后重试", retryable=True)

    def _new_handle(self, rows: list[dict[str, Any]], columns: list[str], derived: bool = False) -> str:
        while True:
            handle = f"tbl_{self.rng.getrandbits(16):04x}"
            if handle not in self.tables:
                break
        self.tables[handle] = {"rows": rows, "columns": columns, "created_step": self.step}
        inject = self.config.get("error_injection") or {}
        # handle_expired injection: the first derived table expires before it can be used.
        if derived and inject.get("type") == "handle_expired" and self._expire_target is None:
            self._expire_target = handle
        return handle

    def _get_table(self, handle: str) -> dict[str, Any]:
        if handle not in self.tables:
            raise ToolError("unknown_table_ref", f"没有表句柄 {handle}")
        if handle == self._expire_target:
            raise ToolError("handle_expired", "该表句柄已过期，请重新读取数据集后重做后续步骤", retryable=True)
        return self.tables[handle]

    # ----- tools -----------------------------------------------------------------------
    def _tool_list_versions(self, resource_id: str) -> dict[str, Any]:
        source = self.datasets.get(resource_id) or self.protocols.get(resource_id)
        if source is None:
            raise ToolError("not_found", f"找不到资源 {resource_id}")
        versions = sorted(
            ({"version": ver, "effective_date": meta["date"]} for ver, meta in source["versions"].items()),
            key=lambda item: item["effective_date"],
        )
        return {"resource_id": resource_id, "versions": versions}

    def _tool_read_dataset(self, dataset_id: str, version: str) -> dict[str, Any]:
        dataset = self.datasets.get(dataset_id)
        if dataset is None:
            raise ToolError("not_found", f"找不到数据集 {dataset_id}")
        if version not in dataset["versions"]:
            raise ToolError("not_found", f"数据集 {dataset_id} 没有版本 {version}")
        rows = copy.deepcopy(dataset["versions"][version]["rows"])
        columns = list(dataset["columns"])
        handle = self._new_handle(rows, columns)
        return {
            "table_ref": handle,
            "dataset_id": dataset_id,
            "version": version,
            "columns": columns,
            "row_count": len(rows),
            "distinct_units": sorted({row["unit"] for row in rows}),
            "preview": rows[:5],
        }

    def _tool_read_protocol(self, protocol_id: str, version: str) -> dict[str, Any]:
        protocol = self.protocols.get(protocol_id)
        if protocol is None:
            raise ToolError("not_found", f"找不到分析规则 {protocol_id}")
        if version not in protocol["versions"]:
            raise ToolError("not_found", f"分析规则 {protocol_id} 没有版本 {version}")
        meta = protocol["versions"][version]
        return {"protocol_id": protocol_id, "version": version, "effective_date": meta["date"], "text": meta["text"]}

    def _tool_filter_rows(self, table_ref: str, predicate: dict[str, Any]) -> dict[str, Any]:
        table = self._get_table(table_ref)
        kept = [copy.deepcopy(row) for row in table["rows"] if _eval_predicate(predicate, row)]
        handle = self._new_handle(kept, table["columns"], derived=True)
        return {"table_ref": handle, "row_count": len(kept)}

    def _tool_convert_units(self, table_ref: str, column: str, from_unit: str, to_unit: str) -> dict[str, Any]:
        table = self._get_table(table_ref)
        if from_unit not in _TO_VOLTS or to_unit not in _TO_VOLTS:
            raise ToolError("invalid_unit", f"只支持 {', '.join(_TO_VOLTS)}")
        if column not in table["columns"] or column == "unit":
            raise ToolError("invalid_column", f"列 {column} 不能换算")
        factor = _TO_VOLTS[from_unit] / _TO_VOLTS[to_unit]
        rows, converted = [], 0
        for row in table["rows"]:
            new_row = copy.deepcopy(row)
            if row["unit"] == from_unit:
                try:
                    value = to_decimal(row[column])
                except ValueError as exc:
                    raise ToolError("invalid_value", f"无法换算：{exc}") from exc
                new_row[column] = str(value * factor)
                new_row["unit"] = to_unit
                converted += 1
            rows.append(new_row)
        handle = self._new_handle(rows, table["columns"], derived=True)
        return {"table_ref": handle, "converted_rows": converted}

    def _tool_compute_statistics(self, table_ref: str, column: str, statistics: list[Any]) -> dict[str, Any]:
        table = self._get_table(table_ref)
        if not statistics or any(stat not in _ALLOWED_STATS for stat in statistics):
            raise ToolError("invalid_statistics", f"statistics 只能取 {', '.join(_ALLOWED_STATS)}")
        if column not in table["columns"]:
            raise ToolError("invalid_column", f"表中没有列 {column}")
        if not table["rows"]:
            raise ToolError("empty_table", "表为空，无法计算")
        try:
            values = [to_decimal(row[column]) for row in table["rows"]]
        except ValueError as exc:
            raise ToolError("invalid_value", f"列 {column} 含有非数值：{exc}") from exc
        funcs = {"mean": statistics_mean, "max": max, "min": min, "median": statistics_median}
        results = {stat: fmt_number(funcs[stat](values), self.number_format) for stat in statistics}
        return {"table_ref": table_ref, "column": column, "n": len(values), "results": results}

    def _tool_save_draft(self, report: dict[str, Any], draft_key: str = "main") -> dict[str, Any]:
        _validate_report(report)
        existing = next(
            (rid for rid, rec in self.reports.items() if rec.get("task_id") == self.task_id and rec.get("draft_key") == draft_key),
            None,
        )
        draft_id = existing or f"draft_{self.rng.getrandbits(24):06x}"
        self.reports[draft_id] = {
            "kind": "draft",
            "task_id": self.task_id,
            "draft_key": draft_key,
            "status": "draft",
            "report": copy.deepcopy(report),
            "saved_at_step": self.step,
        }
        return {"draft_id": draft_id, "status": "draft", "overwritten": existing is not None}

    def _tool_publish_report(self, draft_id: str) -> dict[str, Any]:
        record = self.reports.get(draft_id)
        if record is None:
            raise ToolError("not_found", f"找不到草稿 {draft_id}")
        record["status"] = "published"
        record["published_at_step"] = self.step
        return {"draft_id": draft_id, "status": "published"}


def statistics_mean(values: list[Decimal]) -> Decimal:
    return statistics.mean(values)


def statistics_median(values: list[Decimal]) -> Decimal:
    return statistics.median(values)


def _validate_report(report: Any) -> None:
    if not isinstance(report, dict):
        raise ToolError("invalid_report", "report 必须是对象")
    allowed = {"results", "dataset", "protocol", "notes"}
    extra = set(report) - allowed
    if extra:
        raise ToolError("invalid_report", f"report 含有未知字段：{', '.join(sorted(extra))}")
    results = report.get("results")
    if not isinstance(results, list) or not results:
        raise ToolError("invalid_report", "results 必须是非空列表")
    for item in results:
        if not isinstance(item, dict) or set(item) != {"statistic", "value", "unit"}:
            raise ToolError("invalid_report", "results 的每一项必须恰好包含 statistic、value、unit")
        try:
            to_decimal(item["value"])
        except ValueError as exc:
            raise ToolError("invalid_report", f"value 不是数值：{exc}") from exc
    for key in ("dataset", "protocol"):
        ref = report.get(key)
        if not isinstance(ref, dict) or set(ref) != {"id", "version"}:
            raise ToolError("invalid_report", f"{key} 必须是 {{\"id\", \"version\"}}")
    if "notes" in report and not isinstance(report["notes"], str):
        raise ToolError("invalid_report", "notes 必须是字符串")


def observation_text(observation: dict[str, Any]) -> str:
    return canonical_json(observation)
