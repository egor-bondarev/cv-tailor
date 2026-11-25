"""Helpers for tests on real spike data (tests/fixtures/private/m2_spike, git-ignored)."""

import json
from pathlib import Path

import pytest

SPIKE = Path(__file__).resolve().parents[1] / "fixtures" / "private" / "m2_spike"


def load(name: str):
    if not SPIKE.exists():
        pytest.skip("private spike fixtures not present")
    return json.loads((SPIKE / name).read_text())
