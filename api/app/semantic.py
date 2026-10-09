import logging
import os
from collections import OrderedDict
from typing import List, Optional

import httpx

from . import http_client
import numpy as np

logger = logging.getLogger("windrush.semantic")

_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
_EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")

# Background work (sync, job ingestion) tolerates the first call loading the model into
# limited VRAM; request handlers pass a short timeout and fall back to non-semantic ranking.
_BACKGROUND_TIMEOUT_S = 600.0
_BATCH_SIZE = 32
_MAX_TEXT_CHARS = 6000  # nomic-embed-text's context is ~2k tokens; Ollama truncates beyond it anyway

# Bounded LRU so a long-running API process doesn't grow without limit.
_CACHE_MAX = 512
_embedding_cache: "OrderedDict[str, list[float]]" = OrderedDict()


def _cache_get(text: str) -> Optional[list[float]]:
    vec = _embedding_cache.get(text)
    if vec is not None:
        _embedding_cache.move_to_end(text)
    return vec


def _cache_put(text: str, vec: list[float]) -> None:
    _embedding_cache[text] = vec
    _embedding_cache.move_to_end(text)
    while len(_embedding_cache) > _CACHE_MAX:
        _embedding_cache.popitem(last=False)


def _clip(text: str) -> str:
    return (text or "")[:_MAX_TEXT_CHARS]


async def get_embedding(text: str, timeout: float = _BACKGROUND_TIMEOUT_S) -> Optional[List[float]]:
    """Dense vector for one text via Ollama, or None if it's unavailable within `timeout`."""
    text = _clip(text)
    if not text:
        return None
    cached = _cache_get(text)
    if cached is not None:
        return cached
    try:
        async with http_client.async_client(timeout=timeout) as client:
            resp = await client.post(f"{_OLLAMA_HOST}/api/embed", json={"model": _EMBEDDING_MODEL, "input": [text]})
            if resp.status_code == 404:  # Ollama < 0.3 only has the single-prompt endpoint
                resp = await client.post(f"{_OLLAMA_HOST}/api/embeddings", json={"model": _EMBEDDING_MODEL, "prompt": text})
                vec = resp.json().get("embedding") if resp.status_code == 200 else None
            else:
                vec = (resp.json().get("embeddings") or [None])[0] if resp.status_code == 200 else None
            if vec:
                _cache_put(text, vec)
                return vec
            logger.warning("Ollama embedding failed with status %s: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("Error getting embedding from Ollama: %s", e)
    return None


def get_embeddings_sync(texts: list[str], timeout: float = _BACKGROUND_TIMEOUT_S) -> list[Optional[list[float]]]:
    """
    Embed many texts with batched /api/embed calls (one HTTP round-trip per _BATCH_SIZE texts
    instead of one per text). Returns a list aligned with `texts`; None where embedding failed.
    Blocking — call from a worker thread or a background job, never on the event loop.
    """
    out: list[Optional[list[float]]] = [None] * len(texts)
    todo = []
    for i, t in enumerate(texts):
        t = _clip(t)
        cached = _cache_get(t) if t else None
        if cached is not None:
            out[i] = cached
        elif t:
            todo.append((i, t))
    if not todo:
        return out
    try:
        with http_client.client(timeout=timeout) as client:
            for start in range(0, len(todo), _BATCH_SIZE):
                chunk = todo[start:start + _BATCH_SIZE]
                resp = client.post(f"{_OLLAMA_HOST}/api/embed",
                                   json={"model": _EMBEDDING_MODEL, "input": [t for _, t in chunk]})
                if resp.status_code == 404:  # old Ollama: fall back to one call per text
                    for i, t in chunk:
                        r = client.post(f"{_OLLAMA_HOST}/api/embeddings", json={"model": _EMBEDDING_MODEL, "prompt": t})
                        if r.status_code == 200 and r.json().get("embedding"):
                            out[i] = r.json()["embedding"]
                    continue
                if resp.status_code != 200:
                    logger.warning("Ollama batch embedding failed with status %s: %s", resp.status_code, resp.text[:200])
                    continue
                for (i, t), vec in zip(chunk, resp.json().get("embeddings") or []):
                    if vec:
                        out[i] = vec
                        _cache_put(t, vec)
    except Exception as e:
        logger.warning("Error getting batch embeddings from Ollama: %s", e)
    return out


def get_embedding_sync(text: str) -> Optional[List[float]]:
    """Synchronous single-text embedding (see get_embeddings_sync for bulk work)."""
    return get_embeddings_sync([text])[0]


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if not v1 or not v2:
        return 0.0
    a = np.array(v1)
    b = np.array(v2)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def vectorize_persona(persona: dict) -> str:
    """Create a descriptive string for a persona to be used for embedding."""
    parts = []

    # Core titles
    prefs = persona.get("preferences", {})
    titles = prefs.get("target_titles", [])
    if titles:
        parts.append(f"Target roles: {', '.join(titles)}")

    # Skills
    all_skills = []
    for cat in persona.get("skills", []):
        all_skills.extend(cat.get("skills", []))
    if all_skills:
        parts.append(f"Skills: {', '.join(all_skills)}")

    # Experience
    for exp in persona.get("history", []):
        parts.append(f"{exp.get('title')} at {exp.get('employer')}: {exp.get('summary')}")

    return " ".join(parts)
