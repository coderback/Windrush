# Windrush

AI career advisor that analyses CVs, scores AI automation-exposure risk, finds matching jobs, generates tailored CVs and cover letters, and fills in job applications with a browser agent — which you review before anything is sent.

Built with FastAPI, Next.js, [browser-use](https://github.com/browser-use/browser-use), and a choice of LLM backend: Anthropic Claude, Groq, or a local Ollama model.

---

## What it does

1. **Accounts & Persona** — sign up, then build a rich persona (contact details, preferences, skills, work history, education, projects, certifications, screening answers, behavioural stories, custom directives).
2. **Upload a CV (PDF)** — parsed into structured data and merged into your persona; the PDF is kept so the browser agent can attach it.
3. **AI Exposure Risk** — scores each skill and job title against the Anthropic Economic Index / O\*NET task-penetration data (~18 000 occupational tasks), with LLM-generated reasoning.
4. **Job Feed** — searches a local job store with real filters (search terms, role/domain tags, level, location, remote) and ranks results by semantic similarity to your persona. When results are thin, live discovery across job boards runs in the background and the feed fills in as it finishes.
5. **Paste any job link** — scrape an arbitrary listing into the same analysis flow.
6. **Per-job analysis** — fit score (LLM semantic match) and AI risk for a single role.
7. **Tailored CV + Cover Letter** — structured, ATS-aware documents with a live in-app preview and PDF export (HTML/CSS → WeasyPrint).
8. **Browser Application** — a headless Chrome agent fills the application form and **stops before the final submit**. You review it in a live view (and can take over with clicks/typing), then `submit`, `done` (you submitted it yourself) or `skip`.
9. **Skill Roadmap** — 6 AI-resilient skill-development recommendations for your industry and target role.
10. **Application Tracker** — every application through a status lifecycle (Saved → Pending Review → Evaluated → Applied → Responded → Interview → Offer → Rejected / Discarded).

---

## Architecture

Four Docker services:

| Service | Stack | Port | Role |
|---|---|---|---|
| `nginx` | nginx:alpine | 80 | Reverse proxy; disables buffering for SSE routes |
| `frontend` | Next.js 14, React 18, TypeScript, Tailwind | 3000 | UI |
| `api` | Python 3.13, FastAPI, browser-use, WeasyPrint | 8000 | LLM features, job search, documents, browser automation |
| `ollama` | ollama/ollama | 11434 | Embeddings for the job feed (+ optional local LLM) |

Only `nginx` is published to the host (port 80). The `ollama` service has an NVIDIA GPU reservation in `docker-compose.yml` — remove it if you don't have a GPU.

---

## LLM Backend

Selected with `LLM_BACKEND`:

| `LLM_BACKEND` | Text features (CV parse, fit, cover letter, tailored CV, roadmap) | Browser agent | Needs |
|---|---|---|---|
| `claude` | `ANTHROPIC_MODEL` (default `claude-sonnet-4-6`) via the `anthropic` SDK | same model via browser-use's `ChatAnthropic` | `ANTHROPIC_API_KEY` |
| `groq` (compose default) | `GROQ_MODEL` (default `meta-llama/llama-4-scout-17b-16e-instruct`) | same model via browser-use's `ChatGroq` | `GROQ_API_KEY` |
| `ollama` | `OLLAMA_MODEL` (default `qwen3.5:4b`) | same model via browser-use's `ChatOllama` | local resources |

The Groq browser model must be one browser-use drives with JSON-schema output (see `JsonSchemaModels` in `browser_use/llm/groq/chat.py`). Embeddings always come from Ollama (`nomic-embed-text`), whatever the backend:

```bash
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull qwen3.5:4b   # only for LLM_BACKEND=ollama
```

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- An API key for your chosen backend (or enough local resources for Ollama)
- Optional: Adzuna and Brave Search keys for more job sources

### 1. Configure

```bash
cp .env.example .env
# Required secrets:
openssl rand -hex 32                                                                  # → JWT_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # → CREDENTIALS_KEY
```

The API refuses to start without `JWT_SECRET` and `CREDENTIALS_KEY`.

### 2. Data files

The economic index and task-penetration data must be present in `./data/` (bind-mounted read-only at `/data`):

```
data/economic_index.json   — Anthropic Economic Index (O*NET occupation exposure scores)
data/task_penetration.csv  — O*NET task-level AI penetration scores (~18 000 rows)
```

### 3. Run

```bash
docker compose up --build
```

Open [http://localhost](http://localhost), create an account, and complete onboarding. Optionally pre-fill the job store with `docker compose exec api python -m app.job_sync`.

Local (non-Docker) dev:

```bash
cd api && uvicorn app.main:app --reload      # needs the env vars above, the data files and a reachable Ollama
cd frontend && npm run dev
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `JWT_SECRET` | **Yes** | Signs login tokens |
| `CREDENTIALS_KEY` | **Yes** | Fernet key encrypting stored job-site passwords. Changing it makes saved passwords unreadable (users re-enter them) |
| `LLM_BACKEND` | No | `claude`, `groq` (compose default) or `ollama` |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | For `claude` | Key / model id |
| `GROQ_API_KEY` / `GROQ_MODEL` | For `groq` | Key / model id |
| `OLLAMA_HOST` / `OLLAMA_MODEL` / `EMBEDDING_MODEL` | No | Ollama URL (compose: `http://ollama:11434`), local model, embedding model |
| `ADZUNA_APP_ID` / `ADZUNA_API_KEY` | Optional | Enables the Adzuna job source |
| `BRAVE_SEARCH_API_KEY` | Optional | Enables the Brave `site:` search job source |
| `ECONOMIC_INDEX_PATH` / `TASK_PENETRATION_PATH` | No | Data file paths (default `/data/...`) |
| `APP_DATA_PATH` | No | SQLite DBs, PDFs and uploaded CVs (compose: `/appdata`) |

Job-site login details are set per user on the Profile page, not via env vars.

---

## API Endpoints

Long-running endpoints stream **Server-Sent Events (SSE)**. Protected endpoints require a `Bearer` JWT from `/login`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/signup` | Create an account |
| `POST` | `/login` | OAuth2 password form → JWT |
| `GET` / `PUT` | `/persona` | Read / update the persona (the job-site password is write-only — GET returns a mask) |
| `GET` | `/persona/export?format=json\|md\|pdf` | Download the persona |
| `POST` | `/upload` | Parse a CV PDF and merge it into the persona |
| `GET` | `/jobs` | Filtered, semantically-ranked job feed; `discovering: true` while background discovery runs |
| `POST` | `/jobs/from-url` | Scrape a pasted job link into a job object |
| `POST` | `/jobs/save` | Bookmark a job into the tracker as `Saved` |
| `POST` | `/jobs/analyze` | SSE: fit + AI-risk analysis for one job |
| `POST` | `/jobs/cover-letter` | SSE: tailored cover letter |
| `POST` | `/jobs/tailored-cv` | SSE: tailored, structured CV |
| `POST` | `/apply` | SSE: browser application (fill → review → submit) |
| `POST` | `/browser-input/{session_id}` | Click/type/key/scroll/`submit`/`done`/`skip` into the live session |
| `GET` | `/browser-stream/{session_id}` | SSE: live JPEG frames (CDP screencast) |
| `GET` / `POST` | `/applications` | List / create tracked applications |
| `PATCH` | `/applications/{id}/status` | Update one of *your* applications' status + notes |
| `GET` / `POST` | `/onboarding/status`, `/onboarding/complete` | Onboarding state |
| `POST` | `/score-skills` | AI risk for all persona skills |
| `POST` | `/careers/roadmap` | SSE: skill-development roadmap |
| `POST` | `/documents/pdf` | Render a structured doc (or legacy text) to PDF |
| `POST` | `/documents/preview` | Render a structured doc to HTML for the live preview |
| `GET` | `/documents/{doc_id}/download` | Download a generated PDF |
| `GET` | `/health` | Liveness check |

---

## AI Exposure Risk Scoring

Scores are deterministic lookups against O\*NET data; the LLM only adds human-readable reasoning afterwards. `score_ai_risk` resolves each skill/title in this order (`agent.py`, `risk_scorer.py`):

1. **Curated exposure table** — a hand-tuned map of common tech skills and job titles.
2. **Keyword task search** — average penetration of all O\*NET tasks containing the term.
3. **TF-IDF semantic match** — cosine similarity against ~1 350 non-zero-penetration task descriptions; requires all content words to appear.
4. **O\*NET word-overlap** — stems and noise-strips the title, then matches the occupation with the most shared content words.
5. **Default 0.5** — neutral when no data differentiates.

Labels: **High ≥ 65 %**, **Medium 35–65 %**, **Low < 35 %**. **Job fit** (`score_job_fit`) is an LLM semantic analysis returning `fit_score` (0–100), `level_match` (`strong`/`ok`/`reach`), `matched_skills`, `skill_gaps` and a one-line rationale.

---

## Job Feed & Discovery

- **Search** (`jobs_db.get_jobs`) filters in SQL: free-text terms (the search box sends them as tags) must appear in title/company/description; role tags (`ml`, `backend`, …) match any; domain tags (`fintech`, `sponsorship`, …) must all match; location uses whole-word aliases (`uk`, `us`, …). Results are ranked by cosine similarity between your persona-plus-search embedding and each job's stored embedding (the 2 000 most recent matches are ranked), and jobs you've applied to or discarded are removed before pagination.
- **Discovery** (`discovery.py` → `job_searcher.py`) runs when page 1 is thin — in a background **worker process**, so the API stays responsive — with one run per query/location at a time and a 30-minute cooldown. Sources: Playwright scraping of curated career pages; Greenhouse / Ashby / Lever / Workable / SmartRecruiters public APIs (60+ companies); Brave `site:` search; Adzuna. If every source is empty it shows bundled fixture jobs, which are never stored.
- **Embeddings** are computed only for new jobs, in batched Ollama `/api/embed` calls.

---

## Browser Automation

`browser_agent.py` targets browser-use **0.11.13** (pinned — its API changes between minor versions):

- **Fill, then review** — the agent is told never to click the final submit button. When it's done you get the live view; `submit` runs a short follow-up agent that clicks it and checks for a confirmation, `done` records that you submitted it yourself, `skip` abandons it. Only a confirmed submission marks the application *Applied*.
- **Live view & takeover** — CDP screencast frames over a separate SSE endpoint; your clicks/typing/scrolling are replayed onto the page via CDP.
- **Credentials** — your job-site password is passed as browser-use `sensitive_data`: the model only ever sees `<secret>job_password</secret>`, and the real value is typed only on the job site's own host over HTTPS. The browser-use "judge" call is disabled because it sees unredacted step history.
- **Network limits** — the agent's browser can't open raw-IP URLs, `localhost` or the internal service hostnames.
- **CV upload** — the tailored CV PDF if you generated one, otherwise your uploaded original.

---

## Security & Privacy

| Control | Where |
|---|---|
| Required `JWT_SECRET` (no default) | `auth.py` |
| Job-site password encrypted at rest, never returned to the browser | `crypto.py`, `tracker.py`, `main.py` |
| Persona sent to LLMs is an allowlist — no credentials, DOB, contact details, diversity data or salary | `agent._llm_persona` |
| Server-side fetches of user-influenced URLs only reach public IPs, re-checked on every redirect | `net_guard.py` |
| Shared job descriptions can only be refreshed from the stored job's own URL | `main._ensure_full_description` |
| Application updates scoped to the owning user | `tracker.update_status` |
| Prompt-injection screening of uploaded CV text | `guardrails.py` |

---

## Frontend

**Stack:** Next.js 14 · React 18 · TypeScript · Tailwind CSS · dark theme.

**Pages:** `login`, `signup`, `onboarding`, `dashboard`, `jobs` (feed), `jobs/[id]` (analysis + documents + apply), `applications` (tracker), `careers` (risk + roadmap), `profile` (persona editor).

**Components:** `AppShell` / `Sidebar` (navigation), `JobCard`, `DocEditor` (structured CV/cover-letter editor with live preview), `BrowserView` (clickable live screencast).

---

## Data & Storage

| File | Description |
|---|---|
| `data/economic_index.json` | 756 O\*NET occupations → `overall_exposure` (0–1). Source: Anthropic Economic Index. |
| `data/task_penetration.csv` | ~18 000 O\*NET task descriptions → `penetration` score. |
| `api/app/jobs_fixture.json` | Mock job listings shown only when every live source is empty. |
| `applications.db` (SQLite, `/appdata`) | `users` (bcrypt password hashes, persona JSON, encrypted job-site password, onboarding flag) + `applications`. |
| `jobs.db` (SQLite, `/appdata`) | Cached jobs with semantic vectors; filled by discovery or `python -m app.job_sync`. |
| `/appdata/pdfs`, `/appdata/cvs` | Generated PDFs; each user's uploaded CV. |

---

## Development

**Tests** (`api/tests/`):

```bash
cd api
pip install -r requirements.txt -r requirements-dev.txt
pytest                      # fast suite — no network, LLM or browser
pytest -m browser           # real headless Chromium (needs: playwright install chromium)
```

CI (`.github/workflows/ci.yml`) runs both, plus a frontend type-check and build.

**Switching backend:** set `LLM_BACKEND` and the matching key (see above).

**Document templates:** `api/app/doc_render.py` + `api/app/templates/` (`registry.py`, `classic_cv.html`, `classic_letter.html`, `base.css`), rendered with Jinja2 → WeasyPrint (fpdf2 fallback).
