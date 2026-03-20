import httpx

FIXTURE = [
    {
        "job_id": "j1",
        "title": "Climate Project Manager",
        "company": "Arup",
        "location": "London",
        "description": "Lead climate resilience projects across urban infrastructure. Strong project management, stakeholder engagement, and sustainability expertise required.",
        "url": "https://www.arup.com/careers",
        "exposure_score": 0.25,
    },
    {
        "job_id": "j2",
        "title": "Data & AI Strategy Consultant",
        "company": "Deloitte",
        "location": "London",
        "description": "Help clients navigate AI transformation. Blend of data strategy, change management, and technical communication.",
        "url": "https://www.deloitte.com/uk/careers",
        "exposure_score": 0.40,
    },
    {
        "job_id": "j3",
        "title": "Community Engagement Lead",
        "company": "Greater London Authority",
        "location": "London",
        "description": "Design and deliver community engagement programmes for city-wide initiatives. Strong communication and facilitation skills essential.",
        "url": "https://www.london.gov.uk/about-us/jobs",
        "exposure_score": 0.20,
    },
    {
        "job_id": "j4",
        "title": "Policy Analyst — Future of Work",
        "company": "IPPR",
        "location": "London",
        "description": "Research and policy analysis on automation, labour markets, and equitable transition. Economics or social science background preferred.",
        "url": "https://www.ippr.org/join-us",
        "exposure_score": 0.30,
    },
    {
        "job_id": "j5",
        "title": "Machine Learning Engineer",
        "company": "Monzo",
        "location": "London",
        "description": "Build ML systems for financial products. Python, PyTorch, and cloud deployment experience required.",
        "url": "https://monzo.com/careers",
        "exposure_score": 0.60,
    },
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
