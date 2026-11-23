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
                              root / calculation.REVIEW, logs / "calculation-trials-v1.jsonl")
    assert page == (logs / "review.html").read_text()
    parsed = Count()
    parsed.feed(page)
    assert parsed.case_count == 4
    assert parsed.openers >= 14 + 12 + 12
    assert '<img' not in review_page.pre('<img src=x onerror=alert(1)>')
