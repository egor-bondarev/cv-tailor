from cvtailor.parse import parse_resume
from cvtailor.requests import build_requests
from private.spike import load
from private.spike_ops import spike_ops


def test_build_matches_spike_requests():
    meta = load("meta.json")
    before = load("before.json")
    resume = parse_resume(before, meta["editable_companies"])
    body = build_requests(resume, spike_ops(resume, meta))
    assert body["requests"] == load("requests.json")
    assert body["writeControl"] == {"requiredRevisionId": before["revisionId"], "writeMode": "SUGGEST"}
