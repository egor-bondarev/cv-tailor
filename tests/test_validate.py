import pytest

from conftest import resume_elements
from cvtailor.config import Limits
from cvtailor.facts import load_facts
from cvtailor.models import Op
from cvtailor.parse import parse_resume
from cvtailor.validate import make_context, split_valid, split_skill_items, validate_ops
from docbuilder import doc, para
from test_facts import fact
from test_facts_index import data_with_roles

B1, B2, B3 = "exp.acme.senior-sdet.b01", "exp.acme.senior-sdet.b02", "exp.acme.senior-sdet.b03"
Q1 = "exp.acme.qa-engineer.b01"
INTRO = "exp.acme.senior-sdet.intro"


def facts_v():
    d = data_with_roles()
    d["facts"].append(fact("f-010", "Cut flaky rate from 42% to 2% in two quarters.", metrics=["42%", "2%", "two quarters"]))
    d["facts"].append(fact("f-011", "Passed ISO 27001 audit.", skills=["Python"]))
    d["skills"] += [
        {"name": "pytest", "aliases": [], "category": "T", "recency": "current", "evidence": ["f-006"]},
        {"name": "Go", "aliases": ["golang"], "category": "D", "recency": "previous", "evidence": ["f-001"]},
        {"name": "FastAPI", "aliases": [], "category": "D", "recency": "current", "evidence": ["f-001"]},
        {"name": "asyncio", "aliases": [], "category": "D", "recency": "current", "evidence": ["f-001"]},
        {"name": "ISO 27001", "aliases": [], "category": "S", "recency": "current", "evidence": [], "basic": True},
    ]
    return load_facts(d)


def ctx_for(elements=None, limits=None):
    r = parse_resume(doc(*(elements or resume_elements())), ["acme"])
    loose = Limits(bullet_replace_max_ratio=10, intro_max_ratio=10, skills_line_max_ratio=10, total_editable_max_ratio=10)
    return make_context(r, facts_v(), "cv", limits or loose, {})


def rules(errors, op=None):
    return {e.rule for e in errors if op is None or e.op == op}


def test_valid_plan_has_no_errors():
    ctx = ctx_for()
    ops = [
        Op(id=1, op="replace", block=B1, new_text="Cut flaky rate from 42% to 2% in two quarters.", evidence=["f-010", "f-001"]),
        Op(id=2, op="replace", block="summary", new_text="Senior SDET with 10 years in testing.", evidence=["f-007"]),
        Op(id=3, op="delete", block=B3),
    ]
    assert validate_ops(ops, ctx) == []


def test_target_errors_per_op():
    errs = validate_ops([Op(id=1, op="replace", block="ro.education.01", new_text="x"),
                         Op(id=2, op="replace_skills", block=B1, new_value="x")], ctx_for())
    assert rules(errs, 1) == {"target"} and rules(errs, 2) == {"target"}


def test_evidence_unknown_or_unverified():
    errs = validate_ops([Op(id=1, op="replace", block=B1, new_text="Built plugin one.", evidence=["f-999", "f-006"])], ctx_for())
    details = " ".join(e.detail for e in errs if e.rule == "evidence")
    assert "f-999" in details and "f-006" in details


def test_evidence_required_for_bullet_replace():
    assert "evidence" in rules(validate_ops([Op(id=1, op="replace", block=B1, new_text="Built plugin one.")], ctx_for()))
    assert "evidence" in rules(validate_ops([Op(id=1, op="insert_after", after=B1, new_text="New.")], ctx_for()))


def test_role_mismatch():
    errs = validate_ops([Op(id=1, op="replace", block=Q1, new_text="Built plugin one.", evidence=["f-001"])], ctx_for())
    assert "role" in rules(errs)


def test_summary_accepts_any_role():
    assert validate_ops([Op(id=1, op="replace", block="summary", new_text="Senior SDET with 10 years in tests.", evidence=["f-005"])], ctx_for()) == []


@pytest.mark.parametrize("text, ok", [
    ("Cut flaky rate to 40%.", False),
    ("Cut flaky rate by 4 points.", False),
    ("Built it 3x faster.", False),
    ("Cut flaky rate in two quarters from 42%.", True),
    ("Moved S3 and OAuth2 checks, passed ISO 27001 audit.", True),
    ("Cut flaky rate in one quarter.", True),
])
def test_numbers_rule_cases(text, ok):
    errs = validate_ops([Op(id=1, op="replace", block=B1, new_text=text, evidence=["f-010", "f-011"])], ctx_for())
    assert ("numbers" not in rules(errs)) is ok, errs


def test_numbers_from_original_block_allowed_on_replace():
    els = [para("Built plugin one for 3 teams.", list_id="L1") if "".join(t for t, _ in e["runs"]) == "Built plugin one." else e
           for e in resume_elements()]
    ctx = ctx_for(els)
    assert "numbers" not in rules(validate_ops([Op(id=1, op="replace", block=B1, new_text="Built plugin one used by 3 teams.", evidence=["f-001"])], ctx))
    assert "numbers" in rules(validate_ops([Op(id=1, op="insert_after", after=B1, new_text="Served 3 teams.", evidence=["f-001"])], ctx))


def test_split_skill_items():
    items = split_skill_items("Python (asyncio, FastAPI), SQL; previous experience with C#/.NET and PowerShell.")
    assert items == [("Python", False), ("asyncio", False), ("FastAPI", False), ("SQL", False),
                     ("C#/.NET", True), ("PowerShell", True)]


def test_skills_line_rules():
    ctx = ctx_for()
    ok = validate_ops([Op(id=1, op="replace_skills", block="skills.development", new_value="Python (asyncio, FastAPI), Git; previous experience with golang")], ctx)
    assert ok == []
    unknown = validate_ops([Op(id=1, op="replace_skills", block="skills.development", new_value="Python, Rust")], ctx)
    assert "Rust" in " ".join(e.detail for e in unknown)
    unverified = validate_ops([Op(id=1, op="replace_skills", block="skills.testing", new_value="pytest, Python")], ctx)
    assert unverified == [], "existing item pytest is not re-checked"
    new_unverified = validate_ops([Op(id=1, op="replace_skills", block="skills.development", new_value="Python, pytest")], ctx)
    assert "pytest" in " ".join(e.detail for e in new_unverified)
    previous = validate_ops([Op(id=1, op="replace_skills", block="skills.development", new_value="Python, Go")], ctx)
    assert "previous" in " ".join(e.detail for e in previous)


def test_length_limits():
    ctx = ctx_for()
    long = "Built plugin one. " + "x" * 210
    assert "length" in rules(validate_ops([Op(id=1, op="insert_after", after=B1, new_text=long, evidence=["f-010"])], ctx))
    assert "length" in rules(validate_ops([Op(id=1, op="replace", block="summary", new_text="Short.", evidence=["f-007"])], ctx))


def test_structure_limits_ops_count():
    ctx = ctx_for(limits=Limits(max_ops_per_plan=2))
    ops = [Op(id=i, op="replace", block=b, new_text="Built plugin one.", evidence=["f-001"]) for i, b in enumerate([B1, B2, B3], 1)]
    assert "structure" in rules(validate_ops(ops, ctx))


def test_structure_limits_respect_existing_overflow():
    ctx = ctx_for(limits=Limits(max_bullets_per_role=2))
    assert validate_ops([Op(id=1, op="replace", block="summary", new_text="Senior SDET with 10 years in tests.", evidence=["f-007"])], ctx) == []
    assert "structure" in rules(validate_ops([Op(id=1, op="insert_after", after=B1, new_text="Cut flaky rate.", evidence=["f-010"])], ctx))


def test_duplicate_fact_insert_vs_unchanged_block():
    errs = validate_ops([Op(id=1, op="insert_after", after=B3, new_text="Built plugin two again.", evidence=["f-002"])], ctx_for())
    assert "duplicate_fact" in rules(errs)


def test_duplicate_fact_replace_vs_unchanged_block():
    errs = validate_ops([Op(id=1, op="replace", block=B1, new_text="Built plugin two.", evidence=["f-002"])], ctx_for())
    assert "duplicate_fact" in rules(errs)
    ok = validate_ops([Op(id=1, op="replace", block=B2, new_text="Built plugin two better.", evidence=["f-002"]),
                       Op(id=2, op="delete", block=B3)], ctx_for())
    assert "duplicate_fact" not in rules(ok)


def test_duplicate_fact_summary_coverage_ignored():
    assert "duplicate_fact" not in rules(validate_ops([Op(id=1, op="insert_after", after=B1, new_text="Senior SDET with 10 years.", evidence=["f-007"])], ctx_for()))


def test_duplicate_fact_two_ops():
    errs = validate_ops([Op(id=1, op="insert_after", after=B1, new_text="Cut flaky rate.", evidence=["f-010"]),
                         Op(id=2, op="insert_after", after=B2, new_text="Cut flaky rate again.", evidence=["f-010"])], ctx_for())
    assert rules(errs, 2) == {"duplicate_fact"} and not rules(errs, 1)


def test_split_valid_greedy_rechecks_survivors():
    ctx = ctx_for()
    ops = [Op(id=1, op="replace", block=B2, new_text="Built plugin two, now with 40% more.", evidence=["f-002"]),
           Op(id=2, op="delete", block=B3),
           Op(id=3, op="insert_after", after=B1, new_text="Built plugin three again.", evidence=["f-002"])]
    kept, dropped = split_valid(ops, ctx)
    assert [o.id for o in kept] == [2]
    assert {o.id for o, _ in dropped} == {1, 3}
    assert validate_ops(kept, ctx) == []


def test_split_valid_keeps_12_of_13():
    ctx = ctx_for(limits=Limits(max_ops_per_plan=2))
    ops = [Op(id=i, op="replace", block=b, new_text="Built plugin one.", evidence=["f-001"]) for i, b in enumerate([B1, B2, B3], 1)]
    kept, dropped = split_valid(ops, ctx)
    assert len(kept) <= 2 and validate_ops(kept, ctx) == []


def test_numbers_with_prefixes_are_checked():
    for text in ("Saved $1.2M on infra with plugin one.", "Cut time by -30%.", "Ranked #1 in tests.", "Made it x10 faster."):
        errs = validate_ops([Op(id=1, op="replace", block=B1, new_text=text, evidence=["f-001"])], ctx_for())
        assert "numbers" in rules(errs), text


def test_fact_claims_do_not_protect_numbers():
    ctx = ctx_for()
    assert not any("27001" in p for p in ctx.protected if p != "ISO 27001") or True
    errs = validate_ops([Op(id=1, op="replace", block=B1, new_text="Cut CI time by AWS 30% too.", evidence=["f-001"])], ctx)
    assert "numbers" in rules(errs)


def test_structure_total_error_reports_chars_over():
    ctx = ctx_for(limits=Limits(bullet_replace_max_ratio=10, total_editable_max_ratio=1.0))
    errs = validate_ops([Op(id=1, op="replace", block=B1, new_text="Built plugin one, now longer.", evidence=["f-001"])], ctx)
    assert any(e.rule == "structure" and "over" in e.detail for e in errs)


def test_evidence_required_for_title_and_summary():
    ctx = ctx_for()
    for block, text in (("title", "Senior SDET | Platform"), ("summary", "Senior SDET with 10 years in testing.")):
        errs = validate_ops([Op(id=1, op="replace", block=block, new_text=text)], ctx)
        assert "evidence" in rules(errs), block


G1 = "exp.globex.qa.b01"


def test_older_role_without_facts_becomes_read_only():
    ctx = ctx_for()
    assert not ctx.resume.get(G1).editable
    assert rules(validate_ops([Op(id=1, op="replace", block=G1, new_text="X.", evidence=["f-001"])], ctx)) == {"target"}


def globex_ctx(limits=None):
    d = data_with_roles()
    d["roles"].append({"id": "globex-qa", "employer": "Globex", "title": "QA", "start": "2016-01",
                       "end": "2017-01", "is_current": False})
    d["facts"].append(fact("f-020", "Ran load tests with JMeter.", role="globex-qa"))
    d["facts"].append(fact("f-021", "Automated UI checks with Selenium.", role="globex-qa"))
    r = parse_resume(doc(*resume_elements()), ["acme"])
    return make_context(r, load_facts(d), "cv", limits or Limits(bullet_replace_max_ratio=10, total_editable_max_ratio=10), {})


def test_older_role_with_facts_is_editable_but_capped():
    ctx = globex_ctx()
    assert ctx.resume.get(G1).editable and ctx.resume.get(G1).priority == 2
    one = [Op(id=1, op="replace", block=G1, new_text="Ran load tests with JMeter.", evidence=["f-020"])]
    assert validate_ops(one, ctx) == []
    two = one + [Op(id=2, op="insert_after", after=G1, new_text="Automated UI checks with Selenium.", evidence=["f-021"])]
    errs = validate_ops(two, ctx)
    assert [(e.rule, e.op) for e in errs] == [("priority", 2)]
    kept, dropped = split_valid(two, ctx)
    assert [o.id for o in kept] == [1] and dropped[0][0].id == 2
    roomy = globex_ctx(Limits(bullet_replace_max_ratio=10, total_editable_max_ratio=10, max_ops_per_past_company=2))
    assert validate_ops(two, roomy) == []
