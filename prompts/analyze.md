# Step: analyse coverage and relevance

Compare the vacancy with the chosen resume copy and the verified fact base. You decide what matters; the next step will write edits.

## Input
`analyze.pack.md`: vacancy JSON, editable resume blocks (`id`, `kind`, `text`, `role`), read-only context, verified facts (`id`, `role_id`, `type`, `claim`, `metrics`, `notes`), `groups` (facts usually told as one bullet), `covered_by` (fact → blocks that already state it).

## Output
Exactly one JSON object:

```json
{
  "requirements": [
    {"text": "CI/CD pipelines", "kind": "must", "status": "covered", "fact_ids": ["f-005"], "block_ids": ["exp.acme.senior-sdet.b04"]},
    {"text": "Load testing", "kind": "nice", "status": "in_facts", "fact_ids": ["f-048"], "block_ids": []},
    {"text": "Kotlin", "kind": "must", "status": "gap", "fact_ids": [], "block_ids": []}
  ],
  "relevance": [
    {"block_id": "exp.acme.senior-sdet.b01", "score": 3, "reason": "directly matches must_have CI"}
  ],
  "candidate_facts": ["f-005", "f-048"],
  "notes": ""
}
```

## Rules
- One `requirements` item per `must_have` and `nice_to_have` entry (`kind` must/nice).
- `status`:
  - `covered` — the resume already shows it explicitly (give `block_ids`, and `fact_ids` if known);
  - `in_facts` — not in the resume, but a verified fact supports it (give `fact_ids`);
  - `partial` — adjacent experience only (give the closest ids);
  - `gap` — nothing supports it; no ids.
- `relevance`: score every editable block whose `kind` is `bullet` or `intro`, exactly once:
  - 3 — directly addresses a must_have;
  - 2 — addresses a nice_to_have or closely related work;
  - 1 — weakly related;
  - 0 — unrelated to this vacancy.
- `candidate_facts`: facts worth using in edits for this vacancy: supporting `in_facts` and `partial` requirements, and facts that could strengthen score-3 blocks. Use only ids from the verified facts list. Prefer whole `groups` when one member is relevant.
- Never treat a `gap` as covered. Never invent experience.
