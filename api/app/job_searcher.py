"""
Multi-source job discovery for Windrush — career-ops style 4-level pipeline.

Level 1 — Playwright direct scraping of custom career pages (real-time)
Level 2 — Greenhouse / Ashby / Lever public JSON APIs (fast, structured)
Level 3 — Brave Search API with site: filters (broad discovery)
Level 4 — Adzuna paid API (supplemental)

All levels run concurrently. Results are title-filtered, deduplicated,
seniority-boosted, and capped at 20. Falls back to fixture if all sources
return zero results.
"""
import asyncio
import logging
import os
import re
import pathlib
import json

import httpx

from .risk_scorer import occupation_exposure

logger = logging.getLogger("windrush.job_searcher")

# ── Credentials ───────────────────────────────────────────────────────────────

ADZUNA_APP_ID  = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_API_KEY = os.environ.get("ADZUNA_API_KEY", "")
ADZUNA_BASE    = "https://api.adzuna.com/v1/api/jobs/gb/search/1"
BRAVE_API_KEY  = os.environ.get("BRAVE_SEARCH_API_KEY", "")

# ── Helpers ───────────────────────────────────────────────────────────────────

_SENIORITY_WORDS = re.compile(
    r"\b(graduate|junior|senior|lead|principal|staff|head of)\b", re.I
)
_BOOLEAN_OPS = re.compile(r"\b(or|and|not)\b", re.I)

_FIXTURE_PATH = pathlib.Path(__file__).parent / "jobs_fixture.json"

# Regex to parse "Title @ Company" / "Title at Company" / "Title | Company"
# from search snippet titles
_TITLE_SEP = re.compile(r"(.+?)(?:\s*[@|—–-]\s*|\s+at\s+)(.+?)$", re.I)


def _load_fixture() -> list[dict]:
    jobs = json.loads(_FIXTURE_PATH.read_text())
    for job in jobs:
        if "exposure_score" not in job:
            job["exposure_score"] = round(occupation_exposure(job["title"]), 3)
    return jobs


_FIXTURE: list[dict] = _load_fixture()


def _score_and_shape(raw: dict) -> dict:
    if "exposure_score" not in raw:
        raw["exposure_score"] = round(occupation_exposure(raw.get("title", "")), 3)
    return raw


def _query_keywords(query: str) -> list[str]:
    stop = {"a", "an", "the", "and", "or", "for", "in", "at", "of", "to", "with"}
    words = re.sub(r"[^a-z0-9\s]", " ", query.lower()).split()
    return [w for w in words if w not in stop and len(w) > 2]


def _title_matches_query(title: str, keywords: list[str]) -> bool:
    title_lower = title.lower()
    return any(kw in title_lower for kw in keywords)


# ── Title filter (from career-ops/portals.yml) ────────────────────────────────

_POSITIVE_KW: list[str] = [
    # AI/ML roles
    "AI", "ML", "Machine Learning", "LLM", "Agent", "Agentic", "GenAI",
    "Generative AI", "NLP", "LLMOps", "MLOps", "Computer Vision", "Data Science",
    # Software Engineering
    "Software Engineer", "Software Developer", "Backend Engineer",
    "Full Stack", "Full-Stack", "Python Developer", "Python Engineer",
    # DevOps / Infra
    "DevOps", "Platform Engineer", "Cloud Engineer", "Infrastructure Engineer",
    "Site Reliability", "SRE", "Kubernetes", "CI/CD",
    # Early careers
    "Graduate", "Junior", "Entry Level", "Associate Engineer", "Trainee Engineer",
]

_NEGATIVE_KW: list[str] = [
    "Intern", ".NET", "Java ", "iOS", "Android", "PHP", "Ruby",
    "Embedded", "Firmware", "FPGA", "ASIC", "Blockchain", "Web3",
    "Salesforce Admin", "SAP ", "Oracle EBS", "Mainframe", "COBOL",
    "Senior", "Staff", "Principal", "Lead", "Head of", "Director", "VP ",
]

_SENIORITY_BOOST_KW: list[str] = ["Graduate", "Junior", "Entry Level", "Associate"]


def _passes_title_filter(title: str) -> bool:
    """At least 1 positive keyword must match AND 0 negative keywords must match."""
    t = title.lower()
    has_positive = any(kw.lower() in t for kw in _POSITIVE_KW)
    has_negative = any(kw.lower() in t for kw in _NEGATIVE_KW)
    return has_positive and not has_negative


def _seniority_score(title: str) -> int:
    """Count seniority-boost keywords in title (used for sort priority)."""
    t = title.lower()
    return sum(1 for kw in _SENIORITY_BOOST_KW if kw.lower() in t)


# ── Level 1: Playwright scraping of custom career pages ───────────────────────
#
# These companies use custom career pages not covered by Greenhouse/Ashby/Lever
# APIs. We scrape them with a shared headless Chromium browser.

_CUSTOM_COMPANIES: list[tuple[str, str]] = [
    # (careers_url, display_name)
    ("https://openai.com/careers",                    "OpenAI"),
    ("https://www.revolut.com/en-GB/careers",         "Revolut"),
    ("https://monzo.com/careers",                     "Monzo"),
    ("https://retool.com/careers",                    "Retool"),
    ("https://www.talkdesk.com/careers",              "Talkdesk"),
    ("https://www.twilio.com/en-us/company/jobs",     "Twilio"),
    ("https://www.dialpad.com/careers",               "Dialpad"),
    ("https://www.gong.io/careers",                   "Gong"),
    ("https://careers.salesforce.com",                "Salesforce"),
    ("https://faculty.ai/careers",                    "Faculty AI"),
]

_L1_BATCH_SIZE = 4  # concurrent pages per browser session


async def _scrape_one_page(page, url: str, company: str, keywords: list[str]) -> list[dict]:
    """Navigate to url, extract <a> links whose text matches keywords."""
    try:
        await page.goto(url, wait_until="networkidle", timeout=15_000)
        links = await page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({href: e.href, text: (e.innerText || e.textContent || '').trim()}))",
        )
        jobs = []
        seen_hrefs: set[str] = set()
        for link in links:
            title = re.sub(r"\s+", " ", link.get("text", "")).strip()
            href  = link.get("href", "").strip()
            if not title or not href or href in seen_hrefs:
                continue
            if len(title) < 5 or len(title) > 120:
                continue
            if not _title_matches_query(title, keywords):
                continue
            seen_hrefs.add(href)
            jobs.append({
                "job_id": f"l1-{abs(hash(href)) % 10**8}",
                "title": title,
                "company": company,
                "location": "See listing",
                "description": "",
                "url": href,
                "salary_min": None,
                "salary_max": None,
                "exposure_score": round(occupation_exposure(title), 3),
            })
        return jobs
    except Exception as exc:
        logger.debug("Level 1 scrape failed for %s (%s): %s", company, url, exc)
        return []


async def _search_level1_playwright(keywords: list[str]) -> list[dict]:
    """
    Launch a single shared Chromium browser, visit each custom career page
    in batches of _L1_BATCH_SIZE concurrent tabs, and extract matching links.
    """
    if not keywords:
        return []

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Level 1: playwright not installed, skipping")
        return []

    all_jobs: list[dict] = []

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-gpu",
                ],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )

            # Process in batches to avoid opening too many tabs at once
            for i in range(0, len(_CUSTOM_COMPANIES), _L1_BATCH_SIZE):
                batch = _CUSTOM_COMPANIES[i : i + _L1_BATCH_SIZE]
                pages = [await context.new_page() for _ in batch]
                results = await asyncio.gather(
                    *[_scrape_one_page(pages[j], url, name, keywords)
                      for j, (url, name) in enumerate(batch)],
                    return_exceptions=True,
                )
                for page in pages:
                    try:
                        await page.close()
                    except Exception:
                        pass
                for r in results:
                    if isinstance(r, list):
                        all_jobs.extend(r)

            await browser.close()

    except Exception as exc:
        logger.warning("Level 1: browser session failed: %s", exc)

    logger.info("Level 1 (Playwright): %d jobs from %d custom pages",
                len(all_jobs), len(_CUSTOM_COMPANIES))
    return all_jobs


# ── Level 2: ATS public JSON APIs ────────────────────────────────────────────
#
# Greenhouse, Ashby, and Lever all expose free unauthenticated JSON APIs.
# Company list expanded from career-ops/portals.yml (59 companies total).

_GREENHOUSE_COMPANIES: list[tuple[str, str]] = [
    # existing
    ("anthropic",        "Anthropic"),
    ("polyai",           "PolyAI"),
    ("parloa",           "Parloa"),
    ("intercom",         "Intercom"),
    ("humeai",           "Hume AI"),
    ("airtable",         "Airtable"),
    ("vercel",           "Vercel"),
    ("temporal",         "Temporal"),
    ("arizeai",          "Arize AI"),
    ("runpod",           "RunPod"),
    ("gleanwork",        "Glean"),
    ("ada",              "Ada"),
    ("thoughtmachine",   "Thought Machine"),
    ("monzo",            "Monzo"),
    ("deliveroo",        "Deliveroo"),
    ("gocardless",       "GoCardless"),
    ("checkout",         "Checkout.com"),
    ("revolut",          "Revolut"),
    ("deezersa",         "Deezer"),
    ("improbable",       "Improbable"),
    # added from portals.yml
    ("skyscanner",       "Skyscanner"),
    ("wise",             "Wise"),
    ("wayve",            "Wayve"),
    ("cleo",             "Cleo"),
    ("factorial",        "Factorial"),
    # added from discovery
    ("twilio",           "Twilio"),
    ("dialpad",          "Dialpad"),
    # added from grad-programmes.json
    ("b2c2",             "B2C2"),
    ("baringa",          "Baringa"),
    ("cambridgeconsultantslimited", "Cambridge Consultants"),
    ("catapultsports",   "Catapult"),
    ("davinciderivatives", "Da Vinci Trading"),
    ("drweng",           "DRW"),
    ("dvtrading",        "DV Trading"),
    ("fiveringsllc",     "Five Rings"),
    ("flowtraders",      "Flow Traders"),
    ("glencoreuk",       "Glencore"),
    ("imc",              "IMC Trading"),
    ("lunarenergy",      "Lunar Energy"),
    ("mw-tech-grad",     "Marshall Wace"),
    ("obsidiansecurity", "Obsidian Security"),
    ("rothesaygraduates", "Rothesay"),
    ("towerpeak",        "Tower Peak Partners"),
    ("xantium",          "Xantium"),
    ("xpcampus",         "ExodusPoint"),
    # added from summer-internships.json
    ("quadraturecapital", "Quadrature"),
    ("cloudflare",       "Cloudflare"),
    ("figma",            "Figma"),
    ("mangroup",         "Man Group"),
    ("tripadvisor",      "Viator"),
    ("schonfeld",        "Schonfeld"),
    ("perplexityai",     "Perplexity"),
    ("emergingtalent",   "Maven Securities"),
    ("moloco",           "Moloco"),
    ("aquaticcapitalmanagement", "Aquatic Capital Management"),
    ("copperco",         "Copper.co"),
    ("embed",            "GSA Capital"),
    ("point72",          "Point72"),
    ("mwinternshipprogram", "Marshall Wace"),
    ("xtxmarketstechnologies", "XTX Markets"),
    # added from slug validation
    ("deepmind",          "DeepMind"),
    ("stripe",            "Stripe"),
    ("databricks",        "Databricks"),
    ("jumptrading",       "Jump Trading"),
    ("virtu",             "Virtu Financial"),
    ("datadog",           "Datadog"),
    ("elastic",           "Elastic"),
    ("mongodb",           "MongoDB"),
]

_ASHBY_COMPANIES: list[tuple[str, str]] = [
    # existing
    ("elevenlabs",  "ElevenLabs"),
    ("deepgram",    "Deepgram"),
    ("vapi",        "Vapi"),
    ("bland",       "Bland AI"),
    ("sierra",      "Sierra"),
    ("decagon",     "Decagon"),
    ("n8n",         "n8n"),
    ("zapier",      "Zapier"),
    ("cohere",      "Cohere"),
    ("langchain",   "LangChain"),
    ("lindy",       "Lindy"),
    ("qdrant",      "Qdrant"),
    ("weaviate",    "Weaviate"),
    # added from portals.yml
    ("pinecone",    "Pinecone"),
    ("attio",       "Attio"),
    ("tinybird",    "Tinybird"),
    ("abound",      "Abound"),
    ("babylon",     "Babylon Health"),
    ("travelperk",  "TravelPerk"),
    # added from discovery
    ("openai",      "OpenAI"),
    ("talkdesk",    "Talkdesk"),
    ("faculty",     "Faculty AI"),
    # added from grad-programmes.json
    ("hawkeyeinnovations", "Hawk-Eye Innovations"),
    ("spaice-tech", "SPAICE"),
    # added from summer-internships.json
    ("thought-machine", "Thought Machine"),
    ("red-gate",    "Redgate"),
    ("uipath",      "UiPath"),
    ("runna",       "Runna"),
    ("ariesglobal", "Aries Global"),
    ("unlikelyai",  "UnlikelyAI"),
    ("Talos-Trading", "Talos"),
    ("deliveroo",   "Deliveroo"),
    ("treefera",    "Treefera"),
    ("trainline",   "Trainline"),
    # added from slug validation
    ("perplexity",  "Perplexity AI"),
    ("modal",       "Modal"),
    ("cursor",      "Cursor"),
]

_LEVER_COMPANIES: list[tuple[str, str]] = [
    ("scale-ai",    "Scale AI"),
    ("wandb",       "Weights & Biases"),   # canonical slug (weights-biases also works)
    ("together-ai", "Together AI"),
    ("palantir",    "Palantir"),
    ("mistral",     "Mistral AI"),
    ("clarity-ai",  "Clarity AI"),
    # added from grad-programmes.json
    ("frontier",    "Frontier Developments"),
    ("ion",         "ION"),
    # added from summer-internships.json
    ("cirrus",      "Cirrus Logic"),
    ("spotify",     "Spotify"),
    ("gearset",     "Gearset"),
]

_WORKABLE_COMPANIES: list[tuple[str, str]] = [
    ("starling-bank", "Starling Bank"),
    ("riverlane", "Riverlane"),
    ("capula-investment-management-ltd", "Capula Investment Management"),
    ("longshot-systems-ltd", "Longshot Systems"),
    ("insight-investment", "Insight Investment"),
    # added from summer-internships.json
    ("phasecraft-1", "Phasecraft"),
    ("arondite",     "Arondite"),
    ("cogna",        "Cogna"),
    ("caxton",       "Caxton Associates"),
    # added from slug validation
    ("two-sigma",   "Two Sigma"),
]

_SMARTRECRUITERS_COMPANIES: list[tuple[str, str]] = [
    # Confirmed working via API test (May 2026)
    ("PAConsulting",     "PA Consulting"),
    ("Visa",             "Visa"),
    ("TTP1",             "TTP"),
    ("Vitol",            "Vitol"),
    ("LegalAndGeneral",  "Legal & General"),
    # Additional candidates (200 OK, 0 jobs now but valid boards)
    ("ni",               "Turner & Townsend"),
    ("oneclick-ui",      "EDF Energy"),
    ("GoldmanSachs",     "Goldman Sachs"),
    ("HSBC",             "HSBC"),
    ("Barclays",         "Barclays"),
    ("JPMorgan",         "JPMorgan"),
    ("Macquarie",        "Macquarie"),
    ("Nomura",           "Nomura"),
    ("CitadelSecurities","Citadel Securities"),
]

async def _fetch_greenhouse(slug: str, company: str, keywords: list[str]) -> list[dict]:
    try:
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        jobs = []
        for item in data.get("jobs", []):
            title = item.get("title", "")
            if not _title_matches_query(title, keywords):
                continue
            location = item.get("location", {}).get("name", "")
            jobs.append({
                "job_id": f"gh-{item.get('id', '')}",
                "title": title,
                "company": company,
                "location": location or "Remote",
                "description": (item.get("content") or "")[:500],
                "url": item.get("absolute_url", ""),
                "salary_min": None,
                "salary_max": None,
                "exposure_score": round(occupation_exposure(title), 3),
            })
        return jobs
    except Exception:
        return []


async def _fetch_ashby(slug: str, company: str, keywords: list[str]) -> list[dict]:
    try:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        jobs = []
        for item in data.get("jobs", []):
            title = item.get("title", "")
            if not _title_matches_query(title, keywords):
                continue
            location = (
                item.get("locationName")
                or (item.get("location") or {}).get("locationName")
                or "Remote"
            )
            desc_raw = item.get("descriptionPlain") or item.get("description") or ""
            desc = re.sub(r"<[^>]+>", " ", desc_raw)[:500]
            jobs.append({
                "job_id": f"ashby-{item.get('id', '')}",
                "title": title,
                "company": company,
                "location": location,
                "description": desc,
                "url": item.get("jobUrl", ""),
                "salary_min": None,
                "salary_max": None,
                "exposure_score": round(occupation_exposure(title), 3),
            })
        return jobs
    except Exception:
        return []


async def _fetch_lever(slug: str, company: str, keywords: list[str]) -> list[dict]:
    try:
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        jobs = []
        for item in data:
            title = item.get("text", "")
            if not _title_matches_query(title, keywords):
                continue
            loc = item.get("categories", {}).get("location", "") or item.get("country", "")
            desc_raw = item.get("descriptionPlain") or ""
            jobs.append({
                "job_id": f"lever-{item.get('id', '')}",
                "title": title,
                "company": company,
                "location": loc or "Remote",
                "description": re.sub(r"<[^>]+>", " ", desc_raw)[:500],
                "url": item.get("hostedUrl", ""),
                "salary_min": None,
                "salary_max": None,
                "exposure_score": round(occupation_exposure(title), 3),
            })
        return jobs
    except Exception:
        return []

async def _fetch_workable(slug: str, company: str, keywords: list[str]) -> list[dict]:
    try:
        url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        jobs = []
        for item in data.get("jobs", []):
            title = item.get("title", "")
            if not _title_matches_query(title, keywords):
                continue
            city = item.get("city", "")
            country = item.get("country", "")
            loc = f"{city}, {country}".strip(", ")
            if not loc and item.get("telecommuting"):
                loc = "Remote"
            desc_raw = item.get("description") or ""
            jobs.append({
                "job_id": f"workable-{item.get('shortcode', '')}",
                "title": title,
                "company": company,
                "location": loc or "Remote",
                "description": re.sub(r"<[^>]+>", " ", desc_raw)[:500],
                "url": item.get("url", ""),
                "salary_min": None,
                "salary_max": None,
                "exposure_score": round(occupation_exposure(title), 3),
            })
        return jobs
    except Exception:
        return []


async def _fetch_smartrecruiters(slug: str, company: str, keywords: list[str]) -> list[dict]:
    """Fetch from SmartRecruiters public postings API (no auth required).
    Paginates up to 200 jobs per company; filters locally by keyword.
    API docs: https://dev.smartrecruiters.com/customer-api/live-docs/job-board-api/
    """
    try:
        jobs: list[dict] = []
        limit = 100
        offset = 0
        async with httpx.AsyncClient(timeout=10.0) as client:
            while offset < 200:  # cap at 200 to avoid hammering
                url = (
                    f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
                    f"?limit={limit}&offset={offset}"
                )
                resp = await client.get(url)
                if resp.status_code != 200:
                    break
                data = resp.json()
                content = data.get("content", [])
                if not content:
                    break
                for item in content:
                    title = item.get("name", "")
                    if not _title_matches_query(title, keywords):
                        continue
                    loc_data = item.get("location") or {}
                    city = loc_data.get("city", "")
                    country = loc_data.get("country", "")
                    remote = loc_data.get("remote", False)
                    loc = city or ("Remote" if remote else country or "")
                    job_ref = item.get("ref", "")
                    # Build apply URL from the ref (API URL → public URL)
                    job_uuid = item.get("uuid", item.get("id", ""))
                    apply_url = f"https://jobs.smartrecruiters.com/{slug}/{job_uuid}" if job_uuid else job_ref
                    jobs.append({
                        "job_id": f"sr-{item.get('uuid', item.get('id', ''))}",
                        "title": title,
                        "company": company,
                        "location": loc or "See listing",
                        "description": "",
                        "url": apply_url,
                        "salary_min": None,
                        "salary_max": None,
                        "source": "smartrecruiters",
                        "exposure_score": round(occupation_exposure(title), 3),
                    })
                if len(content) < limit:
                    break  # last page
                offset += limit
        return jobs
    except Exception:
        return []

async def _search_level2_ats_apis(queries: list[str]) -> list[dict]:
    """
    Concurrently fetch from Greenhouse, Ashby, Lever, and Workable public APIs.
    Filters each company's listings by query keyword relevance in a single pass.
    """
    all_keywords = []
    for q in queries:
        all_keywords.extend(_query_keywords(q))
        
    keywords = list(set(all_keywords))
    if not keywords:
        return []

    tasks = (
        [_fetch_greenhouse(slug, name, keywords) for slug, name in _GREENHOUSE_COMPANIES]
        + [_fetch_ashby(slug, name, keywords)         for slug, name in _ASHBY_COMPANIES]
        + [_fetch_lever(slug, name, keywords)         for slug, name in _LEVER_COMPANIES]
        + [_fetch_workable(slug, name, keywords)      for slug, name in _WORKABLE_COMPANIES]
        + [_fetch_smartrecruiters(slug, name, keywords) for slug, name in _SMARTRECRUITERS_COMPANIES]
    )

    results = await asyncio.gather(*tasks, return_exceptions=True)
    jobs: list[dict] = []
    for r in results:
        if isinstance(r, list):
            jobs.extend(r)

    total_companies = (
        len(_GREENHOUSE_COMPANIES) + len(_ASHBY_COMPANIES)
        + len(_LEVER_COMPANIES) + len(_WORKABLE_COMPANIES)
        + len(_SMARTRECRUITERS_COMPANIES)
    )
    logger.info("Level 2 (ATS APIs): %d jobs matched against %d keywords across %d companies",
                len(jobs), len(keywords), total_companies)
    return jobs


# ── Level 3: Brave Search with site: filters ──────────────────────────────────
#
# Execute pre-built site: queries against the Brave Search API.
# Free tier: 2000 requests/month. Set BRAVE_SEARCH_API_KEY to enable.
# Parses "Title @ Company" / "Title at Company" patterns from result titles.
# Gracefully skips if key is unset.

_SEARCH_QUERIES: list[str] = [
    # ── Workday: Finance & Banking ──────────────────────────────────────────────
    # Targets: Barclays, Lloyds, NatWest, Citi, MUFG, TD Securities, Barclays
    (
        'site:barclays.wd3.myworkdayjobs.com OR site:lbg.wd3.myworkdayjobs.com'
        ' OR site:rbs.wd3.myworkdayjobs.com OR site:citi.wd5.myworkdayjobs.com'
        ' OR site:mufgub.wd3.myworkdayjobs.com OR site:td.wd3.myworkdayjobs.com'
        ' "Graduate" OR "Junior" OR "Associate" "Technology" OR "Software" OR "Data" OR "Engineer"'
    ),
    # Targets: Capital One, Blackstone, PIMCO, Houlihan Lokey, Julius Baer, M&G, PGIM
    (
        'site:capitalone.wd12.myworkdayjobs.com OR site:blackstone.wd1.myworkdayjobs.com'
        ' OR site:pimco.wd1.myworkdayjobs.com OR site:hl.wd1.myworkdayjobs.com'
        ' OR site:juliusbaer.wd3.myworkdayjobs.com OR site:mgpru.wd3.myworkdayjobs.com'
        ' OR site:pru.wd5.myworkdayjobs.com'
        ' "Graduate" OR "Junior" OR "Analyst" "Technology" OR "Software" OR "Data" OR "Quantitative"'
    ),
    # Targets: LSEG, Aberdeen, Baillie Gifford, FCA, Frontier Economics, NASDAQ, Dow Jones
    (
        'site:lseg.wd3.myworkdayjobs.com OR site:abrdn.wd3.myworkdayjobs.com'
        ' OR site:bailliegifford.wd3.myworkdayjobs.com OR site:fca.wd3.myworkdayjobs.com'
        ' OR site:frontiereconomics.wd3.myworkdayjobs.com OR site:nasdaq.wd1.myworkdayjobs.com'
        ' OR site:dowjones.wd1.myworkdayjobs.com'
        ' "Graduate" OR "Junior" OR "Associate" "Software" OR "Technology" OR "Data" OR "Engineer"'
    ),
    # ── Workday: Tech & Engineering ─────────────────────────────────────────────
    # Targets: Nvidia, Autodesk, Salesforce, Snyk, CrowdStrike, AVEVA, FactSet, Cadence, KLA
    (
        'site:nvidia.wd5.myworkdayjobs.com OR site:autodesk.wd1.myworkdayjobs.com'
        ' OR site:salesforce.wd12.myworkdayjobs.com OR site:snyk.wd103.myworkdayjobs.com'
        ' OR site:crowdstrike.wd5.myworkdayjobs.com OR site:aveva.wd3.myworkdayjobs.com'
        ' OR site:factset.wd108.myworkdayjobs.com OR site:cadence.wd1.myworkdayjobs.com'
        ' OR site:kla.wd1.myworkdayjobs.com'
        ' "Graduate" OR "Junior" OR "New Grad" "Software Engineer" OR "Data" OR "ML" OR "Platform"'
    ),
    # Targets: Rolls-Royce, Airbus, MBDA, Shell, Thales, Motorola Solutions, BAE/KBR, Centrica
    (
        'site:rollsroyce.wd3.myworkdayjobs.com OR site:ag.wd3.myworkdayjobs.com'
        ' OR site:mbda.wd3.myworkdayjobs.com OR site:shell.wd3.myworkdayjobs.com'
        ' OR site:thales.wd3.myworkdayjobs.com OR site:motorolasolutions.wd5.myworkdayjobs.com'
        ' OR site:kbr.wd5.myworkdayjobs.com OR site:centrica.wd3.myworkdayjobs.com'
        ' "Graduate" OR "Junior" "Software" OR "Data" OR "Systems Engineer" OR "Technology"'
    ),
    # Targets: Expedia, RELX, ING, Liberty Global, Quilter, Tencent, Hiscox, G-Research
    (
        'site:expedia.wd108.myworkdayjobs.com OR site:relx.wd3.myworkdayjobs.com'
        ' OR site:ing.wd3.myworkdayjobs.com OR site:libertyglobal.wd3.myworkdayjobs.com'
        ' OR site:quilter.wd3.myworkdayjobs.com OR site:tencent.wd1.myworkdayjobs.com'
        ' OR site:hiscox.wd3.myworkdayjobs.com OR site:gresearch.wd103.myworkdayjobs.com'
        ' "Graduate" OR "Junior" OR "New Grad" "Software" OR "Engineer" OR "Data" OR "Quant"'
    ),
    # ── Custom Career Pages: Major UK Tech & Finance ─────────────────────────────
    # ARM, Mastercard, PwC Technology, BAE Systems digital
    (
        'site:careers.arm.com OR site:careers.mastercard.com OR site:jobs.pwc.co.uk'
        ' OR site:jobsearch.baesystems.com'
        ' "Graduate" OR "Junior" OR "Early Careers" "Software" OR "Technology" OR "Engineer" OR "Data"'
    ),
    # Capgemini, TikTok/ByteDance, Arup, KKR Technology
    (
        'site:www.capgemini.com/gb-en/careers OR site:lifeattiktok.com'
        ' OR site:careers.arup.com OR site:www.kkr.com/careers'
        ' "Graduate" OR "Junior" "Software Engineer" OR "Technology" OR "Data Analyst"'
    ),
    # Wise (custom portal), Bending Spoons, G-Research careers, Jane Street
    (
        'site:wise.jobs OR site:jobs.bendingspoons.com'
        ' OR site:www.janestreet.com/join-jane-street'
        ' "Graduate" OR "Junior" OR "New Grad" "Software" OR "Engineer" OR "Quant" OR "Developer"'
    ),
    # ── TALlink (tal.net): BlackRock, Jefferies ──────────────────────────────────
    (
        'site:blackrock.tal.net OR site:jefferies.tal.net'
        ' "Graduate" OR "Junior" OR "Analyst" "Technology" OR "Software" OR "Data" OR "Engineering"'
        ' 2025 OR 2026'
    ),
    # ── iCIMS & Taleo: Enterprise Portals ───────────────────────────────────────
    (
        'site:icims.com OR site:taleo.net'
        ' "Graduate" OR "Junior" "Software Engineer" OR "Technology Analyst" OR "Data Scientist"'
        ' London'
    ),
    # ── UK Graduate Job Boards ──────────────────────────────────────────────────
    # Gradcracker: strong UK engineering grad listings
    (
        'site:gradcracker.com "Software" OR "AI" OR "Data" OR "Cloud" OR "DevOps"'
        ' "Graduate" OR "Intern" London OR UK 2025 OR 2026'
    ),
    # Target Jobs: broad UK grad tech
    (
        'site:targetjobs.co.uk "Graduate" "Software Engineer" OR "Technology" OR "Data Scientist"'
        ' OR "Machine Learning" OR "Cloud" London OR hybrid'
    ),
    # Reed & Totaljobs: UK job boards for non-ATS listings
    (
        'site:reed.co.uk OR site:totaljobs.com'
        ' "Graduate" "Software Engineer" OR "AI Engineer" OR "Data Scientist" OR "Cloud Engineer"'
        ' London 2025 OR 2026'
    ),
    # Wellfound: startups not on standard ATS
    (
        'site:wellfound.com "Junior" OR "Graduate" OR "Entry Level"'
        ' "Software Engineer" OR "AI Engineer" OR "ML Engineer" OR "Full Stack" OR "Backend"'
    ),
]

_BRAVE_BASE = "https://api.search.brave.com/res/v1/web/search"


def _parse_search_title(raw_title: str) -> tuple[str, str]:
    """
    Extract (job_title, company) from a search result title.
    Handles: "Software Engineer @ Acme", "ML Engineer at Acme", "Engineer | Acme"
    """
    m = _TITLE_SEP.match(raw_title.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return raw_title.strip(), "Unknown"


async def _brave_search_one(client: httpx.AsyncClient, query: str) -> list[dict]:
    """Execute a single Brave Search query and parse results into job dicts."""
    try:
        resp = await client.get(
            _BRAVE_BASE,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": BRAVE_API_KEY,
            },
            params={"q": query, "count": 20, "search_lang": "en"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        jobs = []
        for result in data.get("web", {}).get("results", []):
            raw_title = result.get("title", "")
            url = result.get("url", "")
            if not raw_title or not url:
                continue
            title, company = _parse_search_title(raw_title)
            # Skip obvious non-job pages (pagination, homepages, etc.)
            if len(title) < 5 or title.lower() in {"jobs", "careers", "open positions"}:
                continue
            jobs.append({
                "job_id": f"brave-{abs(hash(url)) % 10**8}",
                "title": title,
                "company": company,
                "location": "See listing",
                "description": result.get("description", "")[:500],
                "url": url,
                "salary_min": None,
                "salary_max": None,
                "exposure_score": round(occupation_exposure(title), 3),
            })
        return jobs
    except Exception as exc:
        logger.debug("Brave search query failed: %s — %s", query[:60], exc)
        return []


async def _search_level3_websearch() -> list[dict]:
    """
    Execute all site: queries via Brave Search API concurrently.
    Returns [] if BRAVE_SEARCH_API_KEY is not set.
    """
    if not BRAVE_API_KEY:
        logger.debug("Level 3: BRAVE_SEARCH_API_KEY not set, skipping")
        return []

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[_brave_search_one(client, q) for q in _SEARCH_QUERIES],
            return_exceptions=True,
        )

    jobs: list[dict] = []
    for r in results:
        if isinstance(r, list):
            jobs.extend(r)

    logger.info("Level 3 (Brave Search): %d jobs from %d queries",
                len(jobs), len(_SEARCH_QUERIES))
    return jobs


# ── Level 4: Adzuna paid API ──────────────────────────────────────────────────

async def _search_level4_workable(query: str, location: str) -> list[dict]:
    """
    Query the global Workable job board API.
    Provides excellent structured data across all Workable customers.
    """
    try:
        import urllib.parse
        q = urllib.parse.quote(query)
        loc = urllib.parse.quote(location)
        url = f"https://jobs.workable.com/api/v1/jobs?query={q}&location={loc}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error("Workable global search failed: %s", e)
        return []

    jobs = []
    for item in data.get("jobs", []):
        title = item.get("title", "")
        company_name = item.get("company", {}).get("title", "Unknown")
        loc_str = ", ".join(item.get("locations", [])) or "Remote"
        
        # Combine descriptions
        desc_raw = (item.get("description", "") + " " + item.get("requirementsSection", "")).strip()
        
        jobs.append({
            "job_id": f"workable-global-{item.get('id', '')}",
            "title": title,
            "company": company_name,
            "location": loc_str,
            "description": re.sub(r"<[^>]+>", " ", desc_raw)[:500],
            "url": item.get("url", ""),
            "salary_min": None,
            "salary_max": None,
            "exposure_score": round(occupation_exposure(title), 3),
        })

    logger.info("Level 4 (Workable): Found %d jobs for %r in %r", len(jobs), query, location)
    return jobs


# ── Post-Processing ───────────────────────────────────────────────────────────

async def _search_level4_adzuna(query: str, location: str) -> list[dict]:
    if not (ADZUNA_APP_ID and ADZUNA_API_KEY):
        return []

    # Map location to country code
    country = "gb"
    loc_lower = location.lower()
    if any(x in loc_lower for x in ["usa", "us", "san francisco", "new york", "seattle"]):
        country = "us"
    elif any(x in loc_lower for x in ["canada", "toronto", "vancouver"]):
        country = "ca"
    elif any(x in loc_lower for x in ["australia", "sydney"]):
        country = "au"

    base_url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    query = re.sub(r"\s+", " ", _BOOLEAN_OPS.sub(" ", query)).strip()

    async def _fetch(q: str) -> list[dict]:
        params = {
            "app_id": ADZUNA_APP_ID,
            "app_key": ADZUNA_API_KEY,
            "what": q,
            "where": location,
            "results_per_page": 20,
            "sort_by": "relevance",
        }
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(base_url, params=params)
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
                "description": item.get("description", "")[:500],
                "url": item.get("redirect_url", ""),
                "salary_min": item.get("salary_min"),
                "salary_max": item.get("salary_max"),
                "exposure_score": round(occupation_exposure(title), 3),
            })
        return jobs

    try:
        jobs = await _fetch(query)
        if not jobs:
            simplified = _SENIORITY_WORDS.sub("", query).strip()
            if simplified and simplified != query:
                logger.info("Adzuna (%s): 0 results for %r — retrying as %r", country, query, simplified)
                jobs = await _fetch(simplified)
        logger.info("Level 4 (Adzuna %s): %d jobs for %r in %r", country, len(jobs), query, location)
        return jobs
    except Exception as exc:
        logger.warning("Adzuna %s search failed: %s", country, exc)
        return []


# ── Deduplication ─────────────────────────────────────────────────────────────

def _deduplicate(jobs: list[dict]) -> list[dict]:
    seen_keys: set[tuple] = set()
    seen_urls: set[str] = set()
    out = []
    for job in jobs:
        key = (job.get("title", "").lower()[:40], job.get("company", "").lower()[:30])
        url = job.get("url", "")
        if key in seen_keys or (url and url in seen_urls):
            continue
        seen_keys.add(key)
        if url:
            seen_urls.add(url)
        out.append(job)
    return out


# ── Public interface ──────────────────────────────────────────────────────────

async def search_jobs_multi(query: str, location: str) -> list[dict]:
    """
    Run all 4 levels concurrently, apply title filter, deduplicate,
    sort seniority-boosted titles first, and return up to 20 jobs.
    Falls back to fixture if all live sources return nothing.
    """
    keywords = _query_keywords(query)

    l1, l2, l3, l4 = await asyncio.gather(
        _search_level1_playwright(keywords),
        _search_level2_ats_apis(query),
        _search_level3_websearch(),
        _search_level4_adzuna(query, location),
    )

    combined = l1 + l2 + l3 + l4
    deduped  = _deduplicate(combined)

    if not deduped:
        logger.warning("All live sources returned 0 results — falling back to fixture")
        return _FIXTURE

    # Apply title filter — fall back to unfiltered if filter removes everything
    filtered = [j for j in deduped if _passes_title_filter(j["title"])]
    if not filtered:
        logger.warning("Title filter removed all %d results — returning unfiltered", len(deduped))
        filtered = deduped

    # Seniority-boosted titles (Graduate, Junior…) float to the top
    filtered.sort(key=lambda j: _seniority_score(j["title"]), reverse=True)

    logger.info(
        "Job discovery: L1=%d L2=%d L3=%d L4=%d → %d after dedup → %d after filter",
        len(l1), len(l2), len(l3), len(l4), len(deduped), len(filtered),
    )
    return filtered[:20]
