# Case study: Assignment Helper

A Flask web app that walks a student from "I just got this assignment" to a planned, sourced, section-by-section draft. This page explains the problem, the decisions that shaped the code, what went wrong along the way, and how to read the code in about 20 minutes.

## 1. The problem

When students use a general AI chat for coursework, three failures keep showing up:

1. **It guesses the brief.** Ask for "a report on X" and the model picks an audience, a length and a structure without asking. The student only finds out at marking time.
2. **It invents sources.** References look plausible but don't exist, or say something else.
3. **It gives one big answer and no plan.** Nothing tells the student what to do on Tuesday so they finish by Friday.

So the product goal was a pipeline in which every step depends on a confirmed earlier step:

```
Requirements Checklist → Prompt Generator → Task Planner → Paper Finder → Report Drafter
   (what is asked)        (how to approach)   (when to do it)  (real sources)  (the write-up)
```

My learning goal was to put an LLM inside a real backend properly: accounts, a database, server-side calls, output validated in code, and failures that degrade gracefully instead of crashing.

## 2. Key decisions

### The AI proposes, the code decides
Every model response is JSON that is parsed and checked before anything is stored. The rule underneath: **never trust the model with a fact the code can check.**

| What the model returns | What the code does |
|---|---|
| A conflict between the brief and the guideline, with a quote | Checks the quote really appears in the student's text ([`common.quote_is_in`](../app/services/common.py)); otherwise the conflict is dropped. |
| Task due dates | Clamps them to today…deadline, drops nonsense durations, and computes hours per day itself to say whether the plan fits ([`task_planner._clamp_date`, `parse_plan`](../app/services/task_planner.py)). |
| Paper picks | IDs are normalised; anything not in the retrieved candidate set is dropped and logged ([`paper_finder.validate_selection`](../app/services/paper_finder.py)). |
| Citations like `[P12]` in a draft | Any marker that isn't one of this project's papers is removed, and the reference list is built from OpenAlex metadata, never from model text ([`report_drafter.clean_markers`](../app/services/report_drafter.py), [`citations.py`](../app/services/citations.py)). |

### A fixed pipeline, not tool use
For Paper Finder I deliberately did **not** let the model call a search tool. The code decides when to search. The model only proposes search terms, then picks from what came back. It is less flexible but fully predictable, cheaper, and easy to test.

### One module per outside service
`ai_client`, `openalex_client`, `google_auth`, `mailer` and `push` are the only places that talk to the outside world. That made three things cheap: faking every service in tests, adding a model fallback in one place, and later adding a **demo mode** that swaps Gemini and OpenAlex for offline stand-ins with a single `if` in each module.

### Requirements before everything, with an exit
The checker asks at most 3 questions per round and stops after 5 rounds (at most 6 AI calls). The student can press "Finish with what we have" at any time. Whatever is still unclear becomes a labelled **assumption**, and that label follows the item all the way into framework phases, tasks and report paragraphs.

### Progressive enhancement
Every action is a normal form POST that works without JavaScript. `app.js` upgrades forms to in-place `fetch` updates (requests carry `X-Requested-With: fetch` and get JSON back). This kept the server as the single source of truth and made every route testable with the Flask test client.

### Security basics treated as features
CSRF tokens on every POST, ownership checks that return 404 for other users' records, login throttling, signed one-time links (a reset link is bound to the current password hash, so the first use kills it), Google OAuth with `state` and PKCE, and no automatic merge between a Google account and an unverified email.

## 3. Challenges and what I learned

- **Model IDs get retired.** A model that worked one week returned 404 the next. Fix: primary and fallback model names live in `.env`, and 404/429/503 or a timeout on the primary falls back to the second model. Errors another model can't fix (bad key, bad request) don't trigger a fallback. Users see a plain message; the real error goes to the log.
- **A de-duplication step broke valid citations.** Report Drafter removed duplicate papers across searches, then validated citations against the de-duplicated list, so legitimate `[P#]` markers that pointed at a duplicate were stripped. Fix: validate against *all* the project's papers, and send only the de-duplicated list to the model. Lesson: the set you validate against and the set you show the model are different things.
- **A Jinja gotcha.** `counts.clear` in a template resolved to the dict's `.clear()` method instead of the `"clear"` key. It rendered without error and showed the wrong thing. Now `counts['clear']`.
- **Schema changes without migrations.** SQLite and no Alembic meant old databases had to keep working. `ensure_schema()` adds missing columns and indexes on startup and never drops anything. A test builds an old-format database and upgrades it twice.
- **Push notifications are fiddly.** Headless Chrome's incognito context has no Push API, so the end-to-end check needed a persistent profile. Encryption and VAPID signatures are now verified in the test suite by a simulated browser that decrypts the payload.
- **Testing an AI app without spending quota.** The fake AI answers by a task marker embedded in each prompt (`[TASK:PLAN]`, `[TASK:REPORT_SECTION]`…). That one idea made the whole flow testable offline, and later became the basis of the offline demo mode.

## 4. What I'd do next

- Move AI calls to a background job queue so a slow model doesn't hold a request thread.
- Postgres and real migrations (Alembic) before any multi-user deployment.
- Shared login throttling (Redis) instead of in-memory.
- Stream section drafts token by token.
- Evaluate the prompts on a fixed set of real (anonymised) briefs, so prompt changes are measured and not just eyeballed.

## 5. Reading the code (about 20 minutes)

Read in this order. Each step builds on the one before.

1. **[`app/__init__.py`](../app/__init__.py)**: `create_app()`. Config, blueprints, the CSRF hook, `ensure_schema()`, and demo-mode reset on startup.
2. **[`app/security.py`](../app/security.py)**: `login_required`, `get_own_project` / `get_own_child` (why other users get 404), `check_csrf`, `safe_next`.
3. **[`app/services/ai_client.py`](../app/services/ai_client.py)**: `_generate` → `_models_to_try` → `_call_model`. Retries, timeout, fallback, friendly errors. The demo-mode hook is the first line of `_generate`.
4. **[`app/services/common.py`](../app/services/common.py)**: `project_block` (student text wrapped as data, not instructions) and `quote_is_in`.
5. **One tool end to end, the Task Planner:**
   - route: [`app/blueprints/tools/planner.py`](../app/blueprints/tools/planner.py) `draft()` and `save()`. Note that the draft is never stored until the student saves it.
   - service: [`app/services/task_planner.py`](../app/services/task_planner.py) `generate_plan` → `parse_plan` → `_clamp_date`.
6. **The trust boundary for sources:** [`paper_finder.validate_selection`](../app/services/paper_finder.py) and [`report_drafter.clean_markers`](../app/services/report_drafter.py).
7. **[`app/reminders.py`](../app/reminders.py)**: `run()` → `process_digest` / `process_deadlines`, and `already_sent` / `record` (why a reminder is never sent twice).
8. **[`app/blueprints/demo.py`](../app/blueprints/demo.py)** + [`app/services/demo_ai.py`](../app/services/demo_ai.py): how demo mode closes routes and answers offline.
9. **[`test_app.py`](../test_app.py)**: skim `fake_generate` and `ready_project` at the top, then section 12 (demo mode), which ends by asserting that no network connection was opened.

## 6. Questions I expect, with short answers

**Why Flask and not Django or a JS framework?**
I wanted to understand every layer. Flask plus server-rendered templates kept the whole app in one language and one process, with no build step, and every route is testable with the test client.

**How do you stop the AI from making things up?**
I don't rely on the prompt alone. Anything checkable is checked in code: quotes must exist in the source text, dates are clamped, paper IDs must come from the retrieved set, and citation markers must match stored papers. Anything that can't be checked is labelled as an assumption.

**What happens when Gemini is down or slow?**
Every call has a timeout. 5xx errors are retried, then the fallback model is tried. If everything fails, the user gets a plain message, nothing half-written is stored, and they can retry.

**How is user data protected?**
Passwords are salted hashes, every POST needs a CSRF token, and records are looked up through ownership checks. Emails and phone numbers are masked before text reaches the AI (the database keeps the original). Users can export or delete everything from Settings.

**How did you test it without spending API quota?**
A fake AI keyed on task markers, `httpx.MockTransport` for OpenAlex and Google, a fake SMTP server, and a stubbed push service. All 504 checks run offline in a few minutes.

**What would break first with 1,000 users?**
Synchronous AI calls holding request threads, SQLite write locking, and in-memory login throttling. Those are the first three items in "What I'd do next".

**Why is there a demo mode?**
So anyone can try the full flow without API keys, and without their typing being sent to a third party. It also forced a cleaner design: because each outside service already had a single entry point, switching all of them off took a few lines.
