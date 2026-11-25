from cvtailor.parse import parse_resume
from cvtailor.verify import final_check, verify_applied
from private.spike import load
from private.spike_ops import spike_ops


def test_spike_preview_and_final_pass():
    meta = load("meta.json")
    before = load("before.json")
    resume = parse_resume(before, meta["editable_companies"])
    ops = spike_ops(resume, meta)
    applied = verify_applied(before, load("after_preview.json"), resume, ops)
    assert applied.ok, applied.problems
    final = final_check(before, load("final.json"), resume, meta["editable_companies"])
    assert final.ok, final.problems
