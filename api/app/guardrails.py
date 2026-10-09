"""
Windrush Guardrails Module
Deterministic prompt-injection screening for uploaded CVs, before their text reaches an LLM.
No external dependencies — pure stdlib.
"""
import logging
import re

logger = logging.getLogger("windrush.guardrails")

# ── Prompt injection patterns (CV input check) ───────────────────────────────

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


class GuardrailViolation(Exception):
    """Raised when a hard guardrail fires."""
    def __init__(self, check: str, detail: str):
        self.check = check
        self.detail = detail
        super().__init__(f"Guardrail [{check}]: {detail}")


def check_cv_for_injection(cv_text: str) -> None:
    """
    Scan raw CV text for prompt injection before it is sent to the LLM.
    Raises GuardrailViolation if a pattern matches. Call site: main.py /upload.
    """
    for pattern in CV_INJECTION_PATTERNS:
        m = pattern.search(cv_text)
        if m:
            logger.warning("GUARDRAIL fired | check=cv_injection pattern=%r pos=%d", pattern.pattern, m.start())
            raise GuardrailViolation(
                "cv_injection",
                "CV text contains a potential prompt injection attempt and was rejected.",
            )
