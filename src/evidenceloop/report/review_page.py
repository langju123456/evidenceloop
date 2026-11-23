"""Render a portable, offline comparison of the frozen report experiments."""

import json
from html import escape
from pathlib import Path

from evidenceloop.report import calculation, issuer_holdout, peer_runs
from evidenceloop.report.annual import compare, digest, read_json, read_lines
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


STRATEGY_NAMES = {"assume_success": "超时就记成功", "wait_for_human": "等待人工处理",
                  "retry_new_key": "换新编号重试", "reconcile_original_key": "按原编号查收并补送"}
FAULT_NAMES = {"ack": "正常回执", "request_lost": "请求丢失", "receipt_lost_crash": "已收件、回执丢失并中断"}


WORLD_NAMES = {"approved_v2_once": "恰好收到批准版 v2", "returned_v1_once": "错收退回版 v1",
               "inbox_empty": "收件箱为空", "approved_v2_twice": "重复收到批准版", "approval_corrupted": "审批记录被改动"}


def apple_delivery_section(linked):
    revisions = []
    for revision in linked["revisions"]:
        revisions.append([esc(revision["version"]), esc(revision["question"]), esc(revision["answer"]),
                          esc(" → ".join(event["kind"] for event in revision["events"])),
                          details("查原件和查询编号", pre(revision))])
    by_world = {(r["world"], r["reader"]): r for r in linked["simulated_receipt_matrix"]}
    scenarios = []
    for world in WORLD_NAMES:
        readings = [by_world[world, reader] for reader in peer_runs.READERS]
        received = readings[0]["receipt_summary"]
        receipts = "、".join("v" + esc(r["version"]) for r in received) or "无"
        verdicts = []
        for r in readings:
            if r["false_accept"]:
                label = "误放"
            elif r["accepted"]:
                label = "签收"
            else:
                label = "拒收"
            verdicts.append(esc(label))
        scenarios.append([WORLD_NAMES[world], receipts, *verdicts, details("查这组收件回执", pre(readings))])
    returned_reason = next(e["memo"] for e in linked["revisions"][0]["events"] if e["kind"] == "returned")
    return ("<h2 id='apple-delivery'>Apple 报告交付的是审阅人批准的那一版吗？</h2>"
            "<p>同一个本地草稿经两次产品查询完成修订。脚本扮演作者和审阅者，第二版获批并产生本地回执。</p>"
            + "<blockquote>" + esc(returned_reason) + "</blockquote>"
            + table(["版本", "查询", "原答", "本地状态变更", "证据"], revisions)
            + "<p>HorizonBench 读取这两版原件，在五种模拟收件情形中比较四种核验方式。"
              "正常签收和错收旧版都只有一份收件；核对批准版本和内容指纹才能把它们区分开。</p>"
            + table(["模拟收件情形", "收到的版本", "只看本地交付", "只核上游审批", "只数收件", "完整核对", "原始判定"], scenarios)
            + details("查看案例、草稿编号及上游文件指纹", pre({k: linked[k] for k in
                      ("case_id", "draft_id", "product_commit", "environment_commit", "review_index", "matrix_ref")}))
            + "<p>20 格来自同一草稿的五个模拟世界。生产收件与实时跨服务调用仍待验证。</p>")


def peer_section(archive):
    data = read_json(archive)
    if data["schema_version"] != "report-receipts/1" or data["joint_product_environment_runs"] != 0:
        raise ValueError("expected separate historical development runs")
    qa = []
    for r in data["rows"]:
        if r["source"] != "ForgeFlow":
            continue
        pages = "、".join(page_ref(r["data_version"], c["page"]) for c in r["citations"])
        qa.append([esc(r["question"]), esc(r["answer"]), badge(r["verdict"]), pages or "—",
                   esc(r["latency_ms"]), details("查看问答回执", pre(r))])
    records = {(r["strategy"], r["fault"]): r for r in data["rows"] if r["source"] == "HorizonBench"}
    matrix = []
    for strategy in peer_runs.STRATEGIES:
        cells = []
        for fault in peer_runs.FAULTS:
            r = records[strategy, fault]
            cells.append(badge(r["verdict"]) + f' · 收到 {int(r["checks"]["target_receipts"])} 份'
                         + details("收件与恢复记录", pre(r)))
        matrix.append([esc(STRATEGY_NAMES[strategy]), *cells])
    jump = '<p><a href="#apple-delivery">查看 Apple 批准稿与错收旧版的对照</a></p>' if "apple_delivery" in data else ""
    return ("<h2 id='peers'>产品答对了吗？收件方拿到了几份？</h2>" + jump
            + "<h3>ForgeFlow 的年度现金流问答</h3><p>四次请求经过产品 API 和本地计算工具。"
            "评分逐项核对宁德时代年报第 11 页。2022 年超出该表列示范围，保留为待核实。</p>"
            + table(["用户问题", "产品回答", "核验", "出处", "毫秒", "记录"], qa)
            + "<h3>HorizonBench 的独立收件结果</h3><p>同一份报告在三种交付情形下运行四种策略。"
            "外部收件方由本地数据库模拟，进程中断有实测退出码。展开可查本机状态、收件编号和内容指纹。</p>"
            + table(["处理策略"] + [FAULT_NAMES[f] for f in peer_runs.FAULTS], matrix)
            + "<p>两个实验共享业务案例。上游没有贯通这两批记录的运行编号，完整跨项目交付次数尚待实测。</p>"
            + (apple_delivery_section(data["apple_delivery"]) if "apple_delivery" in data else ""))


def holdout_section(folder):
    result_path = folder / "issuer-results-v1.json"
    raw_path = folder / "issuer-trials-v1.jsonl"
    if not result_path.exists():
        return ""
    result = read_json(result_path)
    if digest(raw_path) != result["raw_sha256"]:
        raise ValueError("holdout report and raw archive differ")
    archive = {r["run_id"]: r for r in read_lines(raw_path)}
    protocol_file = issuer_holdout.DATA / "protocol.json"
    path = issuer_holdout.ROOT / protocol_file
    if digest(path) != result["frozen_sha256"][str(protocol_file)]:
        raise ValueError("holdout report and source manifest differ")
    documents = read_json(path)["documents"]
    names = {"direct": "直接回答", "cells": "选择原格", "metric_tool": "选择业务函数"}
    scorecard = []
    for arm, totals in result["summaries"].items():
        scorecard.append([esc(names[arm]), f'{totals["pass"]}/{totals["n"]}',
                          f'{totals["by_issuer"]["dell"]}/4', f'{totals["by_issuer"]["cisco"]}/4',
                          esc(totals["unknown"]), esc("、".join(totals["fixed"]) or "—"),
                          esc("、".join(totals["lost"]) or "—"), f'{totals["model_ms_sum"]/1000:.2f}'])
    cards = []
    for case_id in dict.fromkeys(r["case_id"] for r in result["rows"]):
        rows = [r for r in result["rows"] if r["case_id"] == case_id]
        request = archive[rows[0]["run_id"]]["request"]["messages"][-1]["content"]
        title, evidence = request.split("\n", 1)
        lines = []
        for r in rows:
            receipt = r["receipt"] or {}
            raw = archive[r["run_id"]]
            lines.append([esc(names[r["arm"]]), badge(r["verdict"]), esc(receipt.get("value", "—")),
                          esc(r["expected"]), esc(r["model_ms"]),
                          details("查看动作和核验记录", pre({"动作": r["decision"], "执行": receipt,
                                                        "可见差异": r["observed_errors"], "错误": r["error"]})
                                  + pre(raw))])
        doc = documents[archive[rows[0]["run_id"]]["document"]]
        source = (f'<a href="{esc(doc["pdf_source"])}#page={int(doc["pdf_physical_page"])}" '
                  f'target="_blank" rel="noopener noreferrer">查看发行人原件（印刷页 {int(doc["printed_page"])}）</a>')
        cards.append(f'<h3>{esc(title)}</h3>' + details("模型看到的财报摘录", pre(evidence) + source
                                                      + pre(doc["pdf_sha256"]))
                     + table(["做法", "结论", "回答 %", "参考 %", "毫秒", "证据"], lines))
    gate = "达到预设试点门槛" if result["candidate_meets_pilot_gate"] else "未达到预设试点门槛"
    return ("<h2 id='holdout'>换成 Dell 和 Cisco 年报，公式选择还能用吗？</h2>"
            f"<p>8 道冻结题，24 次本地调用。业务公式候选{gate}。独立人工复核 0 份。"
            f"推理前冻结提交 <code>{esc(result['freeze_commit'][:12])}</code>。</p>"
            + table(["做法", "核准", "Dell", "Cisco", "待核", "相对直接回答修好", "退化", "模型总秒数"], scorecard)
            + "".join(cards))


def render(dataset: Path, prompts: Path, log: Path, calc_prompts: Path, calc_review: Path, calc_log: Path, peers: Path):
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
    holdout = holdout_section(peers.parent)
    link = '<a href="#holdout">跨公司留出结果</a>' if holdout else ""
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>年报逐题评测 · EvidenceLoop</title><style>
*{box-sizing:border-box}body{margin:0;background:#f8faf9;color:#182823;font:16px/1.6 Inter,system-ui,sans-serif}main{max-width:1220px;margin:auto;padding:36px clamp(16px,4vw,55px)}
h1{font-size:clamp(28px,4vw,46px);letter-spacing:-.05em;margin:.45em 0}h2{margin-top:2em}h3,h4{margin:.4em 0}.muted{color:#4b6259}a,summary{color:#146148}nav{display:flex;flex-wrap:wrap;gap:.4em 1.4em}section.case{padding:24px 0;border-top:1px solid #bbcbc4}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:16px}article{background:white;padding:14px;border:1px solid #ccd9d2;border-radius:9px;min-width:0}article p{font-size:14px}.num{font:600 19px ui-monospace,monospace;color:#184439}
.scroll{overflow:auto}table{border-collapse:collapse;background:white;width:100%;font-size:14px}td,th{padding:8px 12px;text-align:left;border-bottom:1px solid #d4ded8}
.tag{border:1px solid;padding:2px 7px;border-radius:6px;font-size:13px}.pass{color:#185d41}.fail{color:#9b3224}.unknown{color:#775713}
summary{cursor:pointer;padding:5px 0;overflow-wrap:anywhere}pre{background:#eef3ef;padding:10px;white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.6 ui-monospace,monospace}
blockquote{margin-left:0;border-left:3px solid #257254;padding:4px 12px}.history>details{border-top:1px solid #ccd9d2;padding:8px 0}@media(max-width:760px){.grid{grid-template-columns:1fr}}
</style><main><h1>年报逐题评测</h1><nav><a href="#trial">真实模型对照</a><a href="#calc">计算工具对照</a>""" + link + """<a href="#peers">产品与收件回执</a><a href="#archive">评分依据</a></nav>
<p><label>关联本地原年报 <input id="pdf" type="file" accept="application/pdf" multiple></label><br>
<span id="pdf-status" class="muted" role="status">选取原 PDF 后可从表格页码打开原页。文件只在本浏览器读取。</span></p>
<h2 id="trial">给同一模型补上列头后，哪些题答对了？</h2>""" + (
        f"<p>{esc(trial['model'][0])} · 公开开发题 · 每种输入每题一次。核准要求数值、单位和引用页组同时满足。"
        "模型弃答与基础设施故障分开记录；本地耗时包含冷启动。</p>" + counts + "".join(blocks)
        + calculation_section(calc_prompts, calc_review, calc_log)
        + holdout + peer_section(peers)
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
                  Path(args.calc_prompts), Path(args.calc_review), Path(args.calc_log), Path(args.peers))
    Path(args.out).write_text(page, encoding="utf-8")
