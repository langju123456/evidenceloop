import json
from pathlib import Path

from evidenceloop.cli import main
from evidenceloop.report import native_report as native

ACCEPTANCE = Path(__file__).parent / "fixtures" / "native_reports"


def _trace(case_id="apple-services-growth", answer="13.51", period="FY2025 vs FY2024", citations=True):
    content = {"observations": [
        {"id": "services-25", "value": "109158", "unit": "USD millions", "period": "FY2025"},
        {"id": "services-24", "value": "96169", "unit": "USD millions", "period": "FY2024"},
    ]}
    content = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    request = {"question": "Apple service growth", "hits": [
        {"id": "apple-services", "version": "2025", "source_hash": native.hashlib.sha256(content.encode()).hexdigest(), "classification": 1, "status": "CURRENT", "content": content},
    ]}
    request["input_sha256"] = native.sha({"schema_version": "forgeflow.report.tool-call.v1", "call_id": "call-1", "question": request["question"], "index_version": "i1", "hits": request["hits"]})
    result = {"schema_version": native.RESULT_SCHEMA, "call_id": "call-1", "status": "ANSWERED", "found": True,
              "answer": answer, "period": period, "unit": "%", "citations": ([{"row_id": "apple-services"}] if citations else []),
              "tool_version": "v1", "input_sha256": request["input_sha256"]}
    result["output_sha256"] = native.sha({k: v for k, v in result.items() if k != "output_sha256"})
    return {"schema_version": native.TRACE_SCHEMA, "trace_id": "trace-apple", "run_id": "run-1", "case_id": case_id,
            "attempt": 1, "producer": {"name": "ForgeFlow", "version": "test"}, "index_version": "i1", "request": request,
            "result": result, "terminal_state": "success", "events": [
                {"event_id": "trace-apple:1", "seq": 1, "kind": "hook_decision", "call_id": "call-1", "tool": "annual_report.answer.v1", "status": "ok", "arguments": {"decision": "allow"}},
                {"event_id": "trace-apple:2", "seq": 2, "kind": "tool_call", "call_id": "call-1", "tool": "annual_report.answer.v1", "status": "ok", "arguments": {"input_sha256": request["input_sha256"]}},
                {"event_id": "trace-apple:3", "seq": 3, "kind": "tool_result", "call_id": "call-1", "tool": "annual_report.answer.v1", "status": "ok", "result": {"output_sha256": result["output_sha256"]}},
            ]}


def _bank(path):
    path.write_text(json.dumps({"case_id": "apple-services-growth", "expected_value": "13.51", "unit": "%", "period": "FY2025 vs FY2024",
                                "citation_ids": ["apple-services"], "observations": [
                                    {"id": "services-25", "value": "109158", "unit": "USD millions", "period": "FY2025"},
                                    {"id": "services-24", "value": "96169", "unit": "USD millions", "period": "FY2024"}],
                                "calculation": {"op": "growth", "current": "services-25", "prior": "services-24", "digits": 2}}) + "\n", encoding="utf-8")


def _write(path, *rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_native_ingest_evaluate_replay_aa_and_failure_bank(tmp_path):
    source, store, bank = tmp_path / "exports.jsonl", tmp_path / "store", tmp_path / "casebank.jsonl"
    _write(source, _trace())
    _bank(bank)
    assert native.ingest(source, store)["accepted"] == 1
    assert native.ingest(source, store)["duplicate"] == 1  # survives a restart from JSONL state
    result = native.evaluate(store, bank, tmp_path / "result.json")
    payload = json.loads((tmp_path / "result.json").read_text())
    assert result["rows"] == 1 and payload["rows"][0]["verdict"] == "pass"
    assert (tmp_path / "result.html").exists()
    aa = native.aa(store, bank, tmp_path / "aa.json")
    assert aa["common"] == 1 and aa["exact"] and aa["a_eval_run_id"] != aa["b_eval_run_id"]
    assert native.mine(tmp_path / "result.json", tmp_path / "failures.json")["failures"] == 0


def test_native_rejects_tampering_and_collision_without_counting_them(tmp_path):
    source, store = tmp_path / "exports.jsonl", tmp_path / "store"
    good = _trace()
    bad = _trace(); bad["result"]["answer"] = "999"  # output digest no longer agrees
    collision = _trace(); collision["result"]["answer"] = "13.50"; collision["result"]["output_sha256"] = native.sha({k: v for k, v in collision["result"].items() if k != "output_sha256"}); collision["events"][-1]["result"]["output_sha256"] = collision["result"]["output_sha256"]
    _write(source, good, bad, collision)
    counts = native.ingest(source, store)
    assert counts == {"schema_version": native.NATIVE_SCHEMA, "source": str(source), "accepted": 1, "duplicate": 0, "quarantined": 2, "raw_digest": native.file_sha(source)}
    raw = [json.loads(line) for line in (store / "raw.jsonl").read_text().splitlines()]
    assert {row["reason"] for row in raw if row["status"] == "quarantined"} == {"bad_output_digest", "trace_export_digest_collision"}
    assert len((store / "cases.jsonl").read_text().splitlines()) == 1


def test_native_rejects_a_tampered_authoritative_export(tmp_path):
    source, store = tmp_path / "export.json", tmp_path / "store"
    export = {"schema_version": native.EXPORT_SCHEMA, "payload": {"evidence": {"tool_trace": _trace()}, "answer": "13.51"}}
    export["digest"] = native.sha(export["payload"])
    export["payload"]["answer"] = "tampered-after-digest"
    _write(source, export)
    assert native.ingest(source, store)["quarantined"] == 1
    raw = json.loads((store / "raw.jsonl").read_text())
    assert raw["reason"] == "bad_export_digest" and not (store / "cases.jsonl").exists()


def test_native_marks_false_answer_wrong_period_and_missing_citation_as_failures(tmp_path):
    source, store, bank = tmp_path / "exports.jsonl", tmp_path / "store", tmp_path / "bank.jsonl"
    _write(source, _trace(answer="13.52", period="FY2024", citations=False)); _bank(bank); native.ingest(source, store)
    native.evaluate(store, bank, tmp_path / "result.json")
    row = json.loads((tmp_path / "result.json").read_text())["rows"][0]
    assert row["verdict"] == "fail"
    assert row["checks"]["answer"] == row["checks"]["period"] == row["checks"]["citations"] == "fail"
    assert native.mine(tmp_path / "result.json", tmp_path / "failures.json")["failures"] == 1
    failure = json.loads((tmp_path / "failures.json").read_text())["failures"][0]
    assert failure["event_ids"] == ["trace-apple:1", "trace-apple:2", "trace-apple:3"] and failure["source_digest"]


def test_native_missing_source_observations_is_unknown_and_cli_is_usable(tmp_path):
    source, store, bank = tmp_path / "exports.jsonl", tmp_path / "store", tmp_path / "bank.jsonl"
    trace = _trace(); trace["request"]["hits"] = []
    trace["request"]["input_sha256"] = native.sha({"schema_version": "forgeflow.report.tool-call.v1", "call_id": "call-1", "question": trace["request"]["question"], "index_version": trace["index_version"], "hits": trace["request"]["hits"]})
    trace["result"]["input_sha256"] = trace["request"]["input_sha256"]
    trace["result"]["output_sha256"] = native.sha({k: v for k, v in trace["result"].items() if k != "output_sha256"})
    trace["events"][1]["arguments"]["input_sha256"] = trace["request"]["input_sha256"]
    trace["events"][-1]["result"]["output_sha256"] = trace["result"]["output_sha256"]
    _write(source, trace); _bank(bank)
    main(["report", "native-ingest", "--input", str(source), "--store", str(store)])
    main(["report", "native-evaluate", "--store", str(store), "--casebank", str(bank), "--out", str(tmp_path / "result.json")])
    row = json.loads((tmp_path / "result.json").read_text())["rows"][0]
    assert row["verdict"] == "unknown" and row["checks"]["answer"] == "unknown"


def test_native_plugin_version_is_code_bound_and_exceptions_stay_unknown(tmp_path):
    @native.plugin("test-native-unknown")
    def broken(_case):
        raise RuntimeError("intentional")

    @native.plugin("test-native-other")
    def other(_case):
        return {"extension": "pass"}

    assert len(native.plugin_descriptor("test-native-unknown")["version"]) == 64
    source, store, bank = tmp_path / "exports.jsonl", tmp_path / "store", tmp_path / "bank.jsonl"
    _write(source, _trace()); _bank(bank); native.ingest(source, store)
    native.evaluate(store, bank, tmp_path / "result.json", "test-native-unknown")
    row = json.loads((tmp_path / "result.json").read_text())["rows"][0]
    assert row["verdict"] == "unknown" and row["checks"] == {"evaluator": "unknown"}


def test_native_product_verifier_accepts_real_apple_shape_and_rejects_semantic_negative(tmp_path):
    call = {"schema_version": "forgeflow.report.tool-call.v1", "call_id": "call-real", "question": "Apple FY2025 service growth and contribution", "index_version": "apple-v1",
            "hits": [{"id": "page-26", "version": "v1", "source_hash": "pdf-apple", "classification": 1, "status": "CURRENT",
                      "content": " | 2025 | 2024\nServices (1) | $ 109,158 | $ 96,169\nTotal net sales | $ 416,161 | $ 391,035"}]}
    call["hits"][0]["source_hash"] = native.hashlib.sha256(call["hits"][0]["content"].encode()).hexdigest()
    result = {"schema_version": native.RESULT_SCHEMA, "call_id": "call-real", "status": "ANSWERED", "found": True,
              "answer": "Apple FY2025，服务收入增速为13.51%（12,989 / 96,169）；服务对公司收入增量的贡献为51.70%（12,989 / 25,126）。金额单位为百万美元。",
              "citations": ["page-26"], "tool_version": "apple-services-v1", "input_sha256": native.sha(call),
              "calculation": {"periods": [2025, 2024], "unit": "百万美元", "services": [109158, 96169], "total_sales": [416161, 391035], "operations": [
                  {"metric": "服务收入增速", "formula": "服务收入增量 / 上期服务收入", "numerator": 12989, "denominator": 96169, "percent": "13.51"},
                  {"metric": "服务对公司收入增量的贡献", "formula": "服务收入增量 / 公司收入增量", "numerator": 12989, "denominator": 25126, "percent": "51.70"}]}}
    result["output_sha256"] = native.sha({k: v for k, v in result.items() if k != "output_sha256"})
    trace = {"schema_version": native.TRACE_SCHEMA, "trace_id": "trace-real", "run_id": "real-1", "case_id": "apple-services-growth-contribution-dev", "attempt": 1,
             "producer": {"name": "forgeflow.report_plugin", "version": "v1"}, "index_version": "apple-v1",
             "request": {"question": call["question"], "input_sha256": native.sha(call), "hits": call["hits"]}, "result": result, "terminal_state": "success",
             "events": [{"event_id": "trace-real:1", "seq": 1, "kind": "hook_decision", "call_id": "call-real", "tool": "annual_report.answer.v1", "status": "ok"}, {"event_id": "trace-real:2", "seq": 2, "kind": "tool_call", "call_id": "call-real", "tool": "annual_report.answer.v1", "status": "ok", "arguments": {"input_sha256": native.sha(call)}}, {"event_id": "trace-real:3", "seq": 3, "kind": "tool_result", "call_id": "call-real", "tool": "annual_report.answer.v1", "status": "ok", "result": {"output_sha256": result["output_sha256"]}}]}
    source, store, bank = tmp_path / "trace.json", tmp_path / "store", tmp_path / "bank.jsonl"
    _write(source, trace); bank.write_text("")
    assert native.ingest(source, store)["accepted"] == 1
    native.evaluate(store, bank, tmp_path / "result.json")
    assert json.loads((tmp_path / "result.json").read_text())["rows"][0]["verdict"] == "pass"
    trace["result"]["calculation"]["operations"][1]["percent"] = "17.40"  # an old-period wrong computation
    trace["result"]["output_sha256"] = native.sha({k: v for k, v in trace["result"].items() if k != "output_sha256"})
    trace["events"][-1]["result"]["output_sha256"] = trace["result"]["output_sha256"]
    trace["trace_id"] = "trace-negative"
    for i, event in enumerate(trace["events"], 1): event["event_id"] = f"trace-negative:{i}"
    _write(source, trace); native.ingest(source, store); native.evaluate(store, bank, tmp_path / "negative.json")
    assert json.loads((tmp_path / "negative.json").read_text())["rows"][-1]["verdict"] == "fail"


def test_native_product_verifier_rejects_catl_quarter_as_annual(tmp_path):
    trace = _trace(case_id="catl-operating-cash-period-dev", answer="133,219,982", period="ignored")
    trace["request"]["hits"] = [{"id": "page-11", "version": "v1", "source_hash": "pdf-catl", "classification": 1, "status": "CURRENT",
                                  "content": "[table] 单位:千元\n项目 | 2025年 | 2024年\n经营活动产生的现金流量净额 | 133,219,982 | 96,990,345"}]
    trace["request"]["hits"][0]["source_hash"] = native.hashlib.sha256(trace["request"]["hits"][0]["content"].encode()).hexdigest()
    call = {"schema_version": "forgeflow.report.tool-call.v1", "call_id": "call-1", "question": trace["request"]["question"], "index_version": trace["index_version"], "hits": trace["request"]["hits"]}
    trace["request"]["input_sha256"] = native.sha(call); trace["result"]["input_sha256"] = native.sha(call)
    trace["events"][1]["arguments"]["input_sha256"] = trace["request"]["input_sha256"]
    trace["result"]["answer"] = "宁德时代 2025 年全年经营活动产生的现金流量净额为 133,219,982 千元人民币。"
    trace["result"]["citations"] = ["page-11"]; trace["result"]["output_sha256"] = native.sha({k: v for k, v in trace["result"].items() if k != "output_sha256"}); trace["events"][-1]["result"]["output_sha256"] = trace["result"]["output_sha256"]
    source, store, bank = tmp_path / "trace.json", tmp_path / "store", tmp_path / "bank.jsonl"; _write(source, trace); bank.write_text("")
    native.ingest(source, store); native.evaluate(store, bank, tmp_path / "ok.json")
    assert json.loads((tmp_path / "ok.json").read_text())["rows"][0]["verdict"] == "pass"
    trace["trace_id"] = "trace-catl-q4"; trace["result"]["answer"] = "宁德时代 2025 年全年经营活动产生的现金流量净额为 52,559,552 千元人民币。"
    trace["result"]["output_sha256"] = native.sha({k: v for k, v in trace["result"].items() if k != "output_sha256"})
    trace["events"][-1]["result"]["output_sha256"] = trace["result"]["output_sha256"]
    for i, event in enumerate(trace["events"], 1): event["event_id"] = f"trace-catl-q4:{i}"
    _write(source, trace); native.ingest(source, store); native.evaluate(store, bank, tmp_path / "bad.json")
    assert json.loads((tmp_path / "bad.json").read_text())["rows"][-1]["checks"]["answer"] == "fail"


def test_native_quarantines_result_bound_to_a_different_request_and_unknown_stays_unknown(tmp_path):
    source, store, bank = tmp_path / "trace.json", tmp_path / "store", tmp_path / "bank.jsonl"
    bad = _trace(); bad["result"]["input_sha256"] = "different"; bad["result"]["output_sha256"] = native.sha({k: v for k, v in bad["result"].items() if k != "output_sha256"})
    _write(source, bad); assert native.ingest(source, store)["quarantined"] == 1
    trace = _trace(); trace["terminal_state"] = "unknown"; _write(source, trace); _bank(bank); native.ingest(source, store)
    native.evaluate(store, bank, tmp_path / "result.json")
    row = json.loads((tmp_path / "result.json").read_text())["rows"][0]
    assert row["checks"]["terminal_state"] == row["tool_verdict"] == "unknown"


def test_raw_journal_recovers_case_after_projection_write_failure(tmp_path, monkeypatch):
    source, store, bank = tmp_path / "trace.json", tmp_path / "store", tmp_path / "bank.jsonl"
    _write(source, _trace()); _bank(bank)
    real_append, failed = native._append, {"value": False}

    def fail_case_append(path, rows):
        if path.name == "cases.jsonl" and rows and not failed["value"]:
            failed["value"] = True
            raise OSError("injected second append failure")
        return real_append(path, rows)

    monkeypatch.setattr(native, "_append", fail_case_append)
    import pytest
    with pytest.raises(OSError, match="injected"):
        native.ingest(source, store)
    raw_before = (store / "raw.jsonl").read_text()
    monkeypatch.setattr(native, "_append", real_append)
    native.evaluate(store, bank, tmp_path / "result.json")  # restart reconstructs cases from raw
    assert len((store / "cases.jsonl").read_text().splitlines()) == 1
    assert native.ingest(source, store)["duplicate"] == 1
    assert (store / "raw.jsonl").read_text().startswith(raw_before)


def test_review_p1_raw_projection_rejects_mutable_record_kind(tmp_path):
    source, store, bank = tmp_path / "trace.json", tmp_path / "store", tmp_path / "bank.jsonl"
    _write(source, _trace()); _bank(bank); native.ingest(source, store)
    case = json.loads((store / "cases.jsonl").read_text()); case["record_kind"] = "export"
    (store / "cases.jsonl").write_text(json.dumps(case) + "\n")
    import pytest
    with pytest.raises(ValueError, match="projection_integrity"):
        native.evaluate(store, bank, tmp_path / "result.json")


def test_review_p1_denied_hook_and_competing_export_are_quarantined(tmp_path):
    denied = _trace(); denied["events"][0]["status"] = "denied"
    source, store = tmp_path / "denied.json", tmp_path / "store"; _write(source, denied)
    assert native.ingest(source, store)["quarantined"] == 1
    export = json.loads((ACCEPTANCE / "catl-export.json").read_text())
    source = tmp_path / "exports.jsonl"; _write(source, export)
    assert native.ingest(source, store)["accepted"] == 1
    clone = json.loads(json.dumps(export)); clone["payload"]["reexport_note"] = "different envelope"
    clone["digest"] = native.sha(clone["payload"])
    for event in clone["events"]: event["digest"] = clone["digest"]
    delivered = next(event for event in clone["events"] if event["kind"] == "delivered")
    clone["local_receipt"] = native.sha(delivered)
    _write(source, clone)
    assert native.ingest(source, store)["quarantined"] == 1
    assert json.loads((store / "raw.jsonl").read_text().splitlines()[-1])["reason"] == "competing_export"


def test_review_p1_forged_citation_and_delivery_failure_are_preserved_in_mine(tmp_path):
    export = json.loads((ACCEPTANCE / "apple-export.json").read_text())
    export["payload"]["evidence"]["citations"][0]["source_hash"] = "forged"
    export["digest"] = native.sha(export["payload"])
    source, store = tmp_path / "forged.json", tmp_path / "store"; _write(source, export)
    assert native.ingest(source, store)["quarantined"] == 1
    export = json.loads((ACCEPTANCE / "apple-export.json").read_text())
    export["payload"]["evidence"]["citations"][0]["page"] = 999
    export["digest"] = native.sha(export["payload"])
    _write(source, export)
    assert native.ingest(source, tmp_path / "wrong-page-store")["quarantined"] == 1
    receipt = ACCEPTANCE / "wrong_receipt.json"; store = tmp_path / "delivery-store"; _write(source, json.loads(receipt.read_text()))
    assert native.ingest(source, store)["accepted"] == 1
    bank = tmp_path / "bank.jsonl"; bank.write_text("")
    result = tmp_path / "result.json"; native.evaluate(store, bank, result)
    mined = tmp_path / "mine.json"; native.mine(result, mined)
    row = json.loads(mined.read_text())["failures"][0]
    assert row["delivery_verdict"] == "fail" and row["delivery_checks"]["delivery_receipt"] == "fail" and row["source_digest"] and row["event_ids"]
    page = (tmp_path / "result.html").read_text()
    assert "delivery_receipt" in page and row["source_id"] in page and row["event_ids"][0] in page


def test_export_visible_calculation_case_and_tool_version_are_trace_bound(tmp_path):
    for field in ("calculation", "case_id", "tool_version"):
        export = json.loads((ACCEPTANCE / "apple-export.json").read_text())
        evidence = export["payload"]["evidence"]
        if field == "calculation":
            evidence[field]["operations"][0]["percent"] = "99.99"
        else:
            evidence[field] = "forged"
        # A fully rehashed export still cannot contradict its own raw tool trace.
        export["digest"] = native.sha(export["payload"])
        for event in export["events"]:
            event["digest"] = export["digest"]
        export["local_receipt"] = native.sha(next(e for e in export["events"] if e["kind"] == "delivered"))
        source, store = tmp_path / f"{field}.json", tmp_path / field
        _write(source, export)
        assert native.ingest(source, store)["quarantined"] == 1
        assert json.loads((store / "raw.jsonl").read_text())["reason"] == "export_trace_lineage_mismatch"
