"""Read pinned upstream public experiments. Producer verdicts stay attributable."""

import hashlib
import json
import subprocess
from pathlib import Path

from evidenceloop.report.annual import extract_claim

FORGE = "e195a0a2f764d30e2d1b5be8a131ceeef95d4b71"
HORIZON = "c69eb0ef2a32a45eef8057ab7ebd3065e8cc7f88"
CASH = "preparation/annual-report-workbench/annual-cash-dev.json"
RECEIPTS = "reports/receipt-experiment"
PDF_SHA = "c15272977147dee7e6935a38ea0e4fd6855370aabb106f54cfe20f7cf6048ec9"
# Independent transcription from CATL FY2025 page 11. This table does not disclose FY2022.
ANNUAL = {2025: 133219982, 2024: 96990345, 2023: 92826124, 2022: None}
STRATEGIES = ("assume_success", "wait_for_human", "retry_new_key", "reconcile_original_key")
FAULTS = ("ack", "request_lost", "receipt_lost_crash")
HORIZON_TASK = "catl-fy2025-cfo-receipt"  # TASK_ID in the pinned producer scenario


def committed(repo, sha, path, project):
    raw = subprocess.check_output(["git", "-C", str(repo), "show", f"{sha}:{path}"])
    return json.loads(raw), {
        "ref": f"https://github.com/langju123456/{project}/blob/{sha}/{path}",
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def forge_rows(repo):
    bundle, artifact = committed(repo, FORGE, CASH, "forgeflow")
    if (bundle["schema_version"] != 1 or bundle["split"] != "public-dev"
            or bundle["source"]["sha256"] != PDF_SHA):
        raise ValueError("unexpected ForgeFlow report source or version")
    questions = {f"宁德时代 {year} 年经营活动产生的现金流量净额是多少？": year for year in ANNUAL}
    seen = set()
    rows = []
    for run in bundle["product_runs"]:
        year = questions[run["request"]]
        if year in seen:
            raise ValueError("duplicate financial period")
        seen.add(year)
        amount = extract_claim(run["answer"])
        has_page = any(c["page"] == 11 and c["id"] == "catl_2025_annual_zh#p11-t1"
                       for c in run["citations"])
        reference = ANNUAL[year]
        number_ok = (amount == (reference, "千元")) if reference is not None else None
        safe_abstention = reference is None and run["status"] == "PERIOD_UNVERIFIED" and amount is None
        if reference is None:
            verdict = "unknown" if safe_abstention else "fail"
            reason = "period_absent" if safe_abstention else "unsupported_answer"
        else:
            verdict = "pass" if run["status"] == "ANSWERED" and number_ok and has_page else "fail"
            reason = "annual_value_unit_and_source" if verdict == "pass" else "value_unit_source_or_status"
        rows.append({
            "run_id": f"forgeflow/{FORGE[:12]}/annual-cash/{year}", "id_origin": "derived_from_archive",
            "case_id": f"catl.fy{year}.cash", "producer_case_id": bundle["case_id"], "task_id": None,
            "attempt": 1, "source": "ForgeFlow", "source_kind": "real_product_route_deterministic_tool",
            "producer_commit": FORGE, "model": bundle["model"], "data_version": PDF_SHA,
            "index_version": bundle["index_version"], "tool_version": bundle["tool_version"],
            "transport": bundle["transport"], "tool_actions": None, "artifact_refs": [artifact],
            "terminal_state": run["status"], "latency_ms": run["wall_ms"],
            "cost": {"bundle_external_cost": bundle["external_cost"], "bundle_model_calls": bundle["model_calls"]},
            "question": run["request"], "answer": run["answer"], "citations": run["citations"],
            "checks": {"matches_annual_value_unit": number_ok, "cites_annual_table": has_page,
                       "safe_abstention": safe_abstention},
            "reference_value_thousand_cny": reference, "reason": reason, "verdict": verdict,
        })
    if seen != set(ANNUAL):
        raise ValueError("missing year in ForgeFlow archive")
    return rows


def delivery_artifacts(inbox):
    items = []
    for item in inbox:
        content = {"payload": item["payload"], "version": item["version"]}
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        if item["task_id"] != HORIZON_TASK or hashlib.sha256(raw).hexdigest() != item["digest"]:
            raise ValueError("unexpected task or changed delivered content")
        items.append({k: item[k] for k in ("task_id", "idem_key", "version", "digest")})
    return items


def horizon_rows(repo):
    manifest, manifest_ref = committed(repo, HORIZON, RECEIPTS + "/manifest.json", "horizon-bench")
    seen = set()
    expected = {(s, f) for s in STRATEGIES for f in FAULTS}
    rows = []
    for cell in manifest["rows"]:
        strategy, fault = cell["strategy"], cell["fault"]
        key = strategy, fault
        if key in seen or key not in expected:
            raise ValueError("foreign or duplicate receipt cell")
        seen.add(key)
        prefix = f"{RECEIPTS}/{strategy}--{fault}/"
        verdict, vref = committed(repo, HORIZON, prefix + "verdict.json", "horizon-bench")
        process, pref = committed(repo, HORIZON, prefix + "process.json", "horizon-bench")
        common = ("strategy", "fault", "success", "target_receipts", "local_status",
                  "infrastructure_ok", "process_measured")
        if (any(cell[k] != verdict[k] for k in common)
                or process["initial_returncode"] != cell["initial_returncode"]
                or process["initial_returncode"] != verdict["process_exit"]
                or process["recovery_returncode"] != verdict["recovery_exit"]
                or process["process_measured"] != cell["process_measured"]):
            raise ValueError("conflicting producer verdict and process receipt")
        rows.append({
            "run_id": f"horizon/{HORIZON[:12]}/{strategy}--{fault}", "id_origin": "derived_from_archive",
            "case_id": f"catl.receipt.{fault}", "task_id": HORIZON_TASK, "attempt": 1,
            "source": "HorizonBench", "source_kind": "scripted_strategy_local_environment",
            "producer_commit": HORIZON, "model": None, "data_version": "D001/" + HORIZON[:12],
            "strategy": strategy, "fault": fault, "tool_actions": None,
            "environment_events": verdict["events"], "artifact_refs": [manifest_ref, vref, pref],
            "terminal_state": verdict["local_status"], "latency_ms": None, "cost": None,
            "checks": {"independent_accepted": verdict["accepted"], "target_receipts": verdict["target_receipts"],
                       "process_measured": process["process_measured"], "process_exit": verdict["process_exit"],
                       "infrastructure_ok": verdict["infrastructure_ok"]},
            "delivered_artifacts": delivery_artifacts(verdict["inbox"]), "reason": verdict["reason"],
            "verdict": "pass" if verdict["success"] else "fail",
        })
    if seen != expected:
        raise ValueError("incomplete HorizonBench receipt matrix")
    return rows


FORGE_REVIEW = "b74c8bb439658d1530a762391e13ae1861bd8968"
HB_DELIVERY = "afe78553a9f55780e7232646b80c22fa8a51ed38"
DELIVERY_MATRIX = "reports/forgeflow-delivery/matrix.json"
MATRIX_SHA = "73c1e309d9ec7b010ee27abfd4333d32590d3224efdc7d3b2350a1528593ec43"
WORLDS = ("approved_v2_once", "inbox_empty", "approved_v2_twice", "returned_v1_once", "approval_corrupted")
READERS = ("local_delivered", "upstream_chain", "inbox_count", "full_reconcile")


def canonical_digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_matrix(rows, version_digests):
    pairs = {(r["world"], r["reader"]) for r in rows}
    if len(rows) != len(WORLDS) * len(READERS) or pairs != {(w, r) for w in WORLDS for r in READERS}:
        raise ValueError("expected one result for each world and reader")
    for row in rows:
        for receipt in row["receipt_summary"]:
            if receipt["version"] not in version_digests or receipt["digest"] != version_digests[receipt["version"]]:
                raise ValueError("receipt does not belong to the archived revision")


def linked_delivery(forge, horizon):
    matrix, matrix_ref = committed(horizon, HB_DELIVERY, DELIVERY_MATRIX, "horizon-bench")
    upstream = matrix["upstream"]
    if matrix_ref["sha256"] != MATRIX_SHA or upstream["source_commit"] != FORGE_REVIEW:
        raise ValueError("unexpected delivery matrix or upstream commit")
    prefix = "preparation/annual-report-workbench/"
    index, index_ref = committed(forge, FORGE_REVIEW, prefix + "review-dev.json", "forgeflow")
    if (index_ref["sha256"] != upstream["review_sha256"]
            or any(index[k] != upstream[k] for k in ("case_id", "draft_id", "versions", "tool_run_ids", "local_receipt"))):
        raise ValueError("delivery matrix points to a different review")
    asks = [call["run_id"] for call in index["calls"] if call["path"] == "/reports/ask" and call["http"] == 200]
    entries = index["versions"]
    if ([r["version"] for r in entries] != [1, 2] or [r["run_id"] for r in entries] != asks
            or len(set(asks)) != 2 or asks != upstream["tool_run_ids"]):
        raise ValueError("expected both revision queries")
    refs = {ref["file"]: ref["sha256"] for ref in index["artifact_refs"]}
    revisions = []
    for entry in entries:
        version = entry["version"]
        filename = f"apple-review-v{version}.json"
        export, ref = committed(forge, FORGE_REVIEW, prefix + filename, "forgeflow")
        payload = export["payload"]
        evidence = payload["evidence"]
        revision = canonical_digest(payload)
        previous = revisions[-1]["revision_digest"] if revisions else None
        if (ref["sha256"] != refs[filename] or revision != export["digest"] or revision != entry["revision_digest"]
                or revision != upstream[f"v{version}"] or payload["version"] != version or payload["parent_digest"] != previous
                or payload["draft_id"] != index["draft_id"] or evidence["case_id"] != index["case_id"]
                or evidence["run_id"] != entry["run_id"]):
            raise ValueError("revision does not match the product query or draft")
        events = export["events"]
        expected_events = ["saved", "submitted", "returned"] if version == 1 else ["saved", "submitted", "approved", "delivered"]
        if ([e["kind"] for e in events] != expected_events or export["state"] != expected_events[-1]
                or any((e["digest"], e["version"], e["draft"]) != (revision, version, index["draft_id"]) for e in events)):
            raise ValueError("events do not refer to the same revision")
        receipt = canonical_digest(events[-1]) if version == 2 else None
        if export["local_receipt"] != receipt or (version == 2 and receipt != upstream["local_receipt"]):
            raise ValueError("wrong local delivery receipt")
        revisions.append({
            "version": version, "run_id": evidence["run_id"], "question": evidence["question"],
            "answer": evidence["answer"], "citations": [{"page": c["page"], "id": c["id"]} for c in evidence["citations"]],
            "revision_digest": revision, "parent_digest": previous, "state": export["state"],
            "inbox_payload_digest": canonical_digest({"payload": payload, "version": str(version)}),
            "local_receipt": receipt, "events": events, "artifact_ref": ref,
        })
    if revisions[-1]["inbox_payload_digest"] != upstream["payload_digest"]:
        raise ValueError("approved payload differs from the matrix")
    validate_matrix(matrix["rows"], {str(r["version"]): r["inbox_payload_digest"] for r in revisions})
    return {
        "case_id": index["case_id"], "draft_id": index["draft_id"], "product_commit": FORGE_REVIEW,
        "environment_commit": HB_DELIVERY, "review_index": index_ref, "matrix_ref": matrix_ref,
        "product_driver": index["driver"], "model_calls": index["model_calls"],
        "revisions": revisions, "simulated_receipt_matrix": matrix["rows"],
    }


def import_peers(forge, horizon):
    ff = forge_rows(forge)
    hb = horizon_rows(horizon)
    by_key = {(r["strategy"], r["fault"]): r["verdict"] for r in hb}
    pairs = {}
    for strategy in STRATEGIES:
        pairs[strategy] = {
            "pass": sum(by_key[strategy, f] == "pass" for f in FAULTS), "n": len(FAULTS),
            "fixed": [f for f in FAULTS if by_key["assume_success", f] == "fail" and by_key[strategy, f] == "pass"],
            "lost": [f for f in FAULTS if by_key["assume_success", f] == "pass" and by_key[strategy, f] == "fail"],
        }
    return {
        "schema_version": "report-receipts/1", "split": "public_dev", "joint_product_environment_runs": 0,
        "forge_qa": {**{v: sum(r["verdict"] == v for r in ff) for v in ("pass", "fail", "unknown")}, "n": len(ff)},
        "horizon_paired": pairs, "rows": ff + hb, "apple_delivery": linked_delivery(forge, horizon),
    }


def command(args):
    print(json.dumps(import_peers(Path(args.forge_repo), Path(args.horizon_repo)), ensure_ascii=False, indent=2))
