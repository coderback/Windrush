# Windrush

AI career advisor that analyses CVs, scores AI automation-exposure risk, finds matching jobs, generates tailored CVs and cover letters, and autonomously submits applications via browser automation.

Built with open/cloud LLMs served through an OpenAI-compatible client (Groq or local Ollama), [browser-use](https://github.com/browser-use/browser-use), Next.js, and FastAPI.

---

## What it does

1. **Accounts & Persona** — sign up, then build a rich persona (contact details, preferences, skills, work history, education, projects, certifications, screening answers, behavioural stories).
2. **Upload a CV (PDF)** — parsed into structured data and merged into your persona.
3. **AI Exposure Risk** — scores each skill and job title against the Anthropic Economic Index / O\*NET task-penetration data (~18 000 occupational tasks), with LLM-generated reasoning.
4. **Job Feed** — discovers jobs across multiple sources, caches them locally, and ranks them by dense-vector semantic similarity to your persona and search intent.
5. **Per-job analysis** — on demand, scores fit (LLM semantic match) and AI risk for a single role.
6. **Tailored CV + Cover Letter** — generates structured, ATS-aware documents with a live in-app preview and PDF export (HTML/CSS → WeasyPrint).
7. **Browser Application** — autonomously fills and submits the application form with a headless Chrome agent; falls back to interactive user control if the agent gets stuck, with a review step before submit.
8. **Skill Roadmap** — generates 6 AI-resilient skill-development recommendations tailored to your industry and target role.
9. **Application Tracker** — persists every application through a status lifecycle (Saved → Pending Review → Evaluated → Applied → Responded → Interview → Offer → Rejected/Discarded).

---

## Architecture

Six Docker services:

| Service | Stack | Port | Role |
|---|---|---|---|
| `nginx` | nginx:alpine | 80 | Reverse proxy; disables SSE buffering |
| `frontend` | Next.js 14, React 18, TypeScript, Tailwind | 3000 | UI |
| `api` | Python 3.13, FastAPI, OpenAI-compat client, Playwright, WeasyPrint | 8000 | Agent pipeline + browser automation + documents |
| `jobs-mcp` | Python, FastMCP | 8001 | MCP server wrapping the Adzuna Jobs API |
| `civic-guardrails` | Node.js, `@civic/passthrough-mcp-server` | 8002 | MCP proxy: rate-limiting, injection detection, PII scrubbing, audit logging |
| `ollama` | ollama/ollama | 11434 | Local LLM inference + embeddings (`OLLAMA_KEEP_ALIVE=24h`) |

Only `nginx` is published to the host (port 80); every other service is reached through it. The `ollama` service has an NVIDIA GPU reservation enabled in `docker-compose.yml` — remove it if you don't have a GPU.

---

## LLM Backend

The API talks to LLMs through the OpenAI-compatible `AsyncOpenAI` client — there is **no Anthropic SDK**. The backend is selected with the `LLM_BACKEND` env var:

| `LLM_BACKEND` | Agent / tool model | Browser-agent model | Notes |
|---|---|---|---|
| `groq` (compose default) | `meta-llama/llama-4-scout-17b-16e-instruct` | `llama-3.3-70b-versatile` | Requires `GROQ_API_KEY` |
| `ollama` | `${OLLAMA_MODEL}` (default `qwen3.5:4b`) | `${OLLAMA_MODEL}` | Fully local; no API key |

Embeddings for the semantic job feed always come from Ollama (`nomic-embed-text`), regardless of backend.

> If you run with `LLM_BACKEND=ollama`, pull the models into the ollama volume first:
> ```bash
> docker compose exec ollama ollama pull qwen3.5:4b
> docker compose exec ollama ollama pull nomic-embed-text
> ```

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- A Groq API key (for the default backend) **or** enough local resources to run Ollama models
- Adzuna API credentials (free tier) — optional; multiple free job sources and fixture data are used otherwise

### 1. Clone and configure

```bash
git clone <repo>
cd Windrush
cp .env.example .env
# Edit .env (see Environment Variables below)
```

### 2. Data files

The economic index and task-penetration data must be present in `./data/` (bind-mounted read-only at `/data` in the api container):

```
data/economic_index.json   — Anthropic Economic Index (O*NET occupation exposure scores)
data/task_penetration.csv  — O*NET task-level AI penetration scores (~18 000 rows)
```

### 3. Build and run

```bash
docker compose up --build
```

Open [http://localhost](http://localhost), create an account, and complete onboarding.

For local (non-Docker) dev:

```bash
cd api && uvicorn app.main:app --reload      # needs a reachable Ollama/Groq + the data files
cd frontend && npm run dev
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `LLM_BACKEND` | No | `groq` (default in compose) or `ollama` |
| `GROQ_API_KEY` | If `LLM_BACKEND=groq` | Powers the agent pipeline and browser agent via Groq |
| `OLLAMA_HOST` | No | Ollama base URL (default `http://ollama:11434` in compose) |
| `OLLAMA_MODEL` | No | Local model id (default `qwen3.5:4b`) |
| `EMBEDDING_MODEL` | No | Embedding model for the semantic feed (default `nomic-embed-text`) |
| `JOB_EMAIL` | For applying | Email credential passed to the browser agent for job-site login |
| `JOB_PASSWORD` | For applying | Password credential (masked in SSE output) |
| `ADZUNA_APP_ID` | Optional | Adzuna API id (enables the Adzuna job source) |
| `ADZUNA_API_KEY` | Optional | Adzuna API key |
| `ECONOMIC_INDEX_PATH` | No | Path to the economic index JSON (default `/data/economic_index.json`) |
| `TASK_PENETRATION_PATH` | No | Path to the task penetration CSV (default `/data/task_penetration.csv`) |
| `JOBS_MCP_URL` | No | Guardrails MCP endpoint (default `http://civic-guardrails:8002/mcp`) |
| `APP_DATA_PATH` | No | SQLite data dir (default `/appdata` in compose) |

`JOB_EMAIL` / `JOB_PASSWORD` can also be supplied per-application from the persona instead of globally.

---

## API Endpoints

All long-running endpoints use **Server-Sent Events (SSE)** so the frontend renders incrementally. Protected endpoints require a `Bearer` JWT from `/login`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/signup` | Create an account |
| `POST` | `/login` | OAuth2 password form → JWT |
| `GET` / `PUT` | `/persona` | Read / update the structured persona |
| `POST` | `/upload` | Parse a CV PDF, merge into the persona, return a `cv_session_id` |
| `POST` | `/stream` | Run the full agent pipeline → SSE events |
| `POST` | `/apply` | Trigger the browser application → SSE browser events |
| `POST` | `/browser-input/{session_id}` | Send click/type/scroll/submit commands to the live session |
| `GET` | `/browser-stream/{session_id}` | SSE stream of live base64 JPEG frames (CDP screencast) |
| `GET` | `/jobs` | Paginated, filtered, semantically-ranked job feed |
| `POST` | `/jobs/save` | Bookmark a job into the tracker as `Saved` |
| `POST` | `/jobs/analyze` | SSE: fit + AI-risk analysis for one job |
| `POST` | `/jobs/cover-letter` | SSE: generate a tailored cover letter |
| `POST` | `/jobs/tailored-cv` | SSE: generate a tailored, structured CV |
| `GET` / `POST` | `/applications` | List / create tracked applications |
| `PATCH` | `/applications/{id}/status` | Update an application's status + notes |
| `GET` / `POST` | `/onboarding/status`, `/onboarding/complete` | Onboarding state |
| `POST` | `/score-skills` | Score AI risk for all persona skills |
| `POST` | `/careers/roadmap` | SSE: generate a skill-development roadmap |
| `POST` | `/documents/pdf` | Render a structured doc (or legacy text) to PDF |
| `POST` | `/documents/preview` | Render a structured doc to HTML for the live preview |
| `GET` | `/documents/{doc_id}/download` | Download a generated PDF |
| `GET` | `/guardrails/audit` | In-process guardrail audit log |
| `GET` | `/health` | Liveness check |

---

## Agent Pipeline

The API drives the LLM in an agentic tool-use loop (`api/app/agent.py`). The system prompt enforces this order:

```
extract_cv_profile → score_ai_risk → search_jobs (+ optional web_search)
  → score_job_fit → generate_skill_roadmap → generate_cover_letter
```

After the user explicitly approves, the apply phase runs the browser agent. The loop also:
- nudges the model to continue if it stops early (max 2 nudges),
- injects a correction if the model hallucinates a tool name.

The full tool set is: `extract_cv_profile`, `score_ai_risk`, `search_jobs`, `web_search` (DuckDuckGo Lite), `score_job_fit`, `generate_cover_letter`, `generate_tailored_cv`, `generate_skill_roadmap`, `apply_to_job`, `lookup_economic_index`.

**Dual-path tool data:**
- SSE output → PII-redacted (emails, phones, postcodes, NI numbers) and credential-masked.
- LLM context → unredacted (the agent needs real contact details to fill forms).

---

## AI Exposure Risk Scoring

Scores are computed without any neural network — deterministic lookups against O\*NET data, with the LLM only adding human-readable reasoning afterwards.

`score_ai_risk` resolves each skill/title in this order (`agent.py`, `risk_scorer.py`):

1. **Curated exposure table** — a hand-tuned map of common tech skills and job titles.
2. **Keyword task search** — average penetration of all O\*NET tasks containing the term (reliable for multi-word occupational phrases).
3. **TF-IDF semantic match** — cosine similarity against ~1 350 non-zero-penetration task descriptions; requires all content words to appear.
4. **O\*NET word-overlap** — stems and noise-strips the title, then matches the occupation with the most shared content words.
5. **Default 0.5** — neutral when no data differentiates.

Labels: **High ≥ 65 %**, **Medium 35–65 %**, **Low < 35 %**.

**Job fit** (`score_job_fit`) is an LLM semantic analysis returning `fit_score` (0–100), `level_match` (`strong`/`ok`/`reach`), `matched_skills`, `skill_gaps`, and a one-line rationale. **Feed ordering** is done by dense-vector cosine similarity between an interest-weighted persona embedding and each job's embedding.

---

## Job Discovery

`search_jobs` runs a multi-level cascade (`api/app/job_searcher.py`) and caches results in a local SQLite store (`jobs.db`):

1. **Playwright scraping** of curated company career pages.
2. **Public ATS JSON APIs** — Greenhouse, Ashby, Lever, Workable, SmartRecruiters (60+ companies).
3. **Brave Search** with `site:` filters.
4. **Adzuna** paid API (when credentials are set).

If everything is empty, it falls back to `api/app/jobs_fixture.json`. The `/jobs` feed lazily triggers live discovery when local matches run low and persists new jobs (with embeddings) for next time.

---

## Browser Automation

The browser agent (`api/app/browser_agent.py`) uses browser-use with the configured backend's model:

- **No vision** (`use_vision=False`) — the agent reasons from the DOM/accessibility tree, which is faster.
- **CDP screencast** — live JPEG frames (quality 60, up to ~30 fps, max 1280×800) streamed to the frontend via a separate SSE endpoint, independent of the agent.
- **File upload** — the CV PDF path is passed as `available_file_paths` so the agent can attach it directly.
- **Rich task prompt** — persona contact details, skills, education, experience, projects, screening answers, behavioural stories, and dropdown/diversity defaults are compiled into the agent's task.
- **Interactive fallback + review** — if the agent fails (or before final submit), the frontend becomes a clickable remote control; clicks/types/scrolls are dispatched via Playwright until the user types `submit`/`skip`.

---

## Guardrails

| Layer | Where | What |
|---|---|---|
| CV injection check | `guardrails.py` (pre-pipeline) | Regex patterns detect prompt injection in uploaded CV text; blocks before any LLM call |
| Tool input sanitisation | `guardrails.py` | Validates search queries (injection/HTML), validates `apply_to_job` URLs (`http(s)://`), strips credential fields from all tool inputs |
| PII redaction (SSE) | `guardrails.py` | Redacts emails, UK/intl phones, postcodes, NI numbers from SSE-streamed tool results/inputs |
| Credential masking (SSE) | `guardrails.py` | Replaces password/token/secret/api_key values with `***` in SSE events |
| MCP rate limiting | `civic-guardrails/server.js` | 30 requests/minute per session |
| MCP search guardrail | `civic-guardrails/server.js` | Blocks injection patterns in `search_jobs` queries |
| MCP PII scrub + audit | `civic-guardrails/server.js` | Scrubs emails/phones from job responses; logs all MCP requests/responses to `/logs/audit.jsonl` |

Guardrail events surface in the UI (flashing shield badge) and via `GET /guardrails/audit`.

---

## Frontend

**Stack:** Next.js 14 · React 18 · TypeScript · Tailwind CSS · dark theme.

**Pages:** `login`, `signup`, `onboarding`, `dashboard`, `jobs` (feed), `jobs/[id]` (analysis + documents + apply), `applications` (tracker), `careers` (risk + roadmap), `profile` (persona editor).

**Key components:**

| Component | Purpose |
|---|---|
| `AppShell` / `Sidebar` | Navigation shell (hidden on auth/onboarding pages) |
| `RiskRadar` | AI exposure % per skill |
| `JobCard` / `JobList` | Ranked job cards with badges |
| `DocEditor` | Structured CV/cover-letter editor with live HTML preview |
| `CoverLetter` | Cover-letter review + job-site credential entry |
| `BrowserView` | Clickable live browser screencast; clicks sent to `/browser-input` |
| `AgentLog` | Real-time tool calls, results, guardrail events, browser steps |
| `SkillRoadmap` | Timeline of skill recommendations |
| `GuardrailBadge` | Flashes when a guardrail fires |
| `ApplicationTracker` | Status lifecycle management |

---

## Data & Storage

| File | Description |
|---|---|
| `data/economic_index.json` | ~3 000 O\*NET occupation codes → `overall_exposure` (0–1). Source: Anthropic Economic Index. |
| `data/task_penetration.csv` | ~18 000 O\*NET task descriptions → `penetration` score (TF-IDF + keyword search). |
| `api/app/jobs_fixture.json` | Mock job listings used as a last-resort fallback. |
| `applications.db` (SQLite, `/appdata`) | `users` (bcrypt passwords, persona JSON, onboarding flag) + `applications`. |
| `jobs.db` (SQLite, `/appdata`) | Cached jobs with semantic vectors; populated lazily or via `python -m app.job_sync`. |

---

## Models in Use

| Use case | `groq` backend | `ollama` backend |
|---|---|---|
| Agent loop + internal tools (CV parse, fit, cover letter, roadmap, tailored CV) | `meta-llama/llama-4-scout-17b-16e-instruct` | `qwen3.5:4b` (`OLLAMA_MODEL`) |
| Browser automation | `llama-3.3-70b-versatile` | `qwen3.5:4b` (`OLLAMA_MODEL`) |
| Embeddings (semantic feed) | `nomic-embed-text` (Ollama) | `nomic-embed-text` (Ollama) |

---

## Development Notes

**Switching backend:** set `LLM_BACKEND=ollama` (and pull the models) or `LLM_BACKEND=groq` (and set `GROQ_API_KEY`).

**Adding a new tool:**
1. Add the definition to `TOOLS` in `agent.py` (`name`, `description`, `input_schema`).
2. Add a handler branch in `execute_tool()`.
3. If the tool processes user data, add it to `_PII_REDACT_TOOLS` in `guardrails.py`.

**Document templates:** structured CV/cover-letter rendering lives in `api/app/doc_render.py` + `api/app/templates/` (`registry.py`, `classic_cv.html`, `classic_letter.html`, `base.css`), rendered with Jinja2 → WeasyPrint (fpdf2 is the fallback).
