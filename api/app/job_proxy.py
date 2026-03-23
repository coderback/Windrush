import json
import os
import pathlib

import httpx

from .risk_scorer import occupation_exposure

ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_API_KEY = os.environ.get("ADZUNA_API_KEY", "")
ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/gb/search/1"

_FIXTURE_PATH = pathlib.Path(__file__).parent / "jobs_fixture.json"


def _load_fixture() -> list[dict]:
    jobs = json.loads(_FIXTURE_PATH.read_text())
    for job in jobs:
        if "exposure_score" not in job:
            job["exposure_score"] = round(occupation_exposure(job["title"]), 3)
    return jobs


FIXTURE = _load_fixture()


async def search_jobs(query: str, location: str) -> list[dict]:
    if ADZUNA_APP_ID and ADZUNA_API_KEY:
        try:
            params = {
                "app_id": ADZUNA_APP_ID,
                "app_key": ADZUNA_API_KEY,
                "what": query,
                "where": location,
                "results_per_page": 8,
                "content-type": "application/json",
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(ADZUNA_BASE, params=params)
                resp.raise_for_status()
                data = resp.json()
            jobs = []
            for item in data.get("results", []):
                title = item.get("title", "")
                jobs.append({
                    "job_id": str(item.get("id", "")),
                    "title": title,
                    "company": item.get("company", {}).get("display_name", "Unknown"),
                    "location": item.get("location", {}).get("display_name", location),
                    "description": item.get("description", "")[:400],
                    "url": item.get("redirect_url", ""),
                    "salary_min": item.get("salary_min"),
                    "salary_max": item.get("salary_max"),
                    "exposure_score": round(occupation_exposure(title), 3),
                })
            if jobs:
                return jobs
        except Exception:
            pass  # fall through to fixture
    return FIXTURE
