# Assignment Helper

A web app that helps students stay on top of assignments and turns a vague project idea into a clear, structured prompt for any AI assistant.

I built it to learn how to integrate an LLM API into a real backend: authentication, a database, server-side AI calls, structured output, and graceful failure handling.

## Features

- **Accounts** – register / login / logout, passwords stored as salted hashes, session-based auth.
- **Dashboard** – each assignment has a colored status dot: red = not started, yellow = in progress, cyan = done (not yet submitted). Overdue items are highlighted.
- **Create project** – name, deadline (date + time picker), free-text description.
- **Submit** – the "Submitted" button hides the project from the dashboard (soft delete: data is kept and listed on the *Submitted* page).
- **Edit project** – update the description, e.g. to record a lecturer's written permission, then regenerate.
- **Paper recommendations** (report, literature review, software and data/ML projects) – a fixed-flow RAG pipeline (retrieval-augmented generation: retrieve real sources first, then let the AI work only with what was retrieved). The AI turns the confirmed summary into English search terms, OpenAlex returns real papers, the AI may only pick from those candidates and explain why, and code checks every picked ID against the candidate list. The student chooses how many papers (1–10) and whether to keep open-access papers only. Results are stored and shown like a search-results list; each paper has a detail page with metadata, the AI's reason and a citation generated from metadata (not by the AI).
- **Prompt generator** – before asking anything, the AI **diagnoses** the project (feasibility, guideline fit, scope, conflicts). It then asks 3–5 clarifying questions (multiple choice, an "I don't know" option, and a free-text box), and produces a summary that separates **confirmed facts, recommendations and assumptions**, plus a ready-to-copy prompt built on a six-step framework. **If a conflict is still unresolved, no prompt is generated.**

## How the prompt generator works

```
Project description (messy notes, brief, CV ...)
   -> Gemini: diagnosis (JSON)                   [feasible? fits the brief? scope? conflicts, each with quoted evidence]
   -> Gemini: clarifying questions (JSON)        [question bank chosen by project type; conflicts first]
   -> Student answers (choice / free text / "don't know")
   -> Gemini: summary + prompt design (JSON)     [confirmed / recommended / assumed / unresolved conflicts,
                                                  plus a role, interaction mode and six steps made for THIS project]
   -> Student reviews the summary and design     [write a correction -> regenerate; or confirm]
   -> unresolved conflict? yes -> blocked page (add context, edit the project, or re-answer)
                           no  -> final prompt is assembled in code (no AI call)
```

The final prompt is **customised per project**: preparing an interview produces a prompt in which the AI plays the hiring manager and asks one question at a time; a software project produces one in which it acts as a senior engineer who guides rather than writes everything. The model proposes the role, interaction rules, six step names/instructions and any special requests the student made. Code validates the design (exactly six steps, a role, etc.) and falls back to a generic design when it is invalid, so a bad model answer degrades gracefully instead of failing.

The safety part of the prompt is **not** left to the model: confirmed facts, recommendations and assumptions are always separated, the "pre-execution check" and the rule against inventing sources or facts are always present, and no prompt is built while a conflict is unresolved. Confirming costs no AI call.

## Architecture

| File | Responsibility |
|---|---|
| `app.py` | Flask routes, SQLAlchemy models, auth, CSRF protection |
| `ai_client.py` | The only module that talks to Gemini: retries, JSON mode, error translation |
| `prompt_builder.py` | The prompt-generator workflow: diagnosis, questions, summary + design, final prompt, validation of AI output |
| `openalex_client.py` | The only module that talks to OpenAlex: search, field normalisation, abstract reconstruction from the inverted index |
| `privacy.py` | Masks e-mail addresses and phone numbers before any text is sent to the AI or placed in a prompt |
| `skills/prompt_generator/` | The method as plain files: decision rules, prompt-design rules, question banks and best practices per project type (assignments, interview preparation, skill learning) |
| `templates/`, `static/` | Jinja2 pages and CSS |
| `test_app.py` | Automated tests (AI is mocked; no API quota used) |

## Design decisions

- **The skill lives in the repo, not in a vendor.** The method was first written as a Claude Agent Skill. Instead of depending on one platform, its rules, question banks and best practices were ported into `skills/prompt_generator/` and loaded by code, so the same knowledge works with any model. Adding a project type means adding a file.
- **The AI can only recommend papers that were actually retrieved.** Its picks are validated in code: IDs are normalised, anything not in the candidate set is dropped and logged, duplicates are removed, and nothing is stored unless the whole pipeline succeeds. Abstracts from OpenAlex are wrapped as data so instruction-like text inside them is not treated as instructions. This is a fixed pipeline, not tool use: code decides when to search; the model only proposes search terms and chooses among results.
- **Privacy.** E-mail addresses and phone numbers are masked before text reaches the model or a generated prompt; the database keeps the user's original text. Other personal details (addresses, ID numbers) cannot be detected reliably, and the form warns users not to enter them.
- **Human in the loop.** Nothing is generated until the student has seen and, if needed, corrected the AI's understanding and the proposed role/steps.
- **Pushing back is a feature.** The workflow is designed to point out conflicts with the brief, oversized scope and contradictory information, and to refuse to help disguise a guideline violation, rather than agreeing with the student.
- **AI calls only happen on the server.** The API key lives in `.env` (git-ignored) and never reaches the browser.
- **One module owns all AI access.** Swapping model or provider touches `ai_client.py` only; the model name comes from `GEMINI_MODEL`.
- **Graceful degradation.** Every request has a timeout (default 45 s, `GEMINI_TIMEOUT_SECONDS`) so a stalled call can never hang a page; 5xx errors are retried; if the primary model is overloaded (503), too slow (timeout), out of quota (429) or missing (404) the call automatically falls back to a second model (`GEMINI_FALLBACK_MODEL`). Errors that a different model cannot fix (invalid key, malformed request) do not trigger a fallback. Remaining failures are translated into a plain message for the user, while the real error goes to the console log. A failed AI call never leaves a half-written record. This was added after observing sustained 503 *"model is experiencing high demand"* responses on the free tier during development.
- **AI output is validated, not trusted.** JSON is parsed and schema-checked; malformed or empty results are rejected with a retry prompt. Output is rendered through Jinja2 auto-escaping.
- **Prompt-injection hygiene.** User-provided text is wrapped in delimiters and declared as data, not instructions.
- **Security basics.** Hashed passwords, per-session CSRF tokens on every POST, ownership checks on every project (other users get 404), a login-required decorator, identical error message for unknown user vs. wrong password.
- **Soft delete.** Submitting changes `status` instead of deleting rows, so a misclick is recoverable and history is preserved.
- **Schema upgrades.** `db.create_all()` does not add columns to existing tables, so `ensure_schema()` adds missing ones at startup; existing users and data are kept.

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env           # then fill in SECRET_KEY and GEMINI_API_KEY
python app.py                  # http://127.0.0.1:5000
```

Generate a `SECRET_KEY` with `python -c "import secrets; print(secrets.token_hex(32))"`. Get a Gemini key at https://aistudio.google.com. Free-tier inputs may be used by Google to improve its models, so don't paste sensitive material.

## Tests

```bash
python test_app.py
```

193 checks covering auth, CSRF, access control between users, project/status/edit flow, skill file loading, the full diagnose → ask → summarise → confirm → prompt flow with a fake AI, per-project customisation (interview vs. software get different roles, steps and references), the revise loop, fallback when the AI's design is invalid, conflict blocking and evidence filtering, simulated 503/429/403/network failures, primary-to-fallback model switching, request timeouts (including a real SDK call against a deliberately slow local server), malformed AI output, the paper pipeline (fake network via httpx MockTransport: real parsing code, no real requests; invented IDs dropped, injected instructions kept inside the data block, timeouts/429/500 store nothing, HTML in titles escaped, javascript: links removed, per-user access control), e-mail/phone masking, and upgrading an existing database.

## Known limitations / roadmap

- Description is text only; file upload / drag & drop of guidelines is not implemented yet.
- One round of clarifying questions (the confirm page does allow written corrections and regeneration).
- AI calls are synchronous: starting a prompt makes two calls (diagnosis + questions) and answering makes one, so the page waits several seconds. A background job queue would be the next step.
- Not deployed; development server only.
- Planned: literature search module backed by a real scholarly API (so references are never invented), and an example-reference module.

## Checking which models work right now

```bash
python check_models.py                              # primary + fallback from .env
python check_models.py gemini-3.8-flash gemini-3.5-flash-lite
```

## Paper module notes

- Requires a free OpenAlex key in `.env` (`OPENALEX_API_KEY`). It is sent in the `Authorization` header, not in the URL, so it does not end up in logs.
- Retrieval is keyword-based full-text search; relevant papers can be missed. The AI's reason is based on the title and abstract only, not the full text.
- "Relevance" is the model's own 1–10 rating, for personal screening only.

## Notes on model names

Model IDs are retired over time (during development `gemini-2.5-flash` started returning 404 "no longer available to new users"). The primary and fallback models therefore live in `.env`, not in the code, and any 404 from the primary model triggers the fallback. If both start failing with 404, check the current model list in Google AI Studio.
