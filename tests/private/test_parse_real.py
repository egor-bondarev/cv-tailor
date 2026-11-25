from cvtailor.parse import parse_resume
from private.spike import load


def test_spike_resume_parses_and_prefixes_resolve():
    meta = load("meta.json")
    r = parse_resume(load("before.json"), meta["editable_companies"])
    for op in meta["ops"]:
        hits = [b for b in r.blocks if b.text.startswith(op["prefix"])]
        assert len(hits) == 1, op["prefix"]
        assert hits[0].editable
