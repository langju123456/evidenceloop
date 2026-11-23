"""One prospective document-transfer experiment using D18's three existing strategies."""

import hashlib
import json
import re
import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from evidenceloop.report import calculation
from evidenceloop.report.annual import read_json
from evidenceloop.report.evidence_trials import run_paired

ROOT = Path(__file__).resolve().parents[3]
DATA = Path("benchmarks/report_holdout/v1")
FROZEN_FILES = tuple(DATA / file for file in ("protocol.json", "questions.json", "references.json")) + tuple(
    Path(file) for file in (
        "src/evidenceloop/report/issuer_holdout.py", "src/evidenceloop/report/calculation.py",
        "src/evidenceloop/report/evidence_trials.py", "src/evidenceloop/report/annual.py",
        "src/evidenceloop/cli.py", "docs/report-lab/06-cross-document.md",
    )
)


def check_freeze(commit):
    if not re.fullmatch("[0-9a-f]{40}", commit):
        raise ValueError("use the full preregistration commit SHA")
    fingerprints = {}
    for path in FROZEN_FILES:
        raw = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{commit}:{path}"])
        if raw != (ROOT / path).read_bytes():
            raise ValueError(f"changed since freeze: {path}")
        fingerprints[str(path)] = hashlib.sha256(raw).hexdigest()
    return fingerprints


def diagnose(row, case):
    if row["verdict"] == "unknown":
        return ["inference_unavailable"]
    if row["receipt"] is None:
        return ["invalid_response_or_arguments"]
    tags = []
    decision = row["decision"]
    pages = decision.get("pages")
    if not isinstance(pages, list) or set_safe_pages(pages) != {case["page"]}:
        tags.append("citation_does_not_locate_table")
    _, year, metric = row["case_id"].split(".")
    current, prior = year[-2:], str(int(year) - 1)[-2:]
    if row["arm"] == "metric_tool":
        if decision["year"] != int(year):
            tags.append("wrong_fiscal_year")
        if decision["series"] != "Services":
            tags.append("wrong_series")
        expected_metric = "yoy_growth" if metric == "growth" else "share_of_change"
        if decision["metric"] != expected_metric:
            tags.append("wrong_metric")
    if row["arm"] == "cells":
        if decision["numerator"] != ["S" + current, "S" + prior]:
            tags.append("different_numerator_cells")
        denominator = ["S" + prior] if metric == "growth" else ["T" + current, "T" + prior]
        if decision["denominator"] != denominator:
            tags.append("different_denominator_cells")
    if Decimal(row["receipt"]["value"]) != Decimal(row["expected"]) and row["arm"] == "direct":
        tags.append("wrong_number_internal_cause_unobserved")
    return tags


def set_safe_pages(pages):
    return {p for p in pages} if all(type(p) is int for p in pages) else set()


def evaluate(commit, log):
    fingerprints = check_freeze(commit)
    protocol = read_json(ROOT / DATA / "protocol.json")
    prompts = ROOT / DATA / "questions.json"
    result = calculation.summarize(prompts, ROOT / DATA / "references.json", log,
                                   split=protocol["split"], freeze=commit)
    if result["model"] != protocol["model"]:
        raise ValueError("unexpected model, weights or inference server")
    cases = {case["case_id"]: case for case in read_json(prompts)}
    for row in result["rows"]:
        row["observed_errors"] = diagnose(row, cases[row["case_id"]])
    baseline = {r["case_id"]: r["verdict"] for r in result["rows"] if r["arm"] == "direct"}
    for arm, totals in result["summaries"].items():
        rows = [r for r in result["rows"] if r["arm"] == arm]
        totals["fixed"] = [r["case_id"] for r in rows
                           if baseline[r["case_id"]] == "fail" and r["verdict"] == "pass"]
        totals["unknown_to_pass"] = [r["case_id"] for r in rows
                                     if baseline[r["case_id"]] == "unknown" and r["verdict"] == "pass"]
        totals["failed"] = sum(r["verdict"] == "fail" for r in rows)
        totals["unknown"] = sum(r["verdict"] == "unknown" for r in rows)
        totals["by_issuer"] = {issuer: sum(r["verdict"] == "pass" for r in rows
                                         if cases[r["case_id"]]["document"] == issuer)
                               for issuer in protocol["documents"]}
        totals["model_ms_sum"] = sum(r["model_ms"] for r in rows)
        for name in ("input_tokens", "output_tokens"):
            counts = [r[name] for r in rows]
            totals[name] = sum(counts) if all(isinstance(n, int) for n in counts) else None
    candidate = result["summaries"]["metric_tool"]
    result["candidate_meets_pilot_gate"] = (
        candidate["pass"] >= 6 and len(candidate["fixed"]) >= 1 and not candidate["lost"]
        and not candidate["unknown"] and min(candidate["by_issuer"].values()) >= 2
        and all(r["verdict"] == "pass" for r in result["rows"]
                if r["arm"] == "metric_tool" and Decimal(r["expected"]) < 0))
    result.update(freeze_commit=commit, frozen_sha256=fingerprints, issuer_families=len(protocol["documents"]),
                  independent_human_reviews=0)
    return result


def command(args):
    if args.action == "run-issuer-holdout":
        check_freeze(args.freeze)
        protocol = read_json(ROOT / DATA / "protocol.json")
        config = tuple(protocol["model"])
        request = SimpleNamespace(model=config[0], prompts=ROOT / DATA / "questions.json", out=args.out)
        run_paired(request, calculation.ARMS, calculation.messages, split=protocol["split"],
                   freeze=args.freeze, required_model=config)
    else:
        print(json.dumps(evaluate(args.freeze, Path(args.log)), ensure_ascii=False, indent=2))
