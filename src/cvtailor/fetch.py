"""Fetch a vacancy page by URL and extract its text (v2 V5).

Only http(s), a timeout, a size limit and no cookies. The schema.org `JobPosting` block many job boards embed
(JSON-LD) gives the role, the company and the description; otherwise the visible page text is used. A page that
needs a browser or a sign-in yields too little text: the caller then asks for the text instead.
"""

from __future__ import annotations

import html as htmllib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urlparse

TIMEOUT_S = 20
MAX_BYTES = 3_000_000
MIN_TEXT_CHARS = 400
USER_AGENT = "Mozilla/5.0 (compatible; cvtailor/0.1; vacancy fetch)"
SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "head", "nav", "footer", "form", "button", "iframe"}
BLOCK_TAGS = {"p", "div", "section", "article", "main", "br", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3",
              "h4", "h5", "h6", "header", "aside", "dd", "dt", "blockquote", "pre"}


class FetchError(RuntimeError):
    pass


@dataclass
class Page:
    url: str
    html: str
    text: str
    company: str | None = None
    title: str | None = None


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.main_parts: list[str] = []  # text inside <main>: drops site menus when the page marks its content
        self.main = 0
        self.skip = 0
        self.title = ""
        self.in_title = False

    def _add(self, text: str) -> None:
        self.parts.append(text)
        if self.main:
            self.main_parts.append(text)

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag == "main":
            self.main += 1
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag in BLOCK_TAGS:
            self._add("\n- " if tag == "li" else "\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self._add("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "main":
            self.main = max(0, self.main - 1)
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCK_TAGS:
            self._add("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if not self.skip:
            self._add(data)


def _clean(raw: str) -> str:
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in raw.splitlines()]
    out: list[str] = []
    for line in lines:
        if line in ("", "-") and (not out or out[-1] == ""):
            continue
        out.append("" if line == "-" else line)
    return "\n".join(out).strip()


def html_to_text(markup: str) -> str:
    """Visible text with line breaks at block elements; only the <main> part when it has enough text."""
    p = _Text()
    p.feed(markup)
    p.close()
    main = _clean("".join(p.main_parts))
    return main if len(main) >= MIN_TEXT_CHARS else _clean("".join(p.parts))


def page_title(markup: str) -> str:
    p = _Text()
    p.feed(markup)
    return re.sub(r"\s+", " ", p.title).strip()


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def job_posting(markup: str) -> dict | None:
    """The first schema.org JobPosting object in the page's JSON-LD blocks."""
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', markup, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip(), strict=False)
        except ValueError:
            continue
        for obj in _walk(data):
            kind = obj.get("@type")
            if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                return obj
    return None


def _org_name(org) -> str | None:
    if isinstance(org, list):
        org = org[0] if org else None
    if isinstance(org, dict):
        org = org.get("name")
    return org.strip() if isinstance(org, str) and org.strip() else None


def extract(url: str, markup: str) -> Page:
    posting = job_posting(markup)
    if posting:
        title = posting.get("title") if isinstance(posting.get("title"), str) else None
        company = _org_name(posting.get("hiringOrganization"))
        body = html_to_text(htmllib.unescape(str(posting.get("description") or "")))
        if len(body) >= MIN_TEXT_CHARS:
            head = [f"Role: {title.strip()}" if title else "", f"Company: {company}" if company else ""]
            text = "\n".join(h for h in head if h) + ("\n\n" if any(head) else "") + body
            return Page(url=url, html=markup, text=text, company=company, title=title)
    return Page(url=url, html=markup, text=html_to_text(markup), title=page_title(markup) or None)


def _open(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5",
                                               "Accept-Language": "en,ru;q=0.8"})
    return urllib.request.urlopen(req, timeout=TIMEOUT_S)


def fetch_vacancy(url: str, opener: Callable = _open) -> Page:
    """Raises FetchError with a short reason when the page cannot be used."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise FetchError(f"not an http(s) link: {url!r}")
    try:
        with opener(url) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if ctype and "html" not in ctype and "text" not in ctype:
                raise FetchError(f"the link is not a web page ({ctype.split(';')[0]})")
            data = resp.read(MAX_BYTES + 1)
            final_url = resp.geturl() or url
            charset = resp.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as exc:
        raise FetchError(f"the site answered HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"cannot open the link ({getattr(exc, 'reason', exc)})") from None
    if len(data) > MAX_BYTES:
        raise FetchError(f"the page is larger than {MAX_BYTES // 1_000_000} MB")
    page = extract(final_url, data.decode(charset, errors="replace"))
    if len(page.text) < MIN_TEXT_CHARS:
        raise FetchError("the page has almost no text without a browser or a sign-in")
    return page
