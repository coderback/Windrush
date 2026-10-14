from .job_searcher import search_jobs_multi

async def search_jobs(query: str, locations: list[str]) -> list[dict]:
    return await search_jobs_multi(query, locations)
