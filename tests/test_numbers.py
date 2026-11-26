from cvtailor.numbers import metric_tokens, number_tokens, protected_names


def test_number_tokens_cases():
    text = "Cut 42% of S3 costs with OAuth2 in two quarters, ~10 min, v4.0, 3x faster, 200ms p95"
    assert number_tokens(text) == ["42%", "2", "10", "3x", "200ms"]
    assert number_tokens("one of the teams") == []
    assert number_tokens("ISO 27001 audit", ["ISO 27001"]) == []
    assert number_tokens("Grew from 64 to 97, (2.5M runs).") == ["64", "97", "2.5M"]
    assert number_tokens("Twelve services, 180+ cases; 1,200 users") == ["12", "180+", "1,200"]


def test_metric_tokens():
    assert metric_tokens(["3 350K", "10 minutes", "two hours"]) == {"3", "350K", "10", "2"}


def test_protected_names():
    names = protected_names(["Python 3", "pytest", "S3"], ["Passed ISO 27001 audit", "Used Python 3 daily"])
    assert "Python 3" in names and "ISO 27001" in names and "S3" in names
    assert "pytest" not in names


def test_prefixed_numbers_are_tokens():
    assert number_tokens("$1.2M saved, -30% time, +40% speed, €50K, x10, #1 rank, Top-5") == [
        "1.2M", "30%", "40%", "50K", "10", "1", "5"]
    assert metric_tokens(["$1.2M"]) == {"1.2M"}


def test_protected_caps_phrase_not_followed_by_unit():
    names = protected_names([], ["Cut AWS 30% of spend", "Passed ISO 27001 audit"])
    assert "ISO 27001" in names and not any(n.startswith("AWS") for n in names)
