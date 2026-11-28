"""Cover letter: limits, plain-text cleanup, checks, text and inputs for the AI steps (v2 V6)."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass

from cvtailor.checks import CheckError
from cvtailor.facts import FactsFile, verified_facts
from cvtailor.numbers import metric_tokens, number_tokens, protected_names
from cvtailor.profile import Profile
from cvtailor.schemas import Analysis, LetterAi, Vacancy

PART_ORDER = ["intro", "value", "motivation", "closing"]
CYRILLIC_LANGS = {"ru", "uk", "be", "bg", "sr", "mk", "kk", "ky", "tg", "mn"}
VACANCY_TEXT_MAX = 8000
MAX_LETTER_FACTS = 5

# Typographic characters that break plain-text pasting: replaced, not rejected.
_REPLACE = {
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "‘": "'", "’": "'", "‚": "'", "′": "'",
    "—": "-", "–": "-", "‒": "-", "−": "-", "…": "...",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    "​": "", "‌": "", "‍": "", "﻿": "",
}
_LIST_MARK = re.compile(r"^\s*(?:[-*•●▪‣]|\d+[.)])\s+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_URL = re.compile(r"https?://|www\.|linkedin\.com", re.I)
_OWN_EXPENSE = re.compile(r"own (?:expense|cost)|self-funded|за св(?:ой|ои) сч[её]т|за собственный сч[её]т", re.I)


@dataclass(frozen=True)
class Limits:
    mode: str
    target_min: int
    target_max: int
    hard_max: int

    def describe(self) -> str:
        if self.mode == "max":
            return f"at most {self.hard_max} characters"
        return f"{self.target_min}-{self.target_max} characters, never more than {self.hard_max}"


def limits(mode: str = "full", max_chars: int | None = None) -> Limits:
    if max_chars:
        return Limits("max", int(max_chars * 0.75), max_chars, max_chars)
    if mode == "short":
        return Limits("short", 650, 900, 1000)
    return Limits("full", 1300, 1800, 2000)


def clean(text: str) -> str:
    """One paragraph of plain text: straight quotes, hyphens, ordinary spaces, no line breaks."""
    text = unicodedata.normalize("NFC", text)
    text = "".join(_REPLACE.get(ch, ch) for ch in text)
    return re.sub(r"[ \t\r\n]+", " ", text).strip()


def _bad_chars(text: str) -> list[str]:
    bad = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf", "Co", "Cs") or cat == "So" or ord(ch) >= 0x1F000:
            bad.append(ch)
    return sorted(set(bad))


def clean_letter(letter: LetterAi) -> LetterAi:
    paras = [p.model_copy(update={"text": clean(p.text)}) for p in letter.paragraphs]
    return letter.model_copy(update={"greeting": clean(letter.greeting), "sign_off": clean(letter.sign_off),
                                     "paragraphs": paras, "language": letter.language.strip().lower()})


def body_text(letter: LetterAi, name: str = "") -> str:
    """Greeting, paragraphs and sign-off separated by blank lines; the signature name on the last line."""
    sign = letter.sign_off + (f"\n{name}" if name else "")
    return "\n\n".join([letter.greeting, *[p.text for p in letter.paragraphs], sign])


def char_count(letter: LetterAi) -> int:
    """What the limits count: the letter without the contacts header and the signature name."""
    return len(body_text(letter))


def full_text(letter: LetterAi, profile: Profile | None, header: bool = False) -> str:
    """The document text: the letter signed with the candidate's name; the contacts header only on request
    (a letter is usually pasted into a form or an e-mail, where contacts are redundant)."""
    name = profile.contacts.name.strip() if profile else ""
    header = profile.header() if profile and header else ""
    body = body_text(letter, name)
    return f"{header}\n\n{body}\n" if header else body + "\n"


def _norm_quote(text: str) -> str:
    return re.sub(r"\s+", " ", clean(text)).casefold()


def quote_in_text(quote: str, text: str) -> bool:
    q = _norm_quote(quote)
    return bool(q) and q in _norm_quote(text)


def script_share(text: str) -> float:
    """Share of Cyrillic letters among all letters."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum("CYRILLIC" in unicodedata.name(ch, "") for ch in letters) / len(letters)


def language_ok(language: str, text: str) -> bool:
    share = script_share(text)
    if language in CYRILLIC_LANGS:
        return share >= 0.6
    if language.isalpha() and len(language) == 2 and language not in {"zh", "ja", "ko", "ar", "he", "hi", "th"}:
        return share <= 0.2
    return True  # other scripts are not checked


@dataclass
class LetterContext:
    vacancy: Vacancy
    vacancy_text: str
    facts: FactsFile
    profile: Profile | None
    limits: Limits
    allowed_numbers: set[str]  # numbers the candidate's own resume already states (summary, intro)
    protected: list[str]


def make_letter_context(vacancy: Vacancy, vacancy_text: str, facts: FactsFile, profile: Profile | None,
                        lim: Limits, resume_texts: list[str]) -> LetterContext:
    protected = protected_names([s.name for s in facts.skills], [vacancy_text, *resume_texts])
    allowed = {t for text in resume_texts for t in number_tokens(text, protected)}
    return LetterContext(vacancy, vacancy_text, facts, profile, lim, allowed, protected)


def check_letter(letter: LetterAi, ctx: LetterContext) -> tuple[list[CheckError], list[str]]:
    """Errors send the letter back to the model; warnings only go to the summary."""
    errs: list[CheckError] = []
    warnings: list[str] = []

    def err(rule: str, detail: str, para: int | None = None) -> None:
        errs.append(CheckError(rule=rule, detail=detail, op=para))

    verified = verified_facts(ctx.facts)
    motivation = ctx.profile.motivation_ids if ctx.profile else set()

    if letter.language != ctx.vacancy.language.lower():
        err("language", f"the letter must be in the vacancy language {ctx.vacancy.language!r}, "
                        f"not {letter.language!r}")
    whole = body_text(letter)
    if not language_ok(ctx.vacancy.language.lower(), whole):
        err("language", f"the text is not written in {ctx.vacancy.language!r}")

    parts = [p.part for p in letter.paragraphs]
    for need in ("intro", "value", "closing"):
        if need not in parts:
            err("structure", f"no {need!r} paragraph")
    if [PART_ORDER.index(p) for p in parts] != sorted(PART_ORDER.index(p) for p in parts):
        err("structure", f"paragraph order must follow {PART_ORDER}, got {parts}")
    for part, most in (("intro", 1), ("value", 2), ("motivation", 1), ("closing", 1)):
        if parts.count(part) > most:
            err("structure", f"at most {most} {part!r} paragraph(s)")

    n = char_count(letter)
    if n > ctx.limits.hard_max:
        err("length", f"{n} characters, the limit is {ctx.limits.hard_max} (target {ctx.limits.describe()}): "
                      f"cut about {n - ctx.limits.target_max} characters")
    elif n < ctx.limits.target_min:
        warnings.append(f"the letter is short: {n} characters, target {ctx.limits.describe()}")

    pieces = [("greeting", letter.greeting, None), ("sign_off", letter.sign_off, None)]
    pieces += [(f"paragraph {i}", p.text, i) for i, p in enumerate(letter.paragraphs, 1)]
    for where, text, i in pieces:
        bad = _bad_chars(text)
        if bad:
            err("plain_text", f"{where}: remove {', '.join(repr(c) for c in bad)} (plain text only)", i)
        if _LIST_MARK.match(text):
            err("plain_text", f"{where}: no list markers, write sentences", i)
        if _EMAIL.search(text) or _URL.search(text):
            err("contacts", f"{where}: no e-mail addresses or links; contacts are added by the tool", i)
        if _OWN_EXPENSE.search(text):
            err("relocation", f"{where}: do not offer to relocate at your own expense", i)

    for i, p in enumerate(letter.paragraphs, 1):
        for fid in p.facts:
            if fid not in verified:
                err("facts", f"paragraph {i}: {fid!r} is not a verified fact", i)
        for mid in p.motivation:
            if mid not in motivation:
                err("motivation", f"paragraph {i}: {mid!r} is not a motivation id in profile.yaml"
                                  + ("" if motivation else " (the profile has no motivation: cite none)"), i)
        cited = [verified[fid] for fid in p.facts if fid in verified]
        allowed = set(ctx.allowed_numbers) | metric_tokens([m.value for f in cited for m in f.metrics])
        allowed |= {t for f in cited for t in number_tokens(f.claim, ctx.protected)}
        if letter.hook and p.part == "intro":
            allowed |= set(number_tokens(letter.hook.quote, ctx.protected))
        for tok in number_tokens(p.text, ctx.protected):
            if tok not in allowed:
                err("numbers", f"paragraph {i}: number {tok!r} is not in its facts {p.facts or '[]'} "
                               "(claims and metrics) or in the resume summary", i)
    cited_all = {f for p in letter.paragraphs for f in p.facts}
    if len(cited_all) > MAX_LETTER_FACTS:
        err("facts", f"{len(cited_all)} facts cited; a letter is not a list of resume bullets: "
                     f"keep the {MAX_LETTER_FACTS} that matter most for this vacancy")
    value = [p for p in letter.paragraphs if p.part == "value"]
    if value and not any(p.facts for p in value):
        err("facts", "the value paragraph must cite the facts it rests on")

    if letter.hook:
        h = letter.hook
        if not quote_in_text(h.quote, ctx.vacancy_text):
            err("hook", "hook.quote must be copied verbatim from the vacancy text")
        if h.bridge not in verified and h.bridge not in motivation:
            err("hook", f"hook.bridge {h.bridge!r} must be a verified fact id or a motivation id")
    if letter.relocation.mentioned and not (ctx.profile and ctx.profile.relocation):
        err("relocation", "profile.yaml has no relocation entry: do not mention relocation")
    return errs, warnings


# --- inputs for the AI steps -------------------------------------------------------------------------------

def _facts_lines(facts: FactsFile, ids: list[str]) -> list[str]:
    verified = verified_facts(facts)
    roles = {r.id: r for r in facts.roles}
    out = []
    for fid in ids:
        f = verified.get(fid)
        if not f:
            continue
        role = roles.get(f.role_id)
        where = f"{role.title} at {role.employer}{' (current)' if role.is_current else ''}" if role else f.role_id
        line = f"{f.id} | {where} | {f.type} | {f.claim}"
        if f.metrics:
            line += " | metrics: " + "; ".join(m.value for m in f.metrics)
        if f.notes:
            line += f" | note: {f.notes}"
        out.append(line)
    return out


def letter_fact_ids(analysis: Analysis, facts: FactsFile) -> list[str]:
    """Facts behind covered requirements first, then the analysis picks. Independent of the resume edits, so the
    letter can be written while the edits are planned (v2 V6)."""
    verified = verified_facts(facts)
    ordered: list[str] = []
    for r in sorted(analysis.requirements, key=lambda r: (r.kind != "must", r.status not in ("covered", "in_facts"))):
        ordered += r.fact_ids
    ordered += analysis.candidate_facts
    seen: set[str] = set()
    return [f for f in ordered if f in verified and not (f in seen or seen.add(f))]


def letter_pack(ctx: LetterContext, analysis: Analysis, fact_ids: list[str], errors: list[CheckError],
                previous: LetterAi | None = None, feedback: list[str] | None = None) -> str:
    v = ctx.vacancy
    lines: list[str] = []
    if errors:
        lines += ["# Errors in your previous answer (fix all of them)", ""]
        lines += [f"- [{e.rule}]{f' paragraph {e.op}' if e.op else ''} {e.detail}" for e in errors] + [""]
    lines += ["# Mode", "", f"{ctx.limits.mode}: {ctx.limits.describe()} (greeting, paragraphs and sign-off; "
              "the signature name, and the contacts header when enabled, are added by the tool)", ""]
    if feedback:
        lines += ["# What the candidate asked to change (apply all, the latest wins on conflict)", ""]
        lines += [f"- {f}" for f in feedback] + [""]
    if previous is not None:
        lines += ["# Current letter (revise it, keep what the feedback does not touch)", "",
                  "```json", previous.model_dump_json(indent=1), "```", ""]
    vac = {"title": v.title, "company": v.company, "language": v.language, "location": v.location,
           "summary": v.summary, "must_have": v.must_have, "responsibilities": v.responsibilities[:8]}
    lines += ["# Vacancy", "", "```json", json.dumps(vac, ensure_ascii=False, indent=1), "```", ""]
    if v.hooks:
        lines += ["# Hook candidates found in the vacancy", ""]
        lines += [f"- [{h.type}, {h.strength}] «{h.quote}» — {h.why}" for h in v.hooks] + [""]
    else:
        lines += ["# Hook candidates found in the vacancy", "", "none listed: look in the company block of the "
                  "vacancy text yourself, by the same rules", ""]
    must = [r for r in analysis.requirements if r.kind == "must"]
    lines += ["# Must-have match (from the resume analysis)", ""]
    lines += [f"- {r.text}: {r.status}{' — facts ' + ', '.join(r.fact_ids) if r.fact_ids else ''}" for r in must]
    lines += ["", "# Verified facts (cite their ids; numbers only from their metrics)", ""]
    lines += _facts_lines(ctx.facts, fact_ids) or ["(none)"]
    lines += ["", "# Numbers the resume already states (may be repeated)", "",
              ", ".join(sorted(ctx.allowed_numbers)) or "(none)", ""]
    p = ctx.profile
    lines += ["# Candidate motivation (profile.yaml; cite ids, never invent motivation)", ""]
    lines += [f"- {m.id}: {m.text}" for m in p.motivation] if p and p.motivation else ["(none: build the "
              "motivation paragraph on the match between the vacancy and the experience, or leave it out)"]
    lines += ["", "# Relocation", ""]
    if p and p.relocation:
        lines += [f"Candidate is based in {p.relocation.base}; phrase if needed: \"{p.relocation.text}\". "
                  f"Vacancy location: {v.location or 'not stated'}.", ""]
    else:
        lines += ["not configured: never mention relocation", ""]
    text = ctx.vacancy_text if len(ctx.vacancy_text) <= VACANCY_TEXT_MAX else ctx.vacancy_text[:VACANCY_TEXT_MAX] + "\n[…]"
    lines += ["# Vacancy text (the only source about the company)", "", "```text", text, "```", ""]
    return "\n".join(lines)


def digest(obj) -> str:
    """Stable hash of a pack text or a letter, to tell whether a draft written in parallel still fits."""
    import hashlib
    text = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def review_letter_pack(letter: LetterAi, ctx: LetterContext) -> str:
    verified = verified_facts(ctx.facts)
    roles = {r.id: r for r in ctx.facts.roles}
    motivation = {m.id: m.text for m in ctx.profile.motivation} if ctx.profile else {}

    def role(fid: str) -> str:
        r = roles.get(verified[fid].role_id)
        if not r:
            return verified[fid].role_id
        return f"{r.title} at {r.employer} ({'current role' if r.is_current else 'past role'})"

    items = []
    for i, p in enumerate(letter.paragraphs, 1):
        items.append({
            "op": i, "part": p.part, "text": p.text,
            "facts": [{"id": f, "role": role(f), "claim": verified[f].claim,
                       "metrics": [m.value for m in verified[f].metrics], "notes": verified[f].notes}
                      for f in p.facts if f in verified],
            "motivation": [{"id": m, "text": motivation[m]} for m in p.motivation if m in motivation],
        })
    v = ctx.vacancy
    head = {"company_quote": letter.hook.quote if letter.hook else None, "vacancy_summary": v.summary,
            "title": v.title, "must_have": v.must_have, "nice_to_have": v.nice_to_have,
            "responsibilities": v.responsibilities}
    return ("# Letter paragraphs to review\n\n```json\n" + json.dumps(items, ensure_ascii=False, indent=1)
            + "\n```\n\n# What the vacancy says about the company and the role\n\n```json\n"
            + json.dumps(head, ensure_ascii=False, indent=1) + "\n```\n")


# --- Google Docs ---------------------------------------------------------------------------------------------

def _role(vacancy: Vacancy) -> str:
    return re.sub(r"\s+", " ", vacancy.title).strip(" .") or "Application"


def letter_doc_name(profile: Profile | None, vacancy: Vacancy, company: str, existing: set[str]) -> str:
    """`<Name>. Cover Letter - <Role>` (Notion rule); without a name in the profile the company goes in."""
    name = profile.contacts.name.strip() if profile else ""
    base = f"{name}. Cover Letter - {_role(vacancy)}" if name else f"Cover Letter - {_role(vacancy)} - {company}"
    if base not in existing:
        return base
    n = 2
    while f"{base} ({n})" in existing:
        n += 1
    return f"{base} ({n})"


def pdf_names(profile: Profile | None, vacancy: Vacancy, resume_doc: str, letter_doc: str | None) -> dict[str, str]:
    name = profile.contacts.name.strip() if profile else ""
    if name:
        out = {"resume": f"{name}. Resume - {_role(vacancy)}.pdf"}
        if letter_doc:
            out["letter"] = f"{name}. Cover Letter - {_role(vacancy)}.pdf"
        return out
    out = {"resume": f"{resume_doc}.pdf"}
    if letter_doc:
        out["letter"] = f"{letter_doc}.pdf"
    return out


def replace_text_requests(doc: dict, text: str) -> list[dict]:
    """Requests that replace the whole body of a plain document with `text` (written directly, not suggested)."""
    from cvtailor.docmodel import body_content

    content = body_content(doc)
    end = content[-1]["endIndex"] if content else 1
    requests: list[dict] = []
    if end - 1 > 1:
        requests.append({"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end - 1}}})
    requests.append({"insertText": {"location": {"index": 1}, "text": text.rstrip("\n")}})
    return requests
