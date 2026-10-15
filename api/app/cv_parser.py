import re
from urllib.parse import urlparse

import fitz  # PyMuPDF

# A URL written out in the text: with a scheme, starting "www.", or a bare linkedin/github address.
_TEXT_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.|(?:[a-z]{2,3}\.)?linkedin\.com/|github\.com/)[^\s<>()\"'|,;]+")


def extract_text(pdf_bytes: bytes) -> str:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except Exception as exc:
        raise ValueError(f"Could not parse PDF: {exc}") from exc


def extract_links(pdf_bytes: bytes) -> list[tuple[str, str]]:
    """
    (anchor text, URL) for each web link in a CV PDF, de-duplicated, in page order: the targets of
    its clickable links, then URLs written out in its text. A CV often shows only "LinkedIn" or an
    icon, so a profile's URL is in no text at all. Best-effort: [] for a PDF it can't read.
    """
    links: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(anchor: str, url: str) -> None:
        url = url.strip().rstrip(".")
        key = url.lower().removeprefix("https://").removeprefix("http://").removeprefix("www.").rstrip("/")
        if url.lower().startswith(("http://", "https://", "www.", "linkedin.com", "github.com")) and key not in seen:
            seen.add(key)
            links.append((" ".join(anchor.split())[:60], url))

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page in doc:
            for link in page.get_links():
                if link.get("uri"):
                    add(page.get_textbox(link["from"]), link["uri"])
        for page in doc:
            for m in _TEXT_URL_RE.finditer(page.get_text()):
                add("", m.group(0))
    except Exception:
        return []
    return links


def profile_links(links: list[tuple[str, str]]) -> dict[str, str]:
    """The candidate's LinkedIn profile and GitHub account among a CV's links, by address alone:
    a linkedin.com/in/<name> page, and a github.com/<user> page (not a repository, which may be
    someone else's)."""
    found: dict[str, str] = {}
    for _, url in links:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = (parsed.hostname or "").lower().removeprefix("www.")
        parts = [p for p in parsed.path.split("/") if p]
        if host.endswith("linkedin.com") and len(parts) >= 2 and parts[0] == "in":
            found.setdefault("linkedin", url)
        elif host == "github.com" and len(parts) == 1:
            found.setdefault("github", url)
    return found
