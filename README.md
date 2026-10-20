# Windrush

AI career advisor that analyses CVs, scores AI automation-exposure risk, finds matching jobs, generates tailored CVs and cover letters, and fills in job applications with a browser agent — which you review before anything is sent.

Built with FastAPI, Next.js, [browser-use](https://github.com/browser-use/browser-use), and a choice of LLM backend: Azure OpenAI, Anthropic Claude, Groq, or a local Ollama model.

---

## What it does

1. **Accounts & Persona** — sign up, then build a rich persona (contact details, preferences, skills, work history, education, projects, certifications, screening answers, behavioural stories, custom directives).
2. **Upload a CV (PDF)** — parsed into structured data and merged into your persona; the PDF is kept so the browser agent can attach it.
3. **AI Exposure Risk** — scores each skill and job title against the Anthropic Economic Index / O\*NET task-penetration data (~18 000 occupational tasks), with LLM-generated reasoning.
4. **Job Feed** — searches a local job store with real filters (search terms, role/domain tags, level, location, remote, visa sponsorship, experience asked for, degree requirement) and ranks results by semantic similarity to your persona. When results are thin, live discovery across job boards runs in the background and the feed fills in as it finishes.
5. **Paste any job link** — scrape an arbitrary listing into the same analysis flow.
6. **Per-job analysis** — fit score (LLM semantic match) and AI risk for a single role.
7. **Tailored CV + Cover Letter** — structured, ATS-aware documents with a live in-app preview and PDF export (HTML/CSS → WeasyPrint).
8. **Browser Application** — a headless Chrome agent fills the application form and **stops before the final submit**. You review it in a live view (and can take over with clicks/typing), then `submit`, `done` (you submitted it yourself) or `skip`.
9. **Application questions** — every screening question on a form is answered from your answer bank, then your persona; written ones ("Why us?", "A time when…") are drafted for the job and fact-checked. A fact nothing you've given states is never guessed: it's left blank, and what you answer in the review is saved for the next form.
10. **Skill Roadmap** — 6 AI-resilient skill-development recommendations for your industry and target role.
11. **Application Tracker** — every application through a status lifecycle (Saved → Pending Review → Evaluated → Applied → Responded → Interview → Offer → Rejected / Discarded).

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
| `azure` | the `AZURE_OPENAI_DEPLOYMENT` reasoning model (e.g. `gpt-6-luna`) via the `openai` SDK on Azure's v1 API | same deployment via browser-use's `ChatAzureOpenAI` | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT` |
| `claude` | `ANTHROPIC_MODEL` (default `claude-sonnet-4-6`) via the `anthropic` SDK | same model via browser-use's `ChatAnthropic` | `ANTHROPIC_API_KEY` |
| `groq` (compose default) | `GROQ_MODEL` (default `meta-llama/llama-4-scout-17b-16e-instruct`) | same model via browser-use's `ChatGroq` | `GROQ_API_KEY` |
| `ollama` | `OLLAMA_MODEL` (default `qwen3.5:4b`) | same model via browser-use's `ChatOllama` | local resources |

The Azure backend expects a reasoning model: it sends `max_completion_tokens` (the call's answer budget plus headroom for hidden reasoning, scaled by `AZURE_OPENAI_REASONING_EFFORT`) and `reasoning_effort`, and never `temperature`, `top_p` or `frequency_penalty`. With `LLM_BACKEND=azure` the API refuses to start if a required Azure variable is missing.

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

Open [http://localhost](http://localhost), create an account, and complete onboarding. The containers restart on their own after a reboot (as long as Docker starts with your computer), so scheduled collections and autopilot runs keep going. The app answers only on this computer; set `WINDRUSH_BIND=0.0.0.0` in `.env` to reach it from other devices on your network. The API collects jobs for every user's target titles and preferred locations every 6 hours (`JOB_COLLECT_HOURS`, `0` turns it off); to collect now, run `docker compose exec api python -m app.job_sync`.

Local (non-Docker) dev:

```bash
cd api && uvicorn app.main:app --reload      # needs the env vars above, the data files and a reachable Ollama
cd frontend && npm run dev                   # needs API_URL (below)
```

**Frontend without nginx** (`npm run dev`, Vercel): the browser calls `/api/*` on the frontend's own origin, and `frontend/src/app/api/[...path]/route.ts` forwards those calls to `API_URL`. Set it to the API's base URL — for local dev, put `API_URL=http://localhost:8000` in `frontend/.env` (git-ignored); on Vercel, add it to the project's environment variables. Without it every `/api/*` call returns 503. Under Docker Compose nginx routes `/api` straight to the API, so `API_URL` isn't needed. On Vercel, streamed responses (analysis, the apply session) end at the function duration limit.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `JWT_SECRET` | **Yes** | Signs login tokens |
| `CREDENTIALS_KEY` | **Yes** | Fernet key encrypting stored job-site passwords. Changing it makes saved passwords unreadable (users re-enter them) |
| `LLM_BACKEND` | No | `azure`, `claude`, `groq` (compose default) or `ollama` |
| `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_DEPLOYMENT` | For `azure` | Resource endpoint (`https://<resource>.openai.azure.com/`) / key / deployment name (used as the model) |
| `AZURE_OPENAI_REASONING_EFFORT` | No | `none`, `low` (default), `medium`, `high` or `xhigh` — trades latency and tokens for deliberation |
| `AZURE_OPENAI_API_VERSION` | No | API version for the browser agent's Azure client (default `2024-12-01-preview`) |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | For `claude` | Key / model id |
| `GROQ_API_KEY` / `GROQ_MODEL` | For `groq` | Key / model id |
| `OLLAMA_HOST` / `OLLAMA_MODEL` / `EMBEDDING_MODEL` | No | Ollama URL (compose: `http://ollama:11434`), local model, embedding model |
| `ADZUNA_APP_ID` / `ADZUNA_API_KEY` | Optional | Enables the Adzuna job source |
| `BRAVE_SEARCH_API_KEY` | Optional | Enables the Brave `site:` search job source |
| `ECONOMIC_INDEX_PATH` / `TASK_PENETRATION_PATH` | No | Data file paths (default `/data/...`) |
| `APP_DATA_PATH` | No | SQLite DBs, PDFs and uploaded CVs (compose: `/appdata`) |
| `JOB_ATTRIBUTES_LLM` | No | `1` / `0` turns the LLM reading of job ads (seniority, years, degree, sponsorship, clearance) on or off; by default it's on except with the local Ollama model |
| `SPONSOR_REGISTER_REFRESH` | No | `0` stops the weekly download of the Home Office register of licensed sponsors (the stored copy is still used) |
| `API_URL` | Frontend, without nginx | Base URL of the API that the frontend's `/api/*` proxy forwards to (e.g. `http://localhost:8000`). Set in the frontend's environment, not the root `.env`; not needed under Docker Compose |

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
| `GET` | `/jobs` | Filtered, semantically-ranked job feed; `discovering: true` while background discovery runs; `sponsorship=any\|possible\|likely`; `max_years=N` hides ads asking for more experience, `no_degree=true` ads requiring a degree (ads that don't say are kept) |
| `GET` / `PUT` | `/jobs/{id}/sponsorship` | What the ad and the sponsor register say about visa sponsorship / clearance; mark the job as sponsoring or not (your mark wins) |
| `POST` | `/jobs/from-url` | Scrape a pasted job link into a job object |
| `POST` | `/jobs/save` | Bookmark a job into the tracker as `Saved` |
| `POST` | `/jobs/analyze` | SSE: fit + AI-risk analysis for one job |
| `POST` | `/jobs/cover-letter` | SSE: tailored cover letter |
| `POST` | `/jobs/tailored-cv` | SSE: tailored, structured CV |
| `POST` | `/apply` | SSE: browser application (fill → review → submit) |
| `POST` | `/browser-input/{session_id}` | Click/type/key/scroll/`submit`/`done`/`skip` into the live session, or `{type: answers}` to put answers you gave in the review on the form |
| `GET` | `/browser-stream/{session_id}` | SSE: live JPEG frames (CDP screencast) |
| `GET` / `POST` | `/applications` | List / create tracked applications |
| `PATCH` | `/applications/{id}/status` | Update one of *your* applications' status + notes |
| `GET` / `POST` | `/onboarding/status`, `/onboarding/complete` | Onboarding state |
| `POST` | `/score-skills` | AI risk for all persona skills |
| `POST` | `/careers/roadmap` | SSE: skill-development roadmap |
| `POST` | `/documents/pdf` | Render a structured doc (or legacy text) to PDF |
| `POST` | `/documents/preview` | Render a structured doc to HTML for the live preview |
| `GET` | `/documents/{doc_id}/download` | Download a generated PDF |
| `GET` / `POST` | `/answers` | Your answer bank / save an answer (`kind` fact or written; kept for one employer only when it names it) |
| `PUT` / `DELETE` | `/answers/{id}` | Change / delete a saved answer |
| `POST` | `/answers/draft` | Answer a job's application questions as the agent would (saved, profile, drafted or needs_you); nothing is saved |
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

- **Search** (`jobs_db.get_jobs`) filters in SQL: every word of a free-text term (the search box sends them as tags) must appear in title/company/description as a word, in any of its forms (`ml` / machine learning, quant / quantitative, front end / frontend, …); role tags (`ml`, `backend`, …) match any; domain tags (`fintech`, `sponsorship`, …) must all match; location uses whole-word aliases (`uk`, `us`, …). Results are ranked by cosine similarity between your persona-plus-search embedding and each job's stored embedding (the 2 000 most recent matches are ranked), nudged up for your search words in the title, jobs at your level, sponsoring employers when you need sponsorship, and new jobs; jobs you've applied to or discarded are removed before pagination.
- **Collection and discovery** (`discovery.py` → `job_searcher.py`) run in a background **worker process**, so the API stays responsive: a scheduled collection for everyone's target titles every 6 hours, and a search when page 1 is thin (one run per query/location at a time, 30-minute cooldown). Sources: Playwright scraping of curated career pages; Greenhouse / Ashby / Lever / Workable / SmartRecruiters public APIs (~110 listed companies, plus boards found automatically for employers the other sources name, checked weekly and dropped when gone); Brave `site:` search, once a day; Adzuna (UK-wide and its graduate category) and Workable's job board. If every source is empty it shows bundled fixture jobs, which are never stored.
- **Embeddings** are computed only for new jobs, in batched Ollama `/api/embed` calls.
- **Visa sponsorship** — each ad is read for what it says (`sponsorship.py`: offered / ruled out, e.g. "we are unable to sponsor", "without sponsorship", "UK nationals only", with the deciding sentence kept as evidence) and for SC / DV security clearance, which usually needs years of UK residence. The employer is matched against the Home Office **register of licensed sponsors** (Skilled Worker route), downloaded weekly from gov.uk (`sponsor_register.py`); a licence means it *can* sponsor, so an ad that rules it out still wins. The feed's sponsorship filter: `possible` hides jobs that rule a sponsored candidate out, `likely` keeps only those that offer it or whose employer is licensed; it defaults to `possible` when your profile says you need sponsorship. You can mark any job as sponsoring or not, and your mark wins. Snippet-only listings often say nothing; opening a job fetches the full ad and re-reads it.
- **LLM-read attributes** — a background task (`job_attributes.py`) reads each new job ad, and each full ad once fetched, with one LLM call: seniority, the minimum years of experience, the degree requirement, sponsorship and clearance. On a blind, hand-labelled set of 470 titles / ads its seniority was right ~96% of the time against the regex's 88.3% (senior recall 97% vs 81%), so it sets the stored level. For sponsorship and clearance the model must quote the deciding sentence, and a quote that isn't in the ad is ignored, so the regex readers stay as the fallback; clearance takes the stricter of the two. A job the model keeps failing on is left with its regex values after three tries. Cards show the years asked for and whether a degree is required, and the feed can filter on both.

---

## Browser Automation

`browser_agent.py` targets browser-use **0.11.13** (pinned — its API changes between minor versions):

- **Fill, then review** — the agent is told never to click the final submit button. When it's done you get the live view; `submit` runs a short follow-up agent that clicks it and checks for a confirmation, `done` records that you submitted it yourself, `skip` abandons it. Only a confirmed submission marks the application *Applied*.
- **Live view & takeover** — CDP screencast frames over a separate SSE endpoint; your clicks/typing/scrolling are replayed onto the page via CDP.
- **Credentials** — your job-site password is passed as browser-use `sensitive_data` to both the fill and the submit agent: the models only ever see `<secret>job_password</secret>` (also when the page copies the typed value into its HTML). The real value is only ever *typed* (`input`) into a field whose own document is on the job site's host over HTTPS — not into an iframe from elsewhere; any other action carrying the placeholder (navigate, evaluate, done…) is refused rather than substituted, so a prompt-injected page can't send it to another site. While a run is active the password is masked in browser-use's and the app's log lines, and text you type during takeover is echoed back only as a character count. The browser-use "judge" call is disabled because it sees unredacted step history.
- **No telemetry** — browser-use's product telemetry (PostHog) and cloud sync default to on and would send each run's task prompt, actions and visited URLs to browser-use; `browser_agent.py` defaults `ANONYMIZED_TELEMETRY` / `BROWSER_USE_CLOUD_SYNC` to `false` and `docker-compose.yml` sets both.
- **Network limits** — the agent's browser can't open raw-IP URLs, `localhost` or the internal service hostnames.
- **CV upload** — the tailored CV PDF if you generated one, otherwise your uploaded original.
- **Questions** — the agent isn't given facts to answer from. It sends each page's questions to an `answer_questions` action (`answers.py`), which answers from your saved answers, then your persona, and drafts written ones, and says where each answer came from. A model maps each question to the fact that answers it, but the value comes from the fact, and code checks the reading (a cited fact, one of the form's options, a yes/no fact's direction, a UK fact not used for another country). Contact details, salary and equality answers reach that model only as "this fact exists". Questions nothing answers are left blank and listed first in the review, which shows every answer and its source. What you answer there is saved, and while the browser is paused a short follow-up agent puts it on the form (like the one that clicks submit, it never sends the form). A salary question with bands gets the one band that holds your figure; on a boundary it's left for you.

---

## Security & Privacy

| Control | Where |
|---|---|
| Required `JWT_SECRET` (no default) | `auth.py` |
| Job-site password encrypted at rest, never returned to the browser | `crypto.py`, `tracker.py`, `main.py` |
| Job-site password only typed into the job site's own fields, masked in prompts and logs; browser-use telemetry off | `browser_agent.py` |
| Persona sent to the writing, scoring and question-reading LLM calls is an allowlist — no credentials, DOB, contact details, diversity data or salary | `agent._llm_persona`, `answers.py` |
| The form-filling agent (also an LLM) is given what forms ask for: name, contact details and DOB in its task, salary and equality answers only when a question asks; never the job-site password | `browser_agent.py` |
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
| `jobs.db` (SQLite, `/appdata`) | Cached jobs with semantic vectors, filled by the scheduled collection and the feed's discovery; jobs no source has listed for 3 days are expired. Also the collection runs and the sponsor register. |
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

The CV and cover-letter PDF tests need WeasyPrint's Pango libraries; where those are missing (Windows) they skip, except in CI. To run them locally, use the API image: `docker run --rm -v "$PWD/api:/app" -w /app windrush-api sh -c "pip install -r requirements-dev.txt && pytest tests/test_documents.py"`.

**Model evaluation** (`api/evals/`) scores the LLM's reading of job ads (seniority, sponsorship) against labelled data, so a prompt or model change that makes it worse shows up. It calls the real LLM (about 500 calls, a few minutes), so it only runs when asked for:

```bash
cd api && set -a && . ../.env && set +a
WINDRUSH_LLM_EVAL=1 pytest evals -s   # -s prints the scores; per-item answers go to evals/last_run.json
```

`evals/test_answers_eval.py` puts 40 real application questions to a test persona with an answer bank. It fails if a fact is answered outside its labelled answers (a guess, a wrong option, a UK fact used for the US), a draft keeps an unsupported claim, or a private value reaches the model.

**Frontend smoke tests** (`frontend/e2e/`) drive the built app in Chromium with the API mocked:

```bash
cd frontend
npm run build && npx playwright install chromium
npm run test:e2e
```

CI (`.github/workflows/ci.yml`) runs the API suite, the browser suite, the frontend type-check, build and smoke tests, and checks the Docker config. The model evaluation is not in CI.

**Switching backend:** set `LLM_BACKEND` and the matching key (see above).

**Document templates:** `api/app/doc_render.py` + `api/app/templates/` (`registry.py`, `classic_cv.html`, `classic_letter.html`, `base.css`), rendered with Jinja2 → WeasyPrint (fpdf2 fallback).
