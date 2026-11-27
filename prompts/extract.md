# Step: extract the vacancy

You read one job posting (any language) and write its requirements as JSON in English. Do not invent anything that is not in the text.

## Input
`extract.pack.md`: the raw vacancy text.

## Output
Write exactly one JSON object to the output file, nothing else:

```json
{
  "title": "Senior SDET",
  "company": "Acme",
  "seniority": "senior",
  "language": "ru",
  "summary": "One or two sentences: what the team does and what this role owns.",
  "must_have": ["5+ years of test automation in Python", "CI/CD pipelines"],
  "nice_to_have": ["Kubernetes"],
  "responsibilities": ["Own the API test framework"],
  "skills": ["Python", "pytest", "Kubernetes"],
  "domain": "fintech"
}
```

## Rules
- `language`: language of the original posting (ISO code). Everything else is in English.
- `must_have`: explicit requirements ("required", "must", "you have"). At least one. Keep each item short and atomic. **Split composite requirements**: "pytest and BDD frameworks" becomes two items, so a missing half shows up as its own gap. Keep alternatives together ("Go, Java or Python" stays one item). Split only across **different competencies**; an enumeration from one family stays one item with its members in parentheses: "AWS (SES, SNS, SQS)", "Kubernetes (ingress, services, Helm)", "observability (Prometheus, Grafana)". Aim for 5–12 `must_have` items.
- `nice_to_have`: "plus", "nice to have", "preferred".
- `skills`: every technology, tool, method mentioned, as written (normalisation happens later).
- `company`, `seniority`, `domain`: `null` if not stated.
- Do not copy benefits, salary, or legal text.
