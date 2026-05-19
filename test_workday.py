import asyncio
from playwright.async_api import async_playwright

async def test():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Navigating...")
        await page.goto("https://salesforce.wd1.myworkdayjobs.com/en-US/External_Career_Site", wait_until="networkidle", timeout=30000)
        print("Extracting links...")
        links = await page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({href: e.href, text: (e.innerText || e.textContent || '').trim()}))"
        )
        for l in links:
            if 'job' in l['href'].lower() and len(l['text']) > 5:
                print(l)
        await browser.close()

asyncio.run(test())
