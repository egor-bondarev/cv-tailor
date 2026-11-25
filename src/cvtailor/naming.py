"""Slugs and names for blocks, Drive folders, documents and run directories."""

from __future__ import annotations

import re
from datetime import date

_NON_ALNUM = re.compile(r"[^\w]+|_+")


def slug(s: str) -> str:
    out = _NON_ALNUM.sub("-", s.casefold()).strip("-")
    return out or "x"


_PUNCT = re.compile(r"[^\w\s]+")
_SUFFIXES = {"inc", "llc", "ltd", "gmbh", "corp", "co", "ag", "sa", "bv"}
_PREFIXES = {"ооо", "ао", "зао", "пао"}


def normalize_company(name: str) -> str:
    words = _PUNCT.sub(" ", name.casefold()).split()
    if len(words) > 1 and words[-1] in _SUFFIXES:
        words = words[:-1]
    if len(words) > 1 and words[0] in _PREFIXES:
        words = words[1:]
    return " ".join(words)


def pick_folder(company: str, folders: list[tuple[str, str]]) -> str | None:
    key = normalize_company(company)
    matches = sorted((name, fid) for fid, name in folders if normalize_company(name) == key)
    return matches[0][1] if matches else None


def _with_index(base: str, existing: set[str], fmt: str) -> str:
    if base not in existing:
        return base
    n = 2
    while fmt.format(base=base, n=n) in existing:
        n += 1
    return fmt.format(base=base, n=n)


def doc_name(label: str, company: str, day: date, existing: set[str]) -> str:
    return _with_index(f"{label} - {company} - {day.isoformat()}", existing, "{base} ({n})")


def run_dir_name(company: str, day: date, existing: set[str]) -> str:
    return _with_index(f"{day.isoformat()}_{slug(company)}", existing, "{base}-{n}")
