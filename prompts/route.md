# Step: choose the base resume

Pick the base resume that fits the vacancy best. Each base resume targets a different role.

## Input
`route.pack.md`: the vacancy JSON and the list of base resumes (`id`, `label`, `target_role`, `summary`).

## Output
Exactly one JSON object:

```json
{"choice": "senior-sdet", "confidence": "high", "ranking": ["senior-sdet", "qa-platform", "senior-qa-automation"], "reason": "Vacancy centres on Python test frameworks and CI, which is the senior-sdet target role."}
```

## Rules
- `ranking`: all resume ids, best first; `ranking[0]` must equal `choice`.
- Compare the vacancy's `must_have`, `responsibilities` and `title` with each resume's `target_role` and `summary`.
- `confidence`:
  - `high` — one resume is clearly the best fit;
  - `medium` — the top two are close;
  - `low` — none fits well.
  When unsure, do not say `high`: the user will be asked to choose.
- `reason`: one or two sentences, concrete.
