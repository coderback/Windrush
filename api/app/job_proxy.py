from .job_searcher import search_jobs_multi

async def search_jobs(query: str, location: str) -> list[dict]:
    return await search_jobs_multi(query, location)
