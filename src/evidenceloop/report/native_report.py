"""Native, offline evaluation of ForgeFlow's typed annual-report exports.

This module deliberately does not import ForgeFlow or EvidenceLoop's simulator
verifier.  It stores immutable JSONL observations, evaluates them from a
source-linked casebank, and keeps every non-accepted input as raw provenance.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

TRACE_SCHEMA = "forgeflow.report.trace.v1"
EXPORT_SCHEMA = "forgeflow.research.export.v1"
RESULT_SCHEMA = "forgeflow.report.tool-result.v1"
NATIVE_SCHEMA = "evidenceloop.native-report.v1"
_PLUGINS: dict[str, Callable[[dict[str, Any]], dict[str, str]]] = {}


@contextmanager
def _store_lock(store: Path):
    """Serialize the read/dedupe/append critical section across processes."""
    import fcntl
    store.mkdir(parents=True, exist_ok=True)
    with (store / ".native-import.lock").open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plugin(evaluator_id: str):
    """Register trusted in-process evaluator code; no dynamic plugin loading."""
    def register(fn):
        if evaluator_id in _PLUGINS:
            raise ValueError(f"duplicate native evaluator {evaluator_id}")
        _PLUGINS[evaluator_id] = fn
        return fn
    return register


def plugin_descriptor(evaluator_id: str) -> dict[str, str]:
    # Plugins share this module's parsing/arithmetic helpers, so a function-only
    # hash would mislabel a changed evaluator implementation as the same one.
    if evaluator_id not in _PLUGINS:
        raise KeyError(evaluator_id)
    return {"evaluator_id": evaluator_id, "version": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    whole = path.read_text(encoding="utf-8")
    try:
        document = json.loads(whole)
    except json.JSONDecodeError:
        document = None
    if isinstance(document, dict):
        return [document]
    if isinstance(document, list):
        return [item if isinstance(item, dict) else {"_invalid_line": n + 1, "_raw": json.dumps(item)} for n, item in enumerate(document)]
    result = []
    for n, line in enumerate(whole.splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            result.append({"_invalid_line": n, "_raw": line})
        else:
            if not isinstance(item, dict):
                result.append({"_invalid_line": n, "_raw": line})
            else:
                result.append(item)
    return result


def _append(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as out:
        for record in records:
            out.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        out.flush()
        os.fsync(out.fileno())


def _case_from_raw(raw: dict[str, Any]) -> dict[str, Any] | None:
    if raw.get("status") != "accepted" or not isinstance(raw.get("record"), dict):
        return None
    record, trace = raw["record"], _trace(raw["record"])
    logical_id, reason = _validate_trace(trace)
    reason = reason or _validate_export(record)
    if reason or not logical_id:
        return None
    trace_digest, raw_digest = sha(trace), sha(record)
    kind = "export" if record.get("schema_version") == EXPORT_SCHEMA else "trace"
    source_id = f"export:{logical_id}:{raw_digest}" if kind == "export" else logical_id
    source_digest = raw_digest if kind == "export" else trace_digest
    expected = {"logical_trace_id": logical_id, "trace_digest": trace_digest, "source_id": source_id,
                "source_digest": source_digest, "raw_digest": raw_digest, "record_kind": kind}
    if any(raw.get(key) != value for key, value in expected.items()):
        return None
    return {"schema_version": NATIVE_SCHEMA, **expected, "case_id": trace["case_id"], "run_id": trace["run_id"],
            "attempt": trace["attempt"], "trace_id": logical_id, "event_ids": [event["event_id"] for event in trace["events"]],
            "export": record if kind == "export" else None, "trace": trace}


def _recover_cases_unlocked(store: Path) -> list[dict[str, Any]]:
    existing = {row["source_id"]: row for row in _rows(store / "cases.jsonl") if row.get("source_id")}
    missing = []
    for raw in _rows(store / "raw.jsonl"):
        case = _case_from_raw(raw)
        if case is None:
            continue
        previous = existing.get(case["source_id"])
        if previous is None:
            missing.append(case); existing[case["source_id"]] = case
        elif previous != case:
            raise ValueError("projection_integrity")
    _append(store / "cases.jsonl", missing)
    return list(existing.values())


def _trace(record: dict[str, Any]) -> dict[str, Any] | None:
    if record.get("schema_version") == TRACE_SCHEMA:
        return record
    if record.get("schema_version") == EXPORT_SCHEMA:
        return (((record.get("payload") or {}).get("evidence") or {}).get("tool_trace"))
    return None


def _validate_export(record: dict[str, Any]) -> str | None:
    """The delivery export, unlike a bare trace, is authoritative as a whole."""
    if record.get("schema_version") != EXPORT_SCHEMA:
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return "invalid_export_payload"
    supplied = record.get("digest") or record.get("payload_sha256")
    if not supplied:
        return "missing_export_digest"
    if supplied != sha(payload):
        return "bad_export_digest"
    evidence = payload.get("evidence")
    trace = evidence.get("tool_trace") if isinstance(evidence, dict) else None
    result = trace.get("result") if isinstance(trace, dict) else None
    if not isinstance(evidence, dict) or not isinstance(trace, dict) or not isinstance(result, dict):
        return "missing_export_trace_lineage"
    if (trace.get("run_id") != evidence.get("run_id") or trace.get("index_version") != evidence.get("index_version")
            or trace.get("request", {}).get("question") != evidence.get("question") or result.get("answer") != evidence.get("answer")
            or trace.get("case_id") != evidence.get("case_id") or result.get("tool_version") != evidence.get("tool_version")
            or result.get("calculation") != evidence.get("calculation")):
        return "export_trace_lineage_mismatch"
    trace_citations = set(result.get("citations") or [])
    citations = evidence.get("citations")
    source = evidence.get("source")
    if not isinstance(citations, list) or not isinstance(source, dict) or {c.get("id") for c in citations if isinstance(c, dict)} != trace_citations:
        return "export_citation_lineage_mismatch"
    hits = {hit.get("id"): hit for hit in trace.get("request", {}).get("hits", []) if isinstance(hit, dict)}
    def page_bound(citation: dict[str, Any]) -> bool:
        hit = hits.get(citation.get("id"))
        match = re.fullmatch(r"(.+)#p(\d+)-[^#]+", str(citation.get("id", "")))
        if hit is None or match is None or match.group(1) != source.get("key") or int(match.group(2)) != citation.get("page"):
            return False
        observed = re.search(r"\[source\].*?\|\s*p\.(\d+)", str(hit.get("content", "")), re.DOTALL)
        return observed is None or int(observed.group(1)) == citation.get("page")
    if any(not isinstance(c, dict) or not c.get("source_hash") or not c.get("row_version") or not isinstance(c.get("page"), int) or c["page"] < 1 or c.get("file_prefix") != str(source.get("sha256", ""))[:16] or c.get("doc") != source.get("key") or c.get("id") not in hits or c.get("source_hash") != hits[c["id"]].get("source_hash") or c.get("row_version") != hits[c["id"]].get("version") or not page_bound(c) for c in citations):
        return "export_citation_provenance_mismatch"
    return None


def _validate_trace(trace: Any) -> tuple[str | None, str | None]:
    if not isinstance(trace, dict) or trace.get("schema_version") != TRACE_SCHEMA:
        return None, "missing_or_wrong_trace_schema"
    required = ("trace_id", "run_id", "case_id", "attempt", "request", "terminal_state", "events")
    if any(not trace.get(k) for k in required) or not isinstance(trace["attempt"], int):
        return None, "incomplete_trace"
    events = trace["events"]
    if not isinstance(events, list) or not events:
        return None, "missing_events"
    ids, expected = set(), 1
    for event in events:
        if not isinstance(event, dict) or event.get("seq") != expected or event.get("event_id") != f"{trace['trace_id']}:{expected}":
            return None, "invalid_event_sequence"
        if event["event_id"] in ids:
            return None, "duplicate_event_id"
        ids.add(event["event_id"]); expected += 1
    request = trace["request"]
    if not isinstance(request, dict) or not isinstance(request.get("hits"), list):
        return None, "invalid_request"
    for hit in request["hits"]:
        if not isinstance(hit, dict) or set(hit) != {"id", "version", "content", "source_hash", "classification", "status"}:
            return None, "invalid_typed_hit"
        if not all(isinstance(hit[key], str) and hit[key] for key in ("id", "version", "content", "source_hash", "status")) or type(hit["classification"]) is not int or hit["source_hash"] != hashlib.sha256(hit["content"].encode("utf-8")).hexdigest():
            return None, "invalid_typed_hit"
    if request.get("input_sha256"):
        # Frozen protocol: hash is the complete typed tool-call, never a
        # request-shaped fallback that omits call identity/schema.
        call = {"schema_version": "forgeflow.report.tool-call.v1", "call_id": events[0].get("call_id"),
                "question": request.get("question"), "index_version": trace.get("index_version"), "hits": request.get("hits")}
        if request["input_sha256"] != sha(call):
            return None, "bad_input_digest"
    else:
        return None, "missing_input_digest"
    result = trace.get("result")
    if result is not None:
        if not isinstance(result, dict) or result.get("schema_version") != RESULT_SCHEMA:
            return None, "invalid_result"
        supplied = result.get("output_sha256")
        if not supplied or supplied != sha({k: v for k, v in result.items() if k != "output_sha256"}):
            return None, "bad_output_digest"
        call_id = events[0].get("call_id")
        if result.get("input_sha256") != request.get("input_sha256"):
            return None, "result_input_not_bound_to_request"
        if not call_id or result.get("call_id") != call_id or any(event.get("call_id") != call_id for event in events):
            return None, "call_id_mismatch"
        hook = next((i for i, event in enumerate(events) if event.get("kind") == "hook_decision"), None)
        call_event = next((i for i, event in enumerate(events) if event.get("kind") == "tool_call"), None)
        result_event = next((i for i, event in enumerate(events) if event.get("kind") == "tool_result"), None)
        if hook is None or call_event is None or result_event is None or not (hook < call_event < result_event) or any(events[index].get("status") != "ok" or events[index].get("tool") != "annual_report.answer.v1" for index in (hook, call_event, result_event)) or events[call_event].get("arguments", {}).get("input_sha256") != request.get("input_sha256") or events[result_event].get("result", {}).get("output_sha256") != result.get("output_sha256"):
            return None, "missing_typed_tool_events"
    return str(trace["trace_id"]), None


def _ingest_unlocked(source: Path, store: Path) -> dict[str, Any]:
    """Append raw source lines; accepted traces are idempotent by stable trace ID/digest."""
    store.mkdir(parents=True, exist_ok=True)
    _recover_cases_unlocked(store)
    accepted_raw = {r["source_id"]: r["source_digest"] for r in _rows(store / "raw.jsonl") if r.get("status") == "accepted" and r.get("source_id")}
    logical = {r["logical_trace_id"]: r["trace_digest"] for r in _rows(store / "raw.jsonl") if r.get("status") == "accepted" and r.get("logical_trace_id")}
    exports = {r["logical_trace_id"] for r in _rows(store / "raw.jsonl") if r.get("status") == "accepted" and r.get("record_kind") == "export"}
    raw_records = []
    counts = {"accepted": 0, "duplicate": 0, "quarantined": 0}
    for index, record in enumerate(_rows(source), 1):
        raw_digest = sha(record)
        trace = _trace(record)
        source_id, reason = _validate_trace(trace)
        reason = reason or _validate_export(record)
        raw = {"schema_version": NATIVE_SCHEMA, "source_path": str(source), "line": index,
               "raw_digest": raw_digest, "record": record, "trace_id": source_id, "status": "accepted" if not reason else "quarantined", "reason": reason}
        if reason:
            counts["quarantined"] += 1; raw_records.append(raw); continue
        # An export's delivery payload is its authority boundary.  A bare trace
        # uses its own digest, but two changed exports must never dedupe merely
        # because their nested trace happened to stay the same.
        trace_digest = sha(trace)
        # A later authoritative export is not a conflicting duplicate of its
        # earlier bare trace; retain both provenance records. Exact exports
        # still dedupe by their trace+content identity.
        kind = "export" if record.get("schema_version") == EXPORT_SCHEMA else "trace"
        source_digest = raw_digest if kind == "export" else trace_digest
        source_id = f"export:{source_id}:{source_digest}" if kind == "export" else source_id
        raw.update({"logical_trace_id": trace["trace_id"], "trace_digest": trace_digest, "source_id": source_id,
                    "source_digest": source_digest, "record_kind": kind})
        if logical.get(trace["trace_id"]) not in (None, trace_digest):
            counts["quarantined"] += 1; raw["status"] = "quarantined"; raw["reason"] = "trace_export_digest_collision"; raw_records.append(raw); continue
        if kind == "export" and trace["trace_id"] in exports:
            counts["quarantined"] += 1; raw["status"] = "quarantined"; raw["reason"] = "competing_export"; raw_records.append(raw); continue
        previous = accepted_raw.get(source_id)
        if previous == source_digest:
            counts["duplicate"] += 1; raw["status"] = "duplicate"; raw_records.append(raw); continue
        if previous is not None:
            counts["quarantined"] += 1; raw["status"] = "quarantined"; raw["reason"] = "source_id_digest_collision"; raw_records.append(raw); continue
        accepted_raw[source_id] = source_digest; logical[trace["trace_id"]] = trace_digest
        if kind == "export": exports.add(trace["trace_id"])
        raw_records.append(raw); counts["accepted"] += 1
    _append(store / "raw.jsonl", raw_records); _recover_cases_unlocked(store)
    return {"schema_version": NATIVE_SCHEMA, "source": str(source), **counts, "raw_digest": file_sha(source)}


def ingest(source: Path, store: Path) -> dict[str, Any]:
    """Append/dedupe under an interprocess lock; raw journal remains immutable."""
    with _store_lock(store):
        return _ingest_unlocked(source, store)


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError) as err:
        raise ValueError("invalid_decimal") from err


def _observations(case: dict[str, Any], allowed_hits: set[str] | None = None) -> dict[str, dict[str, Any]]:
    hits = case["trace"]["request"].get("hits", [])
    observations: dict[str, dict[str, Any]] = {}
    years = [int(year) for year in re.findall(r"20\d{2}", str(case["trace"]["request"].get("question", "")))]
    year = years[0] if years else None
    for hit in hits:
        if not isinstance(hit, dict) or not hit.get("id") or not hit.get("source_hash"):
            continue
        if allowed_hits is not None and str(hit["id"]) not in allowed_hits:
            continue
        content = hit.get("content")
        items = content.get("observations", []) if isinstance(content, dict) else []
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                observations[str(item["id"])] = {**item, "hit_id": hit["id"], "source_hash": hit["source_hash"]}
        # The fixed ForgeFlow tool transports public report text, not an
        # EvidenceLoop-specific observations envelope.  Derive only the small,
        # named figures needed for the supported Apple calculation.
        if isinstance(content, str):
            try:
                encoded = json.loads(content)
            except json.JSONDecodeError:
                encoded = None
            if isinstance(encoded, dict):
                for item in encoded.get("observations", []):
                    if isinstance(item, dict) and item.get("id"):
                        observations[str(item["id"])] = {**item, "hit_id": hit["id"], "source_hash": hit["source_hash"]}
            lines = content.splitlines()
            header = next((line for line in lines if "|" in line and year is not None and str(year) in line and str(year - 1) in line), None)
            if header:
                columns = [part.strip() for part in header.split("|")]
                try:
                    current, prior = columns.index(str(year)), columns.index(str(year - 1))
                except ValueError:
                    continue
                extracted = {}
                for label, key in (("Services", "services"), ("Total net sales", "total")):
                    line = next((item for item in lines if item.strip().startswith(label) and "|" in item), None)
                    if not line:
                        continue
                    cells = [part.strip() for part in line.split("|")]
                    if max(current, prior) >= len(cells):
                        continue
                    values = [re.sub(r"[^0-9,]", "", cells[index]) for index in (current, prior)]
                    if all(re.fullmatch(r"[\d,]+", value or "") for value in values):
                        extracted[key] = [value.replace(",", "") for value in values]
                if set(extracted) == {"services", "total"}:
                    for name, value in zip(("services-current", "services-prior", "total-current", "total-prior"), (*extracted["services"], *extracted["total"])):
                        observations[name] = {"id": name, "value": value, "hit_id": hit["id"], "source_hash": hit["source_hash"]}
    return observations


def _status(condition: bool | None) -> str:
    return "pass" if condition is True else "fail" if condition is False else "unknown"


@plugin("native-source-decimal")
def source_decimal(case: dict[str, Any]) -> dict[str, str]:
    """Independent arithmetic and provenance checks against casebank observations."""
    spec, trace = case["spec"], case["trace"]
    result = trace.get("result") or {}
    observations = _observations(case)
    terminal = trace.get("terminal_state")
    checks: dict[str, str] = {"terminal_state": "pass" if terminal == "success" else "fail" if terminal == "failure" else "unknown",
                               "tool_status": _status(result.get("status") == "ANSWERED")}
    if terminal == "unknown":
        return {key: "unknown" for key in ("terminal_state", "tool_status", "source_observations", "answer", "period", "unit", "citations", "calculation")}
    if not result or not observations:
        checks.update({"source_observations": "unknown", "answer": "unknown", "period": "unknown", "unit": "unknown", "citations": "unknown", "calculation": "unknown"})
        return checks
    expected_obs = spec.get("observations", [])
    wanted = {str(item.get("id")): item for item in expected_obs if isinstance(item, dict) and item.get("id")}
    if not wanted:
        checks["source_observations"] = "unknown"
    else:
        checks["source_observations"] = _status(all(key in observations and all(observations[key].get(k) == value for k, value in item.items() if k != "id") for key, item in wanted.items()))
    calc = spec.get("calculation") or {"op": "read", "observation": spec.get("observation")}
    try:
        op = calc.get("op")
        if op == "read":
            calculated = _decimal(observations[str(calc["observation"])] ["value"])
        elif op == "ratio":
            calculated = _decimal(observations[str(calc["numerator"])] ["value"]) / _decimal(observations[str(calc["denominator"])] ["value"]) * Decimal(100)
        elif op == "growth":
            current = _decimal(observations[str(calc["current"])] ["value"])
            prior = _decimal(observations[str(calc["prior"])] ["value"])
            calculated = (current - prior) / prior * Decimal(100)
        elif op == "sum":
            calculated = sum((_decimal(observations[str(key)]["value"]) for key in calc["observations"]), Decimal(0))
        else:
            raise ValueError("unknown_calculation")
        digits = int(calc.get("digits", 2 if op == "ratio" else 0))
        quantized = calculated.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
        expected = _decimal(spec["expected_value"])
        checks["calculation"] = _status(quantized == expected)
        checks["answer"] = _status(_decimal(result.get("answer")) == expected)
    except (KeyError, ValueError, TypeError, InvalidOperation):
        checks["calculation"] = checks["answer"] = "unknown"
    checks["period"] = _status(result.get("period") == spec["period"]) if spec.get("period") else "unknown"
    checks["unit"] = _status(result.get("unit") == spec["unit"]) if spec.get("unit") else "unknown"
    cited = result.get("citations") or []
    wanted_citations = set(spec.get("citation_ids") or [])
    got = {str(c.get("row_id", c.get("id", ""))) if isinstance(c, dict) else str(c) for c in cited}
    valid_hits = {str(h.get("id")) for h in trace["request"].get("hits", []) if isinstance(h, dict)}
    checks["citations"] = _status(bool(got) and got <= valid_hits and (not wanted_citations or got == wanted_citations))
    return checks


@plugin("native-product-v1")
def product_v1(case: dict[str, Any]) -> dict[str, str]:
    """Evaluate the two fixed product cases from their real trace shape.

    A source-linked casebank may supply a stricter independent expected value;
    without one this still recomputes Apple from raw hit text and checks CATL's
    answer against source text. It never consumes a ForgeFlow helper.
    """
    spec = case["spec"]
    if spec.get("expected_value") is not None:
        return source_decimal(case)
    trace, result = case["trace"], case["trace"].get("result") or {}
    valid_hits = {str(h.get("id")) for h in trace["request"].get("hits", []) if isinstance(h, dict)}
    cited = {str(c.get("row_id", c.get("id", ""))) if isinstance(c, dict) else str(c) for c in result.get("citations", [])}
    terminal = trace.get("terminal_state")
    checks = {"terminal_state": "pass" if terminal == "success" else "fail" if terminal == "failure" else "unknown",
              "tool_status": _status(result.get("status") == "ANSWERED"),
              "citations": _status(bool(cited) and cited <= valid_hits)}
    if terminal == "unknown":
        return {key: "unknown" for key in ("terminal_state", "tool_status", "citations", "source_observations", "calculation", "answer", "period", "unit")}
    if not result or not valid_hits:
        checks.update({"source_observations": "unknown", "calculation": "unknown", "answer": "unknown", "period": "unknown", "unit": "unknown"})
        return checks
    observations, calc = _observations(case, cited), result.get("calculation")
    if trace.get("case_id") == "apple-services-growth-contribution-dev":
        required = ("services-current", "services-prior", "total-current", "total-prior")
        if not all(key in observations for key in required) or not isinstance(calc, dict):
            checks.update({"source_observations": "unknown", "calculation": "unknown", "answer": "unknown", "period": "unknown", "unit": "unknown"})
            return checks
        try:
            s0, s1, t0, t1 = (_decimal(observations[key]["value"]) for key in required)
            expected = [(s0 - s1) * 100 / s1, (s0 - s1) * 100 / (t0 - t1)]
            operations = calc.get("operations", [])
            question = str(trace["request"].get("question", ""))
            wanted = []
            if "增速" in question or "增长率" in question or "growth" in question.lower():
                wanted.append(0)
            if "贡献" in question or "contribution" in question.lower():
                wanted.append(1)
            years = re.findall(r"20\d{2}", question)
            source_text = "\n".join(str(hit.get("content", "")) for hit in trace["request"].get("hits", []) if isinstance(hit, dict))
            if not wanted or not years or str(int(years[0]) - 1) not in source_text or years[0] not in source_text:
                checks.update({"source_observations": "unknown", "calculation": "unknown", "answer": "unknown", "period": "unknown", "unit": "unknown"})
                return checks
            selected = [(operations[index], (s1, t0 - t1)[index], expected[index]) for index in wanted if index < len(operations)]
            rendered = result.get("answer", "")
            matched = len(operations) == len(wanted) and len(selected) == len(wanted) and all(_decimal(op.get("numerator")) == s0 - s1 and _decimal(op.get("denominator")) == denominator and _decimal(op.get("percent")) == value.quantize(Decimal(".01"), rounding=ROUND_HALF_UP) and f"{value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)}%" in rendered for op, denominator, value in selected)
            checks.update({"source_observations": "pass", "calculation": _status(matched), "answer": _status(matched),
                           "period": _status(calc.get("periods") == [int(years[0]), int(years[0]) - 1]), "unit": _status(calc.get("unit") == "百万美元")})
        except (InvalidOperation, ValueError, TypeError, KeyError):
            checks.update({"source_observations": "unknown", "calculation": "unknown", "answer": "unknown", "period": "unknown", "unit": "unknown"})
        return checks
    if trace.get("case_id") == "catl-operating-cash-period-dev":
        annual_values = []
        for hit in trace["request"].get("hits", []):
            text = str(hit.get("content", "")) if isinstance(hit, dict) else ""
            # The annual table identifies its unit and calendar-year column;
            # quarterly-only rows (where the historic wrong Q4 answer came
            # from) do not satisfy this source observation.
            if "单位:千元" not in text or "2025年" not in text:
                continue
            for line in text.splitlines():
                match = re.search(r"经营活动产生的现金流量净额\s*\|\s*([\d,]+)", line)
                if match and str(hit.get("id")) in cited:
                    annual_values.append(match.group(1))
        answer_values = re.findall(r"(?<!\d)(\d{1,3}(?:,\d{3})+)(?!\d)", str(result.get("answer", "")))
        checks.update({"source_observations": _status(bool(annual_values)), "calculation": "pass",
                       "answer": _status(len(answer_values) == 1 and answer_values[0] in set(annual_values)),
                       "period": _status("全年" in str(result.get("answer", ""))), "unit": _status("千元" in str(result.get("answer", "")))})
        return checks
    checks.update({"source_observations": "unknown", "calculation": "unknown", "answer": "unknown", "period": "unknown", "unit": "unknown"})
    return checks


def _verdict(checks: dict[str, str]) -> str:
    values = set(checks.values())
    return "fail" if "fail" in values else "unknown" if "unknown" in values else "pass"


def _delivery(imported: dict[str, Any]) -> tuple[dict[str, str], str]:
    """Evaluate delivery separately: a successful tool trace is not a delivery."""
    export = imported.get("export")
    if not isinstance(export, dict):
        return {"delivery_export": "unknown"}, "unknown"
    payload, events = export.get("payload"), export.get("events")
    if not isinstance(payload, dict) or not isinstance(events, list):
        return {"delivery_export": "unknown"}, "unknown"
    delivered = [event for event in events if isinstance(event, dict) and event.get("kind") == "delivered"]
    approved = [event for event in events if isinstance(event, dict) and event.get("kind") == "approved"]
    if export.get("state") != "delivered" or not delivered:
        return {"delivery_export": "unknown"}, "unknown"
    bound = all(event.get("digest") == export.get("digest") and event.get("draft") == payload.get("draft_id") and event.get("version") == payload.get("version") for event in events if isinstance(event, dict))
    checks = {
        "delivery_state": "pass",
        "delivery_exactly_once": _status(len(delivered) == 1),
        "delivery_payload_bound": _status(bound),
        "delivery_receipt": _status(len(delivered) == 1 and export.get("local_receipt") == sha(delivered[0])),
        "delivery_prior_reviewer_approval": _status(len(approved) == 1 and approved[0].get("actor") != payload.get("owner") and events.index(approved[0]) < events.index(delivered[0])),
    }
    return checks, _verdict(checks)


def _casebank(path: Path) -> dict[str, dict[str, Any]]:
    items = _rows(path)
    result = {}
    for item in items:
        if not item.get("case_id") or item["case_id"] in result:
            raise ValueError("casebank requires unique case_id rows")
        result[item["case_id"]] = item
    return result


def evaluate(store: Path, casebank: Path, out: Path, evaluator_id: str = "native-product-v1") -> dict[str, Any]:
    if evaluator_id not in _PLUGINS:
        raise ValueError(f"unregistered evaluator {evaluator_id}")
    bank, descriptor = _casebank(casebank), plugin_descriptor(evaluator_id)
    eval_run_id = "native-eval-" + uuid.uuid4().hex
    rows = []
    with _store_lock(store):
        imported_rows = _recover_cases_unlocked(store)
    # Preserve every source envelope in the journal, but do not score the same
    # logical trace twice when a later authoritative export wraps it.
    authoritative = {row["trace_id"] for row in imported_rows if row.get("record_kind") == "export"}
    for imported in imported_rows:
        if imported.get("record_kind") != "export" and imported.get("trace_id") in authoritative:
            continue
        spec = bank.get(imported["case_id"])
        base = {"schema_version": NATIVE_SCHEMA, "eval_run_id": eval_run_id, "evaluator": descriptor,
                "source_id": imported["source_id"], "source_digest": imported["source_digest"], "case_id": imported["case_id"],
                "trace_id": imported["trace_id"], "event_ids": imported["event_ids"]}
        if spec is None:
            spec = {"case_id": imported["case_id"]}
        try:
            checks = _PLUGINS[evaluator_id]({"trace": imported["trace"], "spec": spec})
            if not isinstance(checks, dict) or not all(v in {"pass", "fail", "unknown"} for v in checks.values()):
                raise ValueError("invalid_plugin_checks")
            delivery_checks, delivery_verdict = _delivery(imported)
            tool_verdict = _verdict(checks)
            overall = _verdict({"tool": tool_verdict, "delivery": delivery_verdict}) if imported.get("record_kind") == "export" else tool_verdict
            rows.append({**base, "casebank_digest": sha(spec), "checks": checks, "tool_verdict": tool_verdict,
                         "delivery_checks": delivery_checks, "delivery_verdict": delivery_verdict, "scope": "delivered_export" if imported.get("record_kind") == "export" else "tool_only", "verdict": overall})
        except Exception as err:  # noqa: BLE001 - trusted extension faults are recorded as unknown
            rows.append({**base, "casebank_digest": sha(spec), "checks": {"evaluator": "unknown"}, "verdict": "unknown", "reason": f"evaluator_exception:{type(err).__name__}"})
    if not rows:
        raise ValueError("no accepted imported cases")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"schema_version": NATIVE_SCHEMA, "eval_run_id": eval_run_id, "evaluator": descriptor, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path = out.with_suffix(".html")
    html_path.write_text(render_html(rows, eval_run_id), encoding="utf-8")
    return {"eval_run_id": eval_run_id, "rows": len(rows), "out": str(out), "html": str(html_path)}


def render_html(rows: list[dict[str, Any]], run_id: str) -> str:
    body = "".join("<tr><td>" + "</td><td>".join(html.escape(str(row.get(k, ""))) for k in ("case_id", "trace_id", "source_id", "scope", "tool_verdict", "delivery_verdict", "verdict", "event_ids")) + "</td><td><pre>" + html.escape(json.dumps({"tool": row.get("checks"), "delivery": row.get("delivery_checks")}, ensure_ascii=False, sort_keys=True)) + "</pre></td></tr>" for row in rows)
    return f"<!doctype html><meta charset=utf-8><title>Native evidence report</title><h1>Native evidence report</h1><p>eval run: {html.escape(run_id)}</p><table border=1><tr><th>case</th><th>trace</th><th>source</th><th>scope</th><th>tool</th><th>delivery</th><th>overall</th><th>events</th><th>checks</th></tr>{body}</table>"


def replay(store: Path, casebank: Path, out: Path, evaluator_id: str = "native-product-v1") -> dict[str, Any]:
    return evaluate(store, casebank, out, evaluator_id)


def aa(store: Path, casebank: Path, out: Path, evaluator_id: str = "native-product-v1") -> dict[str, Any]:
    first_path, second_path = out.with_suffix(".a.json"), out.with_suffix(".b.json")
    evaluate(store, casebank, first_path, evaluator_id)
    evaluate(store, casebank, second_path, evaluator_id)
    a = json.loads(first_path.read_text(encoding="utf-8")); b = json.loads(second_path.read_text(encoding="utf-8"))
    left = {r["source_id"]: r for r in a["rows"]}; right = {r["source_id"]: r for r in b["rows"]}
    common = sorted(set(left) & set(right))
    if not common:
        raise ValueError("A/A has no common denominator")
    dimensions = ("verdict", "checks", "casebank_digest", "tool_verdict", "delivery_checks", "delivery_verdict", "scope", "source_digest", "event_ids")
    exact = all({k: left[key].get(k) for k in dimensions} == {k: right[key].get(k) for k in dimensions} for key in common)
    payload = {"schema_version": NATIVE_SCHEMA, "a_eval_run_id": a["eval_run_id"], "b_eval_run_id": b["eval_run_id"], "common": len(common), "exact": exact, "rows": common}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def mine(results: Path, out: Path) -> dict[str, Any]:
    payload = json.loads(results.read_text(encoding="utf-8"))
    failures = [{"source_id": r["source_id"], "source_digest": r["source_digest"], "case_id": r["case_id"], "trace_id": r["trace_id"], "event_ids": r["event_ids"], "checks": r["checks"], "tool_verdict": r.get("tool_verdict"), "delivery_checks": r.get("delivery_checks"), "delivery_verdict": r.get("delivery_verdict"), "scope": r.get("scope"), "verdict": r["verdict"]} for r in payload.get("rows", []) if r.get("verdict") != "pass"]
    out.write_text(json.dumps({"schema_version": NATIVE_SCHEMA, "source_results_digest": file_sha(results), "failures": failures}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"failures": len(failures), "out": str(out)}
