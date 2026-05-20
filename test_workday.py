"""
Test a sample of the new Brave search queries to verify they actually return job results.
"""
import httpx, os

BRAVE_KEY = "BSALbA_u26h_eOUL3akzExgKoBy6mAi"
BRAVE_BASE = "https://api.search.brave.com/res/v1/web/search"

# Sample one query from each group
test_queries = [
    (
        "Workday Finance (Barclays/Lloyds/Citi/NatWest)",
        'site:barclays.wd3.myworkdayjobs.com OR site:lbg.wd3.myworkdayjobs.com'
        ' OR site:rbs.wd3.myworkdayjobs.com OR site:citi.wd5.myworkdayjobs.com'
        ' "Graduate" OR "Junior" OR "Associate" "Technology" OR "Software" OR "Data" OR "Engineer"',
    ),
    (
        "Workday Tech (Nvidia/Autodesk/Salesforce/Snyk/CrowdStrike)",
        'site:nvidia.wd5.myworkdayjobs.com OR site:autodesk.wd1.myworkdayjobs.com'
        ' OR site:salesforce.wd12.myworkdayjobs.com OR site:snyk.wd103.myworkdayjobs.com'
        ' OR site:crowdstrike.wd5.myworkdayjobs.com OR site:aveva.wd3.myworkdayjobs.com'
        ' "Graduate" OR "Junior" OR "New Grad" "Software Engineer" OR "Data" OR "ML" OR "Platform"',
    ),
    (
        "Workday Aerospace (Rolls-Royce/Shell/Airbus/Thales)",
        'site:rollsroyce.wd3.myworkdayjobs.com OR site:ag.wd3.myworkdayjobs.com'
        ' OR site:shell.wd3.myworkdayjobs.com OR site:thales.wd3.myworkdayjobs.com'
        ' "Graduate" OR "Junior" "Software" OR "Data" OR "Systems Engineer" OR "Technology"',
    ),
    (
        "Custom Pages (ARM/Mastercard/PwC/BAE)",
        'site:careers.arm.com OR site:careers.mastercard.com OR site:jobs.pwc.co.uk'
        ' OR site:jobsearch.baesystems.com'
        ' "Graduate" OR "Junior" OR "Early Careers" "Software" OR "Technology" OR "Engineer" OR "Data"',
    ),
    (
        "Custom Pages (Wise/Jane Street/Bending Spoons)",
        'site:wise.jobs OR site:jobs.bendingspoons.com'
        ' OR site:www.janestreet.com/join-jane-street'
        ' "Graduate" OR "Junior" OR "New Grad" "Software" OR "Engineer" OR "Quant" OR "Developer"',
    ),
    (
        "TALnet (BlackRock/Jefferies)",
        'site:blackrock.tal.net OR site:jefferies.tal.net'
        ' "Graduate" OR "Junior" OR "Analyst" "Technology" OR "Software" OR "Data" OR "Engineering"'
        ' 2025 OR 2026',
    ),
    (
        "Gradcracker UK",
        'site:gradcracker.com "Software" OR "AI" OR "Data" OR "Cloud" OR "DevOps"'
        ' "Graduate" OR "Intern" London OR UK 2025 OR 2026',
    ),
    (
        "Wellfound startups",
        'site:wellfound.com "Junior" OR "Graduate" OR "Entry Level"'
        ' "Software Engineer" OR "AI Engineer" OR "ML Engineer" OR "Full Stack" OR "Backend"',
    ),
]

headers = {
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
    "X-Subscription-Token": BRAVE_KEY,
}

print(f"Testing {len(test_queries)} Brave queries...\n")
total_results = 0

for label, query in test_queries:
    try:
        r = httpx.get(
            BRAVE_BASE,
            headers=headers,
            params={"q": query, "count": 10, "search_lang": "en"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            results = data.get("web", {}).get("results", [])
            total_results += len(results)
            print(f"[OK] {label}")
            print(f"     {len(results)} results")
            for res in results[:3]:
                print(f"     -> {res.get('title','?')[:70]}")
                print(f"        {res.get('url','?')[:80]}")
        elif r.status_code == 429:
            print(f"[RATE LIMITED] {label}")
        elif r.status_code == 401:
            print(f"[AUTH ERROR] {label} - check API key")
        else:
            print(f"[{r.status_code}] {label}: {r.text[:100]}")
    except Exception as e:
        print(f"[ERROR] {label}: {e}")
    print()

print(f"Total results across all queries: {total_results}")
