import logging
import os
import json
import numpy as np
from typing import List, Optional
import httpx

logger = logging.getLogger("windrush.semantic")

_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
_EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")

# Simple in-memory cache for embeddings to avoid redundant calls
_embedding_cache = {}

async def get_embedding(text: str) -> Optional[List[float]]:
    """Get dense vector embedding for text via Ollama."""
    if not text:
        return None
    
    if text in _embedding_cache:
        return _embedding_cache[text]
    
    try:
        # Increased timeout to 300s to allow for model loading into GPU on limited VRAM
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{_OLLAMA_HOST}/api/embeddings",
                json={"model": _EMBEDDING_MODEL, "prompt": text}
            )
            if resp.status_code == 200:
                embedding = resp.json().get("embedding")
                _embedding_cache[text] = embedding
                return embedding
            else:
                logger.warning(f"Ollama embedding failed with status {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Error getting embedding from Ollama: {e}")
    
    return None

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if not v1 or not v2:
        return 0.0
    
    a = np.array(v1)
    b = np.array(v2)
    
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    
    if norm_a == 0 or norm_b == 0:
        return 0.0
        
    return float(dot / (norm_a * norm_b))

def get_embedding_sync(text: str) -> Optional[List[float]]:
    """Synchronous version of get_embedding for use in db operations."""
    if not text:
        return None
    
    if text in _embedding_cache:
        return _embedding_cache[text]
    
    try:
        # Increased timeout to 300s to allow for model loading into GPU on limited VRAM
        with httpx.Client(timeout=300.0) as client:
            resp = client.post(
                f"{_OLLAMA_HOST}/api/embeddings",
                json={"model": _EMBEDDING_MODEL, "prompt": text}
            )
            if resp.status_code == 200:
                embedding = resp.json().get("embedding")
                _embedding_cache[text] = embedding
                return embedding
            else:
                logger.warning(f"Ollama embedding failed with status {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Error getting embedding from Ollama: {e}")
    
    return None

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
