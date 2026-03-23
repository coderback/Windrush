# Windrush

AI career advisor that analyses CVs, scores AI automation exposure risk, finds matching jobs, generates cover letters, and autonomously submits applications via browser automation.

Built with Claude (Anthropic), browser-use, Next.js, and FastAPI.

---

## What it does

1. **Upload a CV (PDF)** — the system parses it into a structured profile
2. **AI Exposure Risk** — scores each skill and job title against the Anthropic Economic Index (O\*NET task penetration data across ~18 000 occupational tasks)
3. **Job Matching** — searches for relevant jobs and ranks them by a composite score: fit (skill overlap) + AI-safety (lower exposure = higher rank)
4. **Cover Letter** — generates a personalised 3-paragraph cover letter grounded in the CV and job description
5. **Browser Application** — autonomously fills and submits the application form using a headless Chrome agent; falls back to interactive user control if the agent gets stuck
6. **Skill Roadmap** — after submission, generates 6 AI-resilient skill development recommendations tailored to the candidate's industry and target role

---

## Architecture`

Five Docker services:

| Service | Stack | Role |
|---|---|---|
| `nginx` | nginx:alpine | Reverse proxy; disables SSE buffering |
| `frontend` | Next.js 14, React 18, TypeScript, Tailwind | UI |
| `api` | Python 3.13, FastAPI, Anthropic SDK, Playwright | Agent + browser automation |
| `jobs-mcp` | Python, FastMCP | MCP server wrapping the Adzuna Jobs API |
| `civic-guardrails` | Node.js, @civic/passthrough-mcp-server | MCP proxy with rate-limiting, injection detection, PII scrubbing, audit logging |

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- Anthropic API key
- Adzuna API credentials (free tier) — optional; fixture data is used by default

### 1. Clone and configure

```bash
git clone <repo>
cd windrush
cp .env.example .env
# Edit .env — minimum required:
#   ANTHROPIC_API_KEY=sk-ant-...
#   JOB_EMAIL=your@email.com
#   JOB_PASSWORD=yourpassword
```

### 2. Download data files

The economic index and task penetration data must be present in `./data/` before building:

```bash
# economic_index.json  — Anthropic Economic Index (O*NET occupation exposure scores)
# task_penetration.csv — O*NET task-level AI penetration scores (~18 000 rows)
```

### 3. Build and run

```bash
docker-compose up --build
```

Open [http://localhost](http://localhost).

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Powers the agent pipeline (claude-sonnet-4-6) and browser agent (claude-haiku-4-5) |
| `JOB_EMAIL` | Yes | Email credential passed to the browser agent for job site login |
| `JOB_PASSWORD` | Yes | Password credential (masked in SSE output) |
| `ADZUNA_APP_ID` | Optional | Adzuna API — only needed if switching from fixture to live job search |
| `ADZUNA_API_KEY` | Optional | Adzuna API key |
| `GROQ_API_KEY` | No | Legacy — no longer used |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/stream` | Upload CV PDF + location → SSE stream of pipeline events |
| `POST` | `/apply` | Trigger browser application → SSE stream of browser events + skill roadmap |
| `POST` | `/browser-input/{session_id}` | Send click/type/scroll/submit commands to the live browser session |
| `GET` | `/browser-stream/{session_id}` | SSE stream of live base64 JPEG frames from the browser (CDP screencast) |
| `GET` | `/guardrails/audit` | JSON array of all guardrail events logged in-process |
| `GET` | `/health` | Liveness check |

All long-running endpoints use **Server-Sent Events** — the frontend renders incrementally as each step completes.

---

## Agent Pipeline

The API uses Claude (`claude-sonnet-4-6`) in an agentic tool-use loop. The system prompt enforces this exact sequence:

```
extract_cv_profile  →  score_ai_risk  →  search_jobs
  →  score_job_fit  →  generate_cover_letter
```

After the user approves the application:

```
apply_with_browser  →  generate_skill_roadmap
```

**Tool execution dual-path:**
- SSE output → PII-redacted (emails, phones, postcodes, NI numbers replaced with `[email]`, `[phone]`, etc.)
- LLM context → unredacted (the agent needs real contact details to fill forms)

---

## AI Exposure Risk Scoring

Scores are computed without any neural network — purely deterministic lookups against O\*NET data.

**4-tier cascade for each skill:**

1. **Keyword task search** — average penetration of all O\*NET tasks containing the skill phrase (e.g. "machine learning" → 0.91). Unreliable for single-word tools; falls through.
2. **TF-IDF semantic match** — cosine similarity against 1 354 non-zero-penetration task descriptions; requires all content words to appear in the matched task.
3. **O\*NET word-overlap** — stems and noise-strips the job title, finds the O\*NET occupation with the most shared content words (e.g. "Graduate Software Engineer" → "Software Developers" → 0.288).
4. **Default 0.5** — returned when no data is available; treated as neutral, not high risk.

**Job composite score:**

```
composite = (1 − exposure) × 0.5 + fit_score × 0.5
```

`fit_score` = fraction of CV skills found in the job description. Jobs are ranked descending by composite score; top 4 are shown.

---

## Browser Automation

The browser agent uses [browser-use](https://github.com/browser-use/browser-use) with `claude-haiku-4-5` (fast, low-latency):

- **No vision** (`use_vision=False`) — agent reasons from DOM/accessibility tree, not screenshots. Significantly faster than vision mode.
- **CDP screencast** — live JPEG frames streamed to the frontend via a separate SSE endpoint at up to 30 fps, independent of the agent.
- **File upload** — the CV PDF temp path is passed as `available_file_paths` so the agent can attach it to upload fields directly.
- **Interactive fallback** — if the agent fails or when reviewing the completed form, the frontend becomes a clickable remote control: clicks are translated to page coordinates and dispatched via Playwright.

---

## Guardrails

Six layers of defence:

| Layer | Where | What |
|---|---|---|
| CV injection check | `main.py` (pre-pipeline) | 14 regex patterns detect prompt injection in uploaded CV text; blocks before LLM call |
| Tool input sanitisation | `guardrails.py` | Validates search queries (injection patterns, HTML tags), job URLs (must be `https?://`), strips credential field names from all tool inputs |
| PII redaction (SSE) | `guardrails.py` | Redacts emails, UK/intl phones, postcodes, NI numbers from SSE-streamed tool results |
| Credential masking (SSE) | `guardrails.py` | Replaces password/token/secret values with `***` in SSE tool_call events |
| MCP rate limiting | `civic-guardrails/server.js` | 30 requests/minute from the api container |
| MCP audit + PII scrub | `civic-guardrails/server.js` | Logs all MCP requests/responses to `/logs/audit.jsonl`; scrubs emails/phones from job description responses |

Guardrail events are surfaced in the UI as a flashing red shield badge and logged entries in the agent log.

---

## Frontend

**Stack:** Next.js 14 · React 18 · TypeScript · Tailwind CSS · IBM Plex Mono + Playfair Display · dark theme

**Key components:**

| Component | Purpose |
|---|---|
| `RiskRadar` | Horizontal bar chart of AI exposure % per skill; teal < 35%, amber ≥ 35% |
| `JobList` | Ranked job cards with composite score badges; "Apply" button triggers browser flow |
| `CoverLetter` | Modal for cover letter review + job site credential input before applying |
| `BrowserView` | Clickable live screenshot; click coordinates sent to `/browser-input` |
| `AgentLog` | Real-time log of tool calls, results, guardrail events, browser steps |
| `SkillRoadmap` | Timeline of 6 skill recommendations with action, resource, and timeline |
| `GuardrailBadge` | Persistent header badge; flashes red for 2 s when any guardrail fires |

---

## Data

| File | Size | Description |
|---|---|---|
| `data/economic_index.json` | ~3 MB | ~3 000 O\*NET occupation codes → `overall_exposure` (0–1). Source: Anthropic Economic Index. |
| `data/task_penetration.csv` | ~18 000 rows | O\*NET task descriptions → `penetration` score. Used by TF-IDF vectorizer and keyword search. |
| `api/app/jobs_fixture.json` | ~8 jobs | Mock job listings used instead of live Adzuna API calls. `exposure_score` computed on load. |

---

## Development Notes

**Switching from fixture to live Adzuna job search:**
In `api/app/job_proxy.py`, uncomment the Adzuna import and replace the `search_jobs` stub with the Adzuna HTTP call. The `jobs-mcp` server already implements the full Adzuna integration.

**Adding a new tool:**
1. Add the tool definition to `TOOLS` in `agent.py` (Anthropic format: `name`, `description`, `input_schema`)
2. Add a handler branch in `execute_tool()`
3. If the tool processes user data, add it to `_PII_REDACT_TOOLS` in `guardrails.py`

**Models in use:**

| Use case | Model |
|---|---|
| Agent pipeline (tool use, multi-turn) | `claude-sonnet-4-6` |
| CV parsing, cover letter, skill roadmap | `claude-sonnet-4-6` |
| Browser automation | `claude-haiku-4-5-20251001` |
