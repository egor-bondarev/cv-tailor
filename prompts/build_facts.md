# Prompt: building `facts.json`

How to use: give this whole prompt to any capable model (Claude Code, Codex, ChatGPT…) and attach:
1. your Master CV (the most complete version of your experience);
2. your 2–3 base resumes with their `resume_id` from `resumes.yaml`;
3. optionally: notes, an export of ChatGPT memory, performance reviews. Remove anything private first: salary, health, family, colleagues' names, confidential internal project names.

Output: `docs/facts.json` and the report `docs/facts_report.md` (both git-ignored). Then read every fact yourself and set `verified: true` on the ones that are correct.

---

## Prompt (copy from here)

You are building a structured, verifiable fact base about one person's professional experience. This file is the single source of truth for an automated resume-tailoring tool: the tool may only write resume text that is backed by facts from this file. Accuracy matters more than completeness, and completeness matters more than brevity.

### Inputs
- `MASTER_CV`: the most complete description of the person's experience.
- `RESUMES`: 2–3 role-specific resumes, each with a `resume_id`.
- `NOTES` (optional): extra material.

### Output
Two artifacts:
1. `facts.json` that matches the schema below exactly. Valid JSON, UTF-8, no comments, no trailing commas.
2. `facts_report.md` that lists conflicts, gaps and questions for the person.

### Schema

```json
{
  "schema_version": 1,
  "roles": [
    {
      "id": "acme-senior-sdet",
      "employer": "Acme Analytics",
      "employer_description": "B2B analytics platform",
      "title": "Senior SDET - Test Infrastructure",
      "start": "2025-10",
      "end": null,
      "project": null,
      "is_current": true
    }
  ],
  "facts": [
    {
      "id": "f-001",
      "role_id": "acme-senior-sdet",
      "type": "achievement",
      "claim": "Cut the flaky test rate from 2.1% to 0.4% in one quarter without changing the retry policy.",
      "metrics": [
        {"value": "2.1%", "meaning": "flaky test rate, before"},
        {"value": "0.4%", "meaning": "flaky test rate, after", "period": "one quarter"}
      ],
      "skills": ["pytest", "GitLab CI/CD"],
      "tags": ["flaky-tests", "reliability", "ci"],
      "used_in": [
        {"resume_id": "senior-sdet", "quote": "Cut the flaky test rate from 2.1% to 0.4%"}
      ],
      "sources": ["master_cv"],
      "confidence": "stated",
      "verified": false,
      "notes": ""
    }
  ],
  "skills": [
    {
      "name": "Kubernetes",
      "aliases": ["k8s"],
      "category": "Delivery and tooling",
      "recency": "previous",
      "evidence": ["f-031", "f-034"]
    }
  ],
  "education": [
    {"id": "edu-001", "title": "ISTQB Certified Tester Foundation Level (CTFL) v4.0", "issuer": "ISTQB", "date": "2024-01"}
  ]
}
```

Field rules:
- `roles[].id`: kebab-case, `<employer>-<short-title>`. Every role gets its own entry, including early or short ones. Dates use `YYYY-MM`; `end: null` means current.
- `facts[].id`: `f-001`, `f-002`, … sequential, never reused.
- `facts[].type`, one of:
  - `achievement`: a result, ideally measurable ("reduced X from A to B");
  - `responsibility`: ongoing ownership or scope ("own the QA platform used by 3 teams");
  - `built`: something the person created (tool, plugin, pipeline, service);
  - `scope`: scale or context numbers (team size, executions per month, number of integrations);
  - `leadership`: mentoring, reviews, coordination, release management;
  - `recognition`: promotion, certification passed inside a company.
- `claim`: one atomic statement in English, past tense for finished work and present tense for current work, no first person. One fact = one idea. Split compound sentences: "Built X and reduced Y" becomes two facts.
- `metrics`: every number in `claim` must appear here with its exact string form (`"42%"`, `"1M+"`, `"~10 minutes"`, `"17"`, `"two hours"`). Each entry needs a `meaning`; add `period` and `source` when the input states them. Never compute, round, or convert numbers. If a claim has no numbers, use `[]`.
- `skills`: canonical technology names from the `skills` list, written exactly as in `skills[].name`.
- `tags`: 2–5 lowercase kebab-case topic tags for retrieval (`api-testing`, `load-testing`, `ai-agents`, `mentoring`).
- `used_in`: one entry for every base resume that already expresses this fact (fully or partly). `quote` is an exact, verbatim substring of that resume (≥ 30 characters where possible, no reformatting) so a program can find it. Empty list if no resume uses it.
- `sources`: where the fact came from: `master_cv`, `resume:<resume_id>`, `notes`.
- `confidence`: `stated` if copied from input; `inferred` if you derived it (allowed only for `skills` evidence and `type`, never for numbers).
- `verified`: always `false`. Only the person sets `true`.
- `skills[]`: every technology, tool, method, and domain mentioned anywhere. `recency` is `current` (used in the current job) or `previous`. `evidence` lists fact ids that show the skill in use. Everyday tools that are never an achievement on their own (Git, Docker, Linux, Bash, a package manager) get `"basic": true` and may keep `"evidence": []`; any other skill without evidence goes into the report.
- `education[]`: degrees, courses, certifications with dates.

### Procedure
1. Read all inputs fully before writing anything.
2. Build `roles` from MASTER_CV. Check titles and dates against each resume.
3. Go through MASTER_CV role by role, bullet by bullet, then through summary and skills, and extract atomic facts. The summary often holds scope facts that are missing from the bullets (team counts, volumes); extract them too and attach them to the right role.
4. Go through each resume and extract facts that are **not** in MASTER_CV. Mark their `sources` accordingly.
5. For every fact, search each resume for wording that expresses it and fill `used_in` with verbatim quotes.
6. Build `skills` and link evidence.
7. Run the self-check below, fix problems, then write the report.

### Conflicts: do not resolve silently
When sources disagree (different numbers, dates, counts, or wording that changes meaning, e.g. "10+ services" against "12 services", or "2M requests in March" against "1M+ per month"):
- create **one** fact with the wording from the most specific source;
- describe the disagreement in `notes` ("resume senior-sdet says '20+'; master says '23'");
- add the conflict to `facts_report.md`, section "Conflicts".

### Prohibited
- Inventing, rounding, generalising, or "improving" anything. No new numbers, no new technologies, no stronger verbs than the source uses ("participated in" never becomes "led").
- Personal data: contacts, addresses, salary, health, family, nationality, visa status.
- Names of colleagues or customers, and confidential internal project names unless they already appear in a resume.
- Merging facts from different roles into one.

### Self-check before output
- [ ] JSON parses; every `role_id` exists in `roles`; every `evidence` id exists in `facts`.
- [ ] Every digit sequence in every `claim` appears in that fact's `metrics[].value`.
- [ ] Every `used_in[].quote` is a verbatim substring of the named resume.
- [ ] Every bullet of MASTER_CV maps to at least one fact (list any that don't in the report).
- [ ] Every bullet of every base resume maps to at least one fact (list any that don't in the report; these are claims with no backing in the master).
- [ ] No fact has more than one idea; no personal data.

### `facts_report.md` structure
1. **Stats**: number of roles, facts per role, skills, facts without `used_in`.
2. **Conflicts**: table `fact_id | source A says | source B says | question for the person`.
3. **Resume claims without backing**: bullets from base resumes that do not match any fact.
4. **Skills without evidence**.
5. **Weak facts**: achievements without numbers where a number would make sense, so the person can add one if it exists.
6. **Questions**: anything you were unsure about.
