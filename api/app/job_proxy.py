import os
import httpx
from .risk_scorer import occupation_exposure

ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_API_KEY = os.environ.get("ADZUNA_API_KEY", "")
ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/gb/search/1"

# Fixture fallback — used when Adzuna credentials are absent or request fails
_RAW_JOBS = [
    {
        "job_id": "j1",
        "title": "Climate Project Manager",
        "company": "Arup",
        "location": "London",
        "description": "Lead climate resilience projects across urban infrastructure. Strong project management, stakeholder engagement, and sustainability expertise required.",
        "url": "https://www.arup.com/careers",
        "_onet_hint": "construction managers",
    },
    {
        "job_id": "j2",
        "title": "Data & AI Strategy Consultant",
        "company": "Deloitte",
        "location": "London",
        "description": "Help clients navigate AI transformation. Blend of data strategy, change management, and technical communication.",
        "url": "https://www.deloitte.com/uk/careers",
        "_onet_hint": "management analysts",
    },
    {
        "job_id": "j3",
        "title": "Community Engagement Lead",
        "company": "Greater London Authority",
        "location": "London",
        "description": "Design and deliver community engagement programmes for city-wide initiatives. Strong communication and facilitation skills essential.",
        "url": "https://www.london.gov.uk/about-us/jobs",
        "_onet_hint": "social and community service managers",
    },
    {
        "job_id": "j4",
        "title": "Policy Analyst — Future of Work",
        "company": "IPPR",
        "location": "London",
        "description": "Research and policy analysis on automation, labour markets, and equitable transition. Economics or social science background preferred.",
        "url": "https://www.ippr.org/join-us",
        "_onet_hint": "economists",
    },
    {
        "job_id": "j5",
        "title": "Machine Learning Engineer",
        "company": "Monzo",
        "location": "London",
        "description": "Build ML systems for financial products. Python, PyTorch, and cloud deployment experience required.",
        "url": "https://monzo.com/careers",
        "_onet_hint": "software developers",
    },
]

FIXTURE = [
    {k: v for k, v in job.items() if k != "_onet_hint"} | {
        "exposure_score": round(occupation_exposure(job["_onet_hint"]), 3)
    }
    for job in _RAW_JOBS
]


_BROAD_LOCATIONS = {"united kingdom", "uk", "england", "britain", "great britain"}


def _normalise_location(location: str) -> str:
    """Map overly broad UK regions to London so Adzuna finds results."""
    if location.lower().strip() in _BROAD_LOCATIONS:
        return "London"
    return location


async def search_jobs(query: str, location: str) -> list[dict]:
    location = _normalise_location(location)
    if ADZUNA_APP_ID and ADZUNA_API_KEY:
        try:
            jobs = await _fetch_adzuna(query, location)
            if jobs:
                return jobs
        except Exception:
            pass
    return FIXTURE


async def _fetch_adzuna(query: str, location: str) -> list[dict]:
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_API_KEY,
        "what": query,
        "where": location,
        "results_per_page": 5,
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(ADZUNA_BASE, params=params)
        resp.raise_for_status()
        data = resp.json()

    seen = set()
    jobs = []
    for item in data.get("results", []):
        title = item.get("title", "")
        company = item.get("company", {}).get("display_name", "Unknown")
        dedup_key = (title.lower(), company.lower())
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        jobs.append({
            "job_id": item.get("id", ""),
            "title": title,
            "company": company,
            "location": item.get("location", {}).get("display_name", location),
            "description": item.get("description", "")[:500],
            "url": item.get("redirect_url", ""),
            "salary_min": item.get("salary_min"),
            "salary_max": item.get("salary_max"),
            "exposure_score": round(occupation_exposure(title), 3),
        })
    return jobs
