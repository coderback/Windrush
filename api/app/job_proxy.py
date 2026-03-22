import json
import pathlib
from .risk_scorer import occupation_exposure

# Adzuna integration commented out — using scraped fixture from job_links.json
# import os, httpx
# ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
# ADZUNA_API_KEY = os.environ.get("ADZUNA_API_KEY", "")

_FIXTURE_PATH = pathlib.Path(__file__).parent / "jobs_fixture.json"

def _load_fixture() -> list[dict]:
    jobs = json.loads(_FIXTURE_PATH.read_text())
    for job in jobs:
        if "exposure_score" not in job:
            job["exposure_score"] = round(occupation_exposure(job["title"]), 3)
    return jobs

FIXTURE = _load_fixture()


async def search_jobs(query: str, location: str) -> list[dict]:
    return FIXTURE
