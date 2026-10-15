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

    # The review lists what the page still needs, whatever the agent's own summary said.
    review = next(e for e in events if e.get("interactive"))
    assert "4 required fields still empty" in review["action"]
    assert review["notes"].startswith("Required fields still empty on the form:\n"
                                      + "\n".join(f"- {label}" for label in EMPTY_REQUIRED))
    assert_no_chromium_left()
