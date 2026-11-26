# Step: write the edit plan

Write a small set of edits that make the resume copy fit the vacancy, using only verified facts. Python validates every edit; edits that break a rule are rejected.

## Input
`tailor.pack.md`: possibly `Errors from previous attempt` first (on a retry, read that section; the rest is unchanged), then vacancy, analysis, editable blocks (with `chars` and `max_chars`), read-only context, candidate facts (`claim`, `metrics`, `role_id`, `skills`, `notes`), `groups`, `covered_by`, skills vocabulary (one line per category with marks), limits and length budget.

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
1. **Facts only.** Every statement in `new_text` must follow from the facts in `evidence`. Respect each fact's `notes`: they limit wording (for example "maintained, not created"). Use the fact's own verb, including in the summary and title: "documented" stays "documented" (not "set"), "participated" never becomes "led".
2. **Evidence everywhere.** Every `replace` of a bullet, intro, summary or title and every `insert_after` lists the facts that back its new claims in `evidence`.
3. **Role.** `evidence` of a bullet or intro edit must belong to that block's role (`role_id` = the block's role). Summary, title and skills may use facts from any role.
4. **Numbers.** Any token that starts with a digit — `42%`, `2.5M`, `180+`, `3x`, `200ms`, `10` — and number words two…twelve must equal a value in the `metrics` of the evidence facts (for `replace`, a number already in that block's text is also allowed). Do not round, convert or combine numbers. If unsure, write the sentence without the number.
5. **Group related facts.** Facts in one group are one bullet: combine them in one `replace` or one `insert_after`, do not make a bullet per fact.
6. **No repeats.** A fact listed in `covered_by` for a block you are not replacing or deleting must not appear in another edit. If a fact is already in a bullet, strengthen that bullet with `replace` instead of adding a new one. One fact appears in at most one bullet edit.
7. **Skills lines.** Keep existing items unless they are irrelevant; new items must come from the skills vocabulary and be marked `ev` or `basic`. Skills marked `prev` go after "previous experience with". The validator splits a line into items at commas and semicolons (outside parentheses) and at " and "; parentheses hold sub-items. So write new items with their **exact vocabulary names**, one per comma ("chaos testing, load testing", not "chaos and load testing"). `replace_skills` needs no `evidence`: each new item's backing comes from the vocabulary.
8. **Limits.** Each block has `max_chars` for a replacement; new bullets are limited by `bullet_max_chars`. The sum of all editable text after your edits must stay within `editable_total_max` from `Length budget`: count it before answering, and pay for new bullets by shortening or deleting low-relevance text. **Check lengths before answering**: every `new_text` within its block's `max_chars`, the total within `editable_total_max`.
9. **Adjacent technologies.** When a requirement is backed only by an adjacent tool (the vacancy asks for Selenium, the facts show Playwright), name the tool the facts show, never the vacancy's tool, and keep the fact's scope (for example "built an initial Playwright UI test layer", not "automated UI tests with Playwright in production").
10. **Summary is the showcase.** When you edit the summary, build it around the 2–3 strongest matches with the vacancy's must_have and core responsibilities, including matches already shown in bullets or skills (for a UI role: recent frontend tests, not only backend tooling). Keep its existing length class and cite every fact you surface.
11. **Never** change dates, employers, job titles in role headings, contacts or education; they are not editable. The `title` block is the target-role headline under your name and may be adapted.
12. **Style.** Match the existing bullets: past tense for finished work, present tense for current ownership, no first person, one sentence, no trailing marketing words.
13. **Fewer, better edits.** Prioritise score-3 blocks and must_have requirements. Delete only score-0 bullets, and only when the role keeps enough bullets. It is fine to return few ops.
11. If `Errors from previous attempt` is present, fix each listed error and keep the ops that were valid.
