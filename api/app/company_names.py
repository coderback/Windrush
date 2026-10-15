"""Employer-name normalisation shared by company research, CV import and the sponsor register."""
import re

_COMPANY_SUFFIXES = {"ltd", "limited", "plc", "inc", "llc", "llp", "corp", "corporation", "co", "uk", "group",
                     "holdings", "gmbh", "sa", "ag", "bv"}


def normalise_company_name(text: str) -> str:
    """Lower-case words only, legal / regional suffixes dropped: 'Kestrel Ledger Analytics Ltd.' ->
    'kestrel ledger analytics'."""
    words = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split()
    while words and words[-1] in _COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)
