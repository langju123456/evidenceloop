import hashlib
import json
from pathlib import Path

import pytest

from evidenceloop.report import peer_runs


ARCHIVE = Path(__file__).resolve().parents[1] / "reports/report-lab/peer-runs-v1.json"


def test_frozen_rows_keep_separate_authorities_and_denominators():
    data = json.loads(ARCHIVE.read_text())
    rows = data["rows"]
    assert len({r["run_id"] for r in rows}) == 16
    assert data["joint_product_environment_runs"] == 0
    assert data["forge_qa"] == {"pass": 3, "fail": 0, "unknown": 1, "n": 4}
    assert data["horizon_paired"]["retry_new_key"] == {
        "pass": 2, "n": 3, "fixed": ["request_lost"], "lost": ["receipt_lost_crash"]}
    abstention = next(r for r in rows if r["case_id"] == "catl.fy2022.cash")
    assert abstention["checks"]["safe_abstention"] and abstention["verdict"] == "unknown"
    dup = next(r for r in rows if r.get("strategy") == "retry_new_key" and r["fault"] == "receipt_lost_crash")
    assert dup["verdict"] == "fail" and dup["terminal_state"] == "completed"
    assert dup["checks"]["process_exit"] == -9
    assert len({i["idem_key"] for i in dup["delivered_artifacts"]}) == 2


def test_reject_receipt_digest_or_task_mismatch():
    content = {"payload": {"year": 2025}, "version": "v1"}
    raw = json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    item = dict(content, idem_key="k", task_id=peer_runs.HORIZON_TASK, digest=hashlib.sha256(raw).hexdigest())
    assert peer_runs.delivery_artifacts([item])[0]["digest"] == item["digest"]
    for changes in ({"payload": {"year": 2024}}, {"task_id": "other"}):
        with pytest.raises(ValueError, match="changed delivered content"):
            peer_runs.delivery_artifacts([{**item, **changes}])


def test_reject_incomplete_matrix_and_contradictory_process(monkeypatch):
    def check_fixture(cell_rows):
        def load(_repo, _sha, path, _project):
            if path.endswith("manifest.json"):
                return {"rows": cell_rows}, {}
            if path.endswith("verdict.json"):
                return {**cell_rows[0], "process_exit": 0, "recovery_exit": 0}, {}
            return {"initial_returncode": -9, "recovery_returncode": 0, "process_measured": False}, {}
        monkeypatch.setattr(peer_runs, "committed", load)
        peer_runs.horizon_rows("unused")
    with pytest.raises(ValueError, match="incomplete"):
        check_fixture([])
    with pytest.raises(ValueError, match="conflicting"):
        check_fixture([dict(strategy="assume_success", fault="ack", success=True, target_receipts=1,
                            local_status="completed", infrastructure_ok=True, process_measured=False, initial_returncode=0)])
