"""The blind labelling form for a frozen judge-calibration split, and reading a returned file back.

Built on report/blind_review.py: the same opaque hashing for form keys, the same export shape
(schema report-review/1: packet_id, reviewer, labels[key, verdict, reason]) and the same checks on
return (right packet, every key exactly once, known verdicts). Differences, because one person labels
120 items here: the note is optional, the choice is one click or one key, and the page keeps a draft in the
browser's local storage. The form is rendered from the item sections only; model names, the verifier's
verdicts and judge outputs are not in the page. The order is by form key, which differs between the first
round and the retest round.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from evidenceloop.judge import items as judge_items
from evidenceloop.judge import rubric as rubrics
from evidenceloop.report.annual import read_json
from evidenceloop.report.blind_review import opaque
from evidenceloop.report.review_page import details, esc

SCHEMA = "judge-labels/1"


def packet(dataset: dict[str, Any], split: str) -> tuple[str, dict[str, str], list[dict[str, Any]]]:
    """Packet id, item_id -> form key, and the items in the order the form shows them."""
    shown = judge_items.split_items(dataset, split)
    packet_id = opaque("/".join(("judge", dataset["manifest"]["files"]["key.jsonl"], split)))
    keys = {item["item_id"]: opaque(packet_id + "/" + item["item_id"]) for item in shown}
    return packet_id, keys, sorted(shown, key=lambda item: keys[item["item_id"]])


def render(dataset: dict[str, Any], split: str, root: Path = rubrics.ROOT) -> str:
    rubric = rubrics.load(dataset["rubric"], root)
    packet_id, keys, shown = packet(dataset, split)
    hint = "、".join(f"{i} = {rubric['names'][label]}" for i, label in enumerate(rubric["labels"], 1))
    sections = []
    for number, item in enumerate(shown, 1):
        key = keys[item["item_id"]]
        body = "".join(f"<h3>{esc(s['heading'])}</h3><pre>{esc(s['text'])}</pre>" for s in item["sections"])
        choices = "".join(f'<label class="pick"><input type="radio" name="{key}" value="{esc(label)}"> '
                          f'{esc(rubric["names"][label])}</label>' for label in rubric["labels"])
        sections.append(f'<fieldset data-key="{key}" tabindex="0"><legend>第 {number} 条</legend>{body}'
                        f'<div class="choices">{choices}</div>'
                        '<label class="note">备注（可不填）<textarea rows="1"></textarea></label></fieldset>')
    state = "草稿" if rubric["draft"] else "已定稿"
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>裁判校准标注 · {esc(split)}</title><style>{STYLE}</style>'
            f'<main data-packet="{packet_id}" data-rubric="{rubric["sha256"]}" data-split="{esc(split)}">'
            '<div class="bar"><strong>已标 <span id="done">0</span> / '
            f'{len(shown)}</strong><progress id="meter" max="{len(shown)}" value="0"></progress>'
            '<input id="who" placeholder="标注者代号"><button id="save">导出标注</button>'
            '<span role="status" id="status"></span></div>'
            f'<h1>裁判校准标注（{esc(split)}，{len(shown)} 条）</h1>'
            f'<p>点一条材料后按数字键选判定并跳到下一条：{esc(hint)}。也可以直接点选。'
            '进度存在这个浏览器里，关掉再打开还在；全部标完后点“导出标注”，把下载的 JSON 交回。'
            '拿不准的条目选最接近的一类，并在备注里写一句。</p>'
            + details(f"评分标准（{state}）", f'<pre class="rubric">{esc(rubric["text"])}</pre>')
            + "".join(sections) + '</main>' + FORM_JS + '</html>\n')


STYLE = ("body{font:16px/1.6 system-ui,sans-serif;max-width:920px;margin:auto;padding:0 18px 80px;color:#1c1c1e}"
         ".bar{position:sticky;top:0;z-index:2;display:flex;flex-wrap:wrap;gap:12px;align-items:center;"
         "padding:10px 0;background:#fff;border-bottom:1px solid #d0d0d5}progress{flex:1;min-width:120px;height:10px}"
         "fieldset{margin:22px 0;border:1px solid #c8c8cf;border-radius:10px;padding:10px 16px 14px}"
         "fieldset:focus{outline:3px solid #2f6fed}fieldset.done{border-color:#2e8b57;background:#f4faf6}"
         "legend{font-weight:bold;padding:0 6px}h3{font-size:14px;margin:10px 0 4px;color:#555}"
         "pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;padding:10px 12px;border-radius:8px;"
         "background:#f3f3f6;font:14px/1.55 ui-monospace,Menlo,monospace}pre.rubric{background:#fffbe9}"
         ".choices{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0 8px}"
         ".pick{border:1px solid #b8b8c0;border-radius:8px;padding:6px 14px;cursor:pointer}"
         ".pick:has(input:checked){background:#2f6fed;border-color:#2f6fed;color:#fff}"
         ".note{display:flex;gap:8px;align-items:flex-start;color:#555;font-size:14px}"
         "textarea{flex:1;font:inherit}input,button{font:inherit;padding:4px 10px}summary,button{cursor:pointer}")

FORM_JS = """<script>
const main = document.querySelector('main'), store = 'judge-labels/' + main.dataset.packet;
const sets = Array.from(document.querySelectorAll('fieldset')), who = document.getElementById('who');
const status = document.getElementById('status');
const read = f => ({key: f.dataset.key, verdict: (f.querySelector('input:checked') || {value: ''}).value,
                    reason: f.querySelector('textarea').value.trim()});
function refresh(save) {
  const labels = sets.map(read), done = labels.filter(r => r.verdict).length;
  sets.forEach((f, i) => f.classList.toggle('done', Boolean(labels[i].verdict)));
  document.getElementById('done').textContent = done;
  document.getElementById('meter').value = done;
  if (save) { try { localStorage.setItem(store, JSON.stringify({reviewer: who.value, labels})); } catch (e) {} }
  return labels;
}
try {
  const kept = JSON.parse(localStorage.getItem(store) || 'null');
  if (kept) {
    who.value = kept.reviewer || '';
    const byKey = Object.fromEntries(kept.labels.map(r => [r.key, r]));
    sets.forEach(f => { const r = byKey[f.dataset.key]; if (!r) return;
      f.querySelector('textarea').value = r.reason || '';
      const box = Array.from(f.querySelectorAll('input[type=radio]')).find(b => b.value === r.verdict);
      if (box) box.checked = true; });
  }
} catch (e) {}
refresh(false);
document.addEventListener('change', () => refresh(true));
document.addEventListener('input', () => refresh(true));
document.addEventListener('keydown', e => {
  const f = e.target.closest ? e.target.closest('fieldset') : null;
  if (!f || e.target.tagName === 'TEXTAREA' || e.metaKey || e.ctrlKey || e.altKey) return;
  const boxes = f.querySelectorAll('input[type=radio]'), n = Number(e.key);
  if (!(n >= 1 && n <= boxes.length)) return;
  boxes[n - 1].checked = true; refresh(true);
  const next = sets[sets.indexOf(f) + 1];
  if (next) { next.focus(); next.scrollIntoView({block: 'start', behavior: 'smooth'}); }
});
document.getElementById('save').onclick = () => {
  const labels = refresh(true), reviewer = who.value.trim();
  if (!reviewer || !labels.some(r => r.verdict)) { status.textContent = '请填写代号，并至少标一条。'; return; }
  const data = {schema: 'report-review/1', packet_id: main.dataset.packet, rubric_sha256: main.dataset.rubric,
                reviewer, labels};
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));
  link.download = 'judge-labels-' + main.dataset.split + '.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  const left = labels.filter(r => !r.verdict).length;
  status.textContent = '已导出 ' + (labels.length - left) + ' 条' + (left ? '，还有 ' + left + ' 条没标。' : '。');
};
</script>"""


def reconcile(dataset: dict[str, Any], split: str, submission: dict[str, Any]) -> dict[str, Any]:
    """Check a returned file against the packet it was issued for and turn form keys back into item ids."""
    allowed = rubrics.RUBRICS[dataset["rubric"]]["labels"]
    packet_id, keys, _ = packet(dataset, split)
    if submission.get("schema") != "report-review/1" or submission.get("packet_id") != packet_id:
        raise ValueError("wrong review packet")
    reviewer = submission.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("missing reviewer identifier")
    ids = {key: item_id for item_id, key in keys.items()}
    seen, rows = set(), []
    for entry in submission["labels"]:
        key, verdict, reason = entry["key"], entry["verdict"], entry.get("reason", "")
        if key not in ids or key in seen or verdict not in ("", *allowed) or not isinstance(reason, str):
            raise ValueError("unexpected, invalid or duplicate label")
        seen.add(key)
        if verdict:
            rows.append({"item_id": ids[key], "label": verdict, "reason": reason.strip()})
    if seen != set(ids) or not rows:
        raise ValueError("incomplete packet or no labels submitted")
    return {"schema": SCHEMA, "rubric": dataset["rubric"], "split": split, "reviewer": reviewer.strip(),
            "identity_verified": False, "packet_id": packet_id, "rubric_sha256": submission.get("rubric_sha256"),
            "key_sha256": dataset["manifest"]["files"]["key.jsonl"],
            "reviewed": len(rows), "pending": len(ids) - len(rows), "labels": rows}


def load_labels(path: Path, dataset: dict[str, Any], split: str) -> dict[str, Any]:
    """A reconciled label file for this dataset and split."""
    doc = read_json(path)
    if (doc.get("schema") != SCHEMA or doc.get("rubric") != dataset["rubric"] or doc.get("split") != split
            or doc.get("key_sha256") != dataset["manifest"]["files"]["key.jsonl"]):
        raise ValueError(f"{path} 不是这份样本 {split} 划分的标注")
    return doc


def command(args) -> None:
    try:
        dataset = judge_items.load_dataset(Path(args.dataset))
        if args.action == "form":
            Path(args.out).write_text(render(dataset, args.split), encoding="utf-8")
            print(f"{len(judge_items.split_items(dataset, args.split))} 条 → {args.out}")
            return
        result = reconcile(dataset, args.split, read_json(Path(args.submission)))
    except (ValueError, FileNotFoundError) as err:
        sys.exit(f"不能处理：{err}")
    if Path(args.out).exists():
        sys.exit(f"{args.out} 已经存在；标注文件不覆盖。要换成新交回的这份，先把旧文件改名")
    with open(args.out, "x", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "labels"}, ensure_ascii=False, indent=2))
