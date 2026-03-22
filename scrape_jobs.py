"""
One-off script to scrape job details from job_links.json using Playwright.
Run inside the api Docker container:
  docker-compose exec api python /workspace/scrape_jobs.py

Outputs: /workspace/jobs_fixture.json
"""
import asyncio
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

LINKS_FILE = Path(__file__).parent / "job_links.json"
OUT_FILE   = Path(__file__).parent / "jobs_fixture.json"

TIMEOUT = 20_000  # ms per page


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


async def extract_job(page, url: str, index: int) -> dict:
    """Visit a URL and pull out title, company, description."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
        await page.wait_for_timeout(2000)  # let JS render
    except Exception as e:
        print(f"  [!] Failed to load: {e}")
        return {"job_id": f"j{index}", "url": url, "title": url, "company": "", "description": "", "error": str(e)}

    # ── Title ──────────────────────────────────────────────────────────────
    title = ""
    for sel in [
        "h1",
        "[data-testid='job-title']",
        ".job-title",
        ".posting-headline h2",
        ".job-details-jobs-unified-top-card__job-title",
        "[class*='JobTitle']",
        "[class*='job-title']",
        "[class*='jobtitle']",
        "meta[property='og:title']",
    ]:
        try:
            if sel.startswith("meta"):
                val = await page.get_attribute(sel, "content", timeout=1000)
            else:
                el = page.locator(sel).first
                val = await el.inner_text(timeout=2000)
            if val and val.strip():
                title = _clean(val)
                break
        except Exception:
            continue

    if not title:
        try:
            title = _clean(await page.title())
            # strip common suffixes like " | Careers | Company"
            title = re.split(r"\s*[|\-–—]\s*", title)[0].strip()
        except Exception:
            title = url

    # ── Company ────────────────────────────────────────────────────────────
    company = ""
    for sel in [
        "[data-testid='company-name']",
        ".company-name",
        ".employer-name",
        "[class*='CompanyName']",
        "[class*='company-name']",
        "[class*='employer']",
        "meta[property='og:site_name']",
        "meta[name='author']",
    ]:
        try:
            if sel.startswith("meta"):
                val = await page.get_attribute(sel, "content", timeout=1000)
            else:
                el = page.locator(sel).first
                val = await el.inner_text(timeout=2000)
            if val and val.strip():
                company = _clean(val)
                break
        except Exception:
            continue

    if not company:
        # Derive from domain
        m = re.search(r"https?://(?:www\.|apply\.|jobs\.|careers\.|job-boards\.[a-z]+\.)?([^./]+)", url)
        if m:
            company = m.group(1).replace("-", " ").title()

    # ── Description ────────────────────────────────────────────────────────
    description = ""
    for sel in [
        "[data-testid='job-description']",
        ".job-description",
        ".description",
        ".posting-description",
        "#job-description",
        "[class*='JobDescription']",
        "[class*='job-description']",
        "[class*='jobDescription']",
        "meta[property='og:description']",
        "meta[name='description']",
    ]:
        try:
            if sel.startswith("meta"):
                val = await page.get_attribute(sel, "content", timeout=1000)
            else:
                el = page.locator(sel).first
                val = await el.inner_text(timeout=3000)
            if val and len(val.strip()) > 80:
                description = _clean(val)[:600]
                break
        except Exception:
            continue

    if not description:
        # Last resort: grab body text and trim
        try:
            body = await page.locator("body").inner_text(timeout=3000)
            description = _clean(body)[:600]
        except Exception:
            description = ""

    result = {
        "job_id": f"j{index}",
        "title": title,
        "company": company,
        "location": "United Kingdom",
        "description": description,
        "url": url,
        "salary_min": None,
        "salary_max": None,
    }
    print(f"  title:   {title[:60]}")
    print(f"  company: {company}")
    print(f"  desc:    {description[:80]}…")
    return result


async def main():
    urls = [u.strip() for u in LINKS_FILE.read_text().splitlines() if u.strip()]
    print(f"Scraping {len(urls)} URLs…\n")

    jobs = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] {url}")
            job = await extract_job(page, url, i)
            jobs.append(job)
            print()

        await browser.close()

    OUT_FILE.write_text(json.dumps(jobs, indent=2, ensure_ascii=False))
    print(f"Saved {len(jobs)} jobs → {OUT_FILE}")


asyncio.run(main())
