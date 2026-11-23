"""Render a portable, offline comparison of the frozen report experiments."""

import json
from html import escape
from pathlib import Path

from evidenceloop.report import calculation
from evidenceloop.report.annual import compare, read_json, read_lines
from evidenceloop.report.evidence_trials import ARMS, summarize

ARM_NAMES = {"row":"仅数值行", "header":"同样的行＋列头", "selected":"人工选行＋列头"}
LABELS = {"pass":"已核准", "fail":"未通过", "unknown":"待核实"}


def esc(value):
    return escape(str(value), quote=True)


def badge(verdict):
    return f'<span class="tag {esc(verdict)}">{esc(LABELS[verdict])}</span>'


def details(title, body):
    return f"<details><summary>{esc(title)}</summary>{body}</details>"


def pre(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, indent=2)
    return "<pre>" + esc(value) + "</pre>"


def table(headers, rows):
    head = "".join(f"<th scope='col'>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<div class='scroll'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def page_ref(doc_hash, page):
    return (f'<a data-hash="{esc(doc_hash)}" data-page="{int(page)}" target="_blank" '
            f'rel="noopener noreferrer">第 {int(page)} 页</a>')


def source_table(case, sources):
    rows = []
    for k in case["cells"] + case.get("alternative_sum", []):
        c = sources["cells"][k]
        doc_hash = sources["documents"][c["doc"]]["sha256"]
        rows.append([esc(c["row"]), esc(c["column"]), esc(c["value"]) + " " + esc(c["unit"]),
                     "表头 " + page_ref(doc_hash, c["header_page"]) + " · 数值 " + page_ref(doc_hash, c["page"])])
    return table(["原表行", "列", "标注值", "PDF 页"], rows)


def calculation_section(prompts, review, log):
    result = calculation.summarize(prompts, review, log)
    cases = {i["case_id"]:i for i in read_json(prompts)}
    archive = {r["run_id"]:r for r in read_lines(log)}
    names = {"direct":"直接作答", "cells":"选择原格", "metric_tool":"选择业务函数"}
    summary = table(["做法","核准 / 总题数","修好","退化"],
                    [[esc(names[a]),f"{t['pass']} / {t['n']}",esc("、".join(t["fixed"]) or "—"),
                      esc("、".join(t["lost"]) or "—")] for a,t in result["summaries"].items()])
    cards = []
    for cid, case in cases.items():
        lines = []
        for r in (r for r in result["rows"] if r["case_id"] == cid):
            receipt = r["receipt"] or {}
            lines.append([esc(names[r["arm"]]),badge(r["verdict"]),esc(receipt.get("value","—")),
                          esc(r["expected"]),esc(receipt.get("numerator","—")),esc(receipt.get("denominator","—")),
                          details("动作与原始回复", pre(r["decision"]) + pre(receipt) + pre(archive[r["run_id"]]))])
        cards.append("<h3>" + esc(case["question"]) + "</h3>" + table(
            ["做法","判定","交付值 %","目标 %","分子","分母","证据"],lines))
    return ("<h2 id='calc'>让程序算百分比，哪些错能修好？</h2><p>同一原表、模型与调用预算。"
            "两种工具在归档动作上实际执行。选择年份错误仍会得到格式正确的计算结果。</p>"
            + summary + "".join(cards))


def render(dataset: Path, prompts: Path, log: Path, calc_prompts: Path, calc_review: Path, calc_log: Path):
    facts = read_json(dataset / "sources.json")
    cases = read_json(dataset / "cases.json")
    observations = read_lines(dataset / "observations.jsonl")
    compare_rows = {r["run_id"]:r for r in compare(dataset)["rows"]}
    trial = summarize(prompts, log, dataset)
    raw = {r["run_id"]:r for r in read_lines(log)}
    rows = {(r["case_id"],r["arm"]):r for r in trial["rows"]}
    blocks = []
    for case_id in dict.fromkeys(r["case_id"] for r in trial["rows"]):
        case = cases[case_id]
        cards = []
        for arm in ARMS:
            r = rows[case_id,arm]
            request = raw[r["run_id"]]["request"]
            reply = r["reply"] or {}
            ans = f"{reply.get('value','')} {reply.get('unit','')}" if r["state"] == "answered" else r["state"]
            checks = (r["checks"] or {}).get("checks", {})
            trace = details("输入、原始响应与运行记录", pre(raw[r["run_id"]]))
            cards.append(f"<article><h4>{esc(ARM_NAMES[arm])}</h4>{badge(r['verdict'])}"
                         f"<p class='num'>{esc(ans)}</p><p>{esc(reply.get('explanation',''))}</p>"
                         f"<p>引用页 {esc(reply.get('pages',[]))} · 数值 {esc(checks.get('value_unit','—'))}"
                         f" · 出处 {esc(checks.get('page_support','—'))}</p>"
                         f"<p>{esc(r['latency_ms'])} ms · token {esc(r['input_tokens'])} 入 / {esc(r['output_tokens'])} 出</p>"
                         f"{details('查看模型可见的摘录', pre(request['messages'][-1]['content']))}{trace}</article>")
        doc = facts["documents"][case["cells"][0].split(".")[0]]
        blocks.append(f"<section class='case'><h3>{esc(case['question'])}</h3>"
                      f"<p class='muted'>{esc(case_id)} · {esc(doc['filename'])}</p>"
                      + details("核对原表摘录与文件指纹", source_table(case,facts) + pre(doc['sha256']))
                      + "<div class='grid'>" + "".join(cards) + "</div></section>")
    observations_html = []
    for o in observations:
        c = compare_rows[o["run_id"]]
        body = (f"<p>{esc(cases[o['case_id']]['question'])}</p><blockquote>{esc(o['answer'])}</blockquote>"
                f"<p>开发标注：{esc(c['review_reason'])}</p>"
                + table(["有页码", "摘录出现数字", "独立复算", "复算＋支持页组"],
                        [[badge(c["scores"][m]) for m in ("cited","printed","value_unit","value_pages")]])
                + details("原始记录", pre(o)))
        kind = "历史模型" if o["source_kind"] == "archived_model" else "构造对照"
        observations_html.append(details(f"{kind} · {o['case_id']} · {o['answer']}", body))
    counts = table(["输入条件","核准 / 总题数","待核实","相对仅数值行修好","退化"],
                   [[esc(ARM_NAMES[a]),f"{t['pass']} / {t['n']}",str(t["unknown"]),
                     esc("、".join(t['fixed']) or "—"),esc("、".join(t['lost']) or "—")]
                    for a,t in trial["summaries"].items()])
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>年报逐题评测 · EvidenceLoop</title><style>
*{box-sizing:border-box}body{margin:0;background:#f8faf9;color:#182823;font:16px/1.6 Inter,system-ui,sans-serif}main{max-width:1220px;margin:auto;padding:36px clamp(16px,4vw,55px)}
h1{font-size:clamp(28px,4vw,46px);letter-spacing:-.05em;margin:.45em 0}h2{margin-top:2em}h3,h4{margin:.4em 0}.muted{color:#4b6259}a,summary{color:#146148}nav{display:flex;gap:1.4em}section.case{padding:24px 0;border-top:1px solid #bbcbc4}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:16px}article{background:white;padding:14px;border:1px solid #ccd9d2;border-radius:9px;min-width:0}article p{font-size:14px}.num{font:600 19px ui-monospace,monospace;color:#184439}
.scroll{overflow:auto}table{border-collapse:collapse;background:white;width:100%;font-size:14px}td,th{padding:8px 12px;text-align:left;border-bottom:1px solid #d4ded8}
.tag{border:1px solid;padding:2px 7px;border-radius:6px;font-size:13px}.pass{color:#185d41}.fail{color:#9b3224}.unknown{color:#775713}
summary{cursor:pointer;padding:5px 0;overflow-wrap:anywhere}pre{background:#eef3ef;padding:10px;white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.6 ui-monospace,monospace}
blockquote{margin-left:0;border-left:3px solid #257254;padding:4px 12px}.history>details{border-top:1px solid #ccd9d2;padding:8px 0}@media(max-width:760px){.grid{grid-template-columns:1fr}}
</style><main><h1>年报逐题评测</h1><nav><a href="#trial">真实模型对照</a><a href="#calc">计算工具对照</a><a href="#archive">评分依据</a></nav>
<p><label>关联本地原年报 <input id="pdf" type="file" accept="application/pdf" multiple></label><br>
<span id="pdf-status" class="muted" role="status">选取原 PDF 后可从表格页码打开原页。文件只在本浏览器读取。</span></p>
<h2 id="trial">给同一模型补上列头后，哪些题答对了？</h2>""" + (
        f"<p>{esc(trial['model'][0])} · 公开开发题 · 每种输入每题一次。核准要求数值、单位和引用页组同时满足。"
        "模型弃答与基础设施故障分开记录；本地耗时包含冷启动。</p>" + counts + "".join(blocks)
        + calculation_section(calc_prompts, calc_review, calc_log)
        + "<h2 id='archive'>同一回答在四种评分方法下的结果</h2><p>历史模型回执和脚本构造对照分别标出。"
        "证据不足保留为待核实。标注由 Codex 比照原表完成，尚无独立人工复核。</p><div class='history'>"
        + "".join(observations_html) + "</div></main>" + PDF_SCRIPT + "</html>\n")


PDF_SCRIPT = """<script>
const pdfUrls = new Map();
const picker = document.getElementById('pdf');
picker.addEventListener('change', async () => {
  const labels = [];
  for (const file of picker.files) {
    try {
      const bytes = await file.arrayBuffer();
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
                              b => b.toString(16).padStart(2, '0')).join('');
      const links = Array.from(document.querySelectorAll('a[data-hash]')).filter(a => a.dataset.hash === hash);
      if (!links.length) { labels.push(file.name + '：版本与冻结原件不符'); continue; }
      if (pdfUrls.has(hash)) URL.revokeObjectURL(pdfUrls.get(hash));
      const url = URL.createObjectURL(new Blob([bytes], {type:'application/pdf'}));
      pdfUrls.set(hash, url);
      for (const a of links) a.href = url + '#page=' + a.dataset.page;
      labels.push(file.name + '：版本已核对，可打开原页');
    } catch { labels.push(file.name + '：无法校验文件'); }
  }
  document.getElementById('pdf-status').textContent = labels.join(' · ');
});
</script>"""


def command(args):
    page = render(Path(args.dataset), Path(args.prompts), Path(args.log),
                  Path(args.calc_prompts), Path(args.calc_review), Path(args.calc_log))
    Path(args.out).write_text(page, encoding="utf-8")
