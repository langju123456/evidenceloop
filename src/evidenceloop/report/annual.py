"""Deterministic scorer comparison for scoped, single-number annual report questions."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

METHODS = ("cited", "printed", "value_unit", "value_pages")
AMOUNT = re.compile(r"(?<![\d.,+−-])([+−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(千元|亿元|元|%|％)")
SCALES = {"千元": Decimal(1000), "亿元": Decimal(100000000), "元": Decimal(1)}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference(case, sources):
    cells = [sources["cells"][key] for key in case["cells"]]
    vals = [Decimal(c["value"]) for c in cells]
    if case["op"] == "read":
        value = vals[0]
    elif case["op"] == "growth":
        value = (vals[0] - vals[1]) / vals[1] * 100
    elif case["op"] == "contribution":
        value = (vals[0] - vals[1]) / (vals[2] - vals[3]) * 100
    else:
        raise ValueError(f"unknown operation {case['op']}")
    if case["op"] != "read":
        value = value.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)

    def evidence_path(items):
        return {(c["doc"], page) for c in items for page in (c["page"], c["header_page"])}

    paths = [evidence_path(cells)]
    if "alternative_sum" in case:
        quarters = [sources["cells"][k] for k in case["alternative_sum"]]
        if sum(Decimal(c["value"]) for c in quarters) != value:
            raise ValueError("quarterly sum differs from annual reference")
        paths.append(evidence_path(quarters))
    return value, paths


def extract_claim(text):
    claims = {(Decimal(n.replace(",", "").replace("−", "-")), u.replace("％", "%"))
              for n, u in AMOUNT.findall(text)}
    if len(claims) != 1:
        return None
    return claims.pop()


def score(case, obs, sources):
    expected, paths = reference(case, sources)
    pages = {(ref["doc"], ref["page"]) for ref in obs["citations"]}
    readable = obs["evidence_status"] == "available"
    claim = extract_claim(obs["answer"])
    values = "unknown"
    printed = "unknown"
    if claim is not None:
        value, unit = claim
        expected_unit = case["unit"]
        if unit in SCALES and expected_unit in SCALES:
            correct = value * SCALES[unit] == expected * SCALES[expected_unit]
        else:
            correct = value == expected and unit == expected_unit
        values = "pass" if correct else "fail"
        if readable:
            hit = any((c["doc"], c["page"]) in pages and Decimal(c["value"]) == value
                      for c in sources["cells"].values())
            printed = "pass" if hit else "fail"

    if not readable:
        support = "unknown"
    elif any(path <= pages for path in paths):
        support = "pass"
    elif not pages or not any(doc == case["cells"][0].split(".")[0] for doc, _ in pages):
        support = "fail"
    else:
        support = "unknown"  # Unannotated pages or incomplete cross-page evidence.
    # Page-only receipts make no cell-level assertion. An explicit locator must
    # never be silently discarded, even if its page and the answer are correct.
    located = [item for item in obs["citations"] if "cell" in item]
    cell_status = "not_supplied"
    if located and readable:
        possible = set(case["cells"] + case.get("alternative_sum", []))
        cell_status = "consistent"
        for ref in located:
            identifier = ref["cell"]
            cell = sources["cells"].get(identifier) if isinstance(identifier, str) else None
            if cell is None:
                cell_status = "unknown"
            elif (identifier not in possible or cell["doc"] != ref["doc"] or cell["page"] != ref["page"]):
                cell_status = "conflict"
                break
        if cell_status == "conflict":
            support = "fail"
        elif cell_status == "unknown" and support != "fail":
            support = "unknown"
    elif located:
        cell_status = "unknown"
    hard = (values, support)
    value_pages = "fail" if "fail" in hard else ("unknown" if "unknown" in hard else "pass")
    return {"scores": {"cited": "pass" if obs["answer"] and pages else "fail",
                       "printed": printed, "value_unit": values, "value_pages": value_pages},
            "checks": {"value_unit": values, "page_support": support,
                       "evidence_read": obs["evidence_status"], "explicit_cell": cell_status},
            "expected": str(expected), "unit": case["unit"]}


def compare(folder: Path):
    manifest = read_json(folder / "manifest.json")
    sources = read_json(folder / "sources.json")
    cases = read_json(folder / "cases.json")
    observations = read_lines(folder / "observations.jsonl")
    reviews = read_json(folder / "review.json")
    run_ids = [o["run_id"] for o in observations]
    if not run_ids or len(set(run_ids)) != len(run_ids) or set(reviews) != set(run_ids):
        raise ValueError("observations and reviews must pair one-to-one by run_id")
    rows = []
    for obs in observations:
        row = score(cases[obs["case_id"]], obs, sources)
        review = reviews[obs["run_id"]]
        rows.append(dict(run_id=obs["run_id"], case_id=obs["case_id"], origin=obs["source_kind"],
                         reviewed=review["verdict"], review_reason=review["reason"], **row))
    totals = {}
    for method in METHODS:
        matrix = Counter((r["reviewed"], r["scores"][method]) for r in rows)
        totals[method] = {
            "agreed": sum(count for (gold, pred), count in matrix.items() if gold == pred),
            "false_pass": matrix["fail", "pass"], "unknown_passed": matrix["unknown", "pass"],
            "correct_rejected": matrix["pass", "fail"],
            "fixed_vs_cited": [r["run_id"] for r in rows if r["scores"]["cited"] != r["reviewed"]
                               and r["scores"][method] == r["reviewed"]],
            "regressed_vs_cited": [r["run_id"] for r in rows if r["scores"]["cited"] == r["reviewed"]
                                   and r["scores"][method] != r["reviewed"]],
            "matrix": {gold: {pred: matrix[gold, pred] for pred in ("pass", "fail", "unknown")}
                       for gold in ("pass", "fail", "unknown")}}
    inputs = {name: digest(folder / name) for name in
              ["manifest.json", "cases.json", "sources.json", "observations.jsonl", "review.json"]}
    return {"schema_version": 1, "scorer_version": "page-support-1.1", "dataset_version": manifest["dataset_version"],
            "split": manifest["split"], "input_sha256": inputs, "totals": totals, "rows": rows}


def compare_command(args):
    result = compare(Path(args.dataset))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def verify_sources(folder, pdf_dir, archive):
    sources = read_json(folder / "sources.json")
    manifest = read_json(folder / "manifest.json")
    for doc in sources["documents"].values():
        if digest(pdf_dir / doc["filename"]) != doc["sha256"]:
            raise ValueError(f"PDF digest mismatch: {doc['filename']}")
    if digest(archive) != manifest["archive"]["sha256"]:
        raise ValueError("ForgeFlow archive digest mismatch")
    records = {r["job_id"]: r for r in read_json(archive)["sequential"]}
    checked = 0
    for row in read_lines(folder / "observations.jsonl"):
        if row["source_kind"] != "archived_model":
            continue
        raw = records[row["run_id"]]
        encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        doc = sources["companies"][raw["citations"][0]["company"]]
        citations = [{"doc": sources["companies"][c["company"]], "page": c["page"]} for c in raw["citations"]]
        case = read_json(folder / "cases.json")[row["case_id"]]
        if (raw != row["archived_record"] or raw["answer"] != row["answer"]
                or case["question"] != raw["question"] or citations != row["citations"]
                or doc != case["cells"][0].split(".")[0]
                or hashlib.sha256(encoded).hexdigest() != row["artifact_refs"][0]["sha256"]):
            raise ValueError(f"archived record mismatch: {row['run_id']}")
        checked += 1
    return {"verified_documents": len(sources["documents"]), "verified_archived_runs": checked}


def verify_command(args):
    print(json.dumps(verify_sources(Path(args.dataset), Path(args.pdf_dir), Path(args.archive))))
