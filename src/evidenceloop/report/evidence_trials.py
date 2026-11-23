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


def run_command(args):
    model = args.model
    installed = {m["name"]: m["digest"] for m in request("tags")["models"]}
    if model not in installed:
        raise ValueError("choose an exact installed model tag; this experiment does not download weights")
    version = request("version")["version"]
    dataset = Path(args.prompts)
    items = read_json(dataset)
    out = Path(args.out)
    fingerprint = digest(dataset)
    with out.open("x", encoding="utf-8") as stream:
        for index, item in enumerate(items):
            rotation = index % len(ARMS)
            for arm in ARMS[rotation:] + ARMS[:rotation]:
                payload = {"model": model, "stream": False, "think": False, "format": "json",
                           "options": OPTIONS, "messages": messages(item, arm)}
                row = {"schema_version": 1, "case_id": item["case_id"], "arm": arm,
                       "run_id": f"{item['case_id']}--{arm}", "attempt": 1, "split": "public_dev",
                       "source_kind": "local_model", "document": item["document"],
                       "document_input": "curated_public_excerpts", "prompt_file_sha256": fingerprint,
                       "model_digest": installed[model], "ollama_version": version, "request": payload,
                       "tool_actions": [], "cost": {"external_charge_usd": 0, "energy_cost": None}}
                start = time.monotonic()
                try:
                    row["response"] = request("chat", payload)
                except (OSError, ValueError) as exc:
                    row["error"] = str(exc)
                row["latency_ms"] = round((time.monotonic() - start) * 1000)
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())


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


def summarize(prompts, path, reference_dir):
    items = read_json(prompts)
    case_by_id = {i["case_id"]: i for i in items}
    expected = {(i["case_id"], arm) for i in items for arm in ARMS}
    cases = read_json(reference_dir / "cases.json")
    sources = read_json(reference_dir / "sources.json")
    seen = set()
    configs = set()
    rows = []
    for raw in read_lines(path):
        key = (raw["case_id"], raw["arm"])
        if key not in expected or key in seen:
            raise ValueError(f"unexpected or duplicate pair: {key}")
        seen.add(key)
        item = case_by_id[key[0]]
        req = raw["request"]
        configs.add((req["model"], raw["model_digest"], raw["ollama_version"]))
        if (raw["prompt_file_sha256"] != digest(prompts) or raw["document"] != item["document"]
                or req["messages"] != messages(item, key[1]) or req["options"] != OPTIONS
                or req.get("think") is not False or req.get("format") != "json"):
            raise ValueError(f"changed experiment conditions: {key}")
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
    if seen != expected or len(configs) != 1:
        raise ValueError("incomplete or unmatched experiment")
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
    return {"split":"public_dev", "raw_sha256":digest(path), "model":list(next(iter(configs))),
            "summaries":summaries, "rows":rows}


def summary_command(args):
    print(json.dumps(summarize(Path(args.prompts), Path(args.log), Path(args.dataset)),
                     ensure_ascii=False, indent=2))
