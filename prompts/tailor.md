# Step: write the edit plan

Write a small set of edits that make the resume copy fit the vacancy, using only verified facts. Python validates every edit; edits that break a rule are rejected.

## Input
`tailor.pack.md`: vacancy, analysis, editable blocks (with `chars`), read-only context, candidate facts (`claim`, `metrics`, `role_id`, `skills`, `notes`), `groups`, `covered_by`, skills vocabulary, limits, and possibly `Errors from previous attempt`.

## Output
Exactly one JSON object `{"ops": [...]}`. Each op has an integer `id` (unique, ascending) and:

| `op` | fields | effect |
|---|---|---|
| `replace` | `block`, `new_text`, `evidence`, `reason` | replace the whole text of a bullet, intro, summary or title |
| `replace_skills` | `block`, `new_value`, `reason` | replace the value after `"Category: "` in a skills line |
| `insert_after` | `after`, `new_text`, `evidence`, `reason` | add a new bullet right after bullet `after` (same role) |
| `delete` | `block`, `reason` | remove a bullet |

```json
{"ops": [
  {"id": 1, "op": "replace", "block": "exp.acme.senior-sdet.b04", "new_text": "Reduced CI pipelines with in-run retries from 64% to 22% in one quarter by fixing shared reliability issues.", "evidence": ["f-005"], "reason": "must_have: CI reliability"},
  {"id": 2, "op": "insert_after", "after": "exp.acme.senior-sdet.b04", "new_text": "Built load tests with JMeter running in Kubernetes.", "evidence": ["f-048"], "reason": "nice_to_have: load testing"},
  {"id": 3, "op": "delete", "block": "exp.acme.senior-sdet.b09", "reason": "relevance 0"},
  {"id": 4, "op": "replace_skills", "block": "skills.development", "new_value": "Python, asyncio, FastAPI, Pydantic, SQL", "reason": "lead with vacancy stack"}
]}
```

## Rules
1. **Facts only.** Every statement in `new_text` must follow from the facts in `evidence`. Respect each fact's `notes`: they limit wording (for example "maintained, not created"). Never make a verb stronger than the fact ("participated" never becomes "led").
2. **Role.** `evidence` of a bullet or intro edit must belong to that block's role (`role_id` = the block's role). Summary, title and skills may use facts from any role.
3. **Numbers.** Any token that starts with a digit — `42%`, `2.5M`, `180+`, `3x`, `200ms`, `10` — and number words two…twelve must equal a value in the `metrics` of the evidence facts (for `replace`, a number already in that block's text is also allowed). Do not round, convert or combine numbers. If unsure, write the sentence without the number.
4. **Group related facts.** Facts in one group are one bullet: combine them in one `replace` or one `insert_after`, do not make a bullet per fact.
5. **No repeats.** A fact listed in `covered_by` for a block you are not replacing or deleting must not appear in another edit. If a fact is already in a bullet, strengthen that bullet with `replace` instead of adding a new one. One fact appears in at most one bullet edit.
6. **Skills lines.** Keep existing items unless they are irrelevant; new items must come from the skills vocabulary and have `basic: true` or `has_verified_evidence: true`. Skills with `recency: previous` go after "previous experience with".
7. **Limits.** Respect `limits`: bullet length, replace ratio of the original `chars`, summary 80–115%, number of ops, bullets per role, total growth.
8. **Never** change dates, employers, job titles, contacts or education; they are not editable.
9. **Style.** Match the existing bullets: past tense for finished work, present tense for current ownership, no first person, one sentence, no trailing marketing words.
10. **Fewer, better edits.** Prioritise score-3 blocks and must_have requirements. Delete only score-0 bullets, and only when the role keeps enough bullets. It is fine to return few ops.
11. If `Errors from previous attempt` is present, fix each listed error and keep the ops that were valid.
