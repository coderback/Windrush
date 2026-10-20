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
import html as _html
import logging
import os
import re
import pathlib
import json

import httpx

from . import http_client
from . import jobs_db
from . import net_guard
from .company_names import normalise_company_name
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

# Max chars to store for a job description. ATS APIs return the full JD; we keep
# it (near) whole so fit-scoring and CV/cover-letter tailoring have real context
# rather than a 500-char teaser.
_DESC_MAX = 8000

# Regex to parse "Title @ Company" / "Title at Company" / "Title | Company"
# from search snippet titles
_TITLE_SEP = re.compile(r"(.+?)(?:\s*[@|—–-]\s*|\s+at\s+)(.+?)$", re.I)


def _load_fixture() -> list[dict]:
    jobs = json.loads(_FIXTURE_PATH.read_text())
    for job in jobs:
        job["source"] = "fixture"  # mock data: shown as a fallback, never persisted (see discovery.py)
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


# ── Full job-description fetcher (on-demand) ───────────────────────────────────
# Stored descriptions are truncated to 500 chars at sync time (and for Brave
# results are only a web snippet). When we need the real JD — e.g. to score fit
# or tailor a CV — we re-fetch the listing page and pull the full description.

def _iter_jsonld_objects(data):
    """Walk a parsed JSON-LD blob yielding every object (handles @graph + lists)."""
    if isinstance(data, dict):
        if isinstance(data.get("@graph"), list):
            for x in data["@graph"]:
                yield from _iter_jsonld_objects(x)
        yield data
    elif isinstance(data, list):
        for x in data:
            yield from _iter_jsonld_objects(x)


def _html_to_text(raw: str) -> str:
    """Strip HTML to readable plain text, preserving paragraph/line breaks."""
    # Unescape FIRST: some ATS APIs (e.g. Greenhouse) return entity-escaped HTML
    # (&lt;p&gt;…), so decoding has to happen before tags can be stripped.
    text = _html.unescape(raw)
    text = re.sub(r"(?is)<(script|style|noscript|template|svg)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", text)
    return text.strip()


def _find_jsonld_jobposting(raw_html: str) -> dict:
    """Return the first JSON-LD JobPosting object on the page, or {} if none."""
    for m in re.finditer(
        r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        raw_html,
    ):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        for obj in _iter_jsonld_objects(data):
            t = obj.get("@type", "")
            types = t if isinstance(t, list) else [t]
            if any("JobPosting" in str(x) for x in types):
                return obj
    return {}


def _extract_jsonld_jobposting(raw_html: str) -> str:
    """Return the description from a JSON-LD JobPosting block, if present."""
    obj = _find_jsonld_jobposting(raw_html)
    desc = obj.get("description", "") if obj else ""
    return _html_to_text(desc) if desc else ""


_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def _ats_full_description(url: str) -> str:
    """
    Pull a full JD from a known ATS's structured API by reverse-engineering the
    listing URL. These return clean, complete descriptions — far better than
    scraping the (often JS-rendered) hosted board page.
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path

    async with http_client.async_client(follow_redirects=True, timeout=12.0) as client:
        # Greenhouse — boards(-api).greenhouse.io/{slug}/jobs/{id}
        if "greenhouse.io" in host:
            m = re.search(r"/([^/]+)/jobs/(\d+)", path)
            if m:
                slug, jid = m.group(1), m.group(2)
                r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}")
                if r.status_code == 200:
                    return _html_to_text(r.json().get("content") or "")

        # Lever — jobs.lever.co/{slug}/{id}, or jobs.eu.lever.co on its EU instance (its own API)
        elif "lever.co" in host:
            m = re.search(r"/([^/]+)/([0-9a-fA-F-]{8,})", path)
            if m:
                slug, pid = m.group(1), m.group(2)
                api = "api.eu.lever.co" if host.endswith("eu.lever.co") else "api.lever.co"
                r = await client.get(f"https://{api}/v0/postings/{slug}/{pid}")
                if r.status_code == 200:
                    data = r.json()
                    raw = data.get("descriptionPlain") or data.get("description") or ""
                    return _html_to_text(raw)

        # Workday — <tenant>.wd<n>.myworkdayjobs.com/[<locale>/]<site>/job/…, read through the site's job service
        # (the bare host name: the link can be the user's, and only a Workday host is called)
        elif (parsed.hostname or "").lower().endswith(".myworkdayjobs.com"):
            m = re.match(r"/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)(/job/.+)", path)
            if m:
                workday = parsed.hostname.lower()
                tenant = workday.split(".")[0]
                r = await client.get(f"https://{workday}/wday/cxs/{tenant}/{m.group(1)}{m.group(2)}",
                                     headers={"Accept": "application/json"})
                if r.status_code == 200:
                    return _html_to_text((r.json().get("jobPostingInfo") or {}).get("jobDescription") or "")

    return ""


async def fetch_full_description(url: str, max_chars: int = 8000) -> str:
    """
    Fetch a job listing's full description on demand.

    Strategy, in order of reliability:
      1. Known ATS structured API (Greenhouse, Lever, Workday) — clean, complete JD.
      2. JSON-LD JobPosting block on the page — common on real listing pages.

    Returns "" on any failure or if nothing trustworthy is found, so callers
    safely keep whatever description they already had. We deliberately do NOT
    fall back to raw page text: SPA shells and marketing sites yield navigation
    /footer noise that would pollute the analysis.
    """
    if not url or not url.startswith("http"):
        return ""

    try:
        ats = await _ats_full_description(url)
        if len(ats) >= 200:
            return ats[:max_chars].strip()
    except Exception as exc:
        logger.debug("ATS description fetch failed for %s: %s", url[:80], exc)

    try:
        async with http_client.async_client(
            headers=_BROWSER_HEADERS, timeout=15.0,
        ) as client:
            resp = await net_guard.safe_get(client, url)  # user-influenced URL: no internal hosts
            resp.raise_for_status()
            raw_html = resp.text
        jd = _extract_jsonld_jobposting(raw_html)
        if len(jd) >= 200:
            return jd[:max_chars].strip()
    except Exception as exc:
        logger.debug("JSON-LD description fetch failed for %s: %s", url[:80], exc)

    return ""


# ── User-pasted-URL scraping (build a full Job from an arbitrary listing) ──────

def _meta_content(raw_html: str, prop: str) -> str:
    """Return the content of a <meta property|name="prop"> tag, if present."""
    for attr in ("property", "name"):
        m = re.search(
            rf'(?is)<meta[^>]+{attr}=["\']{re.escape(prop)}["\'][^>]*>',
            raw_html,
        )
        if m:
            c = re.search(r'(?is)content=["\'](.*?)["\']', m.group(0))
            if c:
                return _html.unescape(c.group(1)).strip()
    return ""


def _first_tag_text(raw_html: str, tag: str) -> str:
    m = re.search(rf"(?is)<{tag}[^>]*>(.*?)</{tag}>", raw_html)
    return _html_to_text(m.group(1)) if m else ""


def _jsonld_org_name(obj: dict) -> str:
    org = obj.get("hiringOrganization")
    if isinstance(org, dict):
        return str(org.get("name", "")).strip()
    if isinstance(org, str):
        return org.strip()
    return ""


def _jsonld_location(obj: dict) -> str:
    loc = obj.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    if isinstance(loc, dict):
        addr = loc.get("address", loc)
        if isinstance(addr, dict):
            parts = [
                addr.get("addressLocality", ""),
                addr.get("addressRegion", ""),
                addr.get("addressCountry", "")
                    if isinstance(addr.get("addressCountry"), str)
                    else (addr.get("addressCountry") or {}).get("name", ""),
            ]
            return ", ".join(p for p in parts if p)
    if obj.get("jobLocationType") == "TELECOMMUTE":
        return "Remote"
    return ""


def _jsonld_salary(obj: dict) -> tuple[float | None, float | None]:
    base = obj.get("baseSalary")
    if not isinstance(base, dict):
        return None, None
    value = base.get("value", base)
    if not isinstance(value, dict):
        return None, None

    def _num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    lo = _num(value.get("minValue")) or _num(value.get("value"))
    hi = _num(value.get("maxValue")) or lo
    return lo, hi


async def scrape_job_from_url(url: str) -> dict:
    """
    Scrape an arbitrary job-posting URL into a full Job dict ready for analysis.

    Reuses the ATS/JSON-LD description fetcher and adds structured-metadata
    extraction (title, company, location, salary) from the page's JSON-LD
    JobPosting block, falling back to OpenGraph / <title> / <h1> tags. Raises
    ValueError if the page yields neither a usable title nor a description, so
    the caller can surface a clear "couldn't read that listing" message.
    """
    import uuid
    from urllib.parse import urlparse

    if not url or not url.startswith("http"):
        raise ValueError("Please paste a valid http(s) job-posting link.")
    # Fail loudly (400) rather than as a generic "couldn't read" — UnsafeURLError is a ValueError.
    await net_guard.assert_public_url(url)

    description = await fetch_full_description(url)

    raw_html = ""
    try:
        async with http_client.async_client(
            headers=_BROWSER_HEADERS, timeout=15.0,
        ) as client:
            resp = await net_guard.safe_get(client, url)  # user-influenced URL: no internal hosts
            resp.raise_for_status()
            raw_html = resp.text
    except Exception as exc:
        logger.debug("Page fetch failed for %s: %s", url[:80], exc)

    posting = _find_jsonld_jobposting(raw_html) if raw_html else {}

    title = str(posting.get("title", "")).strip()
    company = _jsonld_org_name(posting)
    location = _jsonld_location(posting)
    salary_min, salary_max = _jsonld_salary(posting)

    # Description fallback: JSON-LD object may carry it even when the ATS/standalone
    # fetcher returned "" (e.g. it was < 200 chars there).
    if not description and posting.get("description"):
        description = _html_to_text(posting["description"])[:_DESC_MAX].strip()

    # OpenGraph / HTML fallbacks for missing metadata.
    if not title:
        title = _meta_content(raw_html, "og:title") or _first_tag_text(raw_html, "h1")
        if not title:
            page_title = _first_tag_text(raw_html, "title")
            title = re.split(r"\s+[|\-–—]\s+", page_title)[0].strip() if page_title else ""
    if not company:
        company = _meta_content(raw_html, "og:site_name")
    if not company:
        company = urlparse(url).netloc.replace("www.", "")

    title = title.strip()
    if not title and not description:
        raise ValueError(
            "Couldn't read that listing — try a direct job-posting link "
            "(e.g. a Greenhouse, Lever, or a page with a standard job schema)."
        )

    job: dict = {
        "id": uuid.uuid4().hex,
        "job_id": uuid.uuid4().hex[:12],
        "title": title or "Job posting",
        "company": company or "Unknown",
        "location": location,
        "description": description,
        "url": url,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "source": "user-url",
    }
    job["exposure_score"] = round(occupation_exposure(job["title"]), 3)
    return job


# ── Title filter (from career-ops/portals.yml) ────────────────────────────────

_POSITIVE_KW: list[str] = [
    # AI/ML roles
    "AI", "ML", "Machine Learning", "LLM", "Agent", "Agentic", "GenAI",
    "Generative AI", "NLP", "LLMOps", "MLOps", "Computer Vision", "Data Science",
    # Software Engineering
    "Software Engineer", "Software Engineering", "Software Developer", "Backend Engineer",
    "Backend", "Back End", "Back-End", "Frontend", "Front End", "Front-End",
    "Full Stack", "Full-Stack", "Fullstack", "Python Developer", "Python Engineer", "Developer", "SWE",
    # Data / research / quant
    "Data Engineer", "Data Scientist", "Analytics Engineer", "Research Engineer", "Research Scientist",
    "Applied Scientist", "Quant", "Quantitative",
    # DevOps / Infra
    "DevOps", "Platform Engineer", "Cloud Engineer", "Infrastructure Engineer",
    "Site Reliability", "SRE", "Kubernetes", "CI/CD",
    # Early careers
    "Graduate", "Junior", "Entry Level", "Associate Engineer", "Trainee Engineer",
]

_NEGATIVE_KW: list[str] = [
    "Intern", "Interns", "Internship", "Internships", ".NET", "Java", "iOS", "Android", "PHP", "Ruby",
    "Embedded", "Firmware", "FPGA", "ASIC", "Blockchain", "Web3",
    "Salesforce Admin", "SAP", "Oracle EBS", "Mainframe", "COBOL",
    "Senior", "Sr", "Staff", "Principal", "Lead", "Head of", "Director", "VP", "Manager",
]

_SENIORITY_BOOST_KW: list[str] = ["Graduate", "Junior", "Entry Level", "Associate"]


def _whole_words(words: list[str]) -> re.Pattern:
    """Any of `words` as whole words: "Intern" isn't "International", "AI" isn't "email"."""
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(w.lower()) for w in words) + r")(?![a-z0-9])", re.I)


_POSITIVE = _whole_words(_POSITIVE_KW)
_NEGATIVE = _whole_words(_NEGATIVE_KW)
_QUERY_STOP = {"a", "an", "the", "and", "or", "for", "in", "at", "of", "to", "with"}


def _names_the_search(title: str, query: str) -> bool:
    """Every word of the search is in the title, so a target title passes even when no listed role word does
    ("Quant Developer" -> "Quantitative Developer"): words of 4+ letters may run on ("quant" -> "quantitative"),
    shorter ones ("ML", "AI") must be whole words."""
    words = [w for w in re.findall(r"[a-z0-9+#]+", (query or "").lower()) if w not in _QUERY_STOP]
    return bool(words) and all(
        re.search(rf"(?<![a-z0-9]){re.escape(w)}" + ("" if len(w) >= 4 else r"(?![a-z0-9])"), title, re.I)
        for w in words)


def _passes_title_filter(title: str, *queries: str) -> bool:
    """A role we look for (a listed role word, or every word of one of the searches) and none of the roles
    we skip, all matched as whole words. Link text naming a page of jobs ("Engineering 26 open positions",
    "Arm Job Search Results for Graduate") isn't a job."""
    if _NEGATIVE.search(title) or _NOT_A_JOB.search(title):
        return False
    return bool(_POSITIVE.search(title)) or any(_names_the_search(title, q) for q in queries)


_NOT_A_JOB = re.compile(
    r"\bopen (?:positions|roles|jobs|vacancies)\b|\bjobs? search\b|\bsearch (?:for )?jobs\b|\bsearch results\b"
    r"|\b\d+\s+(?:open\s+)?(?:positions|roles|jobs|vacancies|openings)\b"
    r"|\b(?:view|see|browse) (?:all )?(?:jobs|roles|positions|openings)\b"
    # a job board's page of them: "Data Scientist Jobs in London", "IT graduate jobs & schemes", "... Vacancies"
    r"|\bjobs\s*(?:$|in\b|for\b|&|\|)|\bvacancies\b|\bhiring for\b|\bsalary and equity\b", re.I)


# ── Locations ─────────────────────────────────────────────────────────────────
# A job's location is the place it's in, with the work setting after it when the source gives one
# ("London, United Kingdom (Hybrid)"), or "" when the source doesn't say: never a guessed "Remote".

_SETTINGS = {"hybrid": "Hybrid", "remote": "Remote", "onsite": "On-site", "on-site": "On-site"}
_NOT_A_PLACE = re.compile(r"^\s*(?:hybrid|remote|on-?site|in[- ]office|flexible|multiple locations|various(?: locations)?)\s*$",
                          re.I)


def _place_and_setting(places: list[str], setting: str = "") -> str:
    """'London; Paris' + 'Hybrid' -> 'London; Paris (Hybrid)'; the setting alone when there's no place."""
    place = "; ".join(dict.fromkeys(p.strip() for p in places if isinstance(p, str) and p.strip()))
    setting = _SETTINGS.get((setting or "").strip().lower(), "")
    if not setting or setting.lower() in place.lower():
        return place
    return f"{place} ({setting})" if place else setting


def _greenhouse_location(item: dict) -> str:
    """Some boards put a work setting in the location and the city in `offices` (Cloudflare: 331 of 433
    jobs say just "Hybrid")."""
    name = ((item.get("location") or {}).get("name") or "").strip()
    if name and not _NOT_A_PLACE.match(name):
        return name
    offices = [o.get("location") or o.get("name") or "" for o in item.get("offices") or [] if isinstance(o, dict)]
    return _place_and_setting(offices, name) or name


def _ashby_location(item: dict) -> str:
    """Ashby gives `location` as a string (older boards: {"locationName": ...}), extra places in
    `secondaryLocations` and the setting in `workplaceType` / `isRemote`."""
    primary = item.get("location") or item.get("locationName") or ""
    if isinstance(primary, dict):
        primary = primary.get("locationName") or ""
    secondary = [(s.get("location") if isinstance(s, dict) else s) or "" for s in item.get("secondaryLocations") or []]
    return _place_and_setting([primary, *secondary], item.get("workplaceType") or ("Remote" if item.get("isRemote") else ""))


_URL_PLACE = re.compile(r"/job/([A-Za-z][A-Za-z-]{1,40})/[^/?#]+")


def _location_from_url(url: str) -> str:
    """Workday and some career sites put the place in the path: .../job/London-United-Kingdom/<title>_R123."""
    m = _URL_PLACE.search(url or "")
    place = m.group(1).replace("-", " ") if m else ""
    return "" if not place or _POSITIVE.search(place) or place.lower() in ("details", "apply") else place


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
                "location": "",
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
    ("arizeai",          "Arize AI"),
    ("gleanwork",        "Glean"),
    ("monzo",            "Monzo"),
    ("deliveroo",        "Deliveroo"),
    ("gocardless",       "GoCardless"),
    # added from portals.yml
    ("wise",             "Wise"),
    ("cleo",             "Cleo"),
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
    ("xantium",          "Xantium"),
    ("xpcampus",         "ExodusPoint"),
    # added from summer-internships.json
    ("quadraturecapital", "Quadrature"),
    ("cloudflare",       "Cloudflare"),
    ("figma",            "Figma"),
    ("mangroup",         "Man Group"),
    ("tripadvisor",      "Viator"),
    ("schonfeld",        "Schonfeld"),
    ("emergingtalent",   "Maven Securities"),
    ("moloco",           "Moloco"),
    ("aquaticcapitalmanagement", "Aquatic Capital Management"),
    ("copperco",         "Copper.co"),
    ("point72",          "Point72"),
    ("mwinternshipprogram", "Marshall Wace"),
    ("xtxmarketstechnologies", "XTX Markets"),
    # added from slug validation
    ("stripe",            "Stripe"),
    ("databricks",        "Databricks"),
    ("jumptrading",       "Jump Trading"),
    ("virtu",             "Virtu Financial"),
    ("datadog",           "Datadog"),
    ("elastic",           "Elastic"),
    ("mongodb",           "MongoDB"),
    # moved from Lever (October 2026)
    ("scaleai",          "Scale AI"),
    ("togetherai",       "Together AI"),
    # moved from Workable (October 2026)
    ("riverlane",        "Riverlane"),
    # graduate employers' careers sites (October 2026)
    ("mavensecuritiesholdingltd", "Maven Securities"),
    ("neptunenorth",     "Neptune North"),
    ("netcraft",         "Netcraft"),
    ("radixuniversity",  "Radix Trading"),
    ("mthree",           "mthree"),
    ("mako",             "Mako Trading"),
    ("gsacapital",       "GSA Capital"),
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
    ("weaviate",    "Weaviate"),
    # added from portals.yml
    ("pinecone",    "Pinecone"),
    ("attio",       "Attio"),
    ("abound",      "Abound"),
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
    # moved from Greenhouse (October 2026)
    ("wayve",       "Wayve"),
    ("improbable",  "Improbable"),
    ("temporal",    "Temporal"),
    ("runpod",      "RunPod"),
    # moved from Lever (October 2026)
    ("mistral.ai",  "Mistral AI"),
    # graduate employers' careers sites (October 2026)
    ("checkout.com", "Checkout.com"),
]

_LEVER_COMPANIES: list[tuple[str, str]] = [
    ("palantir",    "Palantir"),
    # added from grad-programmes.json
    ("ion",         "ION"),
    # added from summer-internships.json
    ("spotify",     "Spotify"),
    ("gearset",     "Gearset"),
]

# Lever's EU instance (jobs.eu.lever.co): these boards are only on its own API.
_LEVER_EU_COMPANIES: list[tuple[str, str]] = [
    # graduate employers' careers sites (October 2026)
    ("coretechsecurity", "CoreTech Security"),
]

_WORKABLE_COMPANIES: list[tuple[str, str]] = [
    ("starling-bank", "Starling Bank"),
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
    # graduate employers' careers sites (October 2026)
    ("grayce",      "Grayce"),
]

_SMARTRECRUITERS_COMPANIES: list[tuple[str, str]] = [
    # Confirmed working via API test (May 2026)
    ("PAConsulting",     "PA Consulting"),
    ("TTP1",             "TTP"),
    ("Vitol",            "Vitol"),
    ("LegalAndGeneral",  "Legal & General"),
    # graduate employers' careers sites (October 2026)
    ("AECOM2",           "AECOM"),
    ("DataIntellect",    "Data Intellect"),
]

# Workday careers sites, as "<tenant>/wd<n>/<site>" (<tenant>.wd<n>.myworkdayjobs.com/<site>): graduate employers'
# careers sites (October 2026). Accenture's (accenture/wd103/AccentureCareers) refuses searches (429) and isn't here.
_WORKDAY_BOARDS: list[tuple[str, str]] = [
    # early-careers sites
    ("lbg/wd3/Graduate_careers",                      "Lloyds Banking Group"),
    ("lseg/wd3/Graduate_Careers",                     "LSEG"),
    ("mufgub/wd3/MUFG-EarlyCareers",                  "MUFG"),
    ("visa/wd5/Visa_Early_Careers",                   "Visa"),
    ("rollsroyce/wd3/Intern_Graduate",                "Rolls-Royce"),
    ("fca/wd3/FCA_earlycareers",                      "Financial Conduct Authority"),
    ("abrdn/wd3/AberdeenEarlyCareer",                 "abrdn"),
    # whole careers sites
    ("citi/wd5/2",                                    "Citi"),
    ("barclays/wd3/External_Career_Site_Barclays",    "Barclays"),
    ("rbs/wd3/RBS",                                   "NatWest Group"),
    ("capitalone/wd12/Capital_One",                   "Capital One"),
    ("allstate/wd5/allstate_careers",                 "Allstate"),
    ("hiscox/wd3/Hiscox_External_Site",               "Hiscox"),
    ("quilter/wd3/External-Career-Site",              "Quilter"),
    ("hyperiongrp/wd3/hyperion_external",             "Howden"),
    ("fticonsulting/wd108/FTIConsultingCareers",      "FTI Consulting"),
    ("clearwateranalytics/wd1/Clearwater_Analytics_Careers", "Clearwater Analytics"),
    ("thales/wd3/Careers",                            "Thales"),
    ("gevernova/wd5/Vernova_ExternalSite",            "GE Vernova"),
    ("motorolasolutions/wd5/Careers",                 "Motorola Solutions"),
    ("crowdstrike/wd5/crowdstrikecareers",            "CrowdStrike"),
    ("aveva/wd3/AVEVA_careers",                       "AVEVA"),
    ("expedia/wd108/search",                          "Expedia"),
    ("bpinternational/wd3/bpCareers",                 "bp"),
    ("shell/wd3/ShellCareers",                        "Shell"),
    ("centrica/wd3/Centrica",                         "Centrica"),
    ("neso/wd103/Careers",                            "NESO"),
    ("glencorecorp/wd3/External",                     "Glencore"),
    ("unilever/wd3/Unilever_Experienced_Professionals", "Unilever"),
    ("ayvens/wd3/AyvensCareers",                      "Ayvens"),
    ("alfa/wd3/Alfa",                                 "Alfa"),
]

async def _fetch_greenhouse(slug: str, company: str, keywords: list[str]) -> list[dict]:
    try:
        # content=true is required — without it the API omits the JD entirely.
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        async with http_client.async_client(timeout=8.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        # Big boards return every posting's full HTML (several MB); decoding + HTML-to-text +
        # exposure scoring is ~1s of CPU, so do it off the event loop.
        return await asyncio.to_thread(_greenhouse_jobs, resp.content, company, keywords)
    except Exception:
        return []


def _greenhouse_jobs(raw: bytes, company: str, keywords: list[str]) -> list[dict]:
    data = json.loads(raw)
    jobs = []
    for item in data.get("jobs", []):
        title = item.get("title", "")
        if not _title_matches_query(title, keywords):
            continue
        jobs.append({
            "job_id": f"gh-{item.get('id', '')}",
            "title": title,
            "company": company,
            "location": _greenhouse_location(item),
            "description": _html_to_text(item.get("content") or "")[:_DESC_MAX],
            "url": item.get("absolute_url", ""),
            "salary_min": None,
            "salary_max": None,
            "exposure_score": round(occupation_exposure(title), 3),
        })
    return jobs


async def _fetch_ashby(slug: str, company: str, keywords: list[str]) -> list[dict]:
    try:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        async with http_client.async_client(timeout=8.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        jobs = []
        for item in data.get("jobs", []):
            title = item.get("title", "")
            if not _title_matches_query(title, keywords):
                continue
            location = _ashby_location(item)
            desc_raw = item.get("descriptionPlain") or item.get("description") or ""
            desc = re.sub(r"<[^>]+>", " ", desc_raw)[:_DESC_MAX]
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


async def _fetch_lever(slug: str, company: str, keywords: list[str], eu: bool = False) -> list[dict]:
    """A Lever board; `eu` for one on Lever's EU instance (jobs.eu.lever.co), whose postings only its own API has."""
    try:
        url = f"https://api.{'eu.' if eu else ''}lever.co/v0/postings/{slug}?mode=json"
        async with http_client.async_client(timeout=8.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        jobs = []
        for item in data:
            title = item.get("text", "")
            if not _title_matches_query(title, keywords):
                continue
            loc = _place_and_setting([(item.get("categories") or {}).get("location") or item.get("country") or ""],
                                     item.get("workplaceType") or "")
            desc_raw = item.get("descriptionPlain") or ""
            jobs.append({
                "job_id": f"lever-{item.get('id', '')}",
                "title": title,
                "company": company,
                "location": loc,
                "description": re.sub(r"<[^>]+>", " ", desc_raw)[:_DESC_MAX],
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
        async with http_client.async_client(timeout=8.0) as client:
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
                "location": loc,
                "description": re.sub(r"<[^>]+>", " ", desc_raw)[:_DESC_MAX],
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
        async with http_client.async_client(timeout=10.0) as client:
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
                        "location": loc,
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

# ── Workday ───────────────────────────────────────────────────────────────────
# A Workday careers site searches through a public JSON service, the one its own pages call: POST
# .../wday/cxs/<tenant>/<site>/jobs lists postings (20 a call at most, no description) and GET
# .../wday/cxs/<tenant>/<site><externalPath> is one posting. Boards are big and worldwide (Citi lists 2000+), so
# each is searched with the collection's queries rather than read whole, and only postings whose title matches and
# that may be in the searched locations are read in full.

_WORKDAY_PAGE = 20           # postings a search call returns (Workday's most)
_WORKDAY_PAGES = 2           # search calls per query and board: its 40 best matches
_WORKDAY_READS = 25          # postings read in full per board and collection
_WORKDAY_CONCURRENCY = 4     # Workday calls at once, across every board
_WORKDAY_BACKOFF_S = 3.0     # wait before the one retry of a call a site refused as too many (429)
_MULTI_PLACE = re.compile(r"^\s*\d+\s+locations?\s*$", re.I)   # "2 Locations": the posting says which


async def _workday_call(client: httpx.AsyncClient, gate: asyncio.Semaphore, method: str, url: str,
                        **kwargs) -> httpx.Response:
    """One call, under `gate`; a 429 is waited out once before it's given up."""
    for attempt in range(2):
        async with gate:
            resp = await client.request(method, url, **kwargs)
        if resp.status_code != 429 or attempt:
            return resp
        await asyncio.sleep(_WORKDAY_BACKOFF_S)
    return resp


async def _fetch_workday(slug: str, company: str, keywords: list[str], queries: list[str] = (),
                         locations: list[str] | None = None, gate: asyncio.Semaphore | None = None) -> list[dict]:
    """
    A Workday board ("<tenant>/wd<n>/<site>"), searched with each of `queries`: each posting whose title matches
    `keywords` and that may be in `locations` (its place is one of them, or it lists several) is read in full, at
    most _WORKDAY_READS. A site still refusing calls (429) after a wait keeps what was read before.
    """
    tenant, wd, site = slug.split("/")
    host = f"https://{tenant}.{wd}.myworkdayjobs.com"
    base = f"{host}/wday/cxs/{tenant}/{site}"
    gate = gate or asyncio.Semaphore(_WORKDAY_CONCURRENCY)
    jobs: list[dict] = []
    try:
        async with http_client.async_client(timeout=15.0, headers={"Accept": "application/json"}) as client:
            listed: dict[str, dict] = {}
            for query in queries or [" ".join(keywords)]:
                for page in range(_WORKDAY_PAGES):
                    resp = await _workday_call(client, gate, "POST", f"{base}/jobs", json={
                        "appliedFacets": {}, "limit": _WORKDAY_PAGE, "offset": page * _WORKDAY_PAGE,
                        "searchText": query})
                    if resp.status_code == 429:
                        logger.info("Workday %s: refused as too many calls; searching it next time", slug)
                        return jobs
                    resp.raise_for_status()
                    postings = resp.json().get("jobPostings") or []
                    for posting in postings:
                        if posting.get("externalPath"):
                            listed.setdefault(posting["externalPath"], posting)
                    if len(postings) < _WORKDAY_PAGE:
                        break
            wanted = [p for p in listed.values() if _title_matches_query(p.get("title") or "", keywords)
                      and (_MULTI_PLACE.match(p.get("locationsText") or "")
                           or jobs_db.in_locations(p.get("locationsText") or "", locations or []))]
            for posting in wanted[:_WORKDAY_READS]:
                resp = await _workday_call(client, gate, "GET", base + posting["externalPath"])
                if resp.status_code == 429:
                    logger.info("Workday %s: refused as too many calls after %d postings", slug, len(jobs))
                    break
                if resp.status_code != 200:
                    continue
                info = resp.json().get("jobPostingInfo") or {}
                title = info.get("title") or posting.get("title") or ""
                places = [info.get("location") or posting.get("locationsText") or "",
                          *(info.get("additionalLocations") or [])]
                jobs.append({
                    "job_id": f"workday-{tenant}-{info.get('jobReqId') or info.get('id') or posting['externalPath']}",
                    "title": title,
                    "company": company,
                    "location": _place_and_setting(places, info.get("remoteType") or ""),
                    "description": _html_to_text(info.get("jobDescription") or "")[:_DESC_MAX],
                    "url": info.get("externalUrl") or f"{host}/{site}{posting['externalPath']}",
                    "salary_min": None,
                    "salary_max": None,
                    "exposure_score": round(occupation_exposure(title), 3),
                })
        return jobs
    except Exception as exc:
        logger.debug("Workday %s failed: %s", slug, type(exc).__name__)
        return jobs


def listed_boards() -> list[tuple[str, str, str]]:
    """(ats, slug, company) of every board listed in this module."""
    lists = {"greenhouse": _GREENHOUSE_COMPANIES, "ashby": _ASHBY_COMPANIES, "lever": _LEVER_COMPANIES,
             "lever_eu": _LEVER_EU_COMPANIES, "workable": _WORKABLE_COMPANIES,
             "smartrecruiters": _SMARTRECRUITERS_COMPANIES, "workday": _WORKDAY_BOARDS}
    return [(ats, slug, company) for ats, listed in lists.items() for slug, company in listed]


def _all_boards(found: list[tuple[str, str, str]] = (), gone: set[tuple[str, str]] = frozenset()
                ) -> dict[str, list[tuple[str, str]]]:
    """{ats: [(slug, company)]}: the listed boards plus `found` ones ((ats, slug, company)), without the
    `gone` ones ((ats, slug) a check found removed)."""
    boards: dict[str, list[tuple[str, str]]] = {}
    gone = {(ats, slug.lower()) for ats, slug in gone or ()}
    seen: set[tuple[str, str]] = set()
    for ats, slug, company in [*listed_boards(), *(found or ())]:
        key = (ats, slug.lower())
        if key in seen or key in gone:
            continue
        seen.add(key)
        boards.setdefault(ats, []).append((slug, company))
    return boards


async def _search_level2_ats_apis(queries: list[str], boards: dict[str, list[tuple[str, str]]] | None = None,
                                  locations: list[str] | None = None) -> list[dict]:
    """
    Concurrently fetch from Greenhouse, Ashby, Lever, Workable, SmartRecruiters and Workday public APIs: `boards`
    ({ats: [(slug, company)]}, see _all_boards), by default the listed ones. Filters each company's
    listings by query keyword relevance in a single pass; Workday boards are searched with `queries` and read
    in full only for postings that may be in `locations` (see _fetch_workday).
    """
    all_keywords = []
    for q in queries:
        all_keywords.extend(_query_keywords(q))

    keywords = list(set(all_keywords))
    if not keywords:
        return []

    async def fetch_lever_eu(slug: str, company: str, keywords: list[str]) -> list[dict]:
        return await _fetch_lever(slug, company, keywords, eu=True)

    workday_gate = asyncio.Semaphore(_WORKDAY_CONCURRENCY)   # every Workday board's calls share it

    async def fetch_workday(slug: str, company: str, keywords: list[str]) -> list[dict]:
        return await _fetch_workday(slug, company, keywords, queries, locations, workday_gate)

    fetchers = {"greenhouse": _fetch_greenhouse, "ashby": _fetch_ashby, "lever": _fetch_lever,
                "lever_eu": fetch_lever_eu, "workable": _fetch_workable, "smartrecruiters": _fetch_smartrecruiters,
                "workday": fetch_workday}
    every = _all_boards() if boards is None else boards
    tasks = [fetchers[ats](slug, name, keywords) for ats, listed in every.items() if ats in fetchers
             for slug, name in listed]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    jobs: list[dict] = []
    for r in results:
        if isinstance(r, list):
            jobs.extend(r)

    logger.info("Level 2 (ATS APIs): %d jobs matched against %d keywords across %d companies",
                len(jobs), len(keywords), len(tasks))
    return jobs


# ── Finding job boards ────────────────────────────────────────────────────────
# Listed boards go stale (26 of them had gone by October 2026, eight to another provider) and cover a
# fraction of employers. find_board looks an employer up by name on the providers with public job APIs,
# so an employer seen through the aggregators or the web search gets its full listings from then on;
# check_board tells whether a known board is still there.

_BOARD_API = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "lever_eu": "https://api.eu.lever.co/v0/postings/{slug}?mode=json",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{slug}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100",
}
_FIND_ON = ("greenhouse", "ashby", "lever")
_BOARD_NAME_DROP = re.compile(r"\b(?:ltd|limited|plc|llp|llc|inc|corp|corporation|uk|group|holdings|the)\b")
_NOT_AN_EMPLOYER = re.compile(r"^(?:unknown|confidential|anonymous|undisclosed|recruit\w*|staffing|careers?|jobs?|"
                              r"hiring|.*myworkdayjobs.*)$", re.I)


def _board_slugs(company: str) -> list[str]:
    """Slugs an employer's board is likely under: "Squarepoint Capital LLP" -> squarepointcapital,
    squarepoint-capital. Never a single word of a longer name ("Squarepoint"): too many other boards."""
    words = re.findall(r"[a-z0-9]+", _BOARD_NAME_DROP.sub(" ", re.sub(r"\(.*?\)", " ", company.lower())))
    return [s for s in dict.fromkeys(["".join(words), "-".join(words)]) if len(s) >= 4]


def _board_jobs(ats: str, data) -> list[dict]:
    if ats in ("lever", "lever_eu"):
        return data if isinstance(data, list) else []
    if ats == "smartrecruiters":
        return data.get("content") or []
    return data.get("jobs") or []


def _names(company: str, text: str) -> bool:
    """Whether `text` names the employer: its normalised name as whole words."""
    name = normalise_company_name(company)
    return bool(name) and re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])",
                                    normalise_company_name(text)) is not None


async def _board_is(client: httpx.AsyncClient, ats: str, slug: str, company: str) -> int | None:
    """How many jobs `slug` on `ats` has if it is `company`'s board (with at least one job), else None.
    A slug can be someone else's board: Greenhouse gives the board's name, which must be the employer's;
    elsewhere one of its ads must name the employer."""
    resp = await client.get(_BOARD_API[ats].format(slug=slug))
    if resp.status_code != 200:
        return None
    jobs = _board_jobs(ats, resp.json())
    if not jobs:
        return None
    if ats == "greenhouse":
        board = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}")
        name = board.json().get("name", "") if board.status_code == 200 else ""
        if normalise_company_name(name) != normalise_company_name(company):
            return None
    else:
        texts = [f"{j.get('descriptionPlain') or j.get('description') or ''} {j.get('additionalPlain') or ''}"
                 for j in jobs[:5]]
        if not any(_names(company, t) for t in texts):
            return None
    return len(jobs)


async def find_board(client: httpx.AsyncClient, company: str) -> tuple[str, str, int] | None:
    """(ats, slug, jobs) of the employer's job board on Greenhouse, Ashby or Lever, else None."""
    if _NOT_AN_EMPLOYER.match((company or "").strip()) or len(normalise_company_name(company)) < 3:
        return None
    for slug in _board_slugs(company):
        for ats in _FIND_ON:
            try:
                jobs = await _board_is(client, ats, slug, company)
            except Exception as exc:
                logger.debug("board lookup %s/%s failed: %s", ats, slug, type(exc).__name__)
                continue
            if jobs:
                return ats, slug, jobs
    return None


async def check_board(client: httpx.AsyncClient, ats: str, slug: str) -> int | None:
    """How many jobs a known board has now, or None when it's gone (404). Raises on anything else, so a
    passing error never drops a board."""
    if ats == "workday":   # a search for anything, one posting long: its total
        tenant, wd, site = slug.split("/")
        resp = await client.post(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs",
                                 json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return int(resp.json().get("total") or 0)
    resp = await client.get(_BOARD_API[ats].format(slug=slug))
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return len(_board_jobs(ats, resp.json()))


async def refresh_boards(lookups: list[str], checks: list[tuple[str, str]]) -> dict:
    """Look `lookups` (employer names) up and check `checks` ((ats, slug)), a few at a time:
    {"found": [(ats, slug, company, jobs)], "missed": [company], "alive": [(ats, slug, jobs)],
    "gone": [(ats, slug)]}."""
    gate = asyncio.Semaphore(4)
    out: dict = {"found": [], "missed": [], "alive": [], "gone": []}
    async with http_client.async_client(timeout=15.0) as client:
        async def look(company: str) -> None:
            async with gate:
                hit = await find_board(client, company)
            if hit:
                out["found"].append((hit[0], hit[1], company, hit[2]))
            else:
                out["missed"].append(company)

        async def check(ats: str, slug: str) -> None:
            async with gate:
                try:
                    jobs = await check_board(client, ats, slug)
                except Exception as exc:
                    logger.debug("board check %s/%s failed: %s", ats, slug, type(exc).__name__)
                    return
            if jobs is None:
                out["gone"].append((ats, slug))
            else:
                out["alive"].append((ats, slug, jobs))

        await asyncio.gather(*[look(c) for c in lookups], *[check(a, s) for a, s in checks])
    logger.info("Boards: %d of %d employers found (%s), %d of %d checked boards gone (%s)",
                len(out["found"]), len(lookups), [f"{a}/{s}" for a, s, _, _ in out["found"]],
                len(out["gone"]), len(checks), [f"{a}/{s}" for a, s in out["gone"]])
    return out


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


# A web search result's page title ends in whatever the site appends: on a careers site or job board
# that's the site ("Myworkdayjobs.com", "Wellfound"), a date ("Updated Daily") or a place ("Edinburgh"),
# rarely the employer. The page's address says who the employer is on most of them, and on job boards
# whether the page is one posting or a page of them.

# Workday tenants searched in _SEARCH_QUERIES (<tenant>.wd<n>.myworkdayjobs.com).
_WORKDAY_TENANTS = {
    "barclays": "Barclays", "lbg": "Lloyds Banking Group", "rbs": "NatWest Group", "citi": "Citi",
    "mufgub": "MUFG", "td": "TD Securities", "capitalone": "Capital One", "blackstone": "Blackstone",
    "pimco": "PIMCO", "hl": "Houlihan Lokey", "juliusbaer": "Julius Baer", "mgpru": "M&G", "pru": "Prudential",
    "lseg": "LSEG", "abrdn": "abrdn", "bailliegifford": "Baillie Gifford", "fca": "Financial Conduct Authority",
    "frontiereconomics": "Frontier Economics", "nasdaq": "Nasdaq", "dowjones": "Dow Jones", "nvidia": "NVIDIA",
    "autodesk": "Autodesk", "salesforce": "Salesforce", "snyk": "Snyk", "crowdstrike": "CrowdStrike",
    "aveva": "AVEVA", "factset": "FactSet", "cadence": "Cadence", "kla": "KLA", "rollsroyce": "Rolls-Royce",
    "ag": "Airbus", "mbda": "MBDA", "shell": "Shell", "thales": "Thales", "motorolasolutions": "Motorola Solutions",
    "kbr": "KBR", "centrica": "Centrica", "expedia": "Expedia", "relx": "RELX", "ing": "ING",
    "libertyglobal": "Liberty Global", "quilter": "Quilter", "tencent": "Tencent", "hiscox": "Hiscox",
    "gresearch": "G-Research",
}
# Careers sites that are one employer's.
_CAREER_SITES = {
    "careers.arm.com": "Arm", "careers.mastercard.com": "Mastercard", "jobs.pwc.co.uk": "PwC",
    "jobsearch.baesystems.com": "BAE Systems", "capgemini.com": "Capgemini", "lifeattiktok.com": "TikTok",
    "careers.arup.com": "Arup", "kkr.com": "KKR", "wise.jobs": "Wise", "jobs.bendingspoons.com": "Bending Spoons",
    "janestreet.com": "Jane Street", "blackrock.tal.net": "BlackRock", "jefferies.tal.net": "Jefferies",
    "tfl.taleo.net": "Transport for London",
}
# Job boards: the address of one posting (anything else on them is a search, a list or an article),
# and where it names the employer.
_BOARD_POSTINGS = {
    "gradcracker.com": re.compile(r"/hub/\d+/[a-z0-9-]+/[a-z-]+/\d+"),
    "targetjobs.co.uk": re.compile(r"^/jobs/[a-z0-9-]+-\d+/?$"),
    "totaljobs.com": re.compile(r"^/job/"),
    "reed.co.uk": re.compile(r"^/jobs/[a-z0-9-]+/\d+"),
    "wellfound.com": re.compile(r"^/jobs/\d+"),
}
_BOARD_EMPLOYER = {
    "gradcracker.com": re.compile(r"/hub/\d+/([a-z0-9-]+)/"),
    "totaljobs.com": re.compile(r"^/job/[^/]+/([a-z0-9-]+?)-job\d+"),
}
_NOT_A_NAME = re.compile(r"myworkdayjobs|workday|wellfound|gradcracker|targetjobs|totaljobs|reed\.co|\bcareers?\b|"
                         r"\bjobs?\b|\bupdated\b|\b(?:19|20)\d\d\b|\bstart\b|\bfull-time\b|^unknown$", re.I)
_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"


def _site(url: str) -> tuple[str, str]:
    """(host without www., path) of a URL."""
    from urllib.parse import urlparse
    parsed = urlparse(url or "")
    return (parsed.hostname or "").removeprefix("www."), parsed.path or ""


def _is_a_posting(url: str) -> bool:
    """False for a job board's or careers site's search, list or article pages (one posting has an
    address of its own); True elsewhere."""
    host, path = _site(url)
    for board, posting in _BOARD_POSTINGS.items():
        if host == board or host.endswith("." + board):
            return bool(posting.search(path))
    if host.endswith(".myworkdayjobs.com") or host == "careers.arm.com":
        return "/job/" in path or "/details/" in path
    return True


def _employer_and_place(tail: str, url: str) -> tuple[str, str]:
    """(employer, place) for a web search result: the employer from the address where it says, else the
    title's tail unless that names the site, a date or a place; a place it names is the job's location."""
    host, path = _site(url)
    tail = (tail or "").strip()
    m = re.match(r"([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com$", host)
    if m:
        return _WORKDAY_TENANTS.get(m.group(1), m.group(1).title()), ""
    for site, name in _CAREER_SITES.items():
        if host == site or host.endswith("." + site):
            return name, ""
    for board, employer in _BOARD_EMPLOYER.items():
        if host == board or host.endswith("." + board):
            m = employer.search(path)
            if m:
                return m.group(1).replace("-", " ").title(), ""
    # "Data Science & AI Graduate Scheme - Edinburgh": the tail is where, not who.
    uk = jobs_db._location_matcher("United Kingdom")[2]
    if tail and uk(tail.lower()):
        return "Unknown", tail
    if not tail or _NOT_A_NAME.search(tail) or re.search(_MONTHS + r"\b", tail, re.I) and re.search(r"\d", tail):
        return "Unknown", ""
    return tail, ""


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
            title, tail = _parse_search_title(raw_title)
            # Skip obvious non-job pages (pagination, homepages, etc.)
            if len(title) < 5 or title.lower() in {"jobs", "careers", "open positions"}:
                continue
            if not _is_a_posting(url):
                continue
            company, place = _employer_and_place(tail, url)
            jobs.append({
                "job_id": f"brave-{abs(hash(url)) % 10**8}",
                "title": title,
                "company": company,
                "location": _location_from_url(url) or place,
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

    async with http_client.async_client() as client:
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
        async with http_client.async_client(timeout=10.0) as client:
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
        loc_str = ", ".join(item.get("locations", []))
        
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

_COUNTRY_NAMES = re.compile(r"^\s*(?:uk|u\.k\.|united kingdom|gb|great britain|britain|"
                            r"us|usa|united states|australia|canada)\s*$", re.I)


def _names_a_country(location: str) -> bool:
    """A location that is a whole country the aggregators index by ("United Kingdom"), not a place in one."""
    return bool(_COUNTRY_NAMES.match(location or ""))


def _aggregator_areas(locations: list[str]) -> list[str]:
    """The locations to run the per-location aggregators over: a UK city is left out when the UK itself
    is searched (one UK-wide call covers it), so London + United Kingdom is one area, not two."""
    uk_wide = any(_names_a_country(l) and jobs_db.in_locations("united kingdom", [l]) for l in locations)
    if not uk_wide:
        return list(locations)
    uk = jobs_db._location_matcher("United Kingdom")[2]
    return [l for l in locations if _names_a_country(l) or not uk(l.lower())]


async def _search_level4_adzuna(query: str, location: str) -> list[dict]:
    if not (ADZUNA_APP_ID and ADZUNA_API_KEY):
        return []

    # Map location to country code
    # Whole-word matching: a substring test sent "Australia" (contains "us") to the US index.
    country = "gb"
    loc_lower = location.lower()
    def _mentions(*names: str) -> bool:
        return any(re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", loc_lower) for n in names)
    if _mentions("australia", "sydney", "melbourne"):
        country = "au"
    elif _mentions("canada", "toronto", "vancouver"):
        country = "ca"
    elif _mentions("usa", "us", "united states", "san francisco", "new york", "seattle"):
        country = "us"

    base_url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    # Adzuna ANDs the words of `what` across the whole ad, so a seniority word cuts the results to almost
    # nothing ("Graduate Software Engineer" in London: 2); its graduate category finds those roles
    # instead (UK-wide: 347). A country isn't a `where` it knows ("United Kingdom": 0): its index is
    # already that country.
    what = re.sub(r"\s+", " ", _SENIORITY_WORDS.sub(" ", _BOOLEAN_OPS.sub(" ", query))).strip() or query.strip()
    where = "" if _names_a_country(location) else location
    searches = [{"what": what}]
    if country == "gb":
        searches.append({"what": what, "category": "graduate-jobs"})

    async def _fetch(extra: dict) -> list[dict]:
        params = {
            "app_id": ADZUNA_APP_ID,
            "app_key": ADZUNA_API_KEY,
            "results_per_page": 50,
            "sort_by": "relevance",
            **({"where": where} if where else {}),
            **extra,
        }
        async with http_client.async_client(timeout=12.0) as client:
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
        jobs = []
        for extra in searches:  # one at a time: the API has a per-minute limit
            jobs += await _fetch(extra)
        jobs = _deduplicate(jobs)
        logger.info("Level 4 (Adzuna %s): %d jobs for %r in %r", country, len(jobs), what, where or country)
        return jobs
    except httpx.HTTPStatusError as exc:
        # Not the exception's text: it carries the request URL, and with it app_id and app_key.
        logger.warning("Adzuna %s search failed for %r in %r: HTTP %s", country, query, location,
                       exc.response.status_code)
        return []
    except Exception as exc:
        logger.warning("Adzuna %s search failed for %r in %r: %s", country, query, location, type(exc).__name__)
        return []


# ── Deduplication ─────────────────────────────────────────────────────────────

def _deduplicate(jobs: list[dict]) -> list[dict]:
    """The first of each posting: same title and employer (legal suffixes aside, so an aggregator's
    "Squarepoint Capital LLP" is the board's "Squarepoint Capital"), or same URL. Callers put the employers'
    own boards before the aggregators, so the copy that can be applied to is the one kept."""
    seen_keys: set[tuple] = set()
    seen_urls: set[str] = set()
    out = []
    for job in jobs:
        key = (job.get("title", "").lower()[:40], normalise_company_name(job.get("company", ""))[:30])
        url = job.get("url", "")
        if key in seen_keys or (url and url in seen_urls):
            continue
        seen_keys.add(key)
        if url:
            seen_urls.add(url)
        out.append(job)
    return out


# ── Public interface ──────────────────────────────────────────────────────────

async def search_jobs_multi(query: str, locations: list[str], web_search: bool = True,
                            boards: dict[str, list[tuple[str, str]]] | None = None) -> list[dict]:
    """One search over `locations` (see collect_jobs)."""
    return await collect_jobs([query], locations, web_search=web_search, boards=boards)


async def _no_jobs() -> list[dict]:
    return []


_ADZUNA_CONCURRENCY = 2


async def collect_jobs(queries: list[str], locations: list[str], web_search: bool = True,
                       boards: dict[str, list[tuple[str, str]]] | None = None) -> list[dict]:
    """
    Run every source once for all `queries`: the career pages, job boards and web search are fetched
    once and matched against every query locally; only the aggregators (level 4: Adzuna and Workable's
    job board), which search server-side, run per (query, location). Keep the jobs in `locations`,
    deduplicate, apply the title filter, sort seniority-boosted titles first, and return every match.
    `web_search=False` skips level 3: its site: searches don't depend on the queries, so callers run it
    once a day. `boards` are the job boards to fetch ({ats: [(slug, company)]}, see _all_boards), by
    default the listed ones. Falls back to fixture if all live sources return nothing.
    """
    queries = [q for q in dict.fromkeys((q or "").strip() for q in queries) if q]
    keywords = list(dict.fromkeys(k for q in queries for k in _query_keywords(q)))
    pairs = [(q, area) for area in _aggregator_areas(locations) for q in queries]
    # A collection makes Adzuna calls per (query, location); all at once trips its rate limit (429).
    gate = asyncio.Semaphore(_ADZUNA_CONCURRENCY)

    async def aggregators(q: str, area: str) -> list[dict]:
        async def adzuna() -> list[dict]:
            async with gate:
                return await _search_level4_adzuna(q, area)
        found = await asyncio.gather(adzuna(), _search_level4_workable(q, area))
        return [job for jobs in found for job in jobs]

    # Only the aggregators (level 4) take a location: run levels 1-3 once and fan level 4
    # out over the locations, rather than repeating the whole search per location.
    l1, l2, l3, *l4_per_pair = await asyncio.gather(
        _search_level1_playwright(keywords),
        _search_level2_ats_apis(queries, boards, locations),
        _search_level3_websearch() if web_search else _no_jobs(),
        *[aggregators(q, area) for q, area in pairs],
    )
    l4_per_location: dict[str, list[dict]] = {}
    for (_, area), jobs in zip(pairs, l4_per_pair):
        l4_per_location.setdefault(area, []).extend(jobs)
    l4 = [job for jobs in l4_per_pair for job in jobs]
    found = len(l1) + len(l2) + len(l3) + len(l4)

    # Only jobs in the searched locations (or remote, or whose source didn't say where) are kept: the
    # feed shows only those, and every stored job is embedded and read by the attribute model (an LLM
    # call each). This runs before deduplicating, so the same title at the same company elsewhere
    # can't stand in for the posting here.
    def here(jobs: list[dict]) -> list[dict]:
        return [j for j in jobs if jobs_db.in_locations(j.get("location") or "", locations)]

    # The same title at the same company in two locations is two postings, so each location's
    # results are deduplicated against levels 1-3 and within themselves, but not against each
    # other. _deduplicate keeps order and `base` is already unique, so the slice is exactly
    # that location's new jobs.
    base = _deduplicate(here(l1 + l2 + l3))
    deduped = list(base)
    for jobs in l4_per_location.values():
        deduped += _deduplicate(base + here(jobs))[len(base):]

    if found and not deduped:
        logger.info("Job discovery: none of the %d jobs found are in %s", found, locations)
        return []
    if not deduped:
        logger.warning("All live sources returned 0 results — falling back to fixture")
        return [dict(j) for j in _FIXTURE]  # copies: callers mutate jobs

    # Apply title filter — fall back to unfiltered if filter removes everything
    filtered = [j for j in deduped if _passes_title_filter(j["title"], *queries)]
    if not filtered:
        logger.warning("Title filter removed all %d results — returning unfiltered", len(deduped))
        filtered = deduped

    # Seniority-boosted titles (Graduate, Junior…) float to the top
    filtered.sort(key=lambda j: _seniority_score(j["title"]), reverse=True)

    logger.info(
        "Job discovery for %s: L1=%d L2=%d L3=%d L4=%d → %d in %s after dedup → %d after filter",
        queries, len(l1), len(l2), len(l3), len(l4), len(deduped), locations, len(filtered),
    )
    return filtered
