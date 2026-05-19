import asyncio
import logging
import os
import re
from . import job_searcher
from . import jobs_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("windrush.job_sync")

def infer_level(title: str) -> str:
    t = title.lower()
    if any(w in t for w in ["junior", "graduate", "entry", "associate", "intern"]):
        return "junior"
    elif any(w in t for w in ["senior", "lead", "principal", "staff", "manager", "head"]):
        return "senior"
    return "mid"

async def sync_jobs():
    jobs_db.init_db()
    
    queries = [
        "software engineer", 
        "data scientist", 
        "machine learning engineer", 
        "devops engineer",
        "frontend engineer",
        "backend engineer"
    ]
    
    all_jobs = []
    
    for query in queries:
        logger.info(f"Syncing jobs for query: {query}")
        
        l2 = await job_searcher._search_level2_ats_apis(query)
        l4 = await job_searcher._search_level4_adzuna(query, "London")
        l4_sf = await job_searcher._search_level4_adzuna(query, "San Francisco")
        
        for job in l2:
            job["source"] = "ats"
        for job in l4 + l4_sf:
            job["source"] = "adzuna"
            
        all_jobs.extend(l2 + l4 + l4_sf)

    logger.info("Syncing jobs from web search (Level 3)")
    l3 = await job_searcher._search_level3_websearch()
    for job in l3:
        job["source"] = "brave"
        all_jobs.append(job)
        
    for job in all_jobs:
        job["level"] = infer_level(job["title"])
        
    deduped = job_searcher._deduplicate(all_jobs)
    
    added = jobs_db.add_jobs(deduped)
    logger.info(f"Sync complete. Added {added} new jobs.")

if __name__ == "__main__":
    asyncio.run(sync_jobs())
