"""form_widgets' reading of a value for a single checkbox (no browser needed)."""
import pytest

from app import form_widgets


@pytest.mark.parametrize("value, on", [
    ("Consent", True), ("I consent", True), ("I acknowledge", True), ("Yes", True), ("Agree", True),
    ("Do not consent", False), ("I don't consent", False), ("Decline", False), ("No", False),
])
def test_a_consent_answer_ticks_or_clears_a_single_checkbox(value, on):
    # Catapult's demographic-data box: the user's saved "Consent" was refused as not yes or no.
    assert bool(form_widgets._YES.search(value)) is on and bool(form_widgets._NO.search(value)) is (not on)


@pytest.mark.parametrize("value", ["Maybe", "Later", "Prefer not to say"])
def test_anything_else_is_neither(value):
    # Left unticked and refused: a single checkbox only takes a clear yes or no.
    assert not form_widgets._YES.search(value) and not form_widgets._NO.search(value)
