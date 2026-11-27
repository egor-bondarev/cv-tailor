from cvtailor import layout
from cvtailor.docmodel import paragraphs, snapshot
from cvtailor.layout import LayoutResult, check_layout, find_split, fix_requests, paragraph_pages, units
from docbuilder import doc, para

BREAK = {"pageBreakBefore": True}


def resume(globex_break=True, inline_break=False):
    els = [
        para("SUMMARY", "HEADING_1"),
        para("Summary text."),
        para("EXPERIENCE", "HEADING_1"),
        para("Acme | Remote", "HEADING_2"),
        para("Payments platform."),
        para("Senior SDET | 2023 - now", "HEADING_3"),
        para("Built the API test framework.", list_id="L1"),
        para("Cut the regression run time.", list_id="L1"),
        para("QA Engineer | 2020 - 2023", "HEADING_3"),
        para("Automated the release checks.", list_id="L2"),
        para("Wrote the load tests.", list_id="L2"),
    ]
    if inline_break:
        els.append(para("X"))
    els += [
        para("Globex | Berlin", "HEADING_2", pstyle=BREAK if globex_break else None),
        para("QA | 2018 - 2020", "HEADING_3"),
        para("Tested the mobile app.", list_id="L3"),
        para("EDUCATION", "HEADING_1"),
        para("BSc Computer Science"),
    ]
    d = doc(*els)
    if inline_break:
        x = next(el for el in d["body"]["content"] if "paragraph" in el
                 and el["paragraph"]["elements"][0].get("textRun", {}).get("content") == "X")
        first = x["paragraph"]["elements"][0]
        x["paragraph"]["elements"][0] = {"startIndex": first["startIndex"], "endIndex": first["endIndex"], "pageBreak": {}}
    return d


PAGE1 = "Summary text. EXPERIENCE Acme | Remote Payments platform. Senior SDET | 2023 - now ● Built the API test framework."
FITS = [PAGE1 + " Cut the regression run time. QA Engineer | 2020 - 2023 Automated the release checks. Wrote the load tests.",
        "Globex | Berlin QA | 2018 - 2020 Tested the mobile app. EDUCATION BSc Computer Science"]
SPLIT = [PAGE1 + " Cut the regression run time. QA Engineer | 2020 - 2023 ● Automated the release checks.",
         "● Wrote the load tests.",
         "Globex | Berlin QA | 2018 - 2020 Tested the mobile app. EDUCATION BSc Computer Science"]


def _para(d, text):
    return next(p for p in paragraphs(d) if p.body_text == text)


def test_units_group_headings_with_their_role():
    us = units(resume())
    assert [u.label for u in us] == ["Senior SDET (Acme)", "QA Engineer (Acme)", "QA (Globex)"]
    assert [p.body_text for p in us[0].paras[:4]] == ["EXPERIENCE", "Acme | Remote", "Payments platform.",
                                                     "Senior SDET | 2023 - now"]
    assert us[1].paras[0].body_text == "QA Engineer | 2020 - 2023"
    assert us[2].paras[-1].body_text == "Tested the mobile app."


def test_paragraph_pages_ignores_bullets_spaces_and_ligatures():
    d = doc(para("Certified profile"), para("Next one"))
    where = paragraph_pages(d, ["Cer-\ntiﬁed   proﬁle", "● Next one"])
    assert sorted(where.values()) == [(0, 0), (1, 1)]


def test_no_split_when_roles_fit():
    assert find_split(resume(), FITS) is None


def test_split_role_found():
    split = find_split(resume(), SPLIT)
    assert split.unit.label == "QA Engineer (Acme)"
    assert (split.first_page, split.last_page, split.starts_page) == (0, 1, False)


def test_fix_moves_role_and_drops_page_break_style_after_it():
    d = resume()
    requests, notes = fix_requests(d, find_split(d, SPLIT).unit)
    globex, role = _para(d, "Globex | Berlin"), _para(d, "QA Engineer | 2020 - 2023")
    assert requests == [
        {"updateParagraphStyle": {"range": {"startIndex": globex.start, "endIndex": globex.end},
                                  "paragraphStyle": {"pageBreakBefore": False}, "fields": "pageBreakBefore"}},
        {"updateParagraphStyle": {"range": {"startIndex": role.start, "endIndex": role.end},
                                  "paragraphStyle": {"pageBreakBefore": True}, "fields": "pageBreakBefore"}},
    ]
    assert notes == ["moved QA Engineer (Acme) to the next page", "removed the page break before 'Globex'"]


def test_fix_deletes_inline_page_break_after_role():
    d = resume(globex_break=False, inline_break=True)
    split = find_split(d, SPLIT)
    requests, notes = fix_requests(d, split.unit)
    brk = next(e for el in d["body"]["content"] if "paragraph" in el
               for e in el["paragraph"]["elements"] if "pageBreak" in e)
    assert requests[0] == {"deleteContentRange": {"range": {"startIndex": brk["startIndex"], "endIndex": brk["endIndex"]}}}
    assert requests[-1]["updateParagraphStyle"]["paragraphStyle"] == {"pageBreakBefore": True}
    assert len(requests) == 2 and "removed 1 page break(s) after it" in notes


def test_role_longer_than_a_page_is_not_fixable():
    pages = [PAGE1 + " Cut the regression run time.",
             "QA Engineer | 2020 - 2023 Automated the release checks.",
             "Wrote the load tests. Globex | Berlin QA | 2018 - 2020 Tested the mobile app. EDUCATION BSc Computer Science"]
    assert find_split(resume(), pages).starts_page


class FakeClient:
    def __init__(self, rounds):
        self.rounds = list(rounds)  # pages before each batch update
        self.bodies = []

    def get_doc(self, doc_id):
        return resume()

    def export_pdf(self, file_id):
        return self.rounds[len(self.bodies)]

    def batch_update(self, doc_id, body):
        self.bodies.append(body)


def test_check_layout_fixes_and_rechecks(monkeypatch):
    monkeypatch.setattr(layout, "pdf_pages", lambda pages: pages)
    client = FakeClient([SPLIT, FITS])
    res = check_layout(client, "doc-1", fix=True)
    assert len(client.bodies) == 1 and client.bodies[0]["writeControl"] == {"requiredRevisionId": "rev-1"}
    assert res.text(True) == ("Layout fixed: moved QA Engineer (Acme) to the next page; "
                              "removed the page break before 'Globex'.")


def test_check_layout_without_fix_only_reports(monkeypatch):
    monkeypatch.setattr(layout, "pdf_pages", lambda pages: pages)
    client = FakeClient([SPLIT])
    res = check_layout(client, "doc-1", fix=False)
    assert client.bodies == []
    assert res.text(False) == ("Layout: QA Engineer (Acme) is split across pages 1-2; "
                               "run `cvtailor final --fix-layout` to move it to the next page.")


def test_check_layout_stops_after_max_rounds(monkeypatch):
    monkeypatch.setattr(layout, "pdf_pages", lambda pages: pages)
    client = FakeClient([SPLIT, SPLIT, SPLIT])
    res = check_layout(client, "doc-1", fix=True, max_rounds=2)
    assert len(client.bodies) == 2 and res.problem == "still split after 2 rounds"


def test_layout_result_ok_text():
    assert LayoutResult().text(False) == "Layout: no role is split across pages."


def test_page_break_style_is_not_compared():
    a = paragraphs(resume())
    b = paragraphs(resume(globex_break=False))
    globex = [i for i, p in enumerate(a) if p.body_text == "Globex | Berlin"][0]
    assert snapshot(a[globex]) == snapshot(b[globex])
