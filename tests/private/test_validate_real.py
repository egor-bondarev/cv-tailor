"""Real resumes + facts (tests/fixtures/private/m3, git-ignored)."""

import json
from pathlib import Path

import pytest

from cvtailor.config import Limits
from cvtailor.facts import load_facts
from cvtailor.models import Op
from cvtailor.parse import parse_resume
from cvtailor.validate import make_context, validate_ops

M3 = Path(__file__).resolve().parents[1] / "fixtures" / "private" / "m3"
RESUMES = ["senior-sdet", "senior-qa-automation", "qa-platform"]


@pytest.mark.parametrize("rid", RESUMES)
def test_real_role_map_and_skills_lines(rid):
    if not (M3 / f"{rid}.json").exists():
        pytest.skip("private m3 fixtures not present")
    facts = load_facts(M3 / "facts.json")
    editable = json.loads((M3 / "meta.json").read_text())["editable_companies"]
    resume = parse_resume(json.loads((M3 / f"{rid}.json").read_text()), editable)
    ctx = make_context(resume, facts, rid, Limits(), {})
    assert ctx.roles
    for i, b in enumerate(b for b in resume.blocks if b.kind == "skills"):
        value = b.text[b.text.index(": ") + 2:]
        assert validate_ops([Op(id=i + 1, op="replace_skills", block=b.id, new_value=value)], ctx) == []
