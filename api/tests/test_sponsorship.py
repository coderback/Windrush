"""Visa sponsorship and security-clearance signals read from job ads."""
import pytest

from app import sponsorship
from app.sponsorship import NOT_OFFERED, OFFERED, UNKNOWN

CASES = [
    # Offered
    ("Visa sponsorship is available for this role.", OFFERED),
    ("We are happy to sponsor Skilled Worker visas for the right candidate.", OFFERED),
    ("We can offer visa sponsorship.", OFFERED),
    ("Benefits include 25 days' holiday, a pension and full visa sponsorship.", UNKNOWN),  # no verb: unclear
    ("We offer Skilled Worker visa sponsorship and relocation support.", OFFERED),
    ("Sponsorship can be considered for exceptional candidates.", OFFERED),
    ("We sponsor work visas.", OFFERED),
    ("Relocation and visa support are provided.", OFFERED),
    # Not offered
    ("Unfortunately we are unable to offer visa sponsorship for this position.", NOT_OFFERED),
    ("We cannot sponsor visas.", NOT_OFFERED),
    ("We can't provide sponsorship at this time.", NOT_OFFERED),
    ("This role does not offer sponsorship.", NOT_OFFERED),
    ("Please note: no visa sponsorship is available.", NOT_OFFERED),
    ("Sponsorship is not available for this role.", NOT_OFFERED),
    ("You must be eligible to work in the UK without sponsorship.", NOT_OFFERED),
    ("Applicants must have the right to work in the UK without requiring visa sponsorship now or in the future.",
     NOT_OFFERED),
    ("Candidates must not require sponsorship to work in the UK.", NOT_OFFERED),
    ("We are not currently able to sponsor candidates.", NOT_OFFERED),
    ("This position is open to UK nationals only.", NOT_OFFERED),
    ("You must be able to work in the UK without restrictions in accordance with UK National Law.", NOT_OFFERED),
    ("Applicants need an unrestricted right to work in the UK.", NOT_OFFERED),
    ("You can work in the UK without restrictions on your hours once you start.", UNKNOWN),   # not about the visa
    ("You must be a British citizen to apply.", NOT_OFFERED),
    ("We do not provide visa support.", NOT_OFFERED),
    ("We are unable to support visa applications.", NOT_OFFERED),
    # Doesn't say
    ("You must have the right to work in the UK.", UNKNOWN),        # Graduate-visa holders do, for now
    ("We are a licensed sponsor and an equal opportunities employer.", UNKNOWN),
    ("Please tell us whether you will require sponsorship.", UNKNOWN),
    ("Join our sponsorship team managing brand partnerships.", UNKNOWN),
    ("", UNKNOWN),
]


@pytest.mark.parametrize("text, expected", CASES)
def test_sponsorship_statements(text, expected):
    assert sponsorship.classify("Graduate Engineer", text).sponsorship == expected


def test_a_negative_anywhere_beats_an_offer_and_is_quoted():
    ad = ("<p>Visa sponsorship is available for some of our roles.</p><p>For this role, however, "
          "we are unable to offer sponsorship&nbsp;and candidates must already have the right to work.</p>")
    signals = sponsorship.classify("Graduate Analyst", ad)
    assert signals.sponsorship == NOT_OFFERED
    assert signals.evidence.startswith("For this role, however, we are unable to offer sponsorship and")


def test_the_title_counts_and_evidence_is_bounded():
    assert sponsorship.classify("Junior Developer (No Sponsorship)", "").sponsorship == NOT_OFFERED
    long_sentence = "Visa sponsorship is available " + "and we would love to hear from you " * 20 + "."
    evidence = sponsorship.classify("Engineer", long_sentence).evidence
    assert evidence.endswith("…") and len(evidence) <= 220


@pytest.mark.parametrize("text, level", [
    ("This role requires you to obtain a Security Check (SC) level security clearance.", "SC"),
    ("This role requires you to obtain a Security Check level security clearance.", "SC"),   # SC's formal name
    ("Candidates must be SC cleared or eligible for SC clearance.", "SC"),
    ("You will need to hold active DV clearance.", "DV"),
    ("Developed Vetting is required.", "DV"),
    ("eDV eligible candidates only.", "DV"),
    ("NPPV3 vetting applies to this role.", "NPPV"),
    ("You must be able to obtain government security clearance.", "unspecified"),
    ("You will need to pass BPSS security clearance.", ""),          # the basic check
    ("No security clearance is required for this role.", ""),
    ("This role does not require SC clearance.", ""),
    ("Our SCADA systems team builds control software.", ""),
])
def test_clearance_levels(text, level):
    assert sponsorship.classify("Engineer", text).clearance == level


def test_the_most_demanding_clearance_wins():
    ad = "Candidates must be SC cleared. Some projects need DV clearance."
    assert sponsorship.classify("Engineer", ad).clearance == "DV"


@pytest.mark.parametrize("status, clearance, ruled_out", [
    (NOT_OFFERED, "", True), (UNKNOWN, "SC", True), (OFFERED, "DV", True),
    (UNKNOWN, "NPPV", False), (UNKNOWN, "unspecified", False), (OFFERED, "", False), (UNKNOWN, "", False),
])
def test_what_rules_a_sponsored_candidate_out(status, clearance, ruled_out):
    assert sponsorship.rules_out_sponsored_candidates(status, clearance) is ruled_out
