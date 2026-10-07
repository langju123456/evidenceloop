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


def test_filter_is_one_flat_condition_not_code(calibration):
    env = _env(calibration[0][0])
    ds_id, _, version = _ids(calibration[0][0])
    handle = env.call("read_dataset", {"dataset_id": ds_id, "version": version})["table_ref"]
    assert env.call("filter_rows", {"table_ref": handle, "column": "quality_flag", "op": "exec", "value": 1})["error"] == "invalid_predicate"
    assert env.call("filter_rows", {"table_ref": handle, "column": "quality_flag", "op": "not_in", "value": "bad"})["error"] == "invalid_predicate"
    ok = env.call("filter_rows", {"table_ref": handle, "column": "quality_flag", "op": "not_in", "value": ["bad", "missing"]})
    assert "table_ref" in ok


def test_json_encoded_lists_are_accepted_but_nothing_looser(calibration):
    """D6: a list sent as a JSON string is the same list; a bare word is not."""
    env = _env(calibration[0][0])
    ds_id, _, version = _ids(calibration[0][0])
    handle = env.call("read_dataset", {"dataset_id": ds_id, "version": version})["table_ref"]
    encoded = env.call("filter_rows", {"table_ref": handle, "column": "quality_flag", "op": "not_in", "value": '["bad", "missing"]'})
    direct = env.call("filter_rows", {"table_ref": handle, "column": "quality_flag", "op": "not_in", "value": ["bad", "missing"]})
    assert encoded["row_count"] == direct["row_count"]
    assert "results" in env.call("compute_statistics", {"table_ref": direct["table_ref"], "column": "value", "statistics": '["mean"]'})
    assert env.call("compute_statistics", {"table_ref": direct["table_ref"], "column": "value", "statistics": "mean"})["error"] == "invalid_arguments"


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
    report = {"dataset_id": "a", "dataset_version": "v1", "protocol_id": "b", "protocol_version": "v1", "unit": "V", "mean": 1.0}
    first = env.call("save_draft", {**report, "draft_key": "k1"})
    again = env.call("save_draft", {**report, "draft_key": "k1"})
    other = env.call("save_draft", {**report, "draft_key": "k2"})
    assert first["draft_id"] == again["draft_id"] and again["overwritten"]
    assert other["draft_id"] != first["draft_id"]
    assert env.call("publish_report", {"draft_id": first["draft_id"]})["status"] == "published"
    assert env.reports[first["draft_id"]]["status"] == "published"
    no_stats = {k: v for k, v in report.items() if k != "mean"}
    assert env.call("save_draft", {**no_stats, "draft_key": "k3"})["error"] == "invalid_report"
    assert env.call("save_draft", {**report, "mean": "about one"})["error"] == "invalid_arguments"
    default_a = env.call("save_draft", report)
    default_b = env.call("save_draft", report)
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
    derived = env.call("filter_rows", {"table_ref": base, "column": "quality_flag", "op": "ne", "value": "bad"})["table_ref"]
    expired = env.call("compute_statistics", {"table_ref": derived, "column": "value", "statistics": ["mean"]})
    assert expired["error"] == "handle_expired"
    again = env.call("read_dataset", {"dataset_id": ds_id, "version": version})["table_ref"]
    fresh = env.call("filter_rows", {"table_ref": again, "column": "quality_flag", "op": "ne", "value": "bad"})
    assert "results" in env.call("compute_statistics", {"table_ref": fresh["table_ref"], "column": "value", "statistics": ["mean"]})
