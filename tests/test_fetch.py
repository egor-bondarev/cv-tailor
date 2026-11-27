import io
import json
import urllib.error
from email.message import Message

import pytest

from cvtailor.fetch import FetchError, extract, fetch_vacancy, html_to_text, job_posting

DESCRIPTION = "<p>We build payments.</p><ul><li>Python test frameworks</li><li>CI pipelines</li></ul>" + (
    "<p>" + "Own the quality of the platform. " * 20 + "</p>")


def posting_page(company="Acme Payments", title="Senior SDET"):
    ld = {"@context": "https://schema.org", "@type": "JobPosting", "title": title, "description": DESCRIPTION,
          "hiringOrganization": {"@type": "Organization", "name": company}}
    return (f'<html><head><title>Jobs</title><script type="application/ld+json">{json.dumps(ld)}</script></head>'
            "<body><nav>Home Careers</nav><p>Apply now</p></body></html>")


class Resp:
    def __init__(self, body: bytes, ctype="text/html; charset=utf-8", url="https://jobs.example.com/1"):
        self.body, self.url = body, url
        self.headers = Message()
        self.headers["Content-Type"] = ctype

    def read(self, n=-1):
        return self.body[:n] if n >= 0 else self.body

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_job_posting_gives_role_company_and_description():
    page = extract("https://jobs.example.com/1", posting_page())
    assert page.company == "Acme Payments" and page.title == "Senior SDET"
    assert page.text.startswith("Role: Senior SDET\nCompany: Acme Payments\n\nWe build payments.")
    assert "- Python test frameworks" in page.text and "Home Careers" not in page.text


def test_job_posting_in_graph_and_type_list():
    ld = {"@graph": [{"@type": "WebPage"}, {"@type": ["JobPosting"], "title": "QA", "description": "x"}]}
    assert job_posting(f'<script type="application/ld+json">{json.dumps(ld)}</script>')["title"] == "QA"


def test_broken_json_ld_is_skipped():
    assert job_posting('<script type="application/ld+json">{not json</script>') is None


def test_visible_text_skips_scripts_and_menus_and_prefers_main():
    body = "<p>" + "Build the test platform. " * 30 + "</p>"
    markup = f"<html><head><title>T</title><style>.a{{}}</style></head><body><nav>Menu</nav><div>Banner</div>" \
             f"<main><h1>Senior SDET</h1>{body}</main><footer>Legal</footer><script>x=1</script></body></html>"
    text = html_to_text(markup)
    assert text.startswith("Senior SDET\n") and "Banner" not in text and "Menu" not in text and "x=1" not in text


def test_short_main_falls_back_to_whole_page():
    markup = "<body><main>Short</main><div>" + "Vacancy text. " * 40 + "</div></body>"
    assert "Vacancy text." in html_to_text(markup)


def test_fetch_ok_uses_final_url():
    page = fetch_vacancy("https://jobs.example.com/x", opener=lambda u: Resp(posting_page().encode()))
    assert page.url == "https://jobs.example.com/1" and page.company == "Acme Payments"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x/y", "jobs.example.com/1", "https://"])
def test_only_http_links(url):
    with pytest.raises(FetchError, match="http"):
        fetch_vacancy(url, opener=lambda u: pytest.fail("must not open"))


def test_page_without_text_asks_for_text():
    with pytest.raises(FetchError, match="almost no text"):
        fetch_vacancy("https://www.example.com/jobs/1", opener=lambda u: Resp(b"<html><body>Sign in</body></html>"))


def test_http_error_and_non_html():
    def denied(u):
        raise urllib.error.HTTPError(u, 403, "Forbidden", Message(), io.BytesIO())
    with pytest.raises(FetchError, match="HTTP 403"):
        fetch_vacancy("https://x.example.com/1", opener=denied)
    with pytest.raises(FetchError, match="not a web page"):
        fetch_vacancy("https://x.example.com/1.pdf", opener=lambda u: Resp(b"%PDF", ctype="application/pdf"))


def test_size_limit(monkeypatch):
    monkeypatch.setattr("cvtailor.fetch.MAX_BYTES", 10)
    with pytest.raises(FetchError, match="larger"):
        fetch_vacancy("https://x.example.com/1", opener=lambda u: Resp(b"x" * 11))
