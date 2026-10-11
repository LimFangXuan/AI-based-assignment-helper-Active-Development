# Assignment Helper

A web app that helps students get assignments done on time: clarify what the task really asks, turn it into a solid AI prompt, split the work into daily tasks before the deadline, find real academic papers, and draft the write-up.

I built it to learn how to integrate an LLM API into a real backend: authentication, a database, server-side AI calls, structured output, and graceful failure handling.

## The workflow

Each project has five tools. The order is the dependency chain: every tool reads the confirmed output of the ones before it.

| # | Tool | What it does |
|---|---|---|
| 1 | Requirements Checklist | Pre-scans the description and guideline, marks 12 aspects (deliverable, audience, scope, marking, constraints...) as clear / unclear / not applicable, then asks up to 3 questions per round about the real gaps only. Conflicts with the guideline are flagged with the exact words they come from. "Finish with what we have" turns what is left into labelled assumptions. |
| 2 | Prompt Generator | Builds a project framework (phases, methods, deliverables) from the confirmed requirements. Genuine forks show up as "Needs your decision" on the same page. Once confirmed, the code assembles a copy-paste prompt that makes any AI chat work one step at a time and wait for you. |
| 3 | Task Planner | Turns the framework into day-by-day tasks before the deadline, says honestly when time is too short, and lets you edit, tick, reorder or add your own tasks. |
| 4 | Paper Finder | Searches OpenAlex with terms derived from the requirements and framework; the AI may only pick from what was retrieved. |
| 5 | Report Drafter | Writes the outline (guideline structure first, then the FYP or Report template), then one section at a time: read, edit, add ideas and rewrite, approve. The next section unlocks only after approval. Paragraphs cite only Paper Finder results; anything without a source is flagged. |

Later tools never lock: they show a hint when an earlier step is missing. Anything that relies on an assumed requirement is labelled all the way down (framework phases, tasks, report paragraphs).

Paper Finder and Report Drafter are hidden for *Portfolio* and *Exam preparation* projects. The type is chosen by the student, not guessed by the AI.

## Features

- **Accounts**: register / login / logout, salted password hashes, session auth.
- **Projects**: name, deadline, description (the task itself), guideline / marking rubric, type, individual or group, citation style. Live character counters.
- **Overview**: a status ring (Not started / In progress / Ready to submit) with counts, today's and the next six days' task counts, then one card per project with a status filter.
- **Today** and **Next 6 days**: tasks across all projects, grouped by day, ticked off in place.
- **Calendar**: month grid of deadlines with a month strip, `+N more` for busy days, today marked.
- **Sidebar**: create button, main menu, the 8 nearest projects with status dots, and an Overview badge for projects that are overdue or due within 3 days. Collapsible (remembered per browser); a drawer on phones.
- **Tasks**: add (press Enter to keep adding), inline edit, tick, delete, drag to reorder. The project status follows: the first tick sets *In progress*, the last one *Ready to submit*.
- **Submit / delete**: submitting is a soft delete (status `submitted`, data kept, can be moved back). Delete permanently removes a project after a confirmation dialog.
- **Stale detection**: requirements checks, frameworks, planned tasks and report drafts store a fingerprint of the description + guideline; if either changes later, the tool says "Details changed since this was created. Update?". Nothing is re-run automatically (that would spend AI quota).
- **Light and dark themes**, chosen in Settings.

## Architecture

```
run.py                     entry point (python run.py, or a WSGI server pointed at run:app)
app/
  __init__.py              create_app(): config, extensions, blueprints, CSRF hook, ensure_schema()
  extensions.py            db = SQLAlchemy()
  security.py              login_required, CSRF, ownership checks, safe redirects
  constants.py             statuses, types, length limits, thresholds (one place to tune)
  tools_registry.py        the five tools, their order and visibility
  schema.py                ensure_schema(): new tables, missing columns, indexes
  template_helpers.py      template filters and sidebar data (one query)
  models/                  user, project, requirements, prompt, plan (tasks), paper, report
  blueprints/              auth, overview (/, /today, /upcoming), calendar, projects, tools/*
  services/                no Flask request objects and no imports from models
    ai_client.py           the only module that talks to Gemini
    openalex_client.py     the only module that talks to OpenAlex
    privacy.py             masks emails and phone numbers before text reaches the AI
    common.py              shared helpers: project block (data, not instructions), input-size check, quote check
    requirements_checker.py  Requirements Checklist: pre-scan, rounds, validation, context for later tools
    prompt_generator.py    framework generation and code-assembled final prompt
    task_planner.py        day-by-day plan, date clamping, time feasibility
    paper_finder.py        search terms and candidate selection
    report_drafter.py      outline, section drafts, citation markers, export
    citations.py           in-text citations and reference lists from metadata (APA 7, Harvard, IEEE, MLA, Chicago)
  skills/                  plain data files: rules, question banks, best practices, the 12 requirement aspects,
                           report templates (FYP, Report)
  templates/               layout.html, components/, pages/
  static/                  style.css (design tokens, light + dark), app.js
test_app.py                automated tests (AI and OpenAlex are mocked)
seed_demo.py               local demo account with sample data
check_models.py            checks which Gemini models currently work
```

## Design decisions

- **The skill lives in the repo, not in a vendor.** The method was first written as a Claude Agent Skill. Its rules, question banks and best practices were ported into `app/skills/prompt_generator/` and loaded by code, so the same knowledge works with any model.
- **The AI can only recommend papers that were actually retrieved.** Picks are validated in code: IDs are normalised, anything not in the candidate set is dropped and logged, duplicates are removed, and nothing is stored unless the whole pipeline succeeds. This is a fixed pipeline, not tool use: code decides when to search; the model only proposes search terms and chooses among results.
- **Requirements before anything else.** Every later tool reads the confirmed requirements, so nothing important is guessed. The checker is capped internally (3 questions per round, 5 rounds, at most 6 AI calls) and the student can stop at any time.
- **Evidence is checked in code.** A conflict the AI reports must quote the student's material, and the code verifies the quote really appears there; otherwise it is dropped. This stops the AI from inventing guideline rules.
- **The generated prompt asks the other AI to work step by step** (one step at a time, waiting for the student's confirmation) rather than restricting it to guidance only. Its safety parts are not left to the model: confirmed facts, recommendations and assumptions are always separated, the rule against inventing sources or facts is always present, and no prompt is built while a conflict is unresolved.
- **Dates are never trusted from the AI.** Task Planner drafts are clamped to today…deadline, nonsense durations are dropped, the code computes hours per day itself to flag a schedule that can't fit, and nothing is saved until the student reviews the draft.
- **Citations can't be invented.** The Report Drafter cites with markers like `[P12]`; code removes any marker that is not one of this project's papers, and builds in-text citations and the reference list from OpenAlex metadata. Paragraphs without a valid source are flagged "needs source".
- **Privacy.** Emails and phone numbers are masked in the description and the guideline before anything reaches the model; the database keeps the original text. Other personal details cannot be detected reliably, and the form warns about them.
- **Prompt-injection hygiene.** Description, guideline and retrieved abstracts are wrapped in delimiters and declared as data, not instructions.
- **AI output is validated, not trusted.** JSON is parsed and schema-checked; invalid output gives a retry message and never leaves a half-written record.
- **Graceful degradation.** Every AI request has a timeout; 5xx errors are retried; an overloaded, slow, out-of-quota or missing primary model falls back to a second model. Errors a different model can't fix (bad key, bad request) don't trigger a fallback. Users see a plain message; the real error goes to the log.
- **Works without JavaScript.** Every action is a normal form POST; `app.js` upgrades it to an in-place update (requests carry `X-Requested-With: fetch` and get JSON back). The `next` redirect target is restricted to same-site paths.
- **Motion has a job.** Animations mark a state change (tick, progress, new row, dialog, AI waiting) and are switched off under `prefers-reduced-motion`. Status is always shown as text too, never by colour alone.
- **Security basics.** Hashed passwords, per-session CSRF tokens on every POST, ownership checks on every project and child record (other users get 404), identical error for unknown user vs wrong password, Jinja auto-escaping.
- **Schema upgrades without data loss.** `ensure_schema()` runs inside `create_app()`, so any start-up path works on a fresh database. Missing columns are added with `ALTER TABLE ... ADD COLUMN`; columns and tables are never dropped. Old projects get `type = other`, `individual` and an empty guideline.

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env           # then fill in SECRET_KEY, GEMINI_API_KEY, OPENALEX_API_KEY
python run.py                  # http://127.0.0.1:5000
python seed_demo.py            # optional: local demo account with sample data
```

Generate a `SECRET_KEY` with `python -c "import secrets; print(secrets.token_hex(32))"`. Get a Gemini key at https://aistudio.google.com and a free OpenAlex key at https://openalex.org/settings/api. Free-tier Gemini inputs may be used by Google to improve its models, so don't paste sensitive material.

Set `FLASK_DEBUG=1` in `.env` for auto-reload and error pages while developing. Never enable it on a public server: the Werkzeug debugger can run code.

## Tests

```bash
python test_app.py
```

258 checks covering the Requirements Checklist (pre-scan, rounds, conflict evidence, the internal round cap, finishing with assumptions, stale detection), the Prompt Generator (blocked by open conflicts, decisions, corrections, the code-built prompt and what it must and must not contain), the Report Drafter (outline, unlock order, invented citations removed, needs-source flags, APA and IEEE),  auth and CSRF, per-user isolation on every route, the project form and its validation, status changes and soft delete, tool visibility by type, tasks (add / edit / tick / reorder / delete, automatic status, Today and Next 6 days, open-redirect protection), the AI task breakdown (date clamping, invalid output, nothing stored until saved), the full prompt flow with a fake AI (customisation per project, revise loop, conflict blocking), simulated 503/429/403/timeout/network failures and model fallback (including a real SDK call against a deliberately slow local server), the paper pipeline (fake network via `httpx.MockTransport`: invented IDs dropped, injected instructions kept inside the data block, failures store nothing, HTML escaped, `javascript:` links removed), email/phone masking, starting on a fresh database, and upgrading an old database without losing data.

## Known limits

- AI-generated content (questions, frameworks, drafts) is written in English.
- Harvard, MLA and Chicago reference entries use a simplified format; check them against the guideline.
- Drag-to-reorder doesn't work on touch screens; AI calls are synchronous; not deployed yet.
- The description/guideline limits (20,000 / 8,000 characters, 26,000 sent to the AI) are tentative.

## Checking which models work right now

```bash
python check_models.py
python check_models.py gemini-3.8-flash gemini-3.5-flash-lite
```

Model IDs are retired over time, so the primary and fallback models live in `.env`, not in the code, and any 404 from the primary model triggers the fallback.
