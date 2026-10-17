"""
Does Windrush read job emails right, and leave alone what isn't about an application?

16 emails as graduate applicants get them (applicant tracking systems, company recruiters, agencies, job
boards, newsletters), each labelled with what it means and which application it is about. Every run writes
evals/last_email_run.json.

The bar: no email is matched to the wrong application; nothing unrelated (job alerts, newsletters, an agency's
pitch) changes an application; every confident reading that would change a status on its own is correct.
How many labelled emails were read correctly is reported, and must be at least 13 of 16.
"""
import asyncio
import json
import pathlib
import time

from app import gmail

HERE = pathlib.Path(__file__).parent

APPLICATIONS = [
    {"id": "catapult", "company": "Catapult", "job_title": "Graduate Software Engineer", "status": "Applied"},
    {"id": "cc", "company": "Cambridge Consultants", "job_title": "Graduate Cloud Software Engineer", "status": "Pending Review"},
    {"id": "dv", "company": "DV Trading", "job_title": "Graduate Software Engineer (DV Commodities)", "status": "Applied"},
    {"id": "baringa", "company": "Baringa", "job_title": "Graduate Analyst Programme - Energy & Resources", "status": "Applied"},
    {"id": "baringa2", "company": "Baringa", "job_title": "Graduate Analyst Programme - Public Sector Consulting", "status": "Applied"},
    {"id": "monzo", "company": "Monzo", "job_title": "Junior Backend Engineer", "status": "Interview"},
    {"id": "ocado", "company": "Ocado Technology", "job_title": "Graduate Software Developer", "status": "Applied"},
]

# (sender, subject, body, expected kind, expected application id or None)
EMAILS = [
    ("Catapult <no-reply@us.greenhouse-mail.io>", "Thank you for applying to Catapult",
     "Hi Timothy, thanks for applying to the Graduate Software Engineer role at Catapult. Our team will review your "
     "application and be in touch.", "received", "catapult"),
    ("Cambridge Consultants Talent <talent@cambridgeconsultants.com>", "Your application - Graduate Cloud Software Engineer",
     "Dear Timothy, thank you for your interest in Cambridge Consultants. After careful consideration we regret to "
     "inform you that we will not be taking your application further.", "rejected", "cc"),
    ("DV Trading Recruiting <recruiting@dvtrading.co>", "DV Trading - Online Assessment",
     "Hi Timothy, as the next step for the Graduate Software Engineer role please complete the HackerRank assessment "
     "within 5 days using the link below.", "assessment", "dv"),
    ("Baringa Graduate Recruitment <graduates@baringa.com>", "Baringa: Invitation to interview - Public Sector Consulting",
     "Dear Timothy, we are delighted to invite you to a first-round interview for our Public Sector Consulting "
     "Graduate Analyst Programme. Please book a slot via the link.", "interview", "baringa2"),
    ("Monzo <careers@monzo.com>", "Offer of employment - Junior Backend Engineer",
     "Hi Timothy! We're thrilled to offer you the Junior Backend Engineer role at Monzo. Your offer letter is attached.",
     "offer", "monzo"),
    ("Ocado Technology Careers <noreply@ocadogroup.com>", "We've received your application",
     "Thanks for applying to Ocado Technology's Graduate Software Developer programme. We review applications on a "
     "rolling basis.", "received", "ocado"),
    ("Ocado Technology <noreply@ocadogroup.com>", "Update on your application",
     "Hi Timothy, your application for Graduate Software Developer is still being reviewed. We appreciate your "
     "patience.", "other", "ocado"),
    ("Monzo <careers@monzo.com>", "Final round interview - scheduling",
     "Hi Timothy, great news: we'd like to move you to the final round. Could you share your availability next week?",
     "interview", "monzo"),
    ("LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", "Graduate Software Engineer at Catapult and 12 more jobs",
     "Jobs you may be interested in: Graduate Software Engineer - Catapult - London. Junior Developer - Monzo.",
     "unrelated", None),
    ("Indeed <alert@indeed.com>", "New jobs for Graduate Software Engineer in Bristol",
     "Ocado Technology is hiring a Graduate Software Developer. Apply now with your Indeed CV.", "unrelated", None),
    ("Baringa <news@baringa.com>", "Baringa Insights: The future of energy markets",
     "Our latest thinking on the energy transition. Read the report.", "unrelated", None),
    ("Sarah at TechRecruit <sarah@techrecruit.co.uk>", "Exciting graduate opportunity - interview this week?",
     "Hi Timothy, I'm recruiting for a fast-growing fintech in London and would love to arrange an interview with you.",
     "unrelated", None),
    ("Workday <notifications@myworkday.com>", "Your application to Globex Corporation",
     "Thank you for applying to Globex Corporation for the role of Software Engineer.", "received", None),
    ("Baringa Graduate Recruitment <graduates@baringa.com>", "Your Baringa application",
     "Dear Timothy, thank you for applying to Baringa. Unfortunately on this occasion we will not be progressing your "
     "application for the Energy & Resources programme.", "rejected", "baringa"),
    ("Catapult People Team <people@catapult.com>", "Catapult - interview invite",
     "Hi Timothy, the hiring team would like to invite you to a 45-minute technical interview for the Graduate "
     "Software Engineer position.", "interview", "catapult"),
    ("GitHub <noreply@github.com>", "[GitHub] A new SSH key was added to your account",
     "A new public key was added to your account.", "unrelated", None),
]


def _email(n, sender, subject, body):
    payload = {"headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}],
               "mimeType": "text/plain", "body": {}}
    message = {"id": f"m{n}", "threadId": f"t{n}", "internalDate": str(int(time.time() * 1000)), "snippet": body[:80],
               "payload": payload}
    email = gmail.parse(message)
    return {**email, "text": body}


def test_emails_are_read_and_matched_right():
    async def run():
        out = []
        for n, (sender, subject, body, kind, app_id) in enumerate(EMAILS, 1):
            email = _email(n, sender, subject, body)
            relevant = gmail.relevant(email, APPLICATIONS)
            reading = await gmail.read(email, APPLICATIONS) if relevant else {"kind": "unrelated", "application": None,
                                                                              "confidence": "high", "summary": ""}
            got = (reading["application"] or {}).get("id")
            target, safe = (gmail.proposed_change((reading["application"] or {}).get("status", ""), reading["kind"])
                            if reading["application"] else (None, False))
            out.append({"subject": subject, "expected": [kind, app_id], "got": [reading["kind"], got],
                        "confidence": reading["confidence"], "summary": reading.get("summary", ""),
                        "auto": bool(target and safe and reading["confidence"] == "high"), "relevant": relevant})
        return out

    results = asyncio.run(run())
    (HERE / "last_email_run.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    wrong_app = [r for r in results if r["got"][1] and r["got"][1] != r["expected"][1]]
    unrelated_changed = [r for r in results if r["expected"][0] == "unrelated" and r["auto"]]
    wrong_auto = [r for r in results if r["auto"] and r["got"] != r["expected"]]
    right = sum(r["got"] == r["expected"] for r in results)
    print(f"\n{right}/{len(results)} read right; wrong application {len(wrong_app)}; unrelated changed "
          f"{len(unrelated_changed)}; wrong automatic changes {len(wrong_auto)}")
    for r in results:
        if r["got"] != r["expected"]:
            print("  MISS", r["subject"], r["expected"], "->", r["got"], r["confidence"])
    assert not wrong_app, wrong_app
    assert not unrelated_changed, unrelated_changed
    assert not wrong_auto, wrong_auto
    assert right >= 13
