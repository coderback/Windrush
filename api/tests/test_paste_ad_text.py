"""A job from an ad the user pasted, for a link Windrush can't read: their text is the ad, the link is kept, and
nothing is fetched or stored."""
from app import jobs_db

FCA = ("https://fca.wd3.myworkdayjobs.com/en-US/FCA_earlycareers/job/London/"
       "XMLNAME-2027-Data--Digital---Technology-Graduate-Programme---London_JR0022847?utm_source=Trackr")
AD = ("Join our 2027 Data, Digital & Technology Graduate Programme. You'll rotate through data engineering, "
      "software development and cyber teams, working with Python, SQL and cloud platforms. ") * 3


def test_a_pasted_ad_becomes_a_job_with_its_link(client, monkeypatch):
    def no_fetch(*a, **k):
        raise AssertionError("nothing is fetched")
    monkeypatch.setattr("app.http_client.async_client", no_fetch)
    job = client.post("/jobs/from-text", json={
        "url": FCA, "title": "  Data, Digital & Technology Graduate Programme ", "company": "Financial Conduct Authority",
        "description": AD}).json()["job"]
    assert (job["title"], job["company"], job["url"], job["source"]) == (
        "Data, Digital & Technology Graduate Programme", "Financial Conduct Authority", FCA, "user-text")
    assert job["location"] == "London" and job["level"] == "junior" and job["description"] == AD.strip()
    assert job["id"] and job["job_id"] and jobs_db.job_count() == 0


def test_markup_is_read_as_text_and_a_bad_link_is_dropped(client):
    job = client.post("/jobs/from-text", json={"url": "javascript:alert(1)", "title": "Analyst", "company": "FCA",
                                               "location": "Leeds", "description": f"<p>{AD}</p><script>x</script>"}).json()["job"]
    assert job["url"] == "" and job["location"] == "Leeds" and "<p>" not in job["description"]


def test_a_job_needs_a_title_an_employer_and_the_whole_ad(client):
    assert client.post("/jobs/from-text", json={"title": "", "company": "FCA", "description": AD}).status_code == 400
    short = client.post("/jobs/from-text", json={"title": "Analyst", "company": "FCA", "description": "Graduate role."})
    assert short.status_code == 400 and "whole ad" in short.json()["detail"]
