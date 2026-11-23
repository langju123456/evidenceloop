from html.parser import HTMLParser
from pathlib import Path

from evidenceloop.report import calculation, evidence_trials, review_page


class Count(HTMLParser):
    def __init__(self):
        super().__init__()
        self.case_count = 0
        self.openers = 0

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        self.case_count += tag == "section" and attr.get("class") == "case"
        self.openers += tag == "summary"


def test_review_page_uses_stored_archives_and_escapes_untrusted_content():
    root = Path(__file__).resolve().parents[1]
    logs = root / "reports/report-lab"
    page = review_page.render(root / "benchmarks/report_dev/v1", root / evidence_trials.DATASET,
                              logs / "evidence-trials-v1.jsonl", root / calculation.PROMPTS,
                              root / calculation.REVIEW, logs / "calculation-trials-v1.jsonl",
                              logs / "peer-runs-v1.json")
    assert page == (logs / "review.html").read_text()
    assert "收到 2 份" in page and "产品与收件回执" in page
    assert "跨公司留出结果" in page and "印刷页 57" in page and "印刷页 77" in page
    assert page.count("查看动作和核验记录") == 24
    assert "错收退回版 v1" in page and page.count("查这组收件回执") == 5
    parsed = Count()
    parsed.feed(page)
    assert parsed.case_count == 4
    assert parsed.openers >= 14 + 12 + 12
    assert '<img' not in review_page.pre('<img src=x onerror=alert(1)>')


def test_partial_acquisition_preserves_existing_review(tmp_path):
    (tmp_path / "issuer-trials-v1.jsonl").write_text('{"in_progress":true}\n')
    assert review_page.holdout_section(tmp_path) == ""
