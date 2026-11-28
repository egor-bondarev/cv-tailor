import copy
import json
from pathlib import Path

import pytest

from cvtailor.config import Config, ConfigError, CoverLetterSettings
from cvtailor.facts import load_facts
from cvtailor.letter import (
    body_text, char_count, check_letter, clean, clean_letter, full_text, language_ok, letter_doc_name,
    letter_fact_ids, letter_pack, limits, make_letter_context, pdf_names, quote_in_text, replace_text_requests,
)
from cvtailor.profile import Profile, load_profile
from cvtailor.schemas import Analysis, LetterAi, Vacancy
from docbuilder import doc, para
from test_facts_index import data_with_roles
from test_state import GOOD_OPS, LOOSE, RunState, analysis, run_to_tailor, start, step, write
from test_state import env  # noqa: F401  (fixture)

VACANCY_TEXT = ("About us\nWe want every developer to ship without fear of breaking production.\n"
                "We are an innovative, fast-growing company.\n\nWhat you will do\n- Own the API test framework\n")
VAC = Vacancy(title="Senior SDET", company="Acme", language="en", summary="Test platform team.",
              must_have=["Python"], location="Remote")
PROFILE = Profile.model_validate({
    "contacts": {"name": "Jane Doe", "email": "jane@example.com", "linkedin": "linkedin.com/in/jane"},
    "motivation": [{"id": "platform-for-engineers", "text": "Build test infrastructure others rely on."}],
    "relocation": {"base": "Berlin", "text": "open to relocation"},
})
FILL = ("The platform runs the API checks for every backend merge and gives a verdict quickly, "
        "so the engineers can rely on it every day. ")


def letter_dict(**over):
    d = {
        "language": "en", "greeting": "Dear Acme team,",
        "hook": {"quote": "We want every developer to ship without fear of breaking production.", "type": "mission",
                 "strength": "strong", "bridge": "platform-for-engineers"},
        "paragraphs": [
            {"part": "intro", "text": "I am applying for the Senior SDET role. " + FILL * 2,
             "motivation": ["platform-for-engineers"]},
            {"part": "value", "text": "I built plugin one and own the QA platform used by three teams. " + FILL * 4,
             "facts": ["f-001", "f-003"]},
            {"part": "motivation", "text": "I want to build test infrastructure others rely on. " + FILL * 3,
             "motivation": ["platform-for-engineers"]},
            {"part": "closing", "text": "Thank you for your time. I would be glad to discuss the role."},
        ],
        "sign_off": "Kind regards,",
        "relocation": {"mentioned": False, "reason": "remote role"},
    }
    d.update(over)
    return d


def facts():
    return load_facts(data_with_roles())


def ctx(profile=PROFILE, lim=None, text=VACANCY_TEXT):
    return make_letter_context(VAC, text, facts(), profile, lim or limits(), ["Senior SDET with 10 years in testing."])


def errors(d, **kw):
    errs, _ = check_letter(clean_letter(LetterAi.model_validate(d)), ctx(**kw))
    return {e.rule for e in errs}, errs


def test_good_letter_passes():
    letter = clean_letter(LetterAi.model_validate(letter_dict()))
    assert 1300 <= char_count(letter) <= 2000
    errs, warnings = check_letter(letter, ctx())
    assert errs == [] and warnings == []


def test_limits_by_mode():
    assert (limits().target_min, limits().target_max, limits().hard_max) == (1300, 1800, 2000)
    assert limits("short").hard_max == 1000
    m = limits(max_chars=900)
    assert (m.mode, m.hard_max, m.target_max) == ("max", 900, 900)


def test_too_long_letter_names_how_much_to_cut():
    rules, errs = errors(letter_dict(), lim=limits("short"))
    assert "length" in rules
    assert "cut about" in next(e.detail for e in errs if e.rule == "length")


def test_short_letter_is_only_a_warning():
    d = letter_dict()
    for p in d["paragraphs"]:
        p["text"] = p["text"].split(". ")[0] + "."
    _, warnings = check_letter(clean_letter(LetterAi.model_validate(d)), ctx())
    assert warnings and "short" in warnings[0]


def test_clean_replaces_typography():
    assert clean("“Quoted” — it’s fine…\nnext") == '"Quoted" - it\'s fine... next'


def test_emoji_list_marks_contacts_and_own_expense_are_rejected():
    d = letter_dict()
    d["paragraphs"][0]["text"] += " Great \U0001F680"
    d["paragraphs"][1]["text"] = "- " + d["paragraphs"][1]["text"]
    d["paragraphs"][2]["text"] += " Write to jane@example.com."
    d["paragraphs"][3]["text"] += " I can relocate at my own expense."
    rules, _ = errors(d)
    assert {"plain_text", "contacts", "relocation"} <= rules


def test_unverified_fact_unknown_motivation_and_numbers():
    d = letter_dict()
    d["paragraphs"][1]["facts"] = ["f-006", "f-003"]  # f-006 is not verified
    d["paragraphs"][1]["text"] += " It cut run time by 40%."
    d["paragraphs"][2]["motivation"] = ["made-up"]
    rules, errs = errors(d)
    assert {"facts", "motivation", "numbers"} <= rules
    assert any("'40%'" in e.detail for e in errs)


def test_numbers_from_resume_summary_and_fact_metrics_are_allowed():
    d = letter_dict()
    d["paragraphs"][1]["text"] += " I have 10 years in testing."
    assert errors(d)[0] == set()


def test_hook_must_be_verbatim_and_bridged():
    d = letter_dict(hook={"quote": "We help developers ship safely.", "type": "mission", "strength": "strong",
                          "bridge": "nothing"})
    rules, errs = errors(d)
    assert rules == {"hook"} and len(errs) == 2


def test_hook_quote_ignores_typography_and_case():
    assert quote_in_text("we want every developer to ship without fear of breaking production",
                         VACANCY_TEXT.replace("ship", "ship\n"))


def test_language_and_structure():
    d = letter_dict(language="ru")
    d["paragraphs"] = [d["paragraphs"][1], d["paragraphs"][0], d["paragraphs"][3]]
    rules, _ = errors(d)
    assert {"language", "structure"} <= rules
    assert language_ok("ru", "Здравствуйте, команда Acme") and not language_ok("en", "Здравствуйте, команда")


def test_relocation_needs_profile_entry():
    d = letter_dict(relocation={"mentioned": True, "reason": "onsite in London"})
    assert "relocation" in errors(d, profile=Profile())[0]


def test_no_motivation_in_profile_means_none_may_be_cited():
    rules, errs = errors(letter_dict(hook=None), profile=None)
    assert rules == {"motivation"} and "has no motivation" in errs[0].detail


def test_full_text_signature_and_optional_header():
    letter = clean_letter(LetterAi.model_validate(letter_dict()))
    text = full_text(letter, PROFILE)
    assert text.startswith("Dear Acme team,") and "jane@example.com" not in text
    assert text.rstrip().endswith("Kind regards,\nJane Doe")
    text = full_text(letter, PROFILE, header=True)
    assert text.startswith("Jane Doe\njane@example.com | linkedin.com/in/jane\n\nDear Acme team,")
    assert text.rstrip().endswith("Kind regards,\nJane Doe")
    assert full_text(letter, None) == body_text(letter) + "\n"


def test_contacts_never_reach_the_model():
    letter = LetterAi.model_validate(letter_dict())
    pack = letter_pack(ctx(), Analysis.model_validate(analysis()), ["f-001"], [], letter, ["shorter"])
    assert "jane@example.com" not in pack and "Jane Doe" not in pack and "linkedin" not in pack
    assert "platform-for-engineers" in pack and "Berlin" in pack and "- shorter" in pack


def test_letter_fact_ids_prefers_covered_must_haves():
    a = Analysis.model_validate({**analysis(), "candidate_facts": ["f-003", "f-006"]})
    assert letter_fact_ids(a, facts()) == ["f-001", "f-003"]


def test_doc_and_pdf_names():
    assert letter_doc_name(PROFILE, VAC, "Acme", set()) == "Jane Doe. Cover Letter - Senior SDET"
    assert letter_doc_name(PROFILE, VAC, "Acme", {"Jane Doe. Cover Letter - Senior SDET"}).endswith("(2)")
    assert letter_doc_name(None, VAC, "Acme", set()) == "Cover Letter - Senior SDET - Acme"
    assert pdf_names(PROFILE, VAC, "copy", "letter") == {"resume": "Jane Doe. Resume - Senior SDET.pdf",
                                                        "letter": "Jane Doe. Cover Letter - Senior SDET.pdf"}
    assert pdf_names(None, VAC, "SDET - Acme", None) == {"resume": "SDET - Acme.pdf"}


def test_replace_text_requests():
    d = doc(para("old line"), para("another"))
    end = d["body"]["content"][-1]["endIndex"]
    assert replace_text_requests(d, "new\n") == [
        {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end - 1}}},
        {"insertText": {"location": {"index": 1}, "text": "new"}},
    ]


def test_load_profile(tmp_path):
    assert load_profile(tmp_path / "profile.yaml") is None
    p = tmp_path / "profile.yaml"
    p.write_text("motivation:\n  - {id: a, text: x}\n  - {id: a, text: y}\n")
    with pytest.raises(ConfigError, match="duplicate"):
        load_profile(p)
    p.write_text("contacts: {name: Jane}\nmotivation: [{id: Bad Id, text: x}]\n")
    with pytest.raises(ConfigError, match="motivation.0.id"):
        load_profile(p)


# --- the letter step in a run ------------------------------------------------------------------------------

class LetterDocs:
    """Letter documents on top of the resume FakeClient."""

    def __init__(self, client):
        self.client, self.docs, self.n, self.created = client, {}, 0, []
        orig_get, orig_update = client.get_doc, client.batch_update

        def get_doc(doc_id, preview_accepted=False):
            if doc_id in self.docs:
                return self.docs[doc_id]
            return orig_get(doc_id, preview_accepted)

        def batch_update(doc_id, body):
            if doc_id not in self.docs:
                return orig_update(doc_id, body)
            text = body["requests"][-1]["insertText"]["text"]
            d = doc(*[para(line) for line in text.split("\n")], doc_id=doc_id)
            d["revisionId"] = f"rev-{doc_id}-{len(self.created)}-{text[:5]}"
            self.docs[doc_id] = d
            self.text = text

        def create_doc(name, parent):
            self.n += 1
            fid = f"letter-{self.n}"
            self.docs[fid] = doc(para(""), doc_id=fid)
            self.created.append(name)
            return fid

        client.get_doc, client.batch_update, client.create_doc = get_doc, batch_update, create_doc


def letter_deps(env, **cfg):
    return env.make(cfg=Config(output_folder_id="out", limits=LOOSE, cover_letter=CoverLetterSettings(), **cfg),
                    profile=PROFILE)


def run_to_letter(env, deps, text=VACANCY_TEXT):
    state = start(env, deps)
    (Path(state.run_dir) / "vacancy.txt").write_text(text)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    a = step(state, deps)
    assert a.action == "ai" and a.step == "letter", a
    return state, a


def test_letter_step_writes_doc_and_summary(env):
    docs = LetterDocs(env.client)
    deps = letter_deps(env)
    state, a = run_to_letter(env, deps)
    pack = Path(a.input).read_text()
    assert "We want every developer" in pack and "jane@example.com" not in pack
    write(a, letter_dict())
    a = step(state, deps)
    assert a.action == "say" and a.step == "report"
    assert "Cover letter: https://docs.google.com/document/d/letter-1/edit" in a.text
    assert "Hook: strong mission" in a.text and "Motivation used: platform-for-engineers" in a.text
    assert docs.created == ["Jane Doe. Cover Letter - SDET"]
    assert docs.text.startswith("Dear Acme team,") and docs.text.endswith("Kind regards,\nJane Doe")
    run = Path(state.run_dir)
    assert json.loads((run / "letter_result.json").read_text())["ok"]
    assert "## Cover letter" in (run / "review.md").read_text()
    assert len(env.reviews) == 2  # resume edits and the letter


def test_letter_errors_go_back_to_the_model(env):
    LetterDocs(env.client)
    deps = letter_deps(env)
    state, a = run_to_letter(env, deps)
    write(a, letter_dict(language="de"))
    a = step(state, deps)
    assert a.action == "ai" and a.step == "letter" and any(e.rule == "language" for e in a.errors)
    assert "Errors in your previous answer" in Path(a.input).read_text()


def test_letter_failure_does_not_block_the_resume(env):
    LetterDocs(env.client)
    deps = letter_deps(env, max_ai_retries=0)
    state, a = run_to_letter(env, deps)
    write(a, letter_dict(language="de"))
    a = step(state, deps)
    assert a.action == "say" and a.step == "report" and "Cover letter: not written" in a.text


def test_reviewer_findings_get_one_fix_round(env):
    import subprocess
    LetterDocs(env.client)
    deps = letter_deps(env)
    answers = iter(['{"verdicts": [{"op": 1, "verdict": "supported"}]}',
                    '{"verdicts": [{"op": 2, "verdict": "partial", "quote": "three teams", "comment": "two"}]}',
                    '{"verdicts": [{"op": 2, "verdict": "partial", "quote": "three teams", "comment": "two"}]}'])
    deps.reviewer_run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=next(answers), stderr="")
    state, a = run_to_letter(env, deps)
    write(a, letter_dict())
    a = step(state, deps)
    assert a.action == "ai" and a.step == "letter" and a.errors[0].rule == "review"
    assert "Current letter" in Path(a.input).read_text()
    write(a, letter_dict())
    a = step(state, deps)
    assert a.action == "say" and "Letter, check carefully: paragraph 2 partial «three teams»" in a.text
    assert "after a fix round" in a.text


def test_revision_rewrites_the_same_doc_unless_edited_by_hand(env):
    docs = LetterDocs(env.client)
    deps = letter_deps(env)
    state, a = run_to_letter(env, deps)
    write(a, letter_dict())
    step(state, deps)
    s = RunState.load(Path(state.run_dir))
    s.letter_feedback, s.letter_revise = ["drop the motivation paragraph"], True
    s.save()
    a = step(state, deps, from_step="letter")
    assert a.action == "ai" and a.step == "letter"
    pack = Path(a.input).read_text()
    assert "drop the motivation paragraph" in pack and "Current letter" in pack
    d = letter_dict()
    d["paragraphs"].pop(2)
    d["paragraphs"][1]["text"] += FILL * 3
    write(a, d)
    a = step(state, deps)
    assert a.action == "say" and docs.created == ["Jane Doe. Cover Letter - SDET"]
    # an edit by hand changes the revision: the next rewrite keeps that document and writes a new one
    docs.docs["letter-1"]["revisionId"] = "edited-by-hand"
    a = step(state, deps, from_step="letter")
    write(a, d)
    a = step(state, deps)
    assert len(docs.created) == 2 and "edited by hand" in a.text


def test_disabled_letter_skips_the_step(env):
    deps = env.make()
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    a = step(state, deps)
    assert a.action == "say" and "Cover letter" not in a.text


def test_extract_drops_paraphrased_hooks(env):
    deps = env.make()
    state = start(env, deps)
    (Path(state.run_dir) / "vacancy.txt").write_text(VACANCY_TEXT)
    a = step(state, deps)
    from test_checks import VAC as RAW
    raw = copy.deepcopy(RAW)
    raw["hooks"] = [{"quote": "We want every developer to ship without fear of breaking production.",
                     "type": "mission", "strength": "strong"},
                    {"quote": "We make developers fearless.", "type": "mission", "strength": "weak"}]
    write(a, raw)
    step(state, deps)
    hooks = json.loads((Path(state.run_dir) / "vacancy.json").read_text())["hooks"]
    assert [h["strength"] for h in hooks] == ["strong"]


def test_too_many_facts_is_a_list_of_bullets():
    d = letter_dict()
    d["paragraphs"][1]["facts"] = ["f-001", "f-002", "f-003", "f-004", "f-005", "f-007"]
    rules, errs = errors(d)
    assert rules == {"facts"} and "6 facts cited" in errs[0].detail


# --- the letter written in parallel by `cvtailor run` ------------------------------------------------------

def test_run_drafts_the_letter_in_parallel_and_adopts_it(env):
    from cvtailor.autorun import run_until_stop
    from test_autorun import ANSWERS, FakeModel
    LetterDocs(env.client)
    deps = letter_deps(env)
    state = start(env, deps)
    (Path(state.run_dir) / "vacancy.txt").write_text(VACANCY_TEXT)
    model = FakeModel({**ANSWERS, "letter": [letter_dict()]})
    act = run_until_stop(Path(state.run_dir), deps, call=model)
    assert act.action == "say" and "Cover letter: https://" in act.text
    assert [c[0] for c in model.calls].count("letter") == 1  # the draft, not a second call
    log = [json.loads(x) for x in (Path(state.run_dir) / "ai_calls.jsonl").read_text().splitlines()]
    assert [r["parallel"] for r in log if r["step"] == "letter"] == [True]
    assert len(env.reviews) == 2  # the letter review also ran in parallel and was reused
    assert not (Path(state.run_dir) / "letter_prefetch.json").exists()


def test_draft_with_errors_becomes_the_first_attempt(env):
    from cvtailor.autorun import run_until_stop
    from test_autorun import ANSWERS, FakeModel
    LetterDocs(env.client)
    deps = letter_deps(env)
    state = start(env, deps)
    (Path(state.run_dir) / "vacancy.txt").write_text(VACANCY_TEXT)
    model = FakeModel({**ANSWERS, "letter": [letter_dict(language="de"), letter_dict()]})
    act = run_until_stop(Path(state.run_dir), deps, call=model)
    assert act.action == "say" and "Cover letter: https://" in act.text
    assert [c for c in model.calls if c[0] == "letter"] == [("letter", False), ("letter", True)]


def test_stale_draft_is_ignored(env):
    LetterDocs(env.client)
    deps = letter_deps(env)
    state = start(env, deps)
    run = Path(state.run_dir)
    (run / "vacancy.txt").write_text(VACANCY_TEXT)
    a = run_to_tailor(env, deps, state)
    (run / "letter_ai.prefetch.json").write_text(json.dumps(letter_dict()))
    (run / "letter_prefetch.json").write_text(json.dumps({"pack_sha": "from-another-analysis"}))
    write(a, GOOD_OPS)
    a = step(state, deps)
    assert a.action == "ai" and a.step == "letter"  # written again, not taken from the old draft
    assert not (run / "letter_ai.prefetch.json").exists()


def test_final_holds_the_pdfs_while_a_role_is_split(env, monkeypatch, capsys):
    import cvtailor.cli as cli
    from cvtailor.layout import LayoutResult
    from cvtailor.models import VerifyReport
    LetterDocs(env.client)
    deps = letter_deps(env)
    state, a = run_to_letter(env, deps)
    write(a, letter_dict())
    step(state, deps)
    monkeypatch.setattr(cli, "_deps", lambda repo: deps)
    monkeypatch.setattr("cvtailor.verify.final_check", lambda *a, **k: VerifyReport(ok=True, problems=[]))
    monkeypatch.setattr("cvtailor.docmodel.has_suggestions", lambda d: [])
    monkeypatch.setattr("cvtailor.layout.check_layout",
                        lambda client, doc_id, fix: LayoutResult(split="QA (Acme)", pages="1-2"))
    exported = []
    monkeypatch.setattr(cli, "export_pdfs", lambda client, st, d: exported.append(1) or "PDF in the company folder: x.")
    assert cli.main(["final", "--run", state.run_dir]) == 0
    assert "PDF not exported: a role is split" in capsys.readouterr().out and not exported
    assert cli.main(["final", "--run", state.run_dir, "--keep-layout"]) == 0
    assert "PDF in the company folder" in capsys.readouterr().out and exported == [1]
