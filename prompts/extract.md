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
  "domain": "fintech",
  "location": "Remote, EU time zones",
  "hooks": [
    {"quote": "We want every developer to ship without fear of breaking production.", "type": "mission", "strength": "strong", "why": "names the company's own goal for its users"}
  ]
}
```

## Rules
- `language`: language of the original posting (ISO code). Everything else is in English.
- `must_have`: explicit requirements ("required", "must", "you have"). At least one. Keep each item short and atomic. **Split composite requirements**: "pytest and BDD frameworks" becomes two items, so a missing half shows up as its own gap. Keep alternatives together ("Go, Java or Python" stays one item). Split only across **different competencies**; an enumeration from one family stays one item with its members in parentheses: "AWS (SES, SNS, SQS)", "Kubernetes (ingress, services, Helm)", "observability (Prometheus, Grafana)". Aim for 5–12 `must_have` items.
- `nice_to_have`: "plus", "nice to have", "preferred".
- `skills`: every technology, tool, method mentioned, as written (normalisation happens later).
- `company`, `seniority`, `domain`: `null` if not stated.
- `location`: where the job is, as stated ("London, onsite", "Remote, EU", "Berlin or remote"); `null` if not stated.
- `hooks`: 0–3 sentences in which the company talks about itself, for the cover letter.
  - **`quote`:** copy the sentence verbatim, in the original language.
  - **Where to look:** only in the company block, which is the introduction before duties and requirements, or an "About us" / "About the company" / "About the project" section anywhere. Never take a sentence from duties, requirements, benefits, legal text or application instructions.
  - **What to skip:**
    - self-promotion: awards, rankings, "best employer", culture or values in general words;
    - sentences made only of praise words ("innovative", "fast-growing").
  - **`type`:**
    - `mission`: mission, goal or intention, including "we aim to", "we strive to", "мы стремимся";
    - `product`: the product or project and the problem it solves;
    - `challenge`: the team's current challenge (scaling, migration, launch);
    - `scale`: a scale fact the company names itself.
  - **`strength`:** `strong` when the sentence would be false with a competitor's name instead; `weak` when it is concrete but common to the industry.
  - **`why`:** one line in English saying what makes the sentence concrete.
  - An empty list is fine.
- Do not copy benefits, salary, or legal text.
