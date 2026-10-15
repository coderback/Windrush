"""
Azure OpenAI settings for LLM_BACKEND=azure, shared by the text features (agent.py) and the
browser agent (browser_agent.py).

The backend targets a reasoning-model deployment (e.g. gpt-6-luna): those reject a non-default
temperature, frequency_penalty, top_p and max_tokens, and spend part of max_completion_tokens on
hidden reasoning — the callers translate their parameters accordingly.
"""
import os
from dataclasses import dataclass, field

REQUIRED = ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT")

# Dated API version for browser-use's ChatAzureOpenAI (AsyncAzureOpenAI); the text features use the
# versionless v1 surface. 2024-12-01-preview is the first with reasoning_effort.
DEFAULT_API_VERSION = "2024-12-01-preview"

# 'none' | 'low' | 'medium' | 'high' | 'xhigh' on gpt-6-luna. Measured on the six text features
# (CV parse, AI-risk reasoning, job fit, cover letter, tailored CV, roadmap): 'low' spent at most 502
# reasoning tokens and ≤ 7 s per call; 'medium' up to 1603 tokens / 15 s and 'high' up to 2561 / 21 s,
# with every output valid at each level ('none': 0 tokens, ≤ 5 s). 'low' keeps a little planning for
# the rule-heavy writing prompts at almost no extra cost.
DEFAULT_REASONING_EFFORT = "low"

# Hidden reasoning counts against max_completion_tokens, so every call gets this much on top of its
# visible-answer budget, by effort: 5-8x the most reasoning measured at that effort. Unused tokens
# cost nothing; running out returns an empty answer, which the features treat like unparseable output.
REASONING_HEADROOM = {"none": 1024, "low": 4096, "medium": 8192, "high": 16384, "xhigh": 32768}


@dataclass(frozen=True)
class AzureSettings:
    endpoint: str                                # resource endpoint, e.g. https://<resource>.openai.azure.com/
    api_key: str = field(repr=False)             # never in a repr / log line
    deployment: str                              # the deployment name is the `model` on every call
    api_version: str = DEFAULT_API_VERSION
    reasoning_effort: str = DEFAULT_REASONING_EFFORT

    @property
    def v1_base_url(self) -> str:
        """The versionless OpenAI-compatible surface: plain `AsyncOpenAI(base_url=...)` works against it."""
        return self.endpoint.rstrip("/") + "/openai/v1/"

    @property
    def reasoning_headroom(self) -> int:
        """Tokens to add to a visible-answer budget for this effort (the largest for an unknown one)."""
        return REASONING_HEADROOM.get(self.reasoning_effort, max(REASONING_HEADROOM.values()))


def load() -> AzureSettings:
    """The settings from the environment; RuntimeError naming every missing required variable."""
    missing = [name for name in REQUIRED if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError(
            f"LLM_BACKEND=azure but {', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set — "
            "add the Azure OpenAI settings to .env (see .env.example)"
        )
    return AzureSettings(
        endpoint=os.environ["AZURE_OPENAI_ENDPOINT"].strip(),
        api_key=os.environ["AZURE_OPENAI_API_KEY"].strip(),
        deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"].strip(),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "").strip() or DEFAULT_API_VERSION,
        reasoning_effort=os.environ.get("AZURE_OPENAI_REASONING_EFFORT", "").strip().lower()
        or DEFAULT_REASONING_EFFORT,
    )
