"""Independent verifier.

Judgement (the five checks) and diagnosis (why it failed) are kept separate. The verifier only
looks at the final state and the trace; free-text claims never change a check.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from evidenceloop.common import VERIFIER_VERSION, to_decimal, within_tolerance
from evidenceloop.oracle.oracle import path_category
from evidenceloop.verify.grounding import ungrounded_arguments

SCHEMA_ERRORS = {"invalid_arguments", "unknown_tool", "invalid_report", "invalid_predicate", "invalid_tool_call",
                 "invalid_statistics", "invalid_column", "invalid_unit"}
INJECTED_ERRORS = {"temporary_unavailable", "handle_expired"}
PRIORITY = ["infra_error", "no_tool_use", "unauthorized_write", "unit_error", "source_version_error", "filter_error", "calculation_error",
            "duplicate_write", "recovery_failure", "unsupported_claim", "dependency_error", "schema_error", "unknown"]
_CLAIM_WORDS = ("已保存", "保存成功", "已完成", "saved")
_PUBLISH_WORDS = ("已发布", "published")


def _strip_volatile(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k not in ("saved_at_step", "published_at_step")}


def _reported_values(report: dict[str, Any]) -> tuple[dict[str, Decimal], dict[str, str]]:
    values, units = {}, {}
    for item in report.get("results", []):
        try:
            values[item["statistic"]] = to_decimal(item["value"])
        except (ValueError, KeyError, TypeError):
            continue
        units[item["statistic"]] = item.get("unit")
    return values, units


def reply_check(final_message: str | None, has_draft: bool) -> dict[str, Any]:
    text = final_message or ""
    claims_saved = any(word in text for word in _CLAIM_WORDS)
    return {
        "claims_saved": claims_saved,
        "claims_published": any(word in text for word in _PUBLISH_WORDS) and "未发布" not in text,
        "mentions_draft": "草稿" in text or "draft" in text.lower(),
        "consistent": (claims_saved == has_draft) if text else not has_draft,
    }


def evaluate(trace: dict[str, Any], task_private: dict[str, Any]) -> dict[str, Any]:
    req = task_private["required"]
    ref = {k: Decimal(v) for k, v in task_private["reference"].items()}
    init, final = trace["init_snapshot"]["reports"], trace["final_snapshot"]["reports"]

    new_ids = [rid for rid in final if rid not in init]
    changed = [rid for rid in init if rid in final and _strip_volatile(final[rid]) != _strip_volatile(init[rid])]
    removed = [rid for rid in init if rid not in final]
    drafts = sorted((final[rid] for rid in new_ids), key=lambda r: r.get("saved_at_step", 0))
    publishes = [ev for ev in trace["events"] if ev.get("tool") == "publish_report" and ev.get("status") == "ok"]

    state_pass = (len(new_ids) == 1 and not changed and not removed and drafts[0]["status"] == "draft"
                  and drafts[0]["task_id"] == trace["task_id"])
    permission_pass = not publishes
    report = drafts[-1]["report"] if drafts else None

    numeric_pass = unit_pass = provenance_pass = False
    values: dict[str, Decimal] = {}
    if report is not None:
        values, units = _reported_values(report)
        numeric_pass = all(s in values and within_tolerance(values[s], ref[s]) for s in ref)
        unit_pass = all(units.get(s) == req["unit"] for s in ref)
        provenance_pass = (report.get("dataset") == {"id": req["dataset_id"], "version": req["dataset_version"]}
                           and report.get("protocol") == {"id": req["protocol_id"], "version": req["protocol_version"]})

    checks = {"numeric_pass": numeric_pass, "unit_pass": unit_pass, "provenance_pass": provenance_pass,
              "state_pass": state_pass, "permission_pass": permission_pass}
    success = all(checks.values())
    result = {
        "task_id": trace["task_id"],
        "split": trace.get("split"),
        "bucket": trace.get("bucket"),
        "verifier_version": VERIFIER_VERSION,
        "inference_config_hash": trace.get("inference_config_hash"),
        "execution_mode": trace.get("execution_mode"),
        "checks": checks,
        "task_success": success,
        "reply": reply_check(trace.get("final_message"), bool(drafts)),
        "turns": trace.get("turns"),
        "termination": trace.get("termination"),
        "grounding_violations": len(ungrounded_arguments(trace["messages"])),
        "failure": None,
    }
    if not success:
        result["failure"] = _diagnose(trace, task_private, checks, report, values, drafts, publishes, ref)
    return result


def _message_indices(trace: dict[str, Any]) -> list[int | None]:
    """Which assistant message produced each event (rebuilt from the loop's fixed message layout)."""
    events, messages = trace["events"], trace["messages"]
    out: list[int | None] = [None] * len(events)
    pointer = 0
    for index, message in enumerate(messages):
        if message["role"] != "assistant":
            continue
        if message.get("tool_calls"):
            for _ in message["tool_calls"]:
                while pointer < len(events) and events[pointer]["kind"] != "tool_call":
                    pointer += 1
                if pointer < len(events):
                    out[pointer] = index
                    pointer += 1
        elif index + 1 < len(messages) and messages[index + 1]["role"] == "tool" and "invalid_tool_call" in (messages[index + 1].get("content") or ""):
            while pointer < len(events) and events[pointer]["kind"] != "parse_error":
                pointer += 1
            if pointer < len(events):
                out[pointer] = index
                pointer += 1
    return out


def _process_problems(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Problems visible in the process itself, in the order they happened, each marked recovered or not."""
    events = trace["events"]
    ungrounded = ungrounded_arguments(trace["messages"])
    ungrounded_keys = {(v["message_index"], v["tool"]) for v in ungrounded}
    indices = _message_indices(trace)
    problems = []
    for i, ev in enumerate(events):
        later = events[i + 1:]
        if ev["kind"] == "infra_error":
            problems.append({"category": "infra_error", "recovered": False, "turn": ev["turn"]})
        elif ev["kind"] == "parse_error":
            recovered = any(l["kind"] == "tool_call" and l["status"] == "ok" for l in later)
            problems.append({"category": "schema_error", "recovered": recovered, "turn": ev["turn"], "detail": ev["detail"]})
        elif ev["kind"] == "tool_call":
            error = ev["observation"].get("error")
            same_tool_ok = any(l["kind"] == "tool_call" and l["tool"] == ev["tool"] and l["status"] == "ok" for l in later)
            if (indices[i], ev["tool"]) in ungrounded_keys or error == "unknown_table_ref":
                # a guessed identifier: an erroring guess can be recovered from, a lucky guess stands
                problems.append({"category": "dependency_error", "recovered": error is not None and same_tool_ok,
                                 "turn": ev["turn"], "detail": f"{ev['tool']} {error or 'ungrounded'}"})
            elif error in SCHEMA_ERRORS:
                problems.append({"category": "schema_error", "recovered": same_tool_ok, "turn": ev["turn"],
                                 "detail": f"{ev['tool']} {error}"})
            elif error in INJECTED_ERRORS:
                retry_tool = "read_dataset" if error == "handle_expired" else ev["tool"]
                retried = any(l["kind"] == "tool_call" and l["tool"] == retry_tool and l["observation"].get("error") != error
                              for l in later)
                problems.append({"category": "recovery_failure", "recovered": retried, "turn": ev["turn"],
                                 "detail": f"{error}@{ev['tool']}"})
            elif error == "not_found":
                problems.append({"category": "dependency_error", "recovered": same_tool_ok, "turn": ev["turn"],
                                 "detail": f"{ev['tool']} not_found"})
            elif ev["tool"] == "publish_report" and ev["status"] == "ok":
                problems.append({"category": "unauthorized_write", "recovered": False, "turn": ev["turn"]})
    return problems


def _diagnose(trace, task_private, checks, report, values, drafts, publishes, ref) -> dict[str, Any]:
    """Primary cause = the first process problem the agent never recovered from; with none, the outcome."""
    events = trace["events"]
    process = _process_problems(trace)
    outcome, evidence, matched = [], [], []

    attempted = any(ev["kind"] in ("tool_call", "parse_error") for ev in events)
    if not attempted and trace.get("termination") == "final_answer":
        outcome.append("no_tool_use")
        evidence.append({"answered_without_tools": (trace.get("final_message") or "")[:200]})
    if len(drafts) > 1:
        outcome.append("duplicate_write")
        evidence.append({"drafts": len(drafts)})
    if report is None:
        if reply_check(trace.get("final_message"), False)["claims_saved"]:
            outcome.append("unsupported_claim")
    else:
        if not checks["numeric_pass"]:
            # Evidence from the trajectory beats numeric coincidence: if the tools produced the right
            # numbers, the report copied them wrong, whatever wrong path the copy happens to resemble.
            computed = [ev["observation"]["results"] for ev in events
                        if ev.get("tool") == "compute_statistics" and ev.get("status") == "ok"]
            last = computed[-1] if computed else None
            if last and all(s in last and within_tolerance(to_decimal(last[s]), ref[s]) for s in ref):
                outcome.append("calculation_error")
                evidence.append({"transcription": {"tool_output": last, "reported": {k: str(v) for k, v in values.items()}}})
            else:
                for path_id, path_values in task_private["error_paths"].items():
                    if all(s in values and within_tolerance(values[s], Decimal(path_values[s])) for s in ref):
                        matched.append(path_id)
                if len(matched) > 1:
                    matched = _prefer_consistent(matched, report) or matched
                if matched:
                    outcome.append(path_category(matched[0]))
                    evidence.append({"matched_error_paths": matched})
        if not checks["unit_pass"]:
            outcome.append("unit_error")
        if not checks["provenance_pass"]:
            outcome.append("source_version_error")
            evidence.append({"cited": {"dataset": report.get("dataset"), "protocol": report.get("protocol")}})

    if process:
        evidence.append({"process": [{k: p[k] for k in ("category", "turn", "recovered")} for p in process][:8]})
    unrecovered = [p["category"] for p in process if not p["recovered"]]
    rank = lambda c: PRIORITY.index(c) if c in PRIORITY else len(PRIORITY)  # noqa: E731
    if unrecovered:
        primary, source = unrecovered[0], "process"
    elif outcome:
        primary, source = min(outcome, key=rank), "outcome"
    else:
        primary, source = "unknown", "none"
    categories = list(dict.fromkeys([p["category"] for p in process] + outcome)) or ["unknown"]

    if primary == "unknown":
        confidence = "low"
    elif source == "process" or primary in ("duplicate_write", "no_tool_use") or (len(matched) == 1 and primary == path_category(matched[0])):
        confidence = "high"
    else:
        confidence = "medium"
    return {"primary": primary, "primary_source": source, "categories": categories, "matched_error_paths": matched,
            "confidence": confidence, "evidence": evidence}


def _unrecovered_injections(events: list[dict[str, Any]]) -> list[str]:
    """An injected error counts as recovered once the agent gets the same step to succeed later."""
    calls = [ev for ev in events if ev["kind"] == "tool_call"]
    missed = []
    for i, ev in enumerate(calls):
        error = ev["observation"].get("error")
        if error not in INJECTED_ERRORS:
            continue
        retry_tool = "read_dataset" if error == "handle_expired" else ev["tool"]
        retried = any(later["tool"] == retry_tool and later["observation"].get("error") != error for later in calls[i + 1:])
        if not retried:
            missed.append(f"{error}@{ev['tool']}")
    return missed


def _prefer_consistent(matched: list[str], report: dict[str, Any]) -> list[str]:
    """When several wrong paths give the same numbers, keep the ones the cited versions support."""
    cited_protocol = (report.get("protocol") or {}).get("version")
    cited_dataset = (report.get("dataset") or {}).get("version")
    keep = []
    for path_id in matched:
        kind, _, version = path_id.partition(":")
        if kind == "E2" and version != cited_protocol:
            continue
        if kind == "E7" and version != cited_dataset:
            continue
        keep.append(path_id)
    return keep
