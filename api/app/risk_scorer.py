import json
import os

_path = os.environ.get("ECONOMIC_INDEX_PATH", "/data/economic_index.json")

try:
    with open(_path) as f:
        ECONOMIC_INDEX: dict = json.load(f)
except FileNotFoundError:
    ECONOMIC_INDEX = {}


def lookup_onet(onet_code: str) -> dict:
    return ECONOMIC_INDEX.get(onet_code, {"occupation_name": "Unknown", "overall_exposure": 0.5})


# Direct skill-name → AI exposure scores based on published automation research
# (Felten et al., Acemoglu et al., Anthropic Economic Index)
SKILL_EXPOSURE: dict[str, float] = {
    # Programming languages
    "python": 0.65, "javascript": 0.62, "typescript": 0.60, "java": 0.58,
    "c++": 0.50, "c#": 0.55, "go": 0.52, "rust": 0.45, "ruby": 0.60,
    "php": 0.62, "swift": 0.52, "kotlin": 0.52, "scala": 0.55, "r": 0.65,
    # Web frameworks & libraries
    "react": 0.58, "next.js": 0.57, "vue": 0.57, "angular": 0.57,
    "svelte": 0.55, "node.js": 0.60, "express": 0.60, "django": 0.60,
    "fastapi": 0.60, "flask": 0.60, "rails": 0.60, "spring": 0.55,
    "tailwind css": 0.62, "tailwind": 0.62, "css": 0.65, "html": 0.68,
    "responsive design": 0.62,
    # Data & databases
    "sql": 0.72, "postgresql": 0.70, "mysql": 0.70, "mongodb": 0.65,
    "redis": 0.65, "elasticsearch": 0.62, "dynamodb": 0.65,
    "data analysis": 0.67, "data science": 0.60, "pandas": 0.65,
    "numpy": 0.65, "excel": 0.78, "tableau": 0.68, "power bi": 0.68,
    # ML / AI
    "pytorch": 0.58, "tensorflow": 0.58, "machine learning": 0.58,
    "deep learning": 0.55, "cnns": 0.55, "transfer learning": 0.55,
    "nlp": 0.55, "computer vision": 0.52, "scikit-learn": 0.62,
    "mlops": 0.52, "llms": 0.50,
    # Infrastructure & DevOps
    "docker": 0.55, "kubernetes": 0.50, "aws": 0.52, "azure": 0.52,
    "gcp": 0.52, "git": 0.55, "ci/cd": 0.50, "azure devops": 0.52,
    "terraform": 0.50, "linux": 0.52, "celery": 0.60,
    # APIs & architecture
    "rest apis": 0.62, "rest": 0.62, "graphql": 0.60,
    "microservices": 0.55, "system design": 0.48,
    # Design & UX
    "figma": 0.58, "ux research": 0.28, "ux design": 0.42,
    "ui design": 0.48, "product design": 0.42,
    # Soft / human skills
    "project management": 0.38, "stakeholder management": 0.30,
    "communication": 0.25, "leadership": 0.22, "negotiation": 0.28,
    "teaching": 0.22, "coaching": 0.20, "community engagement": 0.18,
    # Occupation-level titles
    "full-stack engineer": 0.62, "software engineer": 0.62,
    "machine learning engineer": 0.60, "data engineer": 0.62,
    "product manager": 0.42, "ux researcher": 0.28,
}


def lookup_by_title(title: str) -> dict:
    """Look up a skill or occupation title. Checks skill map first, then ONET fuzzy match."""
    key = title.lower().strip()

    # Direct skill name match
    if key in SKILL_EXPOSURE:
        return {"occupation_name": title, "overall_exposure": SKILL_EXPOSURE[key]}

    # Partial skill name match (e.g. "Tailwind CSS" matches "tailwind")
    for skill_key, exposure in SKILL_EXPOSURE.items():
        if skill_key in key or key in skill_key:
            return {"occupation_name": title, "overall_exposure": exposure}

    # ONET occupation fuzzy match
    for code, data in ECONOMIC_INDEX.items():
        occ = data.get("occupation_name", "").lower()
        if key in occ or occ in key:
            return {"onet_code": code, **data}

    return {"occupation_name": title, "overall_exposure": 0.5}
