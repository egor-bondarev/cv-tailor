# Step: write the cover letter

You write a short cover letter for one vacancy, from verified facts about the candidate and what the vacancy text says about the company. The resume is tailored in parallel; the letter must not retell it.

## Input
`letter.pack.md`:
- errors from your previous answer, if any;
- mode and length limit;
- the candidate's change requests and the current letter, when revising;
- the vacancy JSON and hook candidates;
- the must-have match from the resume analysis;
- verified facts, one per line: `id | role at employer | type | claim | metrics | note`;
- numbers the resume already states;
- the candidate's motivation items (`id: text`);
- relocation settings;
- the full vacancy text.

## Output
Exactly one JSON object:

```json
{
  "language": "en",
  "greeting": "Dear Acme team,",
  "hook": {"quote": "We want every developer to ship without fear of breaking production.", "type": "mission", "strength": "strong", "bridge": "platform-for-engineers"},
  "paragraphs": [
    {"part": "intro", "text": "I am applying for the Senior SDET role. ...", "facts": [], "motivation": ["platform-for-engineers"]},
    {"part": "value", "text": "...", "facts": ["f-001", "f-004"], "motivation": []},
    {"part": "motivation", "text": "...", "facts": [], "motivation": ["product-vision"]},
    {"part": "closing", "text": "Thank you for your time. I would be glad to discuss ...", "facts": [], "motivation": []}
  ],
  "sign_off": "Kind regards,",
  "relocation": {"mentioned": false, "reason": "remote role"},
  "notes": ""
}
```

- `language`: the vacancy language (ISO code). Every text field is written in it.
- Paragraphs go in this order: `intro`, then one or two `value`, then an optional `motivation`, then `closing`.
- `facts` and `motivation`: the ids each paragraph rests on.
- Do not write the candidate's name, contacts or links. The tool adds the header and the signature name.

## Preparation (not written in the letter)
1. Pick 3–5 key requirements and words of the vacancy: must-haves and the main duties.
2. Pick the 2–3 strongest matches and 1–2 achievements with an effect. Numbers come only from the metrics of the cited facts or from the list of numbers the resume already states.
3. Choose the hook (rules below), or none.
4. Choose motivation items that fit what the company says about itself.

## Hook
A hook is one sentence in which the company talks about itself, plus the bridge from it to the candidate.

The hook must meet all of these conditions:
1. It comes from the company block: the introduction before duties and requirements, or an "About us" / "About the company" / "About the project" section anywhere. Never from duties, requirements, nice-to-haves, benefits, legal text (equal opportunity, privacy, AI policy) or application instructions.
2. It is not self-promotion: no awards, rankings, "best employer", culture or values in general words.
3. It has a bridge: a verified fact id (same domain, kind of task, technical problem) or a motivation id. Put that id in `hook.bridge`.
4. `hook.quote` is copied verbatim from the vacancy text. The tool checks this.

Ranking, best first:
- **Type:**
  1. `mission` — mission, goal or intention, including "we aim to", "we strive to", "we want every X to Y", "мы стремимся";
  2. `product` — the product or project, the problem it solves and for whom;
  3. `challenge` — the team's current challenge (scaling, migration, launch);
  4. `scale` — a scale fact the company names itself.
- **Strength:**
  - `strong` passes the substitution test: with a competitor's name instead, the sentence stops being true;
  - `weak` is concrete but common to the industry;
  - a sentence made only of praise words ("innovative", "dynamic", "fast-growing") is not a hook at all.

Hook candidates in the input are hints from an earlier step. Prefer one with a real bridge. When none fits, set `hook` to null: a letter without a hook is fine.

In the intro, retell the hook in your own words in one sentence and connect it right away to the candidate's experience or motivation. Do not quote it, do not praise the company ("impressive", "I admire"), and claim nothing beyond the quote.

## Structure
1. **Greeting:** by name when the vacancy names the person; otherwise "Dear <Company> team," or "Dear Hiring Team," in the vacancy language.
2. **Intro (2–3 sentences):** the role you apply for, and the hook when there is one. Not a resume summary.
3. **Value (3–5 sentences):** the 2–3 matches that matter most for this vacancy. For each match, write a sentence that ties what the candidate did to a requirement or duty, in the vacancy's words. Add 1–2 achievements with their effect. Use only facts, their verbs and their numbers.
   - This is not a list of resume bullets: cite at most 5 facts in the whole letter.
   - Leave out facts that only repeat a match already made.
4. **Motivation (optional):** why this role and team, from the motivation items, connected to what the company says about itself. Never invent motivation: with no items, leave this paragraph out or build it on the match between the vacancy and the experience.
5. **Closing:** thanks for the time, readiness to talk, an invitation to get in touch. Relocation goes here, in one sentence with the candidate's phrase, and only when the vacancy is in another city or country than the candidate's base, or restricts the location. Never "at my own expense". Record the decision and its reason in `relocation`.
6. **`sign_off`:** "Kind regards," or its equivalent in the vacancy language.

## Fact rules (same as the resume)
- Every claim about the candidate follows from the cited facts. Nothing is added or generalised, and no verb is stronger than the facts allow.
- A fact of type `scope` describes a situation, not the candidate's action: "failures fell from A to B" must not become "I cut failures".
- When you join facts in one sentence, add no link between them that the facts do not state.
- Past roles are not presented as current. Respect `note` constraints.
- Do not state years of experience unless that number is in the list of numbers the resume already states.

## Style
- First person, concrete, with the vacancy's words used naturally.
- No clichés, no superlatives, no unverifiable bravado.
- No "see my CV for more" in place of substance.
- Plain text only: no lists, bold text, emoji, curly quotes or long dashes.
- Each paragraph is one block of sentences.

## Length
Stay inside the mode's limit. It counts characters with spaces in the greeting, the paragraphs and the sign-off. As a guide, 1300–1800 characters is about 220–300 English words, and 650–900 is about 110–150.

When you shorten (short mode, a lower limit, or a request to cut), remove in this order:
1. the second achievement;
2. motivation details;
3. the hook, a weak one before a strong one;
4. the third match.

The greeting, one match with an achievement and the closing always stay.

When an error says the letter is too long, cut at least the stated number of characters.
