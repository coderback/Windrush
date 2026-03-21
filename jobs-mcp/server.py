"""
Windrush Jobs MCP Server — wraps the Adzuna API.
Exposes a single `search_jobs` tool the Windrush agent calls via mcp_servers.
"""
import os
import httpx
from mcp.server.fastmcp import FastMCP

ADZUNA_APP_ID = os.environ["ADZUNA_APP_ID"]
ADZUNA_API_KEY = os.environ["ADZUNA_API_KEY"]
ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/gb/search/1"

mcp = FastMCP("windrush-jobs")


@mcp.tool()
async def search_jobs(query: str, location: str, results: int = 8) -> list[dict]:
    """Search for live UK job listings on Adzuna matching the query and location.

    Args:
        query: Job title or keywords (e.g. 'machine learning engineer pytorch')
        location: City or region (e.g. 'London')
        results: Number of listings to return (default 8, max 15)

    Returns:
        List of job objects with id, title, company, location, description, url, salary
    """
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_API_KEY,
        "what": query,
        "where": location,
        "results_per_page": min(results, 15),
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(ADZUNA_BASE, params=params)
        resp.raise_for_status()
        data = resp.json()

    jobs = []
    for item in data.get("results", []):
        jobs.append({
            "job_id": item.get("id", ""),
            "title": item.get("title", ""),
            "company": item.get("company", {}).get("display_name", "Unknown"),
            "location": item.get("location", {}).get("display_name", location),
            "description": item.get("description", "")[:400],
            "url": item.get("redirect_url", ""),
            "salary_min": item.get("salary_min"),
            "salary_max": item.get("salary_max"),
        })

    return jobs


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
