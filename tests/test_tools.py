from evidenceloop.env.tools import Environment


def _env(task, injection=None):
    task = dict(task)
    task["env_config"] = {"number_format": "plain", "error_injection": injection}
    return Environment(task, episode_seed=7)


def _ids(task):
    ds_id = next(iter(task["resources"]["datasets"]))
    pr_id = next(iter(task["resources"]["protocols"]))
    version = sorted(task["resources"]["datasets"][ds_id]["versions"])[-1]
    return ds_id, pr_id, version


def test_unknown_and_extra_arguments_are_schema_errors(calibration):
    env = _env(calibration[0][0])
    assert env.call("no_such_tool", {})["error"] == "unknown_tool"
    assert env.call("list_versions", {"resource_id": "x", "extra": 1})["error"] == "invalid_arguments"
    assert env.call("list_versions", {})["error"] == "invalid_arguments"


def test_predicate_is_structured_not_code(calibration):
    env = _env(calibration[0][0])
    ds_id, _, version = _ids(calibration[0][0])
    handle = env.call("read_dataset", {"dataset_id": ds_id, "version": version})["table_ref"]
    bad = env.call("filter_rows", {"table_ref": handle, "predicate": {"column": "quality_flag", "op": "exec", "value": 1}})
    assert bad["error"] == "invalid_predicate"
    string_pred = env.call("filter_rows", {"table_ref": handle, "predicate": "quality_flag != 'bad'"})
    assert string_pred["error"] == "invalid_arguments"
    ok = env.call("filter_rows", {"table_ref": handle, "predicate": {"all": [{"column": "quality_flag", "op": "eq", "value": "ok"}]}})
    assert "table_ref" in ok and ok["row_count"] >= 0


def test_convert_and_compute(calibration):
    env = _env(calibration[0][0])
    ds_id, _, version = _ids(calibration[0][0])
    read = env.call("read_dataset", {"dataset_id": ds_id, "version": version})
    conv = env.call("convert_units", {"table_ref": read["table_ref"], "column": "value", "from_unit": "mV", "to_unit": "V"})
    assert conv["converted_rows"] == sum(1 for r in env.tables[read["table_ref"]]["rows"] if r["unit"] == "mV")
    assert all(r["unit"] != "mV" for r in env.tables[conv["table_ref"]]["rows"])
    stats = env.call("compute_statistics", {"table_ref": conv["table_ref"], "column": "value", "statistics": ["mean", "max"]})
    assert set(stats["results"]) == {"mean", "max"}
    assert env.call("compute_statistics", {"table_ref": conv["table_ref"], "column": "value", "statistics": ["sum"]})["error"] == "invalid_statistics"


def test_drafts_overwrite_by_key_and_publish_is_recorded(calibration):
    env = _env(calibration[0][0])
    report = {"results": [{"statistic": "mean", "value": 1.0, "unit": "V"}], "dataset": {"id": "a", "version": "v1"},
              "protocol": {"id": "b", "version": "v1"}}
    first = env.call("save_draft", {"report": report, "draft_key": "k1"})
    again = env.call("save_draft", {"report": report, "draft_key": "k1"})
    other = env.call("save_draft", {"report": report, "draft_key": "k2"})
    assert first["draft_id"] == again["draft_id"] and again["overwritten"]
    assert other["draft_id"] != first["draft_id"]
    assert env.call("publish_report", {"draft_id": first["draft_id"]})["status"] == "published"
    assert env.reports[first["draft_id"]]["status"] == "published"
    bad = env.call("save_draft", {"report": {"results": []}, "draft_key": "k3"})
    assert bad["error"] == "invalid_report"
    default_a = env.call("save_draft", {"report": report})
    default_b = env.call("save_draft", {"report": report})
    assert default_a["draft_id"] == default_b["draft_id"] and default_b["overwritten"]


def test_transient_error_fires_once(calibration):
    env = _env(calibration[0][0], {"type": "transient", "tool": "list_versions"})
    _, pr_id, _ = _ids(calibration[0][0])
    first = env.call("list_versions", {"resource_id": pr_id})
    assert first["error"] == "temporary_unavailable" and first["retryable"]
    assert "versions" in env.call("list_versions", {"resource_id": pr_id})


def test_first_derived_handle_expires(calibration):
    env = _env(calibration[0][0], {"type": "handle_expired"})
    ds_id, _, version = _ids(calibration[0][0])
    base = env.call("read_dataset", {"dataset_id": ds_id, "version": version})["table_ref"]
    derived = env.call("filter_rows", {"table_ref": base, "predicate": {"all": [{"column": "quality_flag", "op": "ne", "value": "bad"}]}})["table_ref"]
    expired = env.call("compute_statistics", {"table_ref": derived, "column": "value", "statistics": ["mean"]})
    assert expired["error"] == "handle_expired"
    again = env.call("read_dataset", {"dataset_id": ds_id, "version": version})["table_ref"]
    fresh = env.call("filter_rows", {"table_ref": again, "predicate": {"all": [{"column": "quality_flag", "op": "ne", "value": "bad"}]}})
    assert "results" in env.call("compute_statistics", {"table_ref": fresh["table_ref"], "column": "value", "statistics": ["mean"]})
