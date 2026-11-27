---
name: cv-tailor
description: Tailor one of the user's base resumes in Google Docs to a job posting, using only verified facts, by driving the `cvtailor` CLI step by step. Use when the user pastes a vacancy / job description and asks to adapt, tailor or prepare a resume for it (in any language), or asks to continue or finish a cv-tailor run ("проверь", "готово", "final").
---

# cv-tailor: run the pipeline

You are the agent of a deterministic pipeline. The `cvtailor` CLI decides every step; you only do what its current action says. Python validates everything you write, so follow the prompts exactly instead of improvising.

## 0. Before the first command

- Work from the repository root (the folder with `pyproject.toml` and `prompts/`).
- Find the CLI once and reuse it: `CVT="$(command -v cvtailor || echo .venv/bin/cvtailor)"`, then check `"$CVT" --help`. If it is missing, tell the user to run `pip install -e '.[dev]'` in the project virtualenv and stop.
- Never open `docs/facts.json`, `token.json`, `credentials.json`, `config.yaml` or `resumes.yaml`: everything you need is in the files the CLI points you to.
- Run `next` with a long Bash timeout (at least 300 s): one call may copy a document, apply edits and wait up to ~100 s for the second-model reviewer.

## 1. Start a run

You need the vacancy text and the company name. If the company is not obvious from the message, ask for it in one short question.

```bash
cat > /tmp/cvtailor-vacancy.txt <<'EOF'
<vacancy text exactly as the user gave it; drop salary/benefits only if very long>
EOF
"$CVT" init --company "<Company>" < /tmp/cvtailor-vacancy.txt
```

Add `--resume <id>` only if the user named the base resume. Use a scratch directory instead of `/tmp` if your environment provides one.

## 2. The loop

Run `"$CVT" next` and read the one-line JSON it prints. Do what `action` says, then call `next` again. Repeat until `done` or until you must wait for the user.

| `action` | What you do |
|---|---|
| `ai` | Read the whole file at `prompt`, then the file at `input`, each with your file-reading tool (not `cat`: the input is often 25–30 KB and shell output gets cut). Write **only** the JSON object the prompt specifies to the path in `output` (no prose, no code fences). Then call `next`. |
| `ask_user` | Show `question` and the numbered `options` to the user and stop. When they answer, run `"$CVT" next --answer "<their answer or option number>"`. |
| `say` | Show `text` to the user verbatim. If it is the run summary (starts with `Resume copy:`), go to step 3. If it reports a problem, explain it in one or two sentences and stop; do not retry on your own unless the text tells you to run `next` again. |
| `auth` | Tell the user to run `cvtailor login` (it opens a browser for Google sign-in) and to tell you when done; then call `next`. |
| `done` | Tell the user the run is finished and give the document link. |

### Doing an `ai` step well

- The prompt is the contract: field names, allowed values and rules come from it. Every claim must come from the facts in the input; respect each fact's `note`; keep the fact's own verb and numbers.
- `tailor`: before writing, check each `new_text` against its block's `max_chars` and the total against `editable_total_max` in `Length budget`.
- If the action has non-empty `errors`, this is a retry. Read the `Errors from previous attempt` section at the top of the input and your previous answer (the newest `<output>.attemptN` file next to `output`); fix exactly those errors and keep the parts that were fine. Do not re-read the rest of the input if you already have it in context.
- On a retry the file at `output` **no longer exists**: the CLI renamed your previous answer to `<output>.attemptN`. Write a new `output` file (for example, load the newest `.attemptN`, fix it, save it to `output`), check that it was written, and only then call `next`. Do not chain `next` after a command that may fail.
- Errors with rule `review` come from the independent fact checker after your plan passed validation: rewrite only the quoted fragments of those ops.
- Write the file with a heredoc or your file tool; make sure it is valid JSON.
- Do not read the project's source code (`src/`) to work out a rule: the prompt states the rules and each error message says what to fix.

## 3. After the run summary

Tell the user, in their language and briefly:
- the link to the copy and that every edit is a suggestion they must accept, reject or edit in Google Docs;
- the edits flagged by the reviewer (`partial` / `unsupported`) and the must-have gaps from the summary;
- that `review.md` in the run folder explains each edit.

Then wait. When the user says they reviewed it ("готово", "done", "проверь"), run `"$CVT" final` and report its text: whether the check passed and how many edits were accepted, edited or rejected. Ask whether any accepted edit is not backed by facts; if they name one, note it for the project owner.

## Recovering

- A step is blocked (`say` about invalid output after retries, facts problems, role mapping): explain, and after the cause is fixed run `"$CVT" next --from <step>` as the text suggests.
- To continue an older run: `"$CVT" next --run runs/<run-folder>`.
- Never edit files in `runs/` other than the `output` path of the current `ai` action.
