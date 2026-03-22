"""
Windrush Guardrails Module
Deterministic pre/post-execution checks for all agent tool calls.
No external dependencies — pure stdlib.
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("windrush.guardrails")

# ── 1. Prompt injection patterns (CV input check) ───────────────────────────

CV_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(previous|all|prior|above)\s+instructions", re.I),
    re.compile(r"disregard\s+(previous|all|prior|above)\s+instructions", re.I),
    re.compile(r"forget\s+(everything|previous|your\s+instructions)", re.I),
    re.compile(r"you\s+are\s+now\s+(a\s+)?(different|new|evil|jailbroken)", re.I),
    re.compile(r"\bDAN\b"),                          # "Do Anything Now" jailbreak
    re.compile(r"repeat\s+(your\s+)?(system\s+)?prompt", re.I),
    re.compile(r"(reveal|show|print|output)\s+(your\s+)?(system\s+)?prompt", re.I),
    re.compile(r"pretend\s+(you\s+)?(have\s+)?no\s+restrictions", re.I),
    re.compile(r"(act|behave)\s+as\s+if\s+you\s+(have\s+)?no", re.I),
    re.compile(r"new\s+system\s+prompt\s*:", re.I),
    re.compile(r"<\s*system\s*>", re.I),
    re.compile(r"\[SYSTEM\]", re.I),
    re.compile(r"send\s+(my\s+)?(data|information|cv|profile)\s+to", re.I),
]

# ── 2. Search query sanitisation patterns ────────────────────────────────────

SEARCH_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+instructions", re.I),
    re.compile(r"system\s*prompt", re.I),
    re.compile(r"<\s*\/?script", re.I),
    re.compile(r"[<>]{2,}"),
    re.compile(r"\bexec\s*\(", re.I),
    re.compile(r"\beval\s*\(", re.I),
    re.compile(r"\bdrop\s+table\b", re.I),
    re.compile(r"\bSELECT\s+\*\b", re.I),
]

# ── 3. PII redaction patterns (SSE output only) ──────────────────────────────

PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), "[email]"),
    # UK landline / mobile
    (re.compile(r"(\+?44[\s\-]?|0)[1-9][\d\s\-]{7,12}"), "[phone]"),
    # Generic international
    (re.compile(r"\+\d{1,3}[\s\-]?\d{6,14}"), "[phone]"),
    # UK postcodes (e.g. SW1A 2AA)
    (re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.I), "[postcode]"),
    # NI numbers
    (re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b", re.I), "[ni-number]"),
]

# ── 4. Credential field names ────────────────────────────────────────────────

CREDENTIAL_FIELD_NAMES = {"password", "job_password", "secret", "token", "api_key"}

# Tools whose results contain derived CV data and should have PII masked in SSE
_PII_REDACT_TOOLS = {"extract_cv_profile", "generate_cover_letter", "score_job_fit", "apply_to_job"}

# ── 5. Audit log ─────────────────────────────────────────────────────────────

@dataclass
class GuardrailEvent:
    timestamp: float
    tool_name: str
    check: str
    fired: bool
    detail: str = ""


_audit_log: list[GuardrailEvent] = []


def _record(event: GuardrailEvent) -> None:
    _audit_log.append(event)
    if event.fired:
        logger.warning(
            "GUARDRAIL fired | tool=%s check=%s detail=%s",
            event.tool_name, event.check, event.detail,
        )
    else:
        logger.debug("GUARDRAIL ok | tool=%s check=%s", event.tool_name, event.check)


# ── 6. Public exceptions ─────────────────────────────────────────────────────

class GuardrailViolation(Exception):
    """Raised when a hard guardrail fires."""
    def __init__(self, check: str, detail: str):
        self.check = check
        self.detail = detail
        super().__init__(f"Guardrail [{check}]: {detail}")


# ── 7. Public API ─────────────────────────────────────────────────────────────

def check_cv_for_injection(cv_text: str) -> None:
    """
    Scan raw CV text for prompt injection before it is sent to the LLM.
    Raises GuardrailViolation if a pattern matches.
    Call site: main.py, before run_pipeline().
    """
    for pattern in CV_INJECTION_PATTERNS:
        m = pattern.search(cv_text)
        if m:
            _record(GuardrailEvent(
                timestamp=time.time(),
                tool_name="cv_upload",
                check="cv_injection",
                fired=True,
                detail=f"Pattern '{pattern.pattern}' matched at pos {m.start()}",
            ))
            raise GuardrailViolation(
                "cv_injection",
                "CV text contains a potential prompt injection attempt and was rejected.",
            )
    _record(GuardrailEvent(time.time(), "cv_upload", "cv_injection", False))


def sanitise_tool_input(tool_name: str, tool_input: dict) -> dict:
    """
    Validate and sanitise a tool's input dict before execution.
    Returns a (possibly modified) copy. Raises GuardrailViolation for hard blocks.
    """
    cleaned = dict(tool_input)

    if tool_name == "search_jobs":
        query = cleaned.get("query", "")
        for pattern in SEARCH_INJECTION_PATTERNS:
            if pattern.search(query):
                _record(GuardrailEvent(
                    time.time(), tool_name, "search_injection", True,
                    detail=f"Pattern '{pattern.pattern}' in query",
                ))
                raise GuardrailViolation(
                    "search_injection",
                    "Search query contains a disallowed pattern and was blocked.",
                )
        # Strip any residual HTML tags
        cleaned["query"] = re.sub(r"<[^>]+>", "", query).strip()
        _record(GuardrailEvent(time.time(), tool_name, "search_sanitise", False))

    if tool_name == "apply_to_job":
        job_url = cleaned.get("job_url", "")
        if job_url and not re.match(r"^https?://", job_url, re.I):
            _record(GuardrailEvent(
                time.time(), tool_name, "url_validation", True,
                detail=f"Non-HTTP URL rejected: {job_url[:60]}",
            ))
            raise GuardrailViolation("url_validation", "Job URL must begin with http:// or https://")
        _record(GuardrailEvent(time.time(), tool_name, "url_validation", False))

    # Strip credential fields from any tool input (defensive belt-and-braces)
    for field_name in list(cleaned.keys()):
        if field_name in CREDENTIAL_FIELD_NAMES:
            _record(GuardrailEvent(
                time.time(), tool_name, "credential_strip", True,
                detail=f"Stripped credential field '{field_name}' from {tool_name} input",
            ))
            del cleaned[field_name]

    return cleaned


def _redact_value(v: Any) -> Any:
    """Recursively walk a Python object and apply PII regex patterns to strings only."""
    if isinstance(v, str):
        for pattern, replacement in PII_PATTERNS:
            v = pattern.sub(replacement, v)
        return v
    elif isinstance(v, dict):
        return {k: _redact_value(val) for k, val in v.items()}
    elif isinstance(v, list):
        return [_redact_value(item) for item in v]
    return v


def redact_pii_from_result(tool_name: str, result: Any) -> tuple[Any, bool]:
    """
    Walk the result recursively and apply PII redaction patterns to string values.
    Returns (redacted_result, did_fire).

    IMPORTANT: Only call this for the SSE-streamed copy.
    The internal result passed to messages[] must remain unredacted.
    """
    if tool_name not in _PII_REDACT_TOOLS:
        return result, False

    redacted = _redact_value(result)
    fired = redacted != result
    _record(GuardrailEvent(
        time.time(), tool_name, "pii_redact", fired,
        detail="PII found and redacted" if fired else "",
    ))
    return redacted, fired


def redact_credentials_from_input(tool_name: str, tool_input: dict) -> tuple[dict, bool]:
    """
    Return a copy of tool_input with credential values replaced by '***'.
    Safe for SSE streaming. The original tool_input is still used for execution.
    """
    cleaned = dict(tool_input)
    fired = False
    for field_name in CREDENTIAL_FIELD_NAMES:
        if field_name in cleaned:
            cleaned[field_name] = "***"
            fired = True
    if fired:
        _record(GuardrailEvent(
            time.time(), tool_name, "credential_sse_mask", True,
            detail=f"Masked credentials in SSE tool_call event for {tool_name}",
        ))
    return cleaned, fired


def get_audit_log() -> list[dict]:
    """Return the in-process audit log as a list of dicts."""
    return [
        {
            "timestamp": e.timestamp,
            "tool_name": e.tool_name,
            "check": e.check,
            "fired": e.fired,
            "detail": e.detail,
        }
        for e in _audit_log
    ]
