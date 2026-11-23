"""Run bounded public development prompts on the local Ollama installation."""

import json
import os
import time
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from evidenceloop.report.annual import digest, read_json, read_lines, score

ARMS = ("row", "header", "selected")
OPTIONS = {"num_ctx": 4096, "num_predict": 160, "seed": 23, "temperature": 0}
SYSTEM = (
    '只使用本题所给年报摘录作答。无法从证据确认时状态写 unknown。'
    '只输出 JSON，格式为 {"status":"answered 或 unknown","value":"数值或空串",'
    '"unit":"千元或%或空串","pages":[页码整数],"explanation":"一句话说明取值或分母"}。'
    '百分数用百分比数值，不含百分号，按题目精度舍入。'
)
LOCAL_URL = "http://127.0.0.1:11434/api/"
DATASET = "benchmarks/report_dev/evidence-arms-v1.json"


def request(endpoint, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request(LOCAL_URL + endpoint, data=body, headers={"Content-Type": "application/json"})
    # A local, already-installed model is the only service this command may contact.
    with build_opener(ProxyHandler({})).open(req, timeout=240) as response:
        return json.load(response)


def messages(item, arm):
    prompt = item["question"] + "\n\n年报摘录：\n" + "\n".join(item["arms"][arm])
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]


def run_paired(args, arms, build_messages, *, split="public_dev", freeze=None, required_model=None):
    model = args.model
    installed = {m["name"]: m["digest"] for m in request("tags")["models"]}
    if model not in installed:
        raise ValueError("choose an exact installed model tag; this experiment does not download weights")
    version = request("version")["version"]
    if required_model and (model, installed[model], version) != required_model:
        raise ValueError("installed inference stack differs from the frozen protocol")
    dataset = Path(args.prompts)
    items = read_json(dataset)
    out = Path(args.out)
    fingerprint = digest(dataset)
    with out.open("x", encoding="utf-8") as stream:
        for index, item in enumerate(items):
            rotation = index % len(arms)
            for arm in arms[rotation:] + arms[:rotation]:
                payload = {"model": model, "stream": False, "think": False, "format": "json",
                           "options": OPTIONS, "messages": build_messages(item, arm)}
                row = {"schema_version": 1, "case_id": item["case_id"], "arm": arm,
                       "run_id": f"{item['case_id']}--{arm}", "attempt": 1, "split": split,
                       "source_kind": "local_model", "document": item["document"],
                       "document_input": "curated_public_excerpts", "prompt_file_sha256": fingerprint,
                       "model_digest": installed[model], "ollama_version": version, "request": payload,
                       "tool_actions": [], "cost": {"external_charge_usd": 0, "energy_cost": None}}
                if freeze is not None:
                    row["freeze_commit"] = freeze
                start = time.monotonic()
                try:
                    row["response"] = request("chat", payload)
                except (OSError, ValueError) as exc:
                    row["error"] = str(exc)
                row["latency_ms"] = round((time.monotonic() - start) * 1000)
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())


def run_command(args):
    run_paired(args, ARMS, messages)


def parse_response(row):
    if "error" in row:
        return "infra_error", None
    try:
        response = row["response"]
        content = json.loads(response["message"]["content"])
        if not response.get("done") or not isinstance(content, dict):
            return "invalid", None
        if content.get("status") == "unknown":
            return "abstained", content
        if (content.get("status") != "answered" or not isinstance(content.get("pages"), list)
                or not all(type(p) is int and p > 0 for p in content["pages"])
                or type(content.get("value")) not in (int, float, str)
                or content.get("unit") not in ("千元", "%")):
            return "invalid", content
        return "answered", content
    except (KeyError, TypeError, ValueError):
        return "invalid", None


def checked_archive(prompts, log, arms, build_messages, *, split="public_dev", freeze=None):
    items = read_json(prompts)
    cases = {item["case_id"]: item for item in items}
    if not cases or len(cases) != len(items):
        raise ValueError("empty or duplicate public cases")
    expected = {(cid, arm) for cid in cases for arm in arms}
    fingerprint = digest(prompts)
    seen = set()
    configs = set()
    records = read_lines(log)
    for row in records:
        cid, arm = row["case_id"], row["arm"]
        key = (cid, arm)
        if key not in expected or key in seen:
            raise ValueError(f"unexpected or duplicate pair: {key}")
        seen.add(key)
        item = cases[cid]
        req = row["request"]
        configs.add((req["model"], row["model_digest"], row["ollama_version"]))
        expected_request = {"model":req["model"], "stream":False, "think":False, "format":"json",
                            "options":OPTIONS, "messages":build_messages(item, arm)}
        if (row["prompt_file_sha256"] != fingerprint or row["document"] != item["document"]
                or req != expected_request or row["run_id"] != f"{cid}--{arm}"
                or row["source_kind"] != "local_model" or row["attempt"] != 1
                or row["split"] != split or row.get("freeze_commit") != freeze or row["schema_version"] != 1
                or ("response" in row) == ("error" in row)
                or ("response" in row and row["response"].get("model") != req["model"])):
            raise ValueError(f"changed experiment conditions: {key}")
    if seen != expected or len(configs) != 1:
        raise ValueError("incomplete or unmatched experiment")
    return records, next(iter(configs))


def summarize(prompts, path, reference_dir):
    cases = read_json(reference_dir / "cases.json")
    sources = read_json(reference_dir / "sources.json")
    records, config = checked_archive(prompts, path, ARMS, messages)
    rows = []
    for raw in records:
        key = (raw["case_id"], raw["arm"])
        state, content = parse_response(raw)
        verdict = "unknown" if state == "infra_error" else "fail"
        checks = None
        if state == "answered":
            obs = {"answer": f"{content['value']} {content['unit']}", "evidence_status": "available",
                   "citations": [{"doc": raw["document"], "page": p} for p in content["pages"]]}
            checks = score(cases[key[0]], obs, sources)
            verdict = checks["scores"]["value_pages"]
        resp = raw.get("response", {})
        rows.append({"run_id":raw["run_id"], "case_id":key[0], "arm":key[1], "state":state,
                     "reply":content, "checks":checks, "verdict":verdict, "latency_ms":raw["latency_ms"],
                     "input_tokens":resp.get("prompt_eval_count"), "output_tokens":resp.get("eval_count")})
    by_key = {(r["case_id"],r["arm"]):r for r in rows}
    summaries = {}
    for arm in ARMS:
        subset = [r for r in rows if r["arm"] == arm]
        summaries[arm] = {
            "n":len(subset), "pass":sum(r["verdict"] == "pass" for r in subset),
            "unknown":sum(r["verdict"] == "unknown" for r in subset),
            "fixed":[r["case_id"] for r in subset if r["verdict"] == "pass"
                     and by_key[r["case_id"], "row"]["verdict"] != "pass"],
            "lost":[r["case_id"] for r in subset if r["verdict"] != "pass"
                    and by_key[r["case_id"], "row"]["verdict"] == "pass"]}
    return {"split":"public_dev", "raw_sha256":digest(path), "model":list(config),
            "summaries":summaries, "rows":rows}


def summary_command(args):
    print(json.dumps(summarize(Path(args.prompts), Path(args.log), Path(args.dataset)),
                     ensure_ascii=False, indent=2))
