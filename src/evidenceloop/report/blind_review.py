"""Prepare blind public-dev packets and reconcile returned judgements offline."""

import hashlib
import json
import os
import secrets
from collections import defaultdict
from pathlib import Path

from evidenceloop.report.annual import digest, read_json, read_lines, score
from evidenceloop.report.review_page import details, esc, table

FILES = ("observations.jsonl", "cases.json", "sources.json")
SEED = "report-review-v1"
LABELS = ("pass", "fail", "unknown")


def opaque(value):
    return hashlib.sha256((SEED + "/" + value).encode()).hexdigest()


def load(folder):
    observations = read_lines(folder / FILES[0])
    cases = read_json(folder / FILES[1])
    sources = read_json(folder / FILES[2])
    keys = [row["run_id"] for row in observations]
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("expected distinct observations")
    packet_id = opaque("/".join(digest(folder / name) for name in FILES))
    return observations, cases, sources, packet_id


def sample(folder, n=4):
    observations, cases, sources, _ = load(folder)
    if n < 1 or n > len(observations):
        raise ValueError("invalid review budget")
    shuffled = sorted(observations, key=lambda r: opaque(r["run_id"]))
    groups = defaultdict(list)
    for r in shuffled:
        groups[r["case_id"]].append(r)
    strata = sorted(groups, key=opaque)
    round_robin = [groups[k][i] for i in range(max(map(len, groups.values()))) for k in strata if i < len(groups[k])]

    def disagreement(row):
        votes = list(score(cases[row["case_id"]], row, sources)["scores"].values())
        return sum(left != right for i, left in enumerate(votes) for right in votes[i+1:])

    methods = {"arrival": observations, "shuffle": shuffled, "by_question": round_robin,
               "disagreement": sorted(shuffled, key=disagreement, reverse=True)}
    reviews = read_json(folder / "review.json")
    result = {}
    for name, order in methods.items():
        selected = order[:n]
        ids = [r["run_id"] for r in selected]
        result[name] = {"ids": ids, "n": n, "questions": len({r["case_id"] for r in selected}),
                        "archived": sum(r["source_kind"] == "archived_model" for r in selected),
                        **{v: sum(reviews[k]["verdict"] == v for k in ids) for v in LABELS}}
    return {"seed": SEED, "budget_per_method": n, "population": len(observations),
            "review_source": "existing_codex_dev_labels", "selections": result}


def issue_key(folder, path):
    rows, _, _, dataset_id = load(folder)
    private = {"schema": "review-key/1", "dataset_id": dataset_id,
               "tokens": {r["run_id"]: secrets.token_hex(24) for r in rows}}
    with open(path, "x", encoding="utf-8", opener=lambda name, flags: os.open(name, flags, 0o600)) as out:
        json.dump(private, out, ensure_ascii=False, indent=2)


def packet_keys(rows, dataset_id, private):
    if private is None:
        return dataset_id, {r["run_id"]: opaque(r["run_id"]) for r in rows}
    tokens = private["tokens"]
    if (private.get("schema") != "review-key/1" or private.get("dataset_id") != dataset_id
            or set(tokens) != {r["run_id"] for r in rows}
            or not all(isinstance(t, str) and len(t) == 48 and
                       all(c in "0123456789abcdef" for c in t) for t in tokens.values())
            or len(set(tokens.values())) != len(rows)):
        raise ValueError("invalid private packet mapping")
    payload = json.dumps(private, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest(), tokens


def render(folder, private=None):
    observations, cases, sources, dataset_id = load(folder)
    packet_id, keys = packet_keys(observations, dataset_id, private)
    notice = ("该表使用本次发放的随机编号。请独立核对原表。"
              if private else "公开练习表，编号和开发标注可用仓库数据关联。正式发放时请生成私人编号表。")
    rows = [[esc(c["doc"]), str(c["page"]), str(c["header_page"]), esc(c["row"]), esc(c["column"]),
             esc(c["value"]), esc(c["unit"])] for c in sources["cells"].values()]
    source_table = table(["文档", "数值页", "表头页", "行", "列", "原值", "单位"], rows)
    sections = []
    for row in sorted(observations, key=lambda r: keys[r["run_id"]]):
        key = keys[row["run_id"]]
        citations = "、".join(esc(c["doc"]) + " 第 " + esc(c["page"]) + " 页"
                            + ("，格 " + esc(c["cell"]) if "cell" in c else "") for c in row["citations"])
        status = {"available": "可读取", "timeout": "读取超时"}[row["evidence_status"]]
        sections.append(f'<fieldset data-key="{key}"><legend>{esc(cases[row["case_id"]]["question"])}</legend>'
                        f'<p>{esc(row["answer"])}</p><p>回答所引证据：{citations or "未提供"}。运行时{status}。</p>'
                        '<label>判定 <select><option value="">未评</option><option value="pass">通过</option>'
                        '<option value="fail">错误</option><option value="unknown">证据不足</option></select></label> '
                        '<label>依据 <textarea rows="2" placeholder="记录原表页、取值或缺少的证据"></textarea></label></fieldset>')
    fingerprints = "；".join(esc(d["filename"] + " · " + d["sha256"]) for d in sources["documents"].values())
    return (f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>年报独立复核</title><style>body{{font:16px/1.6 system-ui,sans-serif;max-width:900px;margin:auto;padding:18px}}'
            'fieldset{margin:18px 0}legend{font-weight:bold}textarea{vertical-align:top;max-width:95%}.scroll{overflow:auto}'
            'td,th{padding:4px}summary,button{cursor:pointer}details{overflow-wrap:anywhere}p{margin:8px 0}</style>'
            f'<main data-packet="{packet_id}"><h1>年报独立复核</h1><p>{notice}</p>'
            '<p>请判断回答的数值、单位和引用能否支撑问题所问口径。已能确认错误时记错误；无法判断时记证据不足。'
            '填写判定时请写明依据，可保留未评条目。导出后将 JSON 交给评测负责人。</p>'
            + details("核对两份年报的原表摘录及文件指纹", source_table + "<p>" + fingerprints + "</p>")
            + "".join(sections) + '<label>复核者代号 <input id="who"></label> <button id="save">导出复核记录</button>'
            '<p role="status" id="status"></p></main>' + EXPORT_JS + '</html>\n')


EXPORT_JS = """<script>
document.getElementById('save').onclick = () => {
  const reviewer = document.getElementById('who').value.trim();
  const status = document.getElementById('status');
  const labels = Array.from(document.querySelectorAll('fieldset'), f => ({
    key:f.dataset.key, verdict:f.querySelector('select').value, reason:f.querySelector('textarea').value.trim()
  }));
  if (!reviewer || !labels.some(r=>r.verdict) || labels.some(r=>Boolean(r.verdict)!==Boolean(r.reason))) {
    status.textContent='请填写代号。每条已评记录均需判定与依据，至少填写一条。'; return;
  }
  const data={schema:'report-review/1', packet_id:document.querySelector('main').dataset.packet, reviewer, labels};
  const link=document.createElement('a');
  link.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
  link.download='report-review.json'; link.click(); setTimeout(()=>URL.revokeObjectURL(link.href),1000);
  status.textContent='已导出 '+labels.filter(r=>r.verdict).length+' 条判定。';
};
</script>"""


def reconcile(folder, submission, private=None):
    observations, _, _, dataset_id = load(folder)
    packet_id, keys = packet_keys(observations, dataset_id, private)
    if submission.get("schema") != "report-review/1" or submission.get("packet_id") != packet_id:
        raise ValueError("wrong review packet")
    reviewer = submission.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("missing reviewer identifier")
    ids = {key: run_id for run_id, key in keys.items()}
    seen = set()
    rows = []
    reference = read_json(folder / "review.json")
    for item in submission["labels"]:
        key, verdict, reason = item["key"], item["verdict"], item["reason"]
        if key not in ids or key in seen or verdict not in ("", *LABELS) or not isinstance(reason, str):
            raise ValueError("unexpected, invalid or duplicate label")
        if bool(verdict) != bool(reason.strip()):
            raise ValueError("reviewed item requires a reason and a verdict")
        seen.add(key)
        if verdict:
            run_id = ids[key]
            rows.append({"run_id": run_id, "returned": verdict, "reason": reason,
                         "development_label": reference[run_id]["verdict"],
                         "agrees": verdict == reference[run_id]["verdict"]})
    if seen != set(ids) or not rows:
        raise ValueError("incomplete packet or no labels submitted")
    return {"reviewer": reviewer, "identity_verified": False, "packet_id": packet_id,
            "packet_mode": "private_mapping" if private is not None else "public_practice",
            "development_labels_sha256": digest(folder / "review.json"),
            "reviewed": len(rows), "pending": len(ids) - len(rows), "agreed": sum(r["agrees"] for r in rows),
            "rows": rows}


def command(args):
    folder = Path(args.dataset)
    private = read_json(Path(args.key_file)) if getattr(args, "key_file", None) else None
    if args.action == "review-key":
        issue_key(folder, args.out)
    elif args.action == "blind-review":
        if private is not None and Path(args.out).resolve() == Path(args.key_file).resolve():
            raise ValueError("choose separate form and private mapping files")
        Path(args.out).write_text(render(folder, private), encoding="utf-8")
    elif args.action == "sample-review":
        print(json.dumps(sample(folder, args.budget), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(reconcile(folder, read_json(Path(args.submission)), private), ensure_ascii=False, indent=2))
