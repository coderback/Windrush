"""
Real headless-Chromium tests of the browser agent (browser-use 0.11), with scripted LLMs.
Run with: pytest -m browser   (needs `playwright install chromium`)
"""
import asyncio
import base64
import json
import os
import re

import pytest
from browser_support import (ScriptedLLM, SecretTypingLLM, assert_no_chromium_left, ba, run_apply_flow,  # noqa: F401
                             site)

pytestmark = pytest.mark.browser

SECRET = "hunter2-Sup3rSecret"


def _is_jpeg(b64: str) -> bool:
    return base64.b64decode(b64)[:2] == b"\xff\xd8"


async def _js(ba, session, expr: str) -> str:
    page, _ = await ba._focused_page(session)
    return await page.evaluate(f"() => {expr}")


def test_screencast_and_takeover_commands(ba, site):
    from browser_use import BrowserSession

    async def run():
        session = BrowserSession(browser_profile=ba._browser_profile())
        await session.start()
        await session.navigate_to(f"{site}/form.html")
        await asyncio.sleep(1.0)
        frames: asyncio.Queue = asyncio.Queue(maxsize=8)
        caster = asyncio.create_task(ba._cdp_screencaster(session, frames))
        try:
            assert _is_jpeg(await asyncio.wait_for(frames.get(), timeout=10))
            assert _is_jpeg(await ba._screenshot_b64(session))

            await ba._run_user_command(session, {"type": "click", "x": 250, "y": 115})
            await ba._run_user_command(session, {"type": "type", "text": "Ada Lovelace"})
            assert await _js(ba, session, "document.getElementById('name').value") == "Ada Lovelace"

            await ba._run_user_command(session, {"type": "key", "key": "Tab"})
            assert await _js(ba, session, "document.activeElement.id") == "email"

            await ba._run_user_command(session, {"type": "scroll", "delta": 400})
            assert float(await _js(ba, session, "window.scrollY")) > 0
            await _js(ba, session, "(window.scrollTo(0, 0), 0)")
            await asyncio.sleep(0.3)

            before = session.agent_focus_target_id
            await ba._run_user_command(session, {"type": "click", "x": 150, "y": 312})  # target=_blank link
            await asyncio.sleep(1.5)
            assert session.agent_focus_target_id != before
            assert "Company careers" in await _js(ba, session, "document.body.innerText")
            while not frames.empty():
                frames.get_nowait()
            await _js(ba, session, "(document.body.insertAdjacentHTML('beforeend', '<p>repaint</p>'), 0)")
            assert _is_jpeg(await asyncio.wait_for(frames.get(), timeout=10))  # screencast followed the tab
        finally:
            caster.cancel()
            await asyncio.gather(caster, return_exceptions=True)
            await session.kill()

    asyncio.run(run())
    assert_no_chromium_left()


def test_fill_review_takeover_then_submit(ba, site, monkeypatch):
    llm = ScriptedLLM()
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: llm)
    frames: asyncio.Queue = asyncio.Queue(maxsize=8)
    commands = [json.dumps({"type": "click", "x": 250, "y": 115}), "Grace Hopper", "submit"]

    events = asyncio.run(run_apply_flow(ba, f"{site}/form.html", commands, frame_queue=frames))

    review = next(e for e in events if e.get("interactive"))
    assert "review" in review["action"].lower() and review["screenshot"]
    assert any(e["action"] == "Typed 12 characters" for e in events)   # the length, never the text
    assert llm.tasks == ["fill", "submit"]
    assert events[-1]["done"] and events[-1]["submitted"] is True
    assert not frames.empty()
    assert_no_chromium_left()


def test_failed_submit_keeps_control_then_done(ba, site, monkeypatch):
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: ScriptedLLM(submit_success=False))
    events = asyncio.run(run_apply_flow(ba, f"{site}/form.html", ["submit", "done"]))
    assert any("Couldn't confirm" in e["action"] for e in events)
    assert events[-1]["submitted"] is True


def test_unfinished_fill_then_skip(ba, site, monkeypatch):
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: ScriptedLLM(fill_success=False))
    events = asyncio.run(run_apply_flow(ba, f"{site}/form.html", ["skip"]))
    assert any("couldn't finish" in e["action"] for e in events)
    assert events[-1]["done"] and not events[-1].get("submitted")
    assert_no_chromium_left()


def test_client_disconnect_during_review_kills_the_browser(ba, site, monkeypatch):
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: ScriptedLLM())

    async def run():
        gen = ba.apply_with_browser(f"{site}/form.html", {}, "", asyncio.Queue())
        async for event in gen:
            if event.get("interactive"):
                break
        await gen.aclose()

    asyncio.run(run())
    assert_no_chromium_left()


def test_run_apply_closes_the_browser_as_soon_as_it_is_done(ba, site, monkeypatch):
    from app import agent, tracker
    monkeypatch.setattr(agent, "apply_with_browser", ba.apply_with_browser)
    monkeypatch.setattr(tracker, "get_user_persona", lambda uid: {"core_info": {"first_name": "Ada"}})
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: ScriptedLLM())

    async def run():
        queue: asyncio.Queue = asyncio.Queue()
        events = []
        async for chunk in agent.run_apply("u", "j", f"{site}/form.html", "", [], "s", queue, None):
            event = json.loads(chunk[6:])
            events.append(event)
            if event.get("interactive"):
                await queue.put("skip")
        return events

    final = asyncio.run(run())[-1]
    assert final["type"] == "done" and final["submitted"] is False
    assert_no_chromium_left()      # closed by run_apply's aclosing as soon as it broke out


def test_production_profile_blocks_internal_targets(site, monkeypatch):
    import app.browser_agent as ba_strict          # IP blocking left ON
    from browser_use import BrowserSession
    port = site.rsplit(":", 1)[1]

    async def titles():
        session = BrowserSession(browser_profile=ba_strict._browser_profile())
        await session.start()
        out = {}
        for label, url in (("raw IP", f"{site}/form.html"),
                           ("*.localhost", f"http://windrush-test.localhost:{port}/form.html"),
                           ("compose service", "http://ollama:11434/")):
            try:
                await session.navigate_to(url)
            except Exception:
                pass  # browser-use raises on a blocked navigation
            await asyncio.sleep(1.0)
            try:
                out[label] = await _js(ba_strict, session, "document.title")
            except Exception as exc:
                out[label] = f"<{exc}>"
        await session.kill()
        return out

    for label, title in asyncio.run(titles()).items():
        assert "Test Application Form" not in title, label
    assert_no_chromium_left()


def test_password_typed_via_placeholder_in_scope_and_never_sent_to_the_model(ba, site, monkeypatch):
    sessions = []
    real_session = ba.BrowserSession
    monkeypatch.setattr(ba, "BrowserSession", lambda *a, **k: sessions.append(real_session(*a, **k)) or sessions[-1])

    def run(scope: str):
        llm = SecretTypingLLM()
        monkeypatch.setattr(ba, "_make_browser_llm", lambda: llm)
        monkeypatch.setattr(ba, "_credential_scope", lambda url: scope)
        typed = {}

        async def flow():
            queue: asyncio.Queue = asyncio.Queue()
            async for event in ba.apply_with_browser(f"{site}/form.html", {"core_info": {"first_name": "Ada"}}, "",
                                                     queue, job_email="ada@example.com", job_password=SECRET):
                if event.get("interactive"):
                    typed["value"] = await _js(ba, sessions[-1], "document.getElementById('pw').value")
                    await queue.put("skip")
                if event.get("done"):
                    break
        asyncio.run(flow())
        return llm, typed.get("value")

    llm, value = run("http*://127.0.0.1")
    assert llm.typed and llm.read_back                       # the model read the field back with JS…
    assert value == SECRET                                   # …browser-use substituted the real value…
    assert not any(SECRET in text for text in llm.seen)      # …but no message (incl. a judge call) carried it

    _, value = run("https://*.some-other-site.example")      # out of scope: never typed
    assert value != SECRET
    assert_no_chromium_left()


EMPTY_REQUIRED = ["First Name", "Nationality", "How did you hear about this role?", "Will you require visa sponsorship?"]


def test_required_fields_still_empty_are_read_from_the_page(ba, site):
    from browser_use import BrowserSession

    async def run():
        session = BrowserSession(browser_profile=ba._browser_profile())
        await session.start()
        try:
            await session.navigate_to(f"{site}/application.html")
            await asyncio.sleep(1.0)
            return await ba._empty_required_fields(session)
        finally:
            await session.kill()

    # Not the filled email, the picked react-select country, the optional or the hidden field.
    assert asyncio.run(run()) == EMPTY_REQUIRED
    assert_no_chromium_left()


def test_the_button_that_sends_the_application_is_seen_on_the_form_only(ba, site):
    from browser_use import BrowserSession

    async def run():
        session = BrowserSession(browser_profile=ba._browser_profile())
        await session.start()
        try:
            shown = []
            for page in ("greenhouse.html", "other.html"):
                await session.navigate_to(f"{site}/{page}")
                await asyncio.sleep(1.0)
                shown.append(await ba._submit_button_shown(session))
            return shown
        finally:
            await session.kill()

    # The form's "Submit application" is below the fold: still seen. A careers page has none.
    assert asyncio.run(run()) == [True, False]
    assert_no_chromium_left()


class CoverLetterLLM(ScriptedLLM):
    """Pastes the cover letter into its box by index, reads the box back with JS, then finishes."""

    def __init__(self):
        super().__init__()
        self.pasted = self.read_back = False

    def next_action(self, text: str) -> list[dict]:
        box = re.search(r"\[(\d+)\]<textarea[^\n]*?id=cover", text)
        if box and not self.pasted:
            self.pasted = True
            return [{"paste_cover_letter": {"index": int(box.group(1))}}]
        if self.pasted and not self.read_back:
            self.read_back = True
            return [{"evaluate": {"code": "(function(){var c=document.getElementById('cover');"
                                          "return 'COVER:'+c.value.length+':'+(window.__coverInputs||0)})()"}}]
        return [{"done": {"text": "Filled what I could.", "success": True}}]


LETTER = ("Dear Hiring Manager,\n\nI’d like to join your AI team — here’s why.\n\n"
          + "A paragraph with real detail about the work. " * 40
          + "\n\nYours faithfully,\n\nAda Lovelace")


def test_cover_letter_is_pasted_whole_and_files_go_up_under_the_candidates_name(ba, site, monkeypatch, tmp_path):
    llm = CoverLetterLLM()
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: llm)
    cv = tmp_path / ("ab" * 16 + ".pdf")                 # stored documents are named by id
    cv.write_bytes(b"%PDF-1.4 cv")
    letter_pdf = tmp_path / ("cd" * 16 + ".pdf")
    letter_pdf.write_bytes(b"%PDF-1.4 letter")
    persona = {"core_info": {"first_name": "Ada", "last_name": "Lovelace"}}

    async def flow():
        queue: asyncio.Queue = asyncio.Queue()
        events = []
        async for event in ba.apply_with_browser(f"{site}/application.html", persona, LETTER, queue,
                                                 cv_path=str(cv), cover_letter_path=str(letter_pdf)):
            events.append(event)
            if event.get("interactive"):
                await queue.put("skip")
            if event.get("done"):
                break
        return events
    events = asyncio.run(flow())
    seen = "\n".join(llm.seen)

    # The whole letter went in with one action, firing the input events a paste would.
    assert f"Pasted the whole cover letter ({len(LETTER)} characters)" in seen
    length, inputs = map(int, re.search(r"COVER:(\d+):(\d+)", seen).groups())
    assert length == len(LETTER) and inputs >= 1

    # Uploads are offered under the candidate's name, and the copies are gone once the session ends.
    cv_upload = re.search(r"upload the file at: (\S*Ada_Lovelace_CV\.pdf)", seen).group(1)
    letter_upload = re.search(r"upload the file at: (\S*Ada_Lovelace_Cover_Letter\.pdf)", seen).group(1)
    assert not os.path.exists(cv_upload) and not os.path.exists(letter_upload)
    assert cv.exists() and letter_pdf.exists()            # the stored originals are untouched

    # The review lists what the page still needs, whatever the agent's own summary said: the questions the agent
    # never asked about are asked after it (with no answerer, they're the candidate's), then the plain fields.
    review = next(e for e in events if e.get("interactive"))
    assert "2 questions only you can answer" in review["action"]
    assert review["notes"].startswith("Questions only you can answer (left blank):\n"
                                      + "\n".join(f"- {label}" for label in EMPTY_REQUIRED[2:])
                                      + "\n\nRequired fields still empty on the form:\n"
                                      + "\n".join(f"- {label}" for label in EMPTY_REQUIRED[:2]))
    assert_no_chromium_left()


class QuestionsLLM(ScriptedLLM):
    """Asks answer_questions about the page's questions, fills the written one with fill_answer, reads the
    box back with JS, then finishes."""

    QUESTIONS = [{"question": "Will you require visa sponsorship?", "options": ["Yes", "No"]},
                 {"question": "Why do you want to join us?"},
                 {"question": "Do you have any unspent criminal convictions?", "options": ["Yes", "No"]}]

    def __init__(self):
        super().__init__()
        self.step = 0

    def next_action(self, text: str) -> list[dict]:
        self.step += 1
        if self.step == 1:
            return [{"answer_questions": {"questions": self.QUESTIONS}}]
        box = re.search(r"\[(\d+)\]<textarea[^\n]*?id=why", text)
        if self.step == 2 and box:
            return [{"fill_answer": {"index": int(box.group(1)), "answer": 2}}]
        if self.step == 3:
            return [{"evaluate": {"code": "(function(){var w=document.getElementById('why');"
                                          "return 'WHY:'+w.value.length+':'+(window.__whyInputs||0)})()"}}]
        return [{"done": {"text": "Filled what I could.", "success": True}}]


WHY = ("I want to build the booking services behind your ferry routes, as I built a FastAPI service that "
       "ingests 40k sensor readings a day at Brightwave Analytics.")


def test_questions_go_through_answer_questions_and_written_answers_are_filled_whole(ba, site, monkeypatch):
    llm = QuestionsLLM()
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: llm)

    async def answerer(questions):
        by_question = {
            "Will you require visa sponsorship?": ("fact", "profile", "No"),
            "Why do you want to join us?": ("written", "drafted", WHY),
            "Do you have any unspent criminal convictions?": ("fact", "needs_you", ""),
        }
        return [{"question": q["question"], "options": q["options"], "kind": by_question[q["question"]][0],
                 "source": by_question[q["question"]][1], "answer": by_question[q["question"]][2],
                 "because": "", "bank_id": "", "flags": []} for q in questions]

    async def flow():
        queue: asyncio.Queue = asyncio.Queue()
        events = []
        async for event in ba.apply_with_browser(f"{site}/questions.html", {"core_info": {"first_name": "Ada"}}, "",
                                                 queue, answerer=answerer):
            events.append(event)
            if event.get("interactive"):
                await queue.put("skip")
            if event.get("done"):
                break
        return events
    events = asyncio.run(flow())
    seen = "\n".join(llm.seen)

    # browser-use took the nested questions; answer_questions found each field by its label and filled the answers
    # in itself (the model sees only the start of a written one), leaving the one only the candidate can answer.
    assert '1. "Will you require visa sponsorship?": filled in with "No". Done; leave it.' in seen
    assert '2. "Why do you want to join us?": filled in with "' in seen and WHY not in seen.split("Answers:")[1][:400]
    assert '3. "Do you have any unspent criminal convictions?": LEAVE BLANK' in seen
    # The draft went in exactly, in one paste.
    assert f"Filled answer 2 ({len(WHY)} characters)" in seen
    length, inputs = map(int, re.search(r"WHY:(\d+):(\d+)", seen).groups())
    assert length == len(WHY) and inputs >= 1

    review = next(e for e in events if e.get("interactive"))
    assert [q["source"] for q in review["questions"]] == ["profile", "drafted", "needs_you"]
    assert review["notes"].startswith("Questions only you can answer (left blank):\n"
                                      "- Do you have any unspent criminal convictions?\n\n")
    assert "Will you require visa sponsorship?" not in review["notes"]     # filled: not empty, not self-answered
    assert_no_chromium_left()


class ReviewFillLLM(QuestionsLLM):
    """QuestionsLLM, then as the review-fill agent: picks the candidate's answer in the dropdown, reads it back
    with JS, then finishes."""

    def __init__(self):
        super().__init__()
        self.review_step = 0

    def next_action(self, text: str) -> list[dict]:
        if "has now answered some" not in text:
            return super().next_action(text)
        self.review_step += 1
        select = re.search(r"\[(\d+)\]<select[^\n]*?id=convictions", text)
        if self.review_step == 1 and select:
            return [{"select_dropdown": {"index": int(select.group(1)), "text": "No"}}]
        if self.review_step == 2:
            return [{"evaluate": {"code": "(function(){return 'CONV:'+document.getElementById('convictions').value})()"}}]
        return [{"done": {"text": "Put the answer in.", "success": True}}]


def test_an_answer_given_in_the_review_is_put_on_the_form(ba, site, monkeypatch):
    llm = ReviewFillLLM()
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: llm)

    async def answerer(questions):
        return [{"question": q["question"], "options": q["options"], "kind": "fact", "source": "needs_you",
                 "answer": "", "because": "", "bank_id": "", "flags": []} for q in questions]
    given = json.dumps({"type": "answers", "answers": [
        {"question": "Do you have any unspent criminal convictions?", "answer": "No", "kind": "fact",
         "options": ["Yes", "No"]}]})

    async def flow():
        queue: asyncio.Queue = asyncio.Queue()
        commands = [given, "skip"]
        events = []
        async for event in ba.apply_with_browser(f"{site}/questions.html", {"core_info": {"first_name": "Ada"}}, "",
                                                 queue, answerer=answerer):
            events.append(event)
            if event.get("interactive") and commands:
                await queue.put(commands.pop(0))
            if event.get("done"):
                break
        return events
    events = asyncio.run(flow())
    seen = "\n".join(llm.seen)

    assert '1. "Do you have any unspent criminal convictions?": choose "No"' in seen.split("has now answered some")[1]
    assert "CONV:No" in seen
    reviews = [e for e in events if e.get("interactive")]
    assert reviews[1]["action"].startswith("Filled in your 1 answer")
    convictions = next(q for q in reviews[1]["questions"] if q["question"].startswith("Do you have any unspent"))
    assert (convictions["source"], convictions["answer"]) == ("saved", "No")
    # The dropdown is filled now, so the page no longer lists it as empty.
    assert "Do you have any unspent criminal convictions?" not in reviews[1]["notes"]
    assert_no_chromium_left()


def test_unattended_run_sends_only_when_decide_says_so(ba, site, monkeypatch):
    def run(send: bool):
        llm = ScriptedLLM()
        monkeypatch.setattr(ba, "_make_browser_llm", lambda: llm)
        shown = []

        async def decide(filled):
            shown.append(filled)
            return send

        async def flow():
            return [event async for event in ba.apply_with_browser(
                f"{site}/form.html", {"core_info": {"first_name": "Ada"}}, "", asyncio.Queue(), decide=decide)]
        return llm, shown, asyncio.run(flow())

    llm, shown, events = run(send=True)
    final = events[-1]
    assert not any(e.get("interactive") for e in events)                 # nobody is asked anything
    assert shown == [{"ready": True, "error": "", "notes": "Filled every field", "questions": [], "empty": [],
                      "self_answered": []}]
    assert llm.tasks == ["fill", "submit"]
    assert final["done"] and final["submitted"] and final["submit_attempted"]
    assert _is_jpeg(final["form_screenshot"]) and _is_jpeg(final["confirm_screenshot"])

    llm, shown, events = run(send=False)
    final = events[-1]
    assert llm.tasks == ["fill"]                                          # the submit agent never ran
    assert final["done"] and not final["submitted"] and not final["submit_attempted"]
    assert _is_jpeg(final["form_screenshot"]) and "confirm_screenshot" not in final
    assert_no_chromium_left()


class GreenhouseLLM(ScriptedLLM):
    """Fills greenhouse.html the way the task asks: applicant details with fill_fields, questions through
    answer_questions with their indexes, then tries to fill a question that was left for the candidate."""

    def __init__(self):
        super().__init__()
        self.step = 0

    @staticmethod
    def _index(text: str, element_id: str) -> int:
        return int(re.search(rf"\[(\d+)\]<(?:input|select|textarea)[^\n]*?id={re.escape(element_id)}\b", text).group(1))

    def next_action(self, text: str) -> list[dict]:
        self.step += 1
        at = lambda element_id: self._index(text, element_id)  # noqa: E731
        if self.step == 1:
            return [{"fill_fields": {"fields": [
                {"index": at("first_name"), "label": "First Name", "value": "Ada"},
                {"index": at("last_name"), "label": "First Name", "value": "Ada"},     # the wrong field for that label
                {"index": at("country"), "label": "Country", "value": "United Kingdom"},
                {"index": at("candidate-location"), "label": "Location (City)", "value": "Bristol, United Kingdom"},
            ]}}]
        if self.step == 2:
            return [{"answer_questions": {"questions": [
                {"question": "Do you now or in the future require visa sponsorship to work in the UK?", "index": at("visa")},
                {"question": "How would you describe your race / ethnicity? Please select more than one if applicable.",
                 "index": at("ethnicity")},
                {"question": "Why are you applying to this role?", "index": at("why")},
                {"question": "Notice period", "index": at("notice")},
            ]}}]
        if self.step == 3:
            return [{"fill_fields": {"fields": [{"index": at("notice"), "label": "Notice period", "value": "1 month"}]}}]
        if self.step == 4:
            return [{"evaluate": {"code": "(function(){var g=function(i){var b=document.getElementById(i).closest('.select__container');"
                                          "return b?[].map.call(b.querySelectorAll('[class*=single-value],[class*=multi-value__label]'),"
                                          "function(n){return n.textContent}).join('+'):document.getElementById(i).value};"
                                          "return 'FORM:'+JSON.stringify({first:g('first_name'),last:g('last_name'),country:g('country'),"
                                          "city:g('candidate-location'),visa:g('visa'),eth:g('ethnicity'),why:g('why'),notice:g('notice')})})()"}}]
        return [{"done": {"text": "Filled what I could.", "success": True}}]


def test_fields_and_questions_are_filled_in_bulk_on_a_greenhouse_style_form(ba, site, monkeypatch):
    llm = GreenhouseLLM()
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: llm)
    asked = []

    async def answerer(questions):
        asked.extend(questions)

        def answer(q):
            black = next((o for o in q["options"] if o.startswith("Black")), "")
            return {"Do you now or in the future require visa sponsorship to work in the UK?": ("fact", "profile", "No"),
                    "How would you describe your race / ethnicity? Please select more than one if applicable.":
                        ("fact", "profile", black),
                    "Why are you applying to this role?": ("written", "drafted", WHY),
                    "Notice period": ("fact", "needs_you", "")}[q["question"]]
        return [{"question": q["question"], "options": q["options"], "kind": answer(q)[0], "source": answer(q)[1],
                 "answer": answer(q)[2], "because": "", "bank_id": "", "flags": []} for q in questions]

    async def flow():
        return [event async for event in ba.apply_with_browser(
            f"{site}/greenhouse.html", {"core_info": {"first_name": "Ada"}}, "", asyncio.Queue(), answerer=answerer,
            decide=lambda filled: asyncio.sleep(0, result=False))]
    asyncio.run(flow())
    seen = "\n".join(llm.seen)

    # The dropdowns' real options went to the answerer: searchable ones are read by opening them.
    options = lambda start: next(q["options"] for q in asked if q["question"].startswith(start))  # noqa: E731
    assert options("Do you now") == ["Yes", "No"]
    assert options("How would you")[1].startswith("Black (including")
    assert options("Notice period") == ["Select...", "Immediately", "1 month", "3 months"]
    assert options("Why are you") == []

    assert '- “First Name”: filled with “Ada”. Done; leave it.' in seen
    # The second item's index was Last Name's: the field labelled "First Name" is what got filled, not Last Name.
    assert seen.count("- “First Name”: filled with “Ada”. Done; leave it.") >= 2
    assert '- “Country”: filled with “United Kingdom +44”' in seen
    # That was the phone's dial-code "Country"; the address's "Country" is still empty, and the agent is told.
    assert "The page has 2 fields labelled “Country”: this was element " in seen
    assert re.search(r"Required fields still empty on the page: [^\n]*“Country”", seen)
    # Once a question is left for the candidate (Notice period, from step 2), it isn't listed as still to do.
    assert "Notice period" not in re.findall(r"Required fields still empty on the page: [^\n]*", seen)[-1]
    assert '"Do you now or in the future require visa sponsorship to work in the UK?": filled in with "No"' in seen
    assert '"Notice period": LEAVE BLANK' in seen
    assert "- “Notice period”: NOT filled. Only the candidate can answer it: leave it blank." in seen

    form = json.loads(re.search(r"FORM:(\{.*?\})(?:\n|$)", seen).group(1))
    assert form == {"first": "Ada", "last": "", "country": "+44",
                    "city": "Bristol, England, United Kingdom", "visa": "No",
                    "eth": options("How would you")[1], "why": WHY, "notice": ""}
    assert_no_chromium_left()


class VisaOnlyLLM(GreenhouseLLM):
    def next_action(self, text: str) -> list[dict]:
        self.step += 1
        if self.step == 1:
            return [{"answer_questions": {"questions": [
                {"question": "Do you now or in the future require visa sponsorship to work in the UK?",
                 "index": self._index(text, "visa")}]}}]
        return [{"done": {"text": "Done.", "success": True}}]


class HelperTextLLM(GreenhouseLLM):
    def next_action(self, text: str) -> list[dict]:
        self.step += 1
        if self.step == 1:
            return [{"answer_questions": {"questions": [
                {"question": "If you have multiple disciplines, please select all that apply.",
                 "index": self._index(text, "d1"), "options": ["Physics"]}]}}]
        if self.step == 2:
            return [{"evaluate": {"code": "'DISC:' + [...document.querySelectorAll('[name=disc]')]"
                                          ".filter(b => b.checked).map(b => b.id).join(',')"}}]
        return [{"done": {"text": "Done.", "success": True}}]


def test_a_question_given_by_the_text_under_its_label_is_asked_as_the_form_labels_it(ba, site, monkeypatch):
    """DV Trading's agent gave "Undergrad Discipline(s)" as its hint, "If you have multiple disciplines…": the field
    wasn't found, so its real options weren't read nor the answer filled, and the hint read as a case the profile
    doesn't show. It's found by the hint, and asked under its label with the hint as details."""
    llm = HelperTextLLM()
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: llm)
    asked = []

    async def answerer(questions):
        asked.extend(questions)
        return [{"question": q["question"], "options": q["options"], "kind": "fact", "source": "profile",
                 "answer": "Computer Science" if "Computer Science" in q["options"] else "", "because": "",
                 "bank_id": "", "flags": []} for q in questions]

    async def flow():
        return [event async for event in ba.apply_with_browser(
            f"{site}/greenhouse.html", {"core_info": {"first_name": "Ada"}}, "", asyncio.Queue(), answerer=answerer,
            decide=lambda filled: asyncio.sleep(0, result=False))]
    asyncio.run(flow())
    assert {k: asked[0].get(k) for k in ("question", "options", "details")} == {
        "question": "Undergrad Discipline(s)", "options": ["Mathematics", "Computer Science", "Physics"],
        "details": "If you have multiple disciplines, please select all that apply."}
    assert "DISC:d2" in "\n".join(llm.seen)
    assert_no_chromium_left()


class OneCountryLLM(GreenhouseLLM):
    def next_action(self, text: str) -> list[dict]:
        self.step += 1
        if self.step == 1:          # the phone's dial-code "Country" only, as on Cambridge Consultants' form
            return [{"fill_fields": {"fields": [
                {"index": self._index(text, "country"), "label": "Country", "value": "United Kingdom"}]}}]
        if self.step == 3:
            return [{"done": {"text": "Done.", "success": True}}]
        return [{"evaluate": {"code": "'STEP'"}}]


def test_a_label_two_fields_share_is_tried_again_on_the_one_still_empty(ba, site, monkeypatch):
    """Cambridge Consultants' address "Country" stayed empty beside the phone's dial-code one the agent filled: the
    second try looked it up by label and gave up on two matches. Each of them still empty gets the value now, and
    the one already filled is left alone."""
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: OneCountryLLM())
    held = {}
    real_fill_again = ba._fill_again

    async def fill_again(session, tried, filled, empty, profile=None):
        took = await real_fill_again(session, tried, filled, empty, profile)
        for element_id in ("country", "address-country"):
            node = await session.get_element_by_index(await session.get_index_by_id(element_id))
            held[element_id] = await (await ba.form_widgets.Field(session, node).open()).held()
        return took
    monkeypatch.setattr(ba, "_fill_again", fill_again)

    async def flow():
        return [event async for event in ba.apply_with_browser(
            f"{site}/greenhouse.html", {"core_info": {"first_name": "Ada"}}, "", asyncio.Queue(),
            answerer=ba._no_answers, decide=lambda filled: asyncio.sleep(0, result=False))]
    final = asyncio.run(flow())[-1]
    assert held == {"country": ["+44"], "address-country": ["United Kingdom"]}
    assert "Country" not in final["empty"]
    assert_no_chromium_left()


class StaleCountriesLLM(GreenhouseLLM):
    def next_action(self, text: str) -> list[dict]:
        self.step += 1
        if self.step == 1:          # both "Country" fields, with indexes from an earlier view of the page
            return [{"fill_fields": {"fields": [{"index": 99998, "label": "Country", "value": "United Kingdom"},
                                                {"index": 99999, "label": "Country", "value": "United Kingdom"}]}}]
        return [{"done": {"text": "Done.", "success": True}}]


def test_fill_fields_fills_a_shared_label_with_a_stale_index_into_the_one_still_empty(ba, site, monkeypatch):
    """On Cambridge Consultants' form fill_fields was given both "Country" fields with stale indexes: the label alone
    matched two fields, so neither was filled and the agent typed them in itself. Each goes into the first of them
    still empty."""
    llm = StaleCountriesLLM()
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: llm)

    async def flow():
        return [event async for event in ba.apply_with_browser(
            f"{site}/greenhouse.html", {"core_info": {"first_name": "Ada"}}, "", asyncio.Queue(),
            answerer=ba._no_answers, decide=lambda filled: asyncio.sleep(0, result=False))]
    final = asyncio.run(flow())[-1]
    seen = "\n".join(llm.seen)
    assert "- “Country”: filled with “United Kingdom +44”" in seen      # the phone's dial code, first on the page
    assert "- “Country”: filled with “United Kingdom”." in seen          # then the address's
    assert "Country" not in final["empty"]
    assert_no_chromium_left()


class NoCountryLLM(GreenhouseLLM):
    def next_action(self, text: str) -> list[dict]:
        return [{"done": {"text": "Country fields were left blank.", "success": True}}]


@pytest.mark.parametrize("country, held", [
    ("United Kingdom", {"country": ["+44"], "address-country": ["United Kingdom"]}),
    ("", {"country": [], "address-country": []}),
])
def test_a_country_the_agent_never_filled_is_filled_from_the_profile(ba, site, monkeypatch, country, held):
    """The agent once left both of Cambridge Consultants' required "Country" fields blank on purpose, so the second try
    had no value of its own. Where the user lives isn't a private detail: it fills them. Without one, nothing is."""
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: NoCountryLLM())
    seen = {}
    real_fill_again = ba._fill_again

    async def fill_again(session, tried, filled, empty, profile=None):
        took = await real_fill_again(session, tried, filled, empty, profile)
        for element_id in ("country", "address-country"):
            node = await session.get_element_by_index(await session.get_index_by_id(element_id))
            seen[element_id] = await (await ba.form_widgets.Field(session, node).open()).held()
        return took
    monkeypatch.setattr(ba, "_fill_again", fill_again)

    async def flow():
        return [event async for event in ba.apply_with_browser(
            f"{site}/greenhouse.html", {"core_info": {"first_name": "Ada", "country": country}}, "", asyncio.Queue(),
            answerer=ba._no_answers, decide=lambda filled: asyncio.sleep(0, result=False))]
    final = asyncio.run(flow())[-1]
    assert seen == held
    assert ("Country" in final["empty"]) is not bool(country)
    assert_no_chromium_left()


class LosesAFieldLLM(GreenhouseLLM):
    def next_action(self, text: str) -> list[dict]:
        self.step += 1
        at = lambda element_id: self._index(text, element_id)  # noqa: E731
        if self.step == 1:
            return [{"fill_fields": {"fields": [
                {"index": at("notice"), "label": "Notice period", "value": "1 month"},
                {"index": at("first_name"), "label": "First Name", "value": "Ada"}]}}]
        if self.step == 2:      # something on the page empties it again
            return [{"evaluate": {"code": "document.getElementById('notice').value = ''; 'EMPTIED'"}}]
        return [{"done": {"text": "Done.", "success": True}}]


def test_a_field_the_agent_filled_that_ends_up_empty_is_filled_again(ba, site, monkeypatch):
    """DV Trading's Discipline was empty at the end of a run though the agent had filled it. Once the agent stops,
    a required field still empty that fill_fields was given a value for gets one more try with that value."""
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: LosesAFieldLLM())

    async def flow():
        return [event async for event in ba.apply_with_browser(
            f"{site}/greenhouse.html", {"core_info": {"first_name": "Ada"}}, "", asyncio.Queue(),
            answerer=ba._no_answers, decide=lambda filled: asyncio.sleep(0, result=False))]
    final = asyncio.run(flow())[-1]
    assert "Notice period" not in final["empty"] and "School" in final["empty"]
    assert_no_chromium_left()


class TicksConsentLLM(GreenhouseLLM):
    def next_action(self, text: str) -> list[dict]:
        self.step += 1
        at = lambda element_id: self._index(text, element_id)  # noqa: E731
        if self.step == 1:
            return [{"fill_fields": {"fields": [
                {"index": at("consent"), "label": "I consent to the processing of my data", "value": "checked"},
                {"index": at("consent"), "label": "Consent", "value": "checked"},       # a short label for it
                {"index": at("terms"), "label": "Terms & Conditions", "value": "checked"},  # a consent's short label
                {"index": at("first_name"), "label": "First Name", "value": "Ada"},
            ]}}]
        if self.step == 2:
            return [{"evaluate": {"code": "'CONSENT:' + document.getElementById('consent').checked + "
                                          "',TERMS:' + document.getElementById('terms').checked"}}]
        return [{"done": {"text": "Done.", "success": True}}]


def test_fill_fields_never_ticks_a_consent_or_answers_a_question(ba, site, monkeypatch):
    """Catapult's demographic-data consent was ticked with fill_fields, never asked about: nothing held the form for
    it. A field whose label asks or states something is answer_questions', under its own label or a short one."""
    llm = TicksConsentLLM()
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: llm)

    async def flow():
        return [event async for event in ba.apply_with_browser(
            f"{site}/greenhouse.html", {"core_info": {"first_name": "Ada"}}, "", asyncio.Queue(),
            answerer=ba._no_answers, decide=lambda filled: asyncio.sleep(0, result=False))]
    asyncio.run(flow())
    seen = "\n".join(llm.seen)
    for label in ("I consent to the processing of my data", "Consent", "Terms & Conditions"):
        assert f"- “{label}”: NOT filled. It asks or states something (a question, consent or declaration)" in seen
    assert "CONSENT:false,TERMS:false" in seen
    assert "- “First Name”: filled with “Ada”. Done; leave it." in seen
    assert_no_chromium_left()


class ClicksConsentLLM(GreenhouseLLM):
    def next_action(self, text: str) -> list[dict]:
        self.step += 1
        if self.step == 1:          # browser-use's own click: no Windrush tool sees it
            return [{"click": {"index": self._index(text, "consent")}}]
        if self.step == 2:
            return [{"evaluate": {"code": "'CONSENT:' + document.getElementById('consent').checked"}}]
        return [{"done": {"text": "Done.", "success": True}}]


def test_a_consent_the_agent_ticks_with_a_click_is_flagged_and_holds_the_form(ba, site, monkeypatch):
    """A ticked box reads "checked", and the user's own persona holds that word: a consent the agent clicked
    passed for a detail typed from the persona, so nothing flagged it and autopilot would have sent the form."""
    llm = ClicksConsentLLM()
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: llm)
    persona = {"core_info": {"first_name": "Ada"}, "summary": "I checked every result twice."}

    async def flow():
        return [event async for event in ba.apply_with_browser(
            f"{site}/greenhouse.html", persona, "", asyncio.Queue(), answerer=ba._no_answers,
            decide=lambda filled: asyncio.sleep(0, result=False))]
    final = asyncio.run(flow())[-1]
    from app import autopilot
    assert "CONSENT:true" in "\n".join(llm.seen)
    assert final["self_answered"] == ["I consent to the processing of my data: checked"]
    assert any("the agent chose itself" in r and "I consent to the processing" in r
               for r in autopilot.hold_reasons(final, []))
    assert_no_chromium_left()


class AsksNothingLLM(GreenhouseLLM):
    def next_action(self, text: str) -> list[dict]:
        return [{"done": {"text": "Done.", "success": True}}]


def test_required_questions_the_agent_never_asked_about_are_asked_after_it(ba, site, monkeypatch):
    """On some runs the agent left Catapult's demographic-data consent without giving it to answer_questions: no saved
    answer could fill it and the review didn't list it. Once the agent stops, each required question still empty
    that it never asked about goes through the answerer; a plain field like School stays the agent's."""
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: AsksNothingLLM())
    asked = []

    async def answerer(questions):
        asked.extend(q["question"] for q in questions)
        return [{"question": q["question"], "options": q["options"], "kind": "fact",
                 "source": "profile" if q["options"] == ["Yes", "No"] else "needs_you",
                 "answer": "No" if q["options"] == ["Yes", "No"] else "", "because": "", "bank_id": "", "flags": []}
                for q in questions]

    async def flow():
        return [event async for event in ba.apply_with_browser(
            f"{site}/greenhouse.html", {"core_info": {"first_name": "Ada"}}, "", asyncio.Queue(), answerer=answerer,
            decide=lambda filled: asyncio.sleep(0, result=False))]
    final = asyncio.run(flow())[-1]
    visa = "Do you now or in the future require visa sponsorship to work in the UK?"
    assert asked == ["What university are you currently studying at or have most recently graduated from?", visa,
                     "Why are you applying to this role?"]
    assert [(q["question"], q["answer"]) for q in final["questions"]][1] == (visa, "No")
    assert visa not in final["empty"] and "School" in final["empty"]          # filled; the plain field left alone
    assert_no_chromium_left()


class ScreenfulOfOptionsLLM(GreenhouseLLM):
    def next_action(self, text: str) -> list[dict]:
        self.step += 1
        if self.step == 1:
            return [{"answer_questions": {"questions": [
                {"question": "Undergrad Discipline(s)", "index": self._index(text, "d3"), "options": ["Physics"]},
                {"question": "School", "index": self._index(text, "school"), "options": ["Bath Spa University"]}]}}]
        return [{"done": {"text": "Done.", "success": True}}]


def test_a_questions_options_are_read_off_the_page_even_when_the_agent_gives_some(ba, site, monkeypatch):
    """The agent lists only the options on screen: DV Trading's 83 disciplines came as the last 17, without the
    candidate's. The page's are read instead, unless it shows fewer (a type-ahead lists nothing until typed)."""
    llm = ScreenfulOfOptionsLLM()
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: llm)
    asked = {}

    async def answerer(questions):
        asked.update({q["question"]: q["options"] for q in questions})
        return [{"question": q["question"], "options": q["options"], "kind": "fact", "source": "needs_you",
                 "answer": "", "because": "", "bank_id": "", "flags": []} for q in questions]

    async def flow():
        return [event async for event in ba.apply_with_browser(
            f"{site}/greenhouse.html", {"core_info": {"first_name": "Ada"}}, "", asyncio.Queue(), answerer=answerer,
            decide=lambda filled: asyncio.sleep(0, result=False))]
    asyncio.run(flow())
    # (The page's other required questions are asked after the agent stops: not what this is about.)
    assert {q: asked[q] for q in ("Undergrad Discipline(s)", "School")} == {
        "Undergrad Discipline(s)": ["Mathematics", "Computer Science", "Physics"], "School": ["Bath Spa University"]}
    assert_no_chromium_left()


def test_an_answer_no_option_takes_is_asked_again_with_the_options(ba, site, monkeypatch):
    """When a dropdown's options didn't show the first time, the free-text answer it gets ('Nope') isn't left for
    the agent to type: the options are read again and the question asked again with them."""
    llm = VisaOnlyLLM()
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: llm)
    real_read, reads, asked = ba.form_widgets.read_options, [], []

    async def read_options(field):
        reads.append(1)
        return [] if len(reads) == 1 else await real_read(field)
    monkeypatch.setattr(ba.form_widgets, "read_options", read_options)

    async def answerer(questions):
        asked.append([q["options"] for q in questions])
        return [{"question": q["question"], "options": q["options"], "kind": "fact", "source": "profile",
                 "answer": "No" if q["options"] else "Nope", "because": "", "bank_id": "", "flags": []}
                for q in questions]

    async def flow():
        return [event async for event in ba.apply_with_browser(
            f"{site}/greenhouse.html", {"core_info": {"first_name": "Ada"}}, "", asyncio.Queue(), answerer=answerer,
            decide=lambda filled: asyncio.sleep(0, result=False))]
    final = asyncio.run(flow())[-1]
    assert asked[:2] == [[[]], [["Yes", "No"]]]           # then the questions the agent never asked about
    assert '"Do you now or in the future require visa sponsorship to work in the UK?": filled in with "No"' in \
        "\n".join(llm.seen)
    assert final["questions"][0]["answer"] == "No"
    assert_no_chromium_left()


class SelfAnsweringLLM(GreenhouseLLM):
    """Asks answer_questions with no index at all (it must find the field by label), then types a name from the
    persona and an answer to a question itself, the way a live run did."""

    def next_action(self, text: str) -> list[dict]:
        self.step += 1
        if self.step == 1:
            return [{"answer_questions": {"questions": [
                {"question": "Do you now or in the future require visa sponsorship to work in the UK?"}]}}]
        if self.step == 2:
            return [{"input": {"index": self._index(text, "first_name"), "text": "Ada"}},
                    {"input": {"index": self._index(text, "why"), "text": "Because I like it."}}]
        return [{"done": {"text": "Done.", "success": True}}]


def test_answers_the_agent_types_itself_are_caught_and_fields_are_found_by_label(ba, site, monkeypatch):
    llm = SelfAnsweringLLM()
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: llm)

    async def answerer(questions):
        return [{"question": q["question"], "options": q["options"], "kind": "fact", "source": "profile",
                 "answer": "No", "because": "", "bank_id": "", "flags": []} for q in questions]

    async def flow():
        return [event async for event in ba.apply_with_browser(
            f"{site}/greenhouse.html", {"core_info": {"first_name": "Ada"}}, "", asyncio.Queue(), answerer=answerer,
            decide=lambda filled: asyncio.sleep(0, result=False))]
    final = asyncio.run(flow())[-1]
    # no index given: found by its label
    assert '"Do you now or in the future require visa sponsorship to work in the UK?": filled in with "No"' in \
        "\n".join(llm.seen)
    assert final["self_answered"] == ["Why are you applying to this role?*: Because I like it."]  # not "First Name"
    assert ("Answers the agent chose itself, not from your saved answers or persona (check them):\n"
            "- Why are you applying to this role?*: Because I like it.") in final["notes"]
    assert_no_chromium_left()
