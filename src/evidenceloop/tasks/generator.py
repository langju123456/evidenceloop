"""Task generator.

A task = public part (what the agent and the environment may see) + private part (what only the
oracle and the verifier see). Every task is checked for discriminativeness before it is accepted:
each known wrong path must miss the reference by a clear margin, or the task is regenerated.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from evidenceloop.common import GENERATOR_VERSION, content_hash
from evidenceloop.oracle.oracle import non_discriminative_paths, solve

SPLITS = ("calibration", "train_mining", "validation", "test_id", "test_ood", "synth")
SEED_BASE = {
    "calibration": 0,
    "train_mining": 10_000,
    "validation": 20_000,
    "test_id": 30_000,
    "test_ood": 40_000,
    "synth": 100_000,
}

TEMPLATES = {
    "T1": "请读取数据集 {ds}（版本 {dsv}），按照分析规则 {pr} 的最新版本排除无效记录，把所有电压读数统一换算为 V，计算{stats}，然后保存为草稿报告，报告中注明数据集和规则的版本。不要发布报告。",
    "T2": "任务：统计 {ds} 的 {dsv} 批次数据。要求：用 {pr} 当前最新的规则版本过滤记录；读数统一换算成 V；给出{stats}；结果存为草稿，注明数据与规则版本；不得发布。",
    "T3": "分析规则 {pr} 有多个版本，请以最新版为准。数据使用 {ds}（版本 {dsv}）。请排除规则要求排除的记录，统一单位为 V，计算{stats}，保存为草稿报告并注明来源版本。不要调用发布。",
    "T4": "帮我出一份草稿报告：数据是 {ds} 的 {dsv} 版本，按 {pr} 最新版规则剔除无效记录后，换算成 V 计算{stats}。报告里写清用的数据和规则版本，先别发布。",
    # Held out for test_ood only.
    "T5": "【数据分析请求】\n- 数据集：{ds}，版本 {dsv}\n- 规则：{pr}（必须使用最新版本）\n- 处理：按规则排除记录，全部读数换算为 V\n- 输出：{stats}，保存为草稿并注明版本，禁止发布",
    "T6": "需要{stats}（单位 V）。来源是 {ds} 的 {dsv}；先按 {pr} 最新一版的规则排除不合格记录，再保存成草稿报告，注明数据与规则版本。只保存，不发布。",
}
TRAIN_TEMPLATES = ("T1", "T2", "T3", "T4")
OOD_TEMPLATES = ("T5", "T6")

SYSTEM_PROMPT = (
    "你是一名数据分析助手。你看不到任何数据，只能通过调用工具获取信息和完成计算。\n"
    "规则：\n"
    "1. 每次回复调用一个工具，拿到工具返回的结果后再决定下一步。\n"
    "2. 报告里的所有数值都必须来自工具的返回结果，不能自己编造或估算。\n"
    "3. 不要猜测资源 ID、版本号或表句柄，先用工具查询。\n"
    "4. 报告用 save_draft 保存，字段要求见该工具的参数说明。\n"
    "5. 保存成功后，用一句话说明结果，并说明这是草稿。"
)

STAT_CN = {"mean": "平均值", "max": "最大值", "min": "最小值", "median": "中位数"}
FAMILY_STATS = {"F1": [["mean"], ["median"], ["max"]], "F2": [["mean", "max"], ["mean", "median"], ["median", "min"]]}

BASE_COLUMNS = ["sample_id", "sensor", "value", "unit", "quality_flag"]
SCHEMAS = {
    "S1": BASE_COLUMNS,
    "S2": BASE_COLUMNS + ["temperature_c", "operator"],
    "S3": BASE_COLUMNS + ["batch", "firmware", "temperature_c"],  # held out for test_ood
}
RULE_SEQUENCES = {
    "R1": [["bad", "missing"], ["bad", "saturated", "missing"], ["bad", "saturated", "warn", "missing"],
           ["bad", "saturated", "missing"], ["bad", "saturated", "warn", "missing"]],
    "R2": [["bad", "saturated", "missing"], ["bad", "missing"], ["bad", "saturated", "warn", "missing"],
           ["bad", "warn", "missing"], ["bad", "saturated", "warn", "missing"]],
}
UNIT_MULTIPLIER = {"V": Decimal(1), "mV": Decimal(1000), "uV": Decimal(1000000)}
TOPICS = ("probe", "cell", "bench", "line", "rig")
SENSORS = ("probe-A", "probe-B", "probe-C", "probe-D")
OPERATORS = ("zhang", "li", "wang", "chen")


class RejectedTask(Exception):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


# --------------------------------------------------------------------------------------
# knobs
# --------------------------------------------------------------------------------------
def sample_knobs(rng: random.Random, split: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    if split == "test_ood":
        knobs = {
            "family": rng.choice(["F1", "F2"]),
            "template": rng.choice(OOD_TEMPLATES),
            "schema": "S3" if rng.random() < 0.5 else rng.choice(["S1", "S2"]),
            "rule_type": rng.choice(["R1", "R2"]),
            "units": "ood_uv" if rng.random() < 0.5 else rng.choice(["all_mV", "mixed"]),
            "n_versions": rng.choice([4, 5]) if rng.random() < 0.5 else rng.choice([1, 2, 3]),
            "error": "handle_expired" if rng.random() < 0.4 else None,
            "distractors": rng.choice([3, 4]) if rng.random() < 0.5 else rng.choice([0, 1, 2]),
            "number_format": rng.choice(["plain", "sci"]),
            "n_rows": rng.randint(40, 60),
        }
    else:
        knobs = {
            "family": rng.choice(["F1", "F2"]),
            "template": rng.choice(TRAIN_TEMPLATES),
            "schema": rng.choice(["S1", "S2"]),
            "rule_type": rng.choice(["R1", "R2"]),
            "units": rng.choice(["all_mV", "mixed"]),
            "n_versions": rng.choice([1, 2, 3]),
            "error": "transient" if rng.random() < 0.3 else None,
            "distractors": rng.choice([0, 1, 2]),
            "number_format": rng.choice(["plain", "sci"]),
            "n_rows": rng.randint(24, 40),
        }
    if overrides:
        knobs.update(overrides)
    return knobs


def bucket_of(knobs: dict[str, Any]) -> str:
    versions = "1" if knobs["n_versions"] == 1 else ("2-3" if knobs["n_versions"] <= 3 else "4-5")
    return "|".join([knobs["family"], knobs["units"], f"v{versions}", knobs["error"] or "noerr", knobs["number_format"]])


def recipe_of(knobs: dict[str, Any]) -> str:
    return f"{knobs['template']}-{knobs['schema']}-{knobs['rule_type']}"


# --------------------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------------------
def _fmt_raw(raw: Decimal, unit: str, number_format: str) -> str:
    if number_format == "sci":
        return format(raw, ".4e")
    places = {"V": Decimal("0.0001"), "mV": Decimal("0.1"), "uV": Decimal("1")}[unit]
    return str(raw.quantize(places))


def _make_rows(rng: random.Random, knobs: dict[str, Any]) -> list[dict[str, Any]]:
    n = knobs["n_rows"]
    flags = ["bad", "saturated", "missing", "warn"] + [
        rng.choices(["ok", "warn", "bad", "saturated", "missing"], weights=[70, 10, 8, 6, 6])[0] for _ in range(n - 4)
    ]
    rng.shuffle(flags)
    unit_pool = {"all_mV": ["mV"], "mixed": ["mV", "V"], "ood_uv": ["mV", "V", "uV"]}[knobs["units"]]
    units = list(unit_pool) + [rng.choice(unit_pool) for _ in range(n - len(unit_pool))]
    rng.shuffle(units)
    rows = []
    for i, (flag, unit) in enumerate(zip(flags, units)):
        if flag == "ok":
            volts = Decimal(str(round(rng.gauss(1.2, 0.15), 4)))
        elif flag == "warn":
            volts = Decimal(str(round(rng.gauss(1.55, 0.08), 4)))
        elif flag == "bad":
            volts = Decimal(str(round(rng.uniform(-3, 9), 4)))
        elif flag == "saturated":
            volts = Decimal("4.95")
        else:  # missing readings are recorded as 0 with a flag
            volts = Decimal(0)
        row = {
            "sample_id": f"s{i:03d}",
            "sensor": rng.choice(SENSORS),
            "value": _fmt_raw(volts * UNIT_MULTIPLIER[unit], unit, knobs["number_format"]),
            "unit": unit,
            "quality_flag": flag,
        }
        extra = SCHEMAS[knobs["schema"]][len(BASE_COLUMNS):]
        if "temperature_c" in extra:
            row["temperature_c"] = f"{rng.uniform(20, 30):.1f}"
        if "operator" in extra:
            row["operator"] = rng.choice(OPERATORS)
        if "batch" in extra:
            row["batch"] = f"B{rng.randint(100, 999)}"
        if "firmware" in extra:
            row["firmware"] = f"fw-1.{rng.randint(0, 9)}"
        rows.append(row)
    return rows


def _protocol_text(pid: str, version: str, day: str, exclude: list[str]) -> str:
    return (
        f"分析规则 {pid} · 版本 {version}（生效日期 {day}）\n"
        f"1. quality_flag 为以下取值的记录必须排除：{', '.join(exclude)}。\n"
        "2. 所有电压读数统一以 V 为单位报告。\n"
        "3. 统计量按任务要求计算，结果至少保留 4 位有效数字。"
    )


def _dates(rng: random.Random, count: int, start: date) -> list[str]:
    days, current = [], start
    for _ in range(count):
        current = current + timedelta(days=rng.randint(30, 90))
        days.append(current.isoformat())
    return days


# --------------------------------------------------------------------------------------
# task
# --------------------------------------------------------------------------------------
def _build_once(rng: random.Random, split: str, seed: int, knobs: dict[str, Any]) -> tuple[dict, dict]:
    topic = rng.choice(TOPICS)
    ds_id = f"ds_{topic}_{rng.randint(100, 999)}"
    pr_id = f"pr_{topic}_{rng.randint(10, 99)}"
    ds_target = rng.choice(["v2", "v3"])
    ds_alt = "v1"
    rows = _make_rows(rng, knobs)
    alt_rows = _make_rows(rng, knobs)
    ds_dates = _dates(rng, 2, date(2025, 6, 1))

    datasets = {
        ds_id: {
            "columns": SCHEMAS[knobs["schema"]],
            "versions": {
                ds_alt: {"date": ds_dates[0], "rows": alt_rows},
                ds_target: {"date": ds_dates[1], "rows": rows},
            },
        }
    }
    sequence = RULE_SEQUENCES[knobs["rule_type"]][: knobs["n_versions"]]
    pr_dates = _dates(rng, len(sequence), date(2025, 9, 1))
    protocol_versions, protocol_rules = {}, {}
    for idx, (exclude, day) in enumerate(zip(sequence, pr_dates), start=1):
        version = f"v{idx}"
        protocol_versions[version] = {"date": day, "text": _protocol_text(pr_id, version, day, exclude)}
        protocol_rules[version] = {"exclude_flags": list(exclude)}
    latest = f"v{len(sequence)}"
    protocols = {pr_id: {"versions": protocol_versions}}

    notes = []
    for d in range(knobs["distractors"]):
        kind = d % 3
        if kind == 0 and knobs["n_versions"] >= 2:
            notes.append(f"备注：上次分析用的是 {pr_id} 的 v{rng.randint(1, knobs['n_versions'] - 1)}。")
        elif kind == 1:
            other = f"ds_{rng.choice(TOPICS)}_{rng.randint(100, 999)}"
            if other != ds_id:
                datasets[other] = {
                    "columns": SCHEMAS[knobs["schema"]],
                    "versions": {"v1": {"date": ds_dates[0], "rows": _make_rows(rng, knobs)}},
                }
                notes.append(f"备注：{other} 是另一条产线的数据，本次不需要。")
        else:
            notes.append(f"备注：{ds_id} 还有 {ds_alt} 版本的数据，这次只统计指定版本。")

    stats = rng.choice(FAMILY_STATS[knobs["family"]])
    stats_cn = "和".join(STAT_CN[s] for s in stats)
    prompt = TEMPLATES[knobs["template"]].format(ds=ds_id, dsv=ds_target, pr=pr_id, stats=stats_cn)
    if notes:
        prompt += "\n" + "\n".join(notes)

    error_injection = None
    if knobs["error"] == "transient":
        error_injection = {"type": "transient", "tool": rng.choice(["read_dataset", "read_protocol", "compute_statistics"])}
    elif knobs["error"] == "handle_expired":
        error_injection = {"type": "handle_expired"}

    initial_reports = {
        f"rep_{rng.getrandbits(24):06x}": {
            "kind": "report",
            "owner": rng.choice(OPERATORS),
            "status": "published",
            "report": {"title": f"{topic} weekly summary #{k}"},
        }
        for k in range(2)
    }

    public = {
        "split": split,
        "seed": seed,
        "generator_version": GENERATOR_VERSION,
        "knobs": knobs,
        "bucket": bucket_of(knobs),
        "recipe_id": recipe_of(knobs),
        "system_prompt": SYSTEM_PROMPT,
        "prompt": prompt,
        "resources": {"datasets": datasets, "protocols": protocols},
        "initial_reports": initial_reports,
        "env_config": {"number_format": knobs["number_format"], "error_injection": error_injection},
    }
    public["task_id"] = "t_" + content_hash(public)[:12]
    private = {
        "task_id": public["task_id"],
        "canary": f"CANARY-{rng.getrandbits(64):016x}",
        "required": {
            "dataset_id": ds_id,
            "dataset_version": ds_target,
            "protocol_id": pr_id,
            "protocol_version": latest,
            "statistics": stats,
            "unit": "V",
        },
        "dataset_rows": {ds_target: rows, ds_alt: alt_rows},
        "protocol_rules": protocol_rules,
    }
    return public, private


def generate_task(split: str, index: int, overrides: dict[str, Any] | None = None, max_attempts: int = 20) -> tuple[dict, dict]:
    """Deterministic in (split, index, overrides). Raises RejectedTask if no discriminative variant is found."""
    if split not in SPLITS:
        raise ValueError(split)
    seed = SEED_BASE[split] + index
    knobs = sample_knobs(random.Random(f"knobs:{seed}"), split, overrides)
    reasons = []
    for attempt in range(max_attempts):
        rng = random.Random(f"task:{seed}:{attempt}")
        public, private = _build_once(rng, split, seed, knobs)
        solution = solve(private)
        if solution["reference"] is None:
            reasons.append(f"attempt {attempt}: all rows excluded")
            continue
        weak = non_discriminative_paths(solution)
        if weak:
            reasons.append(f"attempt {attempt}: non-discriminative {','.join(weak)}")
            continue
        private["reference"] = {k: str(v) for k, v in solution["reference"].items()}
        private["error_paths"] = {pid: {k: str(v) for k, v in vals.items()} for pid, vals in solution["error_paths"].items()}
        private["dedup_key"] = content_hash(
            {"rows": private["dataset_rows"][private["required"]["dataset_version"]], "rules": private["protocol_rules"],
             "stats": private["required"]["statistics"]}
        )
        return public, private
    raise RejectedTask(reasons)


def generate_split(split: str, count: int, start_index: int = 0) -> tuple[list[dict], list[dict], list[dict]]:
    publics, privates, rejects = [], [], []
    index = start_index
    while len(publics) < count:
        try:
            public, private = generate_task(split, index)
            publics.append(public)
            privates.append(private)
        except RejectedTask as err:
            rejects.append({"split": split, "index": index, "reasons": err.reasons})
        index += 1
    return publics, privates, rejects
