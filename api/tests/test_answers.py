"""Application questions: the answer bank, and answers taken only from what the user has given."""
import asyncio
import json
import re
from datetime import date

import pytest

import app.browser_agent as ba
from app import agent, answers, net_guard, tracker
from test_documents import GRADUATE

JOB = {"title": "Graduate Backend Engineer", "company": "Harbourline", "location": "London, UK",
       "description": "Python services with FastAPI and PostgreSQL for our ferry booking platform."}

PERSONA = {
    **GRADUATE,
    "core_info": {**GRADUATE["core_info"], "right_to_work_uk": True, "require_sponsorship": False,
                  "nationality": "British", "dob": "1999-04-02"},
    "screening": {"salary_canonical": "£31,500", "notice_period_canonical": "2 weeks"},
    "diversity": {"gender": "Woman", "ethnicity": "Black British"},
}
PRIVATE_VALUES = ["£31,500", "31,500", "sam@example.com", "+44 7700 900456", "Woman", "Black British", "1999-04-02"]


class FakeModel:
    """Stands in for agent._llm_json: `read` maps a question's text to its reading ({kind, fact_ids,
    answer}); written questions get `drafts` in turn (then `revisions`). Every prompt is kept in `.seen`."""

    def __init__(self, read=None, drafts=(), revisions=()):
        self.read, self.drafts, self.revisions = read or {}, list(drafts), list(revisions)
        self.seen: list[tuple[str, str]] = []

    async def __call__(self, system, user, max_tokens=2048, label=""):
        self.seen.append((label, system + "\n" + user))
        if label == "read_questions":
            if self.read is None:
                return None
            numbered = re.findall(r"^(\d+)\. (.+)$", user.split("QUESTIONS:\n", 1)[1], re.M)
            return {"answers": [{"n": int(n), **self.read[q]} for n, q in numbered if q in self.read]}
        if label == "write_answer":
            return {"answer": self.drafts.pop(0)} if self.drafts else None
        if label == "revise_answer":
            return {"answer": self.revisions.pop(0)} if self.revisions else None
        raise AssertionError(f"unexpected model call {label}")

    def prompts(self) -> str:
        return "\n".join(text for _, text in self.seen)


@pytest.fixture
def model(monkeypatch):
    def install(**kwargs):
        fake = FakeModel(**kwargs)
        monkeypatch.setattr(agent, "_llm_json", fake)
        return fake
    return install


def ask(questions, persona=PERSONA, bank=(), job=JOB, cover_letter=""):
    return asyncio.run(answers.answer_questions(questions, persona, list(bank), job, cover_letter))


def fact(*ids, answer=""):
    return {"kind": "fact", "fact_ids": list(ids), "answer": answer}


WRITTEN = {"kind": "written", "fact_ids": [], "answer": ""}


# ── Reading questions ─────────────────────────────────────────────────────────

def test_question_keys_ignore_case_punctuation_and_required_marks():
    assert (answers.question_key("Do you have the right to work in the UK? *")
            == answers.question_key("do you have the RIGHT to work in the UK (Required)")
            == "do you have the right to work in the uk")


@pytest.mark.parametrize("value, options, picked", [
    ("Yes", ["Yes, I have the right to work", "No, I don't"], "Yes, I have the right to work"),
    ("No", ["Yes", "No"], "No"),
    ("British", ["British", "British Indian Ocean Territory"], "British"),
    ("Prefer not to say", ["Man", "Woman", "I'd prefer not to say"], "I'd prefer not to say"),
    ("2 weeks", ["Immediately", "1 month", "2 weeks"], "2 weeks"),
    ("Yes", ["Yes - full time", "Yes - part time", "No"], None),       # two options say yes: not ours to pick
    ("£31,500", ["£25k-£30k", "£30k-£35k"], None),                     # a band isn't the value given
    ("Woman", ["Female", "Male"], None),
])
def test_an_option_is_picked_only_when_exactly_one_states_the_value(value, options, picked):
    assert answers.pick_option(value, options) == picked


@pytest.mark.parametrize("question, location, uk", [
    ("Do you have the right to work in the UK?", "", True),
    ("Are you legally authorised to work in Northern Ireland?", "Belfast", True),
    ("Are you authorized to work in the United States?", "London, UK", False),
    ("Do you need a visa to work in the EU?", "", False),
    ("Will you now or in the future require sponsorship? Tell us honestly.", "London, UK", True),
    ("Will you require sponsorship to work in the country where this role is based?", "New York, NY", False),
    ("Will you require sponsorship?", "Austin, TX", False),
    ("Will you require sponsorship?", "Remote", True),
    ("Will you require sponsorship?", "Cambridge, UK", True),
])
def test_a_uk_fact_answers_only_questions_about_the_uk(question, location, uk):
    assert answers.about_uk(question, location) is uk


# ── Checking the model's reading ──────────────────────────────────────────────

FACTS = {f.id: f for f in answers.profile_facts(PERSONA)}


def resolve(question, reading, options=(), location="London, UK"):
    return answers.resolve_fact({"question": question, "options": list(options)}, reading, FACTS, location)


def test_an_answer_must_rest_on_a_known_fact():
    assert resolve("Do you hold a full UK driving licence?", fact()) is None
    assert resolve("Do you hold a full UK driving licence?", fact("driving_licence", answer="Yes")) is None


def test_a_uk_fact_is_not_carried_to_another_country():
    assert resolve("Are you authorized to work in the US?", fact("right_to_work_uk", answer="Yes")) is None
    answer, rests_on = resolve("Do you have the right to work in the UK?", fact("right_to_work_uk", answer="Yes"),
                               ["Yes", "No"])
    assert answer == "Yes" and rests_on[0].id == "right_to_work_uk"


def test_a_yes_no_fact_keeps_its_polarity_unless_the_question_turns_it_round():
    # require_sponsorship is "No": a "Yes" to the plain question would be a false statement.
    assert resolve("Will you require visa sponsorship?", fact("require_sponsorship", answer="Yes"), ["Yes", "No"]) is None
    assert resolve("Will you require visa sponsorship?", fact("require_sponsorship", answer="No"),
                   ["Yes", "No"])[0] == "No"
    assert resolve("Can you work in the UK without sponsorship?", fact("require_sponsorship", answer="Yes"),
                   ["Yes", "No"])[0] == "Yes"


def test_private_values_are_filled_in_from_the_persona_not_the_model():
    assert resolve("Salary expectations", fact("salary_annual"))[0] == "£31,500"
    assert resolve("Gender", fact("gender"), ["Man", "Woman", "Prefer not to say"])[0] == "Woman"
    # The stored value isn't an option: left for the user, not mapped by guesswork.
    assert resolve("Gender", fact("gender"), ["Female", "Male"]) is None


@pytest.mark.parametrize("value, picked", [
    ("£31,500", "£30,000-£35,000"),
    ("£40k", "£35,000+"),
    ("£22,000", "Up to £25,000"),
    ("£30,000", None),                    # on the boundary of two bands: not ours to pick
    ("£32,000 - £36,000", None),          # a range that straddles two bands
    ("Negotiable", None),
])
def test_a_salary_goes_in_the_band_that_holds_it(value, picked):
    bands = ["Up to £25,000", "£25,000-£30,000", "£30,000-£35,000", "£35,000+"]
    assert answers.pick_band(value, bands) == picked


def test_a_salary_band_question_is_answered_from_the_salary_fact():
    assert resolve("Desired salary band", fact("salary_annual"), ["£25k-£30k", "£30k-£35k"])[0] == "£30k-£35k"
    assert resolve("Desired salary band", fact("salary_annual"), ["£20k-£25k", "£25k-£30k"]) is None
    # Bands decide on their own: text matching never breaks a tie on a boundary.
    on_boundary = {**FACTS, "salary_annual": answers.Fact("salary_annual", "Salary", "£30,000", private=True)}
    assert answers.resolve_fact({"question": "Salary band", "options": ["£25,000-£30,000", "£30,000-£35,000"]},
                                fact("salary_annual"), on_boundary) is None


def test_an_option_must_be_one_the_form_offers():
    assert resolve("Nationality", fact("nationality", answer="United Kingdom"), ["British", "Irish"])[0] == "British"
    assert resolve("Highest qualification", fact("education_1", "skills", answer="PhD"),
                   ["Bachelor's degree", "Master's degree"]) is None


def test_free_text_the_facts_dont_support_falls_back_to_the_facts_own_value():
    assert resolve("What is your notice period?", fact("notice_period", answer="Two weeks, negotiable"))[0] == "2 weeks"
    assert resolve("Which degree do you hold?", fact("education_1", answer="BSc (Hons) Computer Science"))[0] == \
        "BSc (Hons) Computer Science"


def test_a_degree_line_or_the_skills_list_never_goes_on_the_form_whole():
    # Seen on a live form: "What year did you graduate?" filled with the whole education line.
    assert resolve("What year did you graduate or are expected to graduate?", fact("education_1")) is None
    assert resolve("What year did you graduate or are expected to graduate?",
                   fact("education_1", answer="Summer 2025")) is None
    assert resolve("What year did you graduate or are expected to graduate?",
                   fact("education_1", answer="2025"))[0] == "2025"
    assert resolve("Do you have practical programming experience in at least one of: C, C++, Rust, or Python.",
                   fact("skills", answer="Yes, with Python and Go"))[0] == "Yes"


def test_a_yes_or_no_answers_only_a_yes_or_no_question():
    facts = {**FACTS, "can_start_immediately": answers.Fact("can_start_immediately", "Can start immediately",
                                                            "Yes", yes_no=True)}

    def start(question, said):
        return answers.resolve_fact({"question": question, "options": []}, fact("can_start_immediately", answer=said),
                                    facts, "London, UK")
    assert start("Please provide your ideal start date", "Yes") is None
    assert start("If yes, please give your visa type", "Yes") is None
    assert start("Please provide your ideal start date", "Immediately")[0] == "Immediately"
    assert start("Can you start immediately?", "Yes")[0] == "Yes"
    assert start("Please state whether you can start immediately", "Yes")[0] == "Yes"


def test_a_list_of_skills_says_yes_only_to_what_it_names():
    # Seen on a live form: "Is English your primary language?" answered yes from the skills list.
    english = ["Yes, English is my primary language", "No, English is not my primary language"]
    assert resolve("Is English your primary language?", fact("skills", answer=english[0]), english) is None
    assert resolve("Do you have experience with Python?", fact("skills", answer="Yes"), ["Yes", "No"])[0] == "Yes"
    # A CV leaving something out never says no.
    assert resolve("Do you have experience with Rust?", fact("skills", answer="No"), ["Yes", "No"]) is None
    assert resolve("Do you hold a degree from Oxford?", fact("education_1", answer="No"), ["Yes", "No"]) is None


def test_other_is_never_an_answer_from_the_profile():
    # Seen on a live form: "If you have multiple disciplines…" answered "Other" from the education line.
    disciplines = ["Mathematics", "Physics", "Economics", "Other"]
    assert resolve("If you have multiple disciplines, please select all that apply.",
                   fact("education_1", answer="Other"), disciplines) is None
    saved = {**FACTS, "saved_1": answers.Fact("saved_1", "Saved answer", "Other", source="saved")}
    assert answers.resolve_fact({"question": "How did you hear about us?", "options": ["LinkedIn", "Other"]},
                                fact("saved_1", answer="Other"), saved)[0] == "Other"


def test_a_long_dropdown_keeps_every_option(model):
    # Cambridge Consultants lists 350 UK institutions; the candidate's is 320th, under other words.
    unis = [f"College {i}" for i in range(319)] + ["University of Bristol", "Northfield, NU"] + \
           [f"Academy {i}" for i in range(29)]
    question = "What university are you currently studying at or have most recently graduated from?"
    fake = model(read={question: fact("education_1", answer="The Northfield University")})
    persona = {**PERSONA, "education": [{**PERSONA["education"][0], "institution": "The Northfield University"}]}
    got = ask([{"question": question, "options": unis}], persona=persona)
    assert (got[0]["source"], got[0]["answer"]) == ("profile", "Northfield, NU")
    assert "Academy 28" in fake.prompts()


@pytest.mark.parametrize("end, month", [
    ("11/2025", (2025, 11)), ("2025-06", (2025, 6)), ("Nov 2025", (2025, 11)), ("June 2025", (2025, 6)),
    ("2025", (2025, 12)), ("Present", None), ("", None), ("Expected 2027 - ongoing", None),
])
def test_an_end_date_is_read_as_its_month(end, month):
    assert answers._end_month(end) == month


def graduated(education, today=date(2026, 10, 18)):
    facts = {f.id: f for f in answers.profile_facts({**PERSONA, "education": education}, today=today)}
    return facts["graduated"].value if "graduated" in facts else None


def test_whether_they_have_graduated_is_stated_only_when_the_dates_say_so():
    done = {"institution": "Northfield University", "degree": "BSc", "end_date": "06/2025"}
    assert graduated([done]) == "Yes"
    assert graduated([done, {"institution": "Southfield", "degree": "MSc", "is_currently_enrolled": True}]) == "No"
    assert graduated([{**done, "end_date": "Present"}]) == "No"
    # Not marked as enrolled, but not finished yet either; or no end date at all: left out.
    assert graduated([{**done, "end_date": "06/2027"}]) is None
    assert graduated([{**done, "end_date": ""}]) is None
    assert graduated([{**done, "end_date": "10/2026"}]) is None                   # this month: not passed yet
    assert graduated([]) is None


def test_an_expected_graduation_question_is_answered_from_having_graduated(model):
    # DV Trading's "Please re-confirm your expected graduation date" was answered "I've already graduated" on some
    # runs and left for the user on others: the model had to read it off the degree's end date.
    question = "Please re-confirm your expected graduation date"
    options = ["I've already graduated", "August 2026 - December 2026", "January 2027 - July 2027"]
    fake = model(read={question: fact("graduated", answer="I've already graduated")})
    got = ask([{"question": question, "options": options}])
    assert (got[0]["source"], got[0]["answer"]) == ("profile", "I've already graduated")
    assert "graduated: Has already graduated (finished their studies, last in 06/2025): Yes" in fake.prompts()


def test_how_they_heard_about_a_job_is_left_for_the_user():
    assert not [f for f in answers.profile_facts(PERSONA) if "heard" in f.label.lower()]


def test_age_is_derived_without_the_date_of_birth_reaching_the_model():
    facts = {f.id: f for f in answers.profile_facts(PERSONA)}
    assert facts["over_18"].value == "Yes" and facts["dob"].private
    young = {**PERSONA, "core_info": {**PERSONA["core_info"], "dob": "2015-01-01"}}
    assert {f.id: f for f in answers.profile_facts(young)}["over_18"].value == "No"
    assert "over_18" not in {f.id for f in answers.profile_facts({"core_info": {"dob": "sometime"}})}


# ── Answering a form ──────────────────────────────────────────────────────────

def test_each_answer_says_where_it_came_from_and_nothing_is_guessed(model):
    bank = [{"id": "b1", "question": "Do you hold a full UK driving licence?", "question_key": "x",
             "answer": "No", "kind": "fact", "company": ""}]
    fake = model(read={
        "Do you have the right to work in the UK?": fact("right_to_work_uk", answer="Yes"),
        "Do you have a full driving licence?": fact("saved_1", answer="No"),
        "Have you ever been convicted of a criminal offence?": fact(),
        "Why do you want to join Harbourline?": WRITTEN,
    }, drafts=["I want to build Python services for Harbourline's ferry booking platform, as I did with FastAPI "
               "at Brightwave Analytics."])
    got = ask([{"question": "Do you have the right to work in the UK?", "options": ["Yes", "No"]},
               "Do you have a full driving licence?",
               {"question": "Have you ever been convicted of a criminal offence?", "options": ["Yes", "No"]},
               "Why do you want to join Harbourline?"], bank=bank)

    assert [(a["source"], a["answer"]) for a in got[:3]] == [("profile", "Yes"), ("saved", "No"), ("needs_you", "")]
    assert got[1]["bank_id"] == "b1" and "driving licence" in got[1]["because"]
    assert got[2]["kind"] == "fact" and got[2]["because"]
    assert got[3]["kind"] == "written" and got[3]["source"] == "drafted" and got[3]["flags"] == []
    # Contact details, salary, equality answers and the date of birth never reach the model.
    for value in PRIVATE_VALUES:
        assert value not in fake.prompts(), value


def test_the_very_question_answered_before_is_reused_without_a_model_call(model):
    fake = model()
    bank = [answers_entry("Do you require visa sponsorship? *", "No"),
            answers_entry("What is your notice period?", "One month")]
    got = ask([{"question": "Do you require visa sponsorship?", "options": ["Yes", "No"]},
               "What is your notice period"], bank=bank)
    assert [(a["source"], a["answer"]) for a in got] == [("saved", "No"), ("saved", "One month")]
    assert fake.seen == []


def answers_entry(question, answer, kind="fact", company="", id_="b1"):
    return {"id": id_, "question": question, "question_key": answers.question_key(question), "answer": answer,
            "kind": kind, "company": company}


def test_an_answer_saved_for_one_employer_is_not_reused_for_another(model):
    model(read={"Why do you want to work at Harbourline?": WRITTEN}, drafts=["A fresh draft about FastAPI."])
    bank = [answers_entry("Why do you want to work at Harbourline?", "Because of Acme's robots.", "written", "Acme")]
    got = ask(["Why do you want to work at Harbourline?"], bank=bank)
    assert got[0]["source"] == "drafted" and got[0]["answer"] == "A fresh draft about FastAPI."
    reused = ask(["Why do you want to work at Harbourline?"], bank=[{**bank[0], "company": "Harbourline"}])
    assert reused[0]["source"] == "saved"


def test_a_question_is_read_with_what_the_form_says_with_it(model):
    # Catapult's bare "GDPR Statement" was answered from the saved consent on some runs and left on others: the
    # statement under it, which says what it asks, never reached the model.
    statement = "Your personal data will be processed for the purposes of managing Catapult's recruitment. " * 20
    fake = model(read={"GDPR Statement": fact("saved_1", answer="Yes")})
    bank = [answers_entry("I consent to my personal data being processed for recruitment purposes", "Yes")]
    got = ask([{"question": "GDPR Statement", "options": ["Yes", "No"], "details": statement}], bank=bank)
    assert (got[0]["source"], got[0]["answer"]) == ("saved", "Yes")
    shown = statement.strip()[:answers._MAX_DETAILS]
    assert f"1. GDPR Statement\n   the form says with it: {shown}\n   options: Yes | No" in fake.prompts()
    assert statement.strip()[:answers._MAX_DETAILS + 20] not in fake.prompts()       # capped
    # With the statement shown, the real model still took the saved consent only on some runs: it read
    # "a saved answer to it" as the very wording. The same consent in other words counts; one company's document
    # doesn't stand for another's.
    assert "or to the same consent in other words: a saved consent to their personal data being processed for "            "recruitment answers a privacy or GDPR statement" in answers._READ_SYSTEM
    assert "A saved acknowledgement of one named document (a company's disclosure or policy) answers only that "            "document." in answers._READ_SYSTEM


def test_when_the_questions_cant_be_read_nothing_is_stated(model):
    model(read=None)
    got = ask([{"question": "Do you have the right to work in the UK?", "options": ["Yes", "No"]}])
    assert got[0]["source"] == "needs_you" and got[0]["answer"] == ""


def test_a_draft_with_an_unsupported_claim_is_revised_and_the_fix_kept(model):
    model(read={"Tell us about a project you're proud of.": WRITTEN},
          drafts=["I built Pantry Planner with Kubernetes and served 9,000 users."],
          revisions=["I built Pantry Planner, which 300 people used each week in a university trial."])
    got = ask(["Tell us about a project you're proud of."])[0]
    assert got["answer"].startswith("I built Pantry Planner, which 300 people") and got["flags"] == []


def test_a_revision_that_doesnt_help_leaves_the_draft_and_its_flags(model):
    model(read={"Tell us about a project you're proud of.": WRITTEN},
          drafts=["I built Pantry Planner with Kubernetes."], revisions=["I built Pantry Planner with Kafka and Kubernetes."])
    got = ask(["Tell us about a project you're proud of."])[0]
    assert got["answer"] == "I built Pantry Planner with Kubernetes."
    assert any("Kubernetes" in flag for flag in got["flags"])


def test_a_written_answer_keeps_to_the_forms_limit(model):
    long = "I built Pantry Planner with FastAPI. " * 30
    model(read={"Why this role? (max 50 words)": WRITTEN, "Why us?": WRITTEN}, drafts=[long, long])
    got = ask(["Why this role? (max 50 words)", {"question": "Why us?", "max_length": 120}])
    assert len(got[0]["answer"].split()) <= 50 and got[0]["answer"].endswith(".")
    assert len(got[1]["answer"]) <= 120 and got[1]["answer"].endswith(".")


def test_a_word_limit_passed_as_the_box_limit_is_read_as_words(model):
    # A live run: the agent passed "(max 150 words)" on as max_length=150, which cut the draft to one sentence.
    draft = ("I want to build Harbourline's booking services. " * 4).strip()
    model(read={"Why Harbourline? (max 150 words)": WRITTEN}, drafts=[draft])
    got = ask([{"question": "Why Harbourline? (max 150 words)", "max_length": 150}])[0]
    assert got["answer"] == draft


def test_a_dropdowns_placeholder_is_not_an_option(model):
    fake = model(read={"Will you require sponsorship?": fact("require_sponsorship", answer="No")})
    got = ask([{"question": "Will you require sponsorship?", "options": ["Select...", "Yes", "No", "-- Please choose --"]}])
    assert got[0]["options"] == ["Yes", "No"] and got[0]["answer"] == "No"
    assert "Select..." not in fake.prompts()


def test_a_dropdowns_hint_doesnt_stop_a_saved_answer(model):
    # Seen on a live form: the only "option" read was the box's hint, so the saved "Python" wasn't used.
    model()
    question = "If you progress to interview stage, which of these languages would you prefer us to focus on?"
    got = ask([{"question": question, "options": ["You can choose more than one"]}],
              bank=[answers_entry(question, "Python")])
    assert (got[0]["source"], got[0]["answer"], got[0]["options"]) == ("saved", "Python", [])


def test_an_address_read_as_several_facts_is_put_together_without_the_model_seeing_it(model):
    persona = {**PERSONA, "core_info": {**PERSONA["core_info"], "address_line_1": "1 High Street",
                                        "postcode": "BS1 1AA"}}
    fake = model(read={"Address": fact("postcode", "address_line_1", "city")})
    got = ask(["Address"], persona=persona)
    assert (got[0]["source"], got[0]["answer"]) == ("profile", "1 High Street, Bristol, BS1 1AA")
    assert "1 High Street" not in fake.prompts() and "BS1 1AA" not in fake.prompts()


# ── The answer bank ───────────────────────────────────────────────────────────

def test_saving_replaces_the_answer_to_the_same_question(user):
    first = answers.save(user, "Do you hold a full UK driving licence? *", "No")
    second = answers.save(user, "do you hold a full UK driving licence", "Yes")
    assert second["id"] == first["id"] and second["answer"] == "Yes"
    assert [a["answer"] for a in tracker.list_answers(user)] == ["Yes"]


def test_an_answer_is_kept_for_one_employer_only_when_it_names_it(user):
    general = answers.save(user, "What interests you about this role?", "Building services.", "written", "Harbourline")
    specific = answers.save(user, "Why Harbourline?", "Ferries.", "written", "Harbourline")
    assert general["company"] == "" and specific["company"] == "Harbourline"
    with pytest.raises(ValueError):
        answers.save(user, "  ", "x")
    with pytest.raises(ValueError):
        answers.save(user, "Q", "x", kind="guess")


def test_the_answer_bank_api_is_per_user(client_for, make_user):
    me, other = make_user("me@example.com"), make_user("other@example.com")
    saved = client_for(me).post("/answers", json={"question": "Notice period?", "answer": "2 weeks"}).json()
    assert client_for(me).get("/answers").json()[0]["answer"] == "2 weeks"
    assert client_for(me).put(f"/answers/{saved['id']}", json={"answer": "1 month"}).json()["answer"] == "1 month"
    assert client_for(me).put(f"/answers/{saved['id']}", json={"answer": " "}).status_code == 400
    assert client_for(me).post("/answers", json={"question": "", "answer": "x"}).status_code == 400

    assert client_for(other).get("/answers").json() == []
    assert client_for(other).put(f"/answers/{saved['id']}", json={"answer": "x"}).status_code == 404
    assert client_for(other).delete(f"/answers/{saved['id']}").status_code == 404

    assert client_for(me).delete(f"/answers/{saved['id']}").status_code == 200
    assert client_for(me).get("/answers").json() == []


def test_draft_endpoint_answers_without_saving(client, model):
    model(read={"Do you have the right to work in the UK?": fact()})
    r = client.post("/answers/draft", json={"job": JOB, "questions": ["Do you have the right to work in the UK?"]})
    assert r.status_code == 200 and r.json()["answers"][0]["source"] == "needs_you"
    assert client.get("/answers").json() == []
    assert client.post("/answers/draft", json={"questions": []}).status_code == 400


# ── The apply agent ───────────────────────────────────────────────────────────

def test_answer_lines_tell_the_agent_what_to_fill_and_what_to_leave():
    assert ba._answer_line(1, {"question": "Sponsorship?", "options": ["Yes", "No"], "kind": "fact",
                               "source": "profile", "answer": "No"}) == '1. "Sponsorship?": choose "No"'
    assert ba._answer_line(2, {"question": "Notice?", "options": [], "kind": "fact", "source": "saved",
                               "answer": "2 weeks"}) == '2. "Notice?": enter "2 weeks"'
    written = ba._answer_line(3, {"question": "Why us?", "options": [], "kind": "written", "source": "drafted",
                                  "answer": "Because."})
    assert "fill_answer(index=<the text box's index>, answer=3)" in written and "Because." not in written
    assert "LEAVE BLANK" in ba._answer_line(4, {"question": "Convictions?", "options": [], "kind": "fact",
                                                "source": "needs_you", "answer": ""})


class _History:
    def is_successful(self):
        return True

    def final_result(self):
        return "Filled the form."


def _run_with_questions(monkeypatch, answerer, questions, commands=("skip",), fills=None):
    """apply_with_browser with browser-use faked: the fill agent calls answer_questions once, then stops; the
    review is answered with `commands`. Each review-fill agent's task and tools go into `fills`."""
    class FakeAgent:
        def __init__(self, **kwargs):
            self.task, self.tools = kwargs["task"], kwargs["tools"]

        async def run(self, max_steps):
            if self.task.startswith(ba._FILL_TASK):
                fills.append({"task": self.task, "tools": self.tools, "max_steps": max_steps})
                return _History()
            action = self.tools.registry.registry.actions["answer_questions"]
            await action.function(params=ba.AnswerQuestionsParams(questions=questions))
            return _History()

    class FakeSession:
        def __init__(self, **kwargs):
            pass

        async def kill(self):
            pass

    async def nothing(*args):
        return ""

    async def no_empty(session):
        return ["Have you ever been convicted of a criminal offence?", "Postcode"]

    monkeypatch.setattr(ba, "BROWSER_USE_AVAILABLE", True)
    monkeypatch.setattr(ba, "Agent", FakeAgent)
    monkeypatch.setattr(ba, "BrowserSession", FakeSession)
    monkeypatch.setattr(ba, "_browser_profile", lambda: None)
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: None)
    monkeypatch.setattr(ba, "_has_page", lambda session: True)
    monkeypatch.setattr(ba, "_screenshot_b64", nothing)
    monkeypatch.setattr(ba, "_empty_required_fields", no_empty)

    async def run():
        queue: asyncio.Queue = asyncio.Queue()
        for command in commands:
            queue.put_nowait(command)
        return [e async for e in ba.apply_with_browser("https://jobs.example.com/1", {}, "", queue,
                                                       answerer=answerer)]
    return asyncio.run(run())


def test_the_review_lists_what_was_answered_and_leads_with_what_only_you_can_answer(monkeypatch, model):
    model(read={"Do you have the right to work in the UK?": fact("right_to_work_uk", answer="Yes"),
                "Have you ever been convicted of a criminal offence?": fact()})

    async def answerer(questions):
        return await answers.answer_questions(questions, PERSONA, [], JOB)
    events = _run_with_questions(monkeypatch, answerer, [
        ba.FormQuestion(question="Do you have the right to work in the UK?", options=["Yes", "No"]),
        ba.FormQuestion(question="Have you ever been convicted of a criminal offence?", options=["Yes", "No"])])

    review = next(e for e in events if e.get("interactive"))
    assert [(q["question"][:20], q["source"]) for q in review["questions"]] == [
        ("Do you have the righ", "profile"), ("Have you ever been c", "needs_you")]
    assert review["action"].startswith("Form filled, but 1 question only you can answer")
    # The conviction question isn't listed twice; the other empty field still is.
    assert review["notes"] == ("Questions only you can answer (left blank):\n"
                               "- Have you ever been convicted of a criminal offence?\n\n"
                               "Required fields still empty on the form:\n- Postcode\n\nFilled the form.")


def test_without_an_answerer_every_question_is_left_for_you(monkeypatch):
    events = _run_with_questions(monkeypatch, None, [ba.FormQuestion(question="Notice period?")])
    review = next(e for e in events if e.get("interactive"))
    assert review["questions"][0]["source"] == "needs_you"


def test_the_apply_stream_records_the_forms_questions_on_the_application(client, user, monkeypatch):
    async def public(url):
        return None
    monkeypatch.setattr(net_guard, "assert_public_url", public)
    asked = [{"question": "Notice period?", "options": [], "kind": "fact", "source": "profile", "answer": "2 weeks",
              "because": "Your profile: Notice period = 2 weeks", "bank_id": "", "flags": []}]
    seen = {}

    async def fake_apply_with_browser(*args, **kwargs):
        seen["answerer"] = kwargs.get("answerer")
        yield {"action": "Form filled", "screenshot": None, "blocked": True, "reason": "", "done": False,
               "interactive": True, "questions": asked}
        yield {"action": "Cancelled by user", "screenshot": None, "blocked": False, "reason": None, "done": True}
    monkeypatch.setattr(agent, "apply_with_browser", fake_apply_with_browser)

    r = client.post("/apply", data={"job_id": "j", "job_title": "T", "company": "C", "job_description": "Ad",
                                    "job_url": "https://jobs.example.com/1"})
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    assert next(e for e in events if e["type"] == "browser_blocked")["questions"] == asked
    assert callable(seen["answerer"])
    assert tracker.list_applications(user)[0]["questions"] == asked


# ── Answers you give in the review go on the form ─────────────────────────────

def test_review_answers_are_checked_and_capped():
    raw = [{"question": "Convictions?", "answer": " No ", "options": ["Yes", "No", 3]},
           {"question": "", "answer": "x"}, {"question": "Blank?", "answer": "  "}, "nonsense",
           {"question": "Why us?", "answer": "Because.", "kind": "written"}]
    assert ba._review_answers(raw) == [
        {"question": "Convictions?", "answer": "No", "kind": "fact", "options": ["Yes", "No"]},
        {"question": "Why us?", "answer": "Because.", "kind": "written", "options": []}]
    assert ba._review_answers("not a list") == []
    many = [{"question": f"Q{i}", "answer": "a"} for i in range(50)]
    assert len(ba._review_answers(many)) == ba._MAX_REVIEW_ANSWERS


def test_answers_given_in_the_review_are_put_on_the_form_and_the_record_follows(monkeypatch, model):
    model(read={"Do you have the right to work in the UK?": fact("right_to_work_uk", answer="Yes"),
                "Have you ever been convicted of a criminal offence?": fact(),
                "Why do you want to join us?": fact()})

    async def answerer(questions):
        return await answers.answer_questions(questions, PERSONA, [], JOB)
    fills = []
    given = json.dumps({"type": "answers", "answers": [
        {"question": "Have you ever been convicted of a criminal offence?", "answer": "No", "kind": "fact",
         "options": ["Yes", "No"]},
        {"question": "Why do you want to join us?", "answer": "I build booking services.", "kind": "written"}]})
    events = _run_with_questions(monkeypatch, answerer, [
        ba.FormQuestion(question="Do you have the right to work in the UK?", options=["Yes", "No"]),
        ba.FormQuestion(question="Have you ever been convicted of a criminal offence?", options=["Yes", "No"]),
        ba.FormQuestion(question="Why do you want to join us?")], commands=(given, "skip"), fills=fills)

    # One short agent put both answers in, told exactly what to choose and to paste the written one.
    assert len(fills) == 1 and fills[0]["max_steps"] == 8
    task = fills[0]["task"]
    assert '1. "Have you ever been convicted of a criminal offence?": choose "No"' in task
    assert "fill_answer(index=<the text box's index>, answer=2)" in task and "do NOT submit" in task
    assert "fill_answer" in fills[0]["tools"].registry.registry.actions

    reviews = [e for e in events if e.get("interactive")]
    assert len(reviews) == 2
    after = reviews[1]
    assert after["action"].startswith("Filled in your 2 answers")
    by_question = {q["question"]: q for q in after["questions"]}
    convictions = by_question["Have you ever been convicted of a criminal offence?"]
    assert (convictions["source"], convictions["answer"]) == ("saved", "No")
    assert by_question["Why do you want to join us?"]["kind"] == "written"
    assert by_question["Do you have the right to work in the UK?"]["source"] == "profile"   # untouched
    # Nothing is left for you, so the notes no longer lead with it, and the first pass's summary (which still
    # listed these as needing you) gives way to what this pass did.
    assert not after["notes"].startswith("Questions only you can answer")
    assert after["notes"].endswith("From your review: Filled the form.")
    assert reviews[0]["notes"].endswith("Filled the form.") and "From your review" not in reviews[0]["notes"]


def test_a_fill_that_fails_says_so_and_the_review_carries_on(monkeypatch):
    async def failing(*args, **kwargs):
        return False, "Couldn't find the convictions question"
    monkeypatch.setattr(ba, "_fill_with_agent", failing)
    given = json.dumps({"type": "answers", "answers": [{"question": "Notice period?", "answer": "2 weeks"}]})
    events = _run_with_questions(monkeypatch, None, [ba.FormQuestion(question="Notice period?")],
                                 commands=(given, json.dumps({"type": "answers", "answers": []}), "skip"))
    reviews = [e for e in events if e.get("interactive")]
    assert reviews[1]["action"].startswith("Couldn't put every answer on the form: Couldn't find the convictions")
    assert reviews[2]["action"] == "There were no answers to fill in"
    assert events[-1]["action"] == "Cancelled by user"


def test_the_apply_stream_stores_the_questions_again_after_a_fill(client, user, monkeypatch):
    async def public(url):
        return None
    monkeypatch.setattr(net_guard, "assert_public_url", public)
    before = [{"question": "Notice period?", "options": [], "kind": "fact", "source": "needs_you", "answer": "",
               "because": "", "bank_id": "", "flags": []}]
    after = [{**before[0], "source": "saved", "answer": "2 weeks", "because": "Your answer in this review"}]

    async def fake_apply_with_browser(*args, **kwargs):
        yield {"action": "Form filled", "screenshot": None, "blocked": True, "reason": "", "done": False,
               "interactive": True, "questions": before}
        yield {"action": "Filled in your 1 answer", "screenshot": None, "blocked": True, "reason": "", "done": False,
               "interactive": True, "questions": after}
        yield {"action": "Cancelled by user", "screenshot": None, "blocked": False, "reason": None, "done": True}
    monkeypatch.setattr(agent, "apply_with_browser", fake_apply_with_browser)

    client.post("/apply", data={"job_id": "j", "job_title": "T", "company": "C", "job_url": "https://jobs.example.com/1"})
    assert tracker.list_applications(user)[0]["questions"] == after


def test_pick_option_takes_the_option_that_covers_the_value_and_refuses_lookalikes():
    ethnicity = ["Australian Aboriginal", "Black (including African American, African, Carribean, Black-British, etc.)",
                 "White / Caucasian", "Prefer not to say"]
    assert answers.pick_option("Black African", ethnicity) == ethnicity[1]
    uni = "The University of the West of England, Bristol"
    assert answers.pick_option(uni, ["City of Bristol College", "University of Bristol", "Bristol, UWE"]) == "Bristol, UWE"
    assert answers.pick_option(uni, ["University of Bristol", "Arizona State University - West"]) is None
    cities = ["Little Bristol, England, United Kingdom", "Bristol, England, United Kingdom"]
    assert answers.pick_option("Bristol, United Kingdom", cities) == "Bristol, England, United Kingdom"
    assert answers.pick_option("Bristol", cities + ["Bristol, Connecticut, United States"]) is None
    assert answers.pick_option("White", ["White - British", "White - Irish"]) is None
    assert answers.pick_option("Online job search", ["Indeed", "LinkedIn", "Other"]) is None
