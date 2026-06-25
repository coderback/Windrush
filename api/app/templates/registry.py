"""
Document template registry.

Maps a public ``template_id`` to the Jinja files used to render a CV and a
cover letter. We ship one polished template ("classic") now; adding another is
just a new dict entry plus the HTML files — the generate -> preview -> pdf code
paths already thread ``template_id`` through unchanged.
"""
from __future__ import annotations

from typing import TypedDict


class Template(TypedDict):
    label: str
    cv: str
    letter: str


REGISTRY: dict[str, Template] = {
    "classic": {
        "label": "Classic (single column)",
        "cv": "classic_cv.html",
        "letter": "classic_letter.html",
    },
}

DEFAULT_TEMPLATE_ID = "classic"


def resolve(template_id: str | None) -> Template:
    """Return the template config for an id, falling back to the default."""
    return REGISTRY.get(template_id or DEFAULT_TEMPLATE_ID, REGISTRY[DEFAULT_TEMPLATE_ID])
