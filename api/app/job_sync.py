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
    
    # Record the time the sync started for the heartbeat purge
    sync_start = jobs_db._now()
    
    queries = [
        "software engineer", 
        "data scientist", 
        "machine learning engineer",
        "ai engineer",
        "quantitative developer",
        "devops engineer",
        "frontend engineer",
        "backend engineer",
        "full stack engineer",
        "ios developer",
        "android developer",
        "data engineer",
        "security engineer",
        "qa engineer",
        "technology analyst",
        "cloud engineer"
    ]
    
    all_jobs = []
    
    logger.info("Syncing Level 1 custom career pages (Playwright)")
    # Extract keywords from all queries for a broad Level 1 search
    all_keywords = []
    for q in queries:
        all_keywords.extend(job_searcher._query_keywords(q))
    unique_keywords = list(set(all_keywords))
    l1 = await job_searcher._search_level1_playwright(unique_keywords)
    for job in l1:
        job["source"] = "ats"  # Treat custom pages as ATS-like for retention
    all_jobs.extend(l1)

    logger.info("Syncing Level 2 ATS APIs (Single Pass Extraction)")
    l2 = await job_searcher._search_level2_ats_apis(queries)
    for job in l2:
        job["source"] = "ats"
    all_jobs.extend(l2)
    
    for query in queries:
        logger.info(f"Syncing Level 4 aggregators for query: {query}")
        
        l4 = await job_searcher._search_level4_adzuna(query, "London")
        l4_sf = await job_searcher._search_level4_adzuna(query, "San Francisco")
        
        l4_workable = await job_searcher._search_level4_workable(query, "London, United Kingdom")
        
        for job in l4 + l4_sf:
            job["source"] = "adzuna"
        for job in l4_workable:
            job["source"] = "workable"
            
        all_jobs.extend(l4 + l4_sf + l4_workable)

    logger.info("Syncing jobs from web search (Level 3)")
    l3 = await job_searcher._search_level3_websearch()
    for job in l3:
        job["source"] = "brave"
        all_jobs.append(job)
        
    for job in all_jobs:
        job["level"] = infer_level(job["title"])
        
    deduped = job_searcher._deduplicate(all_jobs)
    
    added, refreshed = jobs_db.add_jobs(deduped)
    logger.info(f"Sync complete. Added {added} new jobs, refreshed {refreshed} existing.")
    
    # Purge any dynamic jobs that were not refreshed in this run
    jobs_db.purge_expired_jobs(sync_start)

if __name__ == "__main__":
    asyncio.run(sync_jobs())
