import httpx
from .risk_scorer import occupation_exposure

# Exposure scores are looked up from the Anthropic Economic Index at import time.
# The closest ONET occupation match is used for each job title.
_RAW_JOBS = [
    {
        "job_id": "j1",
        "title": "Climate Project Manager",
        "company": "Arup",
        "location": "London",
        "description": "Lead climate resilience projects across urban infrastructure. Strong project management, stakeholder engagement, and sustainability expertise required.",
        "url": "https://www.arup.com/careers",
        # ONET: Construction Managers (11-9021) or General and Operations Managers (11-1021)
        "_onet_hint": "construction managers",
    },
    {
        "job_id": "j2",
        "title": "Data & AI Strategy Consultant",
        "company": "Deloitte",
        "location": "London",
        "description": "Help clients navigate AI transformation. Blend of data strategy, change management, and technical communication.",
        "url": "https://www.deloitte.com/uk/careers",
        # ONET: Management Analysts (13-1111)
        "_onet_hint": "management analysts",
    },
    {
        "job_id": "j3",
        "title": "Community Engagement Lead",
        "company": "Greater London Authority",
        "location": "London",
        "description": "Design and deliver community engagement programmes for city-wide initiatives. Strong communication and facilitation skills essential.",
        "url": "https://www.london.gov.uk/about-us/jobs",
        # ONET: Social and Community Service Managers (11-9151)
        "_onet_hint": "social and community service managers",
    },
    {
        "job_id": "j4",
        "title": "Policy Analyst — Future of Work",
        "company": "IPPR",
        "location": "London",
        "description": "Research and policy analysis on automation, labour markets, and equitable transition. Economics or social science background preferred.",
        "url": "https://www.ippr.org/join-us",
        # ONET: Political Scientists (19-3094) or Economists (19-3011)
        "_onet_hint": "economists",
    },
    {
        "job_id": "j5",
        "title": "Machine Learning Engineer",
        "company": "Monzo",
        "location": "London",
        "description": "Build ML systems for financial products. Python, PyTorch, and cloud deployment experience required.",
        "url": "https://monzo.com/careers",
        # ONET: Software Developers (15-1252) — closest available
        "_onet_hint": "software developers",
    },
]

FIXTURE = [
    {k: v for k, v in job.items() if k != "_onet_hint"} | {
        "exposure_score": round(occupation_exposure(job["_onet_hint"]), 3)
    }
    for job in _RAW_JOBS
]


async def search_jobs(query: str, location: str) -> list[dict]:
    try:
        return await _fetch_indeed(query, location)
    except Exception:
        return FIXTURE


async def _fetch_indeed(query: str, location: str) -> list[dict]:
    # Attempt host bridge on port 8099 (optional setup)
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(
            "http://host.docker.internal:8099/search",
            params={"q": query, "l": location},
        )
        resp.raise_for_status()
        return resp.json()
