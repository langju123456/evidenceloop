"""Independent reference implementation.

Deliberately shares no code with the tools: its own unit table, its own statistics, its own
row handling. If a tool has a bug, the oracle disagrees with it instead of repeating it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from evidenceloop.common import DISCRIMINATIVE_MARGIN, within_tolerance

# Divide a raw reading by this to get volts.
_DIVISOR_TO_VOLTS = {"V": Decimal(1), "mV": Decimal(1000), "uV": Decimal(1000000)}

# Which diagnosis category each error path implies.
PATH_CATEGORY = {
    "E1": "filter_error",  # no exclusion at all
    "E2": "source_version_error",  # an older protocol version's exclusions
    "E3": "unit_error",  # no conversion
    "E4": "unit_error",  # only one of several non-V units converted
    "E5": "unit_error",  # converted in the wrong direction (V rows to mV)
    "E6": "filter_error",  # excluded invalid flags but kept missing rows
    "E7": "source_version_error",  # wrong dataset version
}


def _reading(row: dict[str, Any]) -> Decimal:
    return Decimal(str(row["value"]).strip())


def _values(rows: list[dict[str, Any]], exclude: set[str], mode: str, only_unit: str | None = None) -> list[Decimal]:
    out = []
    for row in rows:
        if row["quality_flag"] in exclude:
            continue
        raw, unit = _reading(row), row["unit"]
        if mode == "full":
            out.append(raw / _DIVISOR_TO_VOLTS[unit])
        elif mode == "none":
            out.append(raw)
        elif mode == "partial":
            out.append(raw / _DIVISOR_TO_VOLTS[unit] if unit == only_unit else raw)
        elif mode == "reverse":
            out.append(raw * 1000 if unit == "V" else raw)
        else:
            raise ValueError(mode)
    return out


def _stats(values: list[Decimal], names: list[str]) -> dict[str, Decimal] | None:
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)
    total = Decimal(0)
    for value in ordered:
        total += value
    out: dict[str, Decimal] = {}
    for name in names:
        if name == "mean":
            out[name] = total / count
        elif name == "max":
            out[name] = ordered[-1]
        elif name == "min":
            out[name] = ordered[0]
        elif name == "median":
            mid = count // 2
            out[name] = ordered[mid] if count % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        else:
            raise ValueError(name)
    return out


def solve(task_private: dict[str, Any]) -> dict[str, Any]:
    """Reference answer plus the answer each known wrong path would give."""
    req = task_private["required"]
    stats = req["statistics"]
    rows = task_private["dataset_rows"][req["dataset_version"]]
    rules = task_private["protocol_rules"]
    latest = req["protocol_version"]
    exclude = set(rules[latest]["exclude_flags"])
    units = {row["unit"] for row in rows}
    non_v = sorted(units - {"V"})

    reference = _stats(_values(rows, exclude, "full"), stats)
    paths: dict[str, dict[str, Decimal] | None] = {"E1": _stats(_values(rows, set(), "full"), stats)}
    for version, rule in rules.items():
        if version != latest and set(rule["exclude_flags"]) != exclude:
            paths[f"E2:{version}"] = _stats(_values(rows, set(rule["exclude_flags"]), "full"), stats)
    if non_v:
        paths["E3"] = _stats(_values(rows, exclude, "none"), stats)
    if len(non_v) >= 2:
        for unit in non_v:
            paths[f"E4:{unit}"] = _stats(_values(rows, exclude, "partial", only_unit=unit), stats)
    if non_v and "V" in units:
        paths["E5"] = _stats(_values(rows, exclude, "reverse"), stats)
    if "missing" in exclude and any(row["quality_flag"] == "missing" for row in rows):
        paths["E6"] = _stats(_values(rows, exclude - {"missing"}, "full"), stats)
    for version, other_rows in task_private["dataset_rows"].items():
        if version != req["dataset_version"]:
            paths[f"E7:{version}"] = _stats(_values(other_rows, exclude, "full"), stats)
    return {"reference": reference, "error_paths": {k: v for k, v in paths.items() if v is not None}}


def path_category(path_id: str) -> str:
    return PATH_CATEGORY[path_id.split(":")[0]]


def non_discriminative_paths(solution: dict[str, Any]) -> list[str]:
    """Error paths whose answer lands too close to the reference on every statistic."""
    ref = solution["reference"]
    bad = []
    for path_id, values in solution["error_paths"].items():
        if all(within_tolerance(values[name], ref[name], DISCRIMINATIVE_MARGIN) for name in ref):
            bad.append(path_id)
    return bad
