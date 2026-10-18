"""
Real headless-Chromium tests of form_widgets: filling every kind of field on a Greenhouse-style form.
Run with: pytest -m browser
"""
import asyncio
import json
import time

import pytest
from browser_support import assert_no_chromium_left, ba, site  # noqa: F401

from app import form_widgets

pytestmark = pytest.mark.browser


def _on_form(ba, site, check):
    """Open greenhouse.html and run `check(fill, read, held)` against it."""
    from browser_use import BrowserSession

    async def run():
        session = BrowserSession(browser_profile=ba._browser_profile())
        await session.start()
        try:
            await session.navigate_to(f"{site}/greenhouse.html")
            await asyncio.sleep(1.0)
            await session.get_browser_state_summary(include_screenshot=False)

            async def node(element_id):
                return await session.get_element_by_index(await session.get_index_by_id(element_id))

            async def fill(element_id, value):
                return await form_widgets.fill(session, await node(element_id), value)

            async def read(element_id):
                return await form_widgets.read_options(await form_widgets.Field(session, await node(element_id)).open())

            async def held(element_id):
                return await (await form_widgets.Field(session, await node(element_id)).open()).held()

            await check(fill, read, held)
        finally:
            await session.kill()

    asyncio.run(run())
    assert_no_chromium_left()


def test_every_kind_of_field_is_filled_and_checked(ba, site):
    async def check(fill, read, held):
        assert await fill("first_name", "Ada") == (True, "Ada")
        assert await fill("email", "ada@example.com") == (True, "ada@example.com")
        # searchable dropdowns: a dial-code list, yes/no, a long option the value's words are all in
        assert await fill("country", "United Kingdom") == (True, "United Kingdom +44")
        assert await fill("visa", "Yes") == (True, "Yes")
        ok, chosen = await fill("ethnicity", "Black African")
        assert ok and chosen.startswith("Black (including")
        # type-ahead boxes: nothing listed until typed; a city with its country; a university by its full name
        assert await fill("candidate-location", "Bristol, United Kingdom") == (True, "Bristol, England, United Kingdom")
        assert await fill("school", "The University of the West of England, Bristol") == \
            (True, "University of the West of England")
        assert await fill("notice", "Immediately") == (True, "Immediately")
        assert await fill("d2", "Computer Science") == (True, "Computer Science")
        assert await fill("consent", "Yes") == (True, "checked")
        letter = "I build data pipelines.\n\nAnd I'd like to build yours."
        assert await fill("why", letter) == (True, letter)

        assert await held("country") == ["+44"]                         # it shows only the dial code
        assert await held("candidate-location") == ["Bristol, England, United Kingdom"]
    _on_form(ba, site, check)


def test_an_option_far_down_a_long_list_is_found_by_typing_it(ba, site):
    # Cambridge Consultants lists the University of the West of England 320th of 350, as "Bristol, UWE": typed,
    # not reached by 320 arrow presses (29.5s on the live form).
    async def check(fill, read, held):
        assert len(await read("university")) == 350
        started = time.monotonic()
        assert await fill("university", "The University of the West of England, Bristol") == (True, "Bristol, UWE")
        assert time.monotonic() - started < 10
        assert await held("university") == ["Bristol, UWE"]
        # Picked, a multi-select stops listing it; asked again (as on a live run), it's still an option and done.
        options = await read("university")
        assert len(options) == 350 and options[0] == "Bristol, UWE"
        assert await fill("university", "Bristol, UWE") == (True, "Bristol, UWE")
        assert await held("university") == ["Bristol, UWE"]
    _on_form(ba, site, check)


def test_the_agents_snapshot_shows_a_typed_phone_number(ba, site):
    # The value attribute stays empty when text is typed; the snapshot must show it all the same, or the agent
    # thinks the box is blank and types the number again (ten steps on a live Greenhouse form).
    from browser_use import BrowserSession

    async def run():
        session = BrowserSession(browser_profile=ba._browser_profile())
        await session.start()
        try:
            await session.navigate_to(f"{site}/greenhouse.html")
            await asyncio.sleep(1.0)
            await session.get_browser_state_summary(include_screenshot=False)
            node = await session.get_element_by_index(await session.get_index_by_id("phone"))
            assert await form_widgets.fill(session, node, "07700 900123") == (True, "07700 900123")
            state = await session.get_browser_state_summary(include_screenshot=False)
            line = next(l for l in state.dom_state.llm_representation().splitlines() if "id=phone" in l)
            assert "value=07700 900123" in line
        finally:
            await session.kill()

    asyncio.run(run())
    assert_no_chromium_left()


def test_options_are_read_from_the_dropdown_not_the_page(ba, site):
    async def check(fill, read, held):
        assert await read("visa") == ["Yes", "No"]                      # not the phone widget's 244 options
        assert await read("notice") == ["Select...", "Immediately", "1 month", "3 months"]
        assert await read("d1") == ["Mathematics", "Computer Science", "Physics"]
        assert await read("candidate-location") == []                   # type-ahead: nothing until typed
        assert await held("visa") == []                                 # reading chose nothing
    _on_form(ba, site, check)


def test_a_field_is_described_with_what_the_form_says_with_it(ba, site):
    """Catapult's "GDPR Statement" says what it asks only in the statement under it. A field with nothing but its
    label and options has no details: not the label again, not "Select...", not the checkboxes' labels."""
    from browser_use import BrowserSession

    async def run():
        session = BrowserSession(browser_profile=ba._browser_profile())
        await session.start()
        try:
            await session.navigate_to(f"{site}/greenhouse.html")
            await asyncio.sleep(1.0)
            await session.get_browser_state_summary(include_screenshot=False)
            details = {}
            for element_id in ("gdpr", "visa", "d1", "why"):
                node = await session.get_element_by_index(await session.get_index_by_id(element_id))
                details[element_id] = (await (await form_widgets.Field(session, node).open()).describe())["details"]
            return details
        finally:
            await session.kill()

    assert asyncio.run(run()) == {
        "gdpr": "Your personal data will be processed for the purposes of managing our recruitment related activities.",
        "visa": "", "d1": "", "why": ""}
    assert_no_chromium_left()


def test_a_value_no_option_matches_is_refused_and_says_what_there_is(ba, site):
    async def check(fill, read, held):
        ok, why = await fill("visa", "Maybe later")
        assert not ok and "“Yes”" in why and "“No”" in why
        assert await held("visa") == []
        ok, why = await fill("candidate-location", "Bristol")           # three Bristols: not guessed
        assert not ok and "Bristol, Connecticut" in why
        assert await held("candidate-location") == []
        ok, why = await fill("consent", "perhaps")
        assert not ok and "yes or no" in why
        ok, why = await fill("other", "x" * 41)                         # its maxlength is 40
        assert not ok and "at most 40 characters" in why and await held("other") == [""]
    _on_form(ba, site, check)


def test_best_option_and_same_question():
    opts = ["Black (including African American, African, Carribean)", "White / Caucasian", "Prefer not to say"]
    assert form_widgets.best_option("Black African", opts) == opts[0]
    assert form_widgets.best_option("I'd prefer not to say", opts) == "Prefer not to say"
    assert form_widgets.best_option("Asian", opts) is None
    assert form_widgets.best_option("Bristol", ["Bristol, England, United Kingdom", "Bristol, Connecticut, United States"]) is None
    assert form_widgets.best_option("Bristol, United Kingdom", ["Little Bristol, England, United Kingdom",
                                    "Bristol, England, United Kingdom", "Stockland Bristol, England, United Kingdom"]) ==         "Bristol, England, United Kingdom"
    assert form_widgets.same_question("First Name*", "First Name")
    assert form_widgets.same_question("Do you now or in the future require visa sponsorship to work in the UK? *",
                                      "Do you now or in the future require visa sponsorship to work in the UK?")
    uni = "The University of the West of England, Bristol"
    listed = ["City of Bristol College", "University of Bristol", "Bristol, UWE", "University of the West of Scotland"]
    assert form_widgets.best_option(uni, listed) == "Bristol, UWE"            # initials count
    assert form_widgets.best_option(uni, ["University of Bristol", "Arizona State University - West"]) is None
    assert form_widgets.best_option(uni, ["University of the West of England", "University of Bristol"]) ==         "University of the West of England"
    assert "UWE" in form_widgets._queries(uni)                                 # what a type-ahead box is sent
    assert not form_widgets.same_question("Last Name*", "First Name")
    assert not form_widgets.same_question("Do you hold SC clearance?", "Do you require visa sponsorship?")


def test_text_typed_into_a_searchable_dropdown_but_not_picked_counts_as_empty(ba, site):
    from browser_use import BrowserSession

    async def run():
        session = BrowserSession(browser_profile=ba._browser_profile())
        await session.start()
        try:
            await session.navigate_to(f"{site}/greenhouse.html")
            await asyncio.sleep(1.0)
            page, cdp = await ba._focused_page(session)
            await page.evaluate("() => { document.getElementById('school').focus(); return 1; }")
            await ba._insert_text(session, cdp, "University of the West of England")
            return await ba._empty_required_fields(session)
        finally:
            await session.kill()

    assert "School" in asyncio.run(run())
    assert_no_chromium_left()
