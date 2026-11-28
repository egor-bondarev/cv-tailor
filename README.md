# cv-tailor

Tailor your resume to a job posting without making things up.

You paste a job description into a chat with an AI agent. `cv-tailor` picks the best of your base resumes, copies it in Google Drive, and adds targeted edits to the copy as **Google Docs suggestions**. Each edit also gets a comment in the document with its reason, the facts behind it and the reviewer's verdict. You then accept, reject, or edit each one in the document. Every edit must be backed by a fact from your own verified fact base, and code checks this, not the model.

> **Status: design stage.** The design is settled ([DESIGN.md](DESIGN.md), in Russian) and the Google side has been tested. The `cvtailor` CLI is not implemented yet. See [Roadmap](#roadmap).

## How it works

```text
job posting ──► AI: extract requirements ──► AI: pick base resume
                                                   │
             Python: copy the resume in Drive, parse it into blocks
                                                   │
             AI: coverage + relevance analysis ──► AI: edit plan
                                                   │
             Python: validators (facts, numbers, lengths) ──► second model reviews each edit
                                                   │
             Python: apply edits as Google Docs suggestions, verify text and styles
                                                   │
             AI: cover letter ──► Python: checks (facts, numbers, quote, length) ──► second model reviews it
                                                   │
             you: review suggestions and the letter ──► final check ──► PDFs of both
```

- **AI only where language understanding is needed:** reading the job posting, choosing a resume, the analysis, writing the edits, an independent review.
- **Everything else is deterministic Python:** Google API calls, document parsing, validation, building `batchUpdate` requests, verification, reports.
- **No invented facts.** Each edit cites fact ids from `facts.json`. Every number in the new text must match a metric of a cited fact, and facts from one job can't be used in another job's bullets.
- **Originals are never modified.** Edits go into a copy, and only as suggestions.
- **Cover letter next to the copy.** A plain-text Google Doc in the vacancy language, built from the same facts. An optional hook retells one sentence in which the company describes itself, quoted verbatim from the vacancy. Your motivation comes from `profile.yaml`; contacts are added by Python and never sent to a model.
- **Agent-agnostic.** The agent needs only a shell. `cvtailor next` tells it the next step: write JSON for a prompt, ask you a question, or show a summary.

## Requirements

- Python 3.11+
- An AI coding agent with shell access: [Claude Code](https://claude.com/claude-code), Codex CLI, or similar
- Optional: [Codex CLI](https://github.com/openai/codex) for the second-model review
- A Google account with your resumes in Google Docs, plus a free Google Cloud project for OAuth (no billing needed)

## Resume format

The parser expects a Google Doc with this structure (other layouts will fail loudly rather than be guessed):

| Element | Google Docs style |
|---|---|
| Name | Title |
| Target role line | Subtitle |
| Section headers (SUMMARY, TECHNICAL SKILLS, EXPERIENCE, …) | Heading 1 |
| Company | Heading 2 |
| Role and dates (`Title \| Mon YYYY - Mon YYYY`) | Heading 3 |
| Achievements | Bulleted list |
| Skills | Normal text, one `Category: values` line per category |

## Setup

1. **Google OAuth.** Follow [docs/google-setup.md](docs/google-setup.md) to get `credentials.json`, then run the check script:

   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
   python scripts/google_check.py
   ```

2. **Configs.** Copy the examples and fill them in:

   ```bash
   cp config.example.yaml config.yaml
   cp resumes.example.yaml resumes.yaml
   ```

   - `config.yaml`: `output_folder_id` is the Drive folder for tailored copies (the id at the end of the folder URL). Limits and the reviewer command have working defaults.
   - `resumes.yaml`: one entry per base resume:

     | Field | Meaning |
     |---|---|
     | `id` | short name used in runs and in `facts.json` `used_in` |
     | `label` | used in the copy name `<label> - <Company> - <date>` |
     | `doc_id` | the part of the Google Doc URL between `/d/` and `/edit` |
     | `target_role` | which roles this resume is for; used to pick the resume |
     | `editable_companies` | edit priority of employers (Heading 2, as a slug: `Acme Analytics` → `acme-analytics`). Listed employers are priority 1 (main edits); later ones get 2, 3, … and at most one edit each; a map like `{acme: 1, globex: 0}` sets priorities explicitly (0 = read-only). Older roles without facts stay read-only |
     | `role_map` | optional; only if `cvtailor facts check` or a run reports that a role heading cannot be matched to a `facts.json` role: `acme/senior-sdet: acme-senior-sdet` |

3. **Fact base.** Build `docs/facts.json` from your master CV with [prompts/build_facts.md](prompts/build_facts.md). Read every fact and set `verified: true` on the correct ones. Only verified facts are ever used. The schema is shown in [facts.example.json](facts.example.json). Then check it against your resumes:

   ```bash
   pip install -e '.[dev]'
   cvtailor facts check            # schema, references, numbers, quotes found in the live resumes
   cvtailor facts check --offline  # without reading Google Docs
   ```

4. **Profile for the cover letter** (optional, but without it the letter is unsigned and has no motivation):

   ```bash
   cp profile.example.yaml profile.yaml
   ```

   - `contacts`: your name signs the letter; email, phone and LinkedIn go above it only with `cover_letter.header: true`. They stay local.
   - `motivation`: what you look for in work, one concrete item per entry with an `id`. The letter connects these items to what the company says about itself and never invents motivation beyond them.
   - `relocation`: your base city and a phrase such as `open to relocation`. It is mentioned only when the vacancy is in another city or country or restricts location.

## Usage

**With Claude Code (recommended).** Open Claude Code in the repository root and paste a vacancy: "tailor my resume to this vacancy at Acme: …". The project skill [`.claude/skills/cv-tailor/SKILL.md`](.claude/skills/cv-tailor/SKILL.md) starts `cvtailor run`, which calls the model for every AI step itself (`claude -p`, a fresh small context per step); the chat only relays the resume question and shows the link to the copy. Review the suggestions (each has a comment with its reason and facts) in Google Docs, then say "done" and it runs the final check. Other agents can follow the same file as instructions.

**From a terminal.**

```bash
cvtailor run --company "Acme" < vacancy.txt   # add --resume ID to skip resume choice
cvtailor run --url https://jobs.example.com/123 # or download the vacancy page (company from the page)
cvtailor run --answer 1                         # if it stopped with a question
cvtailor final                                  # after you accepted/rejected suggestions in Docs
cvtailor final --fix-layout                     # if final says a role is split across two pages
cvtailor letter --feedback "drop the second achievement"  # rewrite the cover letter of the current run
cvtailor letter --short                         # 650-900 characters (default full: 1300-1800)
cvtailor letter --max-chars 900                 # a site with a field limit
```

`run` stops only when it needs you: a question, the summary, Google sign-in, or `continue` after its time budget (`ai.max_run_seconds`, so a chat agent's shell call does not time out; just run it again). `--non-interactive` takes the top-ranked resume without asking, `--json` prints the stopping action as one JSON line, `--from STEP` restarts from a step. Model calls and their tokens are logged to `runs/<run>/ai_calls.jsonl`.

`--url` downloads the page (http(s) only, 20 s timeout, 3 MB limit, no cookies) and keeps `vacancy.url`, `vacancy.html` and the extracted `vacancy.txt` in the run folder. Role, company and description come from the schema.org `JobPosting` block many job boards embed, otherwise from the page's visible text; `--company` is needed only when the page does not name the company. Pages that need a browser or a sign-in (LinkedIn) give almost no text: then pass the text on stdin with the same `--url` (the terminal asks you to paste it).

The cover letter goes into a Google Doc in the company folder, named `<Name>. Cover Letter - <Role>`. `cvtailor run` writes and reviews it in parallel with the resume edits, because it needs only the vacancy, the analysis and the facts. In manual mode it is written after the edits. The letter is signed with your name. The contacts header is off by default, because a letter is usually pasted into a form or an e-mail; set `cover_letter.header: true` to add it for a PDF attachment. The run summary shows its link and length, the hook (strong, weak, or not found), the motivation items used, whether relocation is mentioned and why, and the second model's verdict per paragraph. `cvtailor letter` rewrites it with your requests (they accumulate), a shorter mode or a character limit, and updates the same document; if you edited the document by hand, it is kept and a new one is written. Set `cover_letter.enabled: false` in `config.yaml` to skip the letter.

`final`, once no suggestions remain and the check passes, exports the resume and the letter to PDF in the company folder (`--no-export` skips it; a later `final` replaces those files). If a role is split across pages, it exports nothing until you choose: `--fix-layout` moves the role and exports, `--keep-layout` exports as it is. It also checks that no role starts on one page and ends on the next. `--fix-layout` fixes such a role directly in the copy: a page break before its heading, and the manual page break right after it (which would now leave a near-empty page) removed; it re-checks until every role fits.

**Manual mode.** `cvtailor init` + `cvtailor next` hand every AI step to an agent instead: `next` returns `ai` (write JSON for a prompt), `ask_user` (answer with `--answer`), `say`, `auth` or `done`. Useful when no model command is available.

## Privacy

- Your resumes, facts, configs, runs, and Google tokens are git-ignored. Check with `git status --ignored` before pushing a fork.
- The job posting, resume blocks, and verified facts are sent to the AI agent you use, and to Codex if review is enabled. Keep `facts.json` free of personal data. The prompt tells the model to leave it out.
- From `profile.yaml`, only the motivation items and the relocation base are sent to the model. Contacts are written into the letter document by Python.
- `credentials.json` and `token.json` give access to your whole Drive. Keep them local. You can revoke access at <https://myaccount.google.com/permissions>.

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| M0 | Docs API experiments: copy, edit, suggestions mode, OAuth | done |
| M1 | Fact base: `facts.json` + `facts check` | done |
| M2 | `google_api`, parser, request builder, `verify`, `final` | done |
| M3 | Run state machine, AI step prompts, validators, second-model review, reports | done |
| M4 | Agent skill, end-to-end run | done |

Later: a fully scripted `cvtailor run` (AI steps via a headless agent CLI), page-count check, an HTML review page.

## Repository layout

```text
DESIGN.md              design document (Russian)
docs/google-setup.md   Google Cloud + OAuth setup
prompts/               prompts for AI steps (extract … tailor, review, cover_letter, review_letter, build_facts)
scripts/               helper scripts (google_check.py)
src/cvtailor/          the CLI
*.example.*            config and data examples
```

## License

[MIT](LICENSE)
