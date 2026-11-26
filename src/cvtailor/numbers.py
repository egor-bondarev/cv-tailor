"""Number tokens for the anti-fabrication rule (DESIGN.md §8, rule 3)."""

from __future__ import annotations

import re

WORDS = {
    "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
}
_WORD_RE = re.compile(r"\b(" + "|".join(WORDS) + r")\b", re.IGNORECASE)
_SPLIT = re.compile(r"[\s()\[\]{}/;:\"']+|,(?=\s|$)")
_LEAD = "~≈<>$€£+-−#x×"
_TRAIL = ".,!?"
_CAPS_NUMBER = re.compile(r"\b[A-Z]{2,}[ -]\d{3,}(?:[.:]\d+)*\b(?![%+]|x\b|[A-Za-z])")
_DASH_NUMBER = re.compile(r"(?<=[A-Za-z]-)\d[\d.,]*[%+]?[A-Za-z]*")


def number_tokens(text: str, protected: list[str] | tuple[str, ...] = ()) -> list[str]:
    for name in sorted(protected, key=len, reverse=True):
        text = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", " ", text, flags=re.IGNORECASE)
    text = _WORD_RE.sub(lambda m: WORDS[m.group(1).lower()], text)
    out = []
    for word in _SPLIT.split(text):
        word = word.rstrip(_TRAIL)
        stripped = word.lstrip(_LEAD)
        if stripped and stripped[0].isdigit():
            out.append(stripped)
        elif word and word[0].isalpha():
            out += [m.group().rstrip(_TRAIL) for m in _DASH_NUMBER.finditer(word)]
    return out


def metric_tokens(values: list[str]) -> set[str]:
    return {tok for v in values for tok in number_tokens(v)}


def protected_names(skill_names: list[str], resume_texts: list[str]) -> list[str]:
    """Names that contain digits but are not quantities: skills like `Python 3`, standards like `ISO 27001`."""
    names = {n for n in skill_names if any(c.isdigit() for c in n)}
    for text in resume_texts:
        names.update(_CAPS_NUMBER.findall(text))
    return sorted(names)
