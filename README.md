# cv-tailor

Tailor your resume to a job posting without making things up.

You paste a job description into a chat with an AI agent. `cv-tailor` picks the best of your base resumes, copies it in Google Drive, and adds targeted edits to the copy as **Google Docs suggestions**. You then accept, reject, or edit each one in the document. Every edit must be backed by a fact from your own verified fact base, and code checks this, not the model.

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
             you: review suggestions in Google Docs
```

- **AI only where language understanding is needed:** reading the job posting, choosing a resume, the analysis, writing the edits, an independent review.
- **Everything else is deterministic Python:** Google API calls, document parsing, validation, building `batchUpdate` requests, verification, reports.
- **No invented facts.** Each edit cites fact ids from `facts.json`. Every number in the new text must match a metric of a cited fact, and facts from one job can't be used in another job's bullets.
- **Originals are never modified.** Edits go into a copy, and only as suggestions.
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
     | `editable_companies` | employers (Heading 2, as a slug: `Acme Analytics` → `acme-analytics`) whose bullets may be edited; everything else stays read-only. Usually only the current employer |
     | `role_map` | optional; only if `cvtailor facts check` or a run reports that a role heading cannot be matched to a `facts.json` role: `acme/senior-sdet: acme-senior-sdet` |

3. **Fact base.** Build `docs/facts.json` from your master CV with [prompts/build_facts.md](prompts/build_facts.md). Read every fact and set `verified: true` on the correct ones. Only verified facts are ever used. The schema is shown in [facts.example.json](facts.example.json). Then check it against your resumes:

   ```bash
   pip install -e '.[dev]'
   cvtailor facts check            # schema, references, numbers, quotes found in the live resumes
   cvtailor facts check --offline  # without reading Google Docs
   ```

## Usage

An agent drives a run; you answer its questions and review the result in Google Docs.

```bash
cvtailor init --company "Acme" < vacancy.txt   # add --resume ID to skip resume choice
cvtailor next                                    # repeat; prints one JSON action per call
cvtailor final                                   # after you accepted/rejected suggestions in Docs
```

`next` returns `ai` (write JSON for a prompt), `ask_user` (answer with `--answer`), `say`, `auth` (run `cvtailor login`) or `done`. `cvtailor next --from STEP` restarts from a step.

## Privacy

- Your resumes, facts, configs, runs, and Google tokens are git-ignored. Check with `git status --ignored` before pushing a fork.
- The job posting, resume blocks, and verified facts are sent to the AI agent you use, and to Codex if review is enabled. Keep `facts.json` free of personal data. The prompt tells the model to leave it out.
- `credentials.json` and `token.json` give access to your whole Drive. Keep them local. You can revoke access at <https://myaccount.google.com/permissions>.

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| M0 | Docs API experiments: copy, edit, suggestions mode, OAuth | done |
| M1 | Fact base: `facts.json` + `facts check` | done |
| M2 | `google_api`, parser, request builder, `verify`, `final` | done |
| M3 | Run state machine, AI step prompts, validators, second-model review, reports | planned |
| M4 | Agent skill, end-to-end run | planned |

Later: a fully scripted `cvtailor run` (AI steps via a headless agent CLI), page-count check, an HTML review page.

## Repository layout

```text
DESIGN.md              design document (Russian)
docs/google-setup.md   Google Cloud + OAuth setup
prompts/               prompts for AI steps (build_facts.md is ready)
scripts/               helper scripts (google_check.py)
src/cvtailor/          the CLI (in progress)
*.example.*            config and data examples
```

## License

[MIT](LICENSE)
