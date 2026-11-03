"""Score the demo's fictional skills and job titles with the project's real lookup code.

Runs api/app/risk_scorer.py (Anthropic Economic Index + O*NET task penetration) and the
_HARDCODED_EXPOSURE table from api/app/agent.py, with the same rounding and labels as the
score_ai_risk tool, minus its LLM step, which only writes explanations. Output goes to
frontend/src/lib/demo-exposure.json, which the read-only demo replays.

From the repo root:
  docker run --rm -v "$PWD:/repo" -w /repo python:3.13-slim sh -c \
    "pip install -q numpy scikit-learn && python frontend/scripts/score_demo_skills.py"
"""
import ast
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["ECONOMIC_INDEX_PATH"] = str(ROOT / "data" / "economic_index.json")
os.environ["TASK_PENETRATION_PATH"] = str(ROOT / "data" / "task_penetration.csv")
sys.path.insert(0, str(ROOT / "api" / "app"))

from risk_scorer import lookup_by_title, occupation_exposure  # noqa: E402

# Read the table without importing agent.py, which pulls in the LLM and browser dependencies.
_tree = ast.parse((ROOT / "api" / "app" / "agent.py").read_text(encoding="utf-8"))
HARDCODED = {}
for node in _tree.body:
    target = node.targets[0] if isinstance(node, ast.Assign) else getattr(node, "target", None)
    if getattr(target, "id", "") == "_HARDCODED_EXPOSURE":
        HARDCODED = ast.literal_eval(node.value)

SKILLS = [
    "Python", "SQL", "Excel", "Tableau", "Data Analysis", "Machine Learning", "Statistics",
    "Financial Analysis", "Project Management", "Stakeholder Management", "Data Analyst", "Reporting Analyst",
]
JOB_TITLES = [
    "Data Analyst", "Analytics Engineer", "Business Intelligence Developer", "Data Scientist",
    "Operations Research Analyst", "Financial Analyst",
]


def score_skill(skill: str) -> dict:
    # Mirrors the score_ai_risk branch of execute_tool in api/app/agent.py.
    key = skill.lower().strip()
    if key in HARDCODED:
        exposure = HARDCODED[key]
    else:
        raw = lookup_by_title(skill).get("overall_exposure", 0.0)
        exposure = round(raw, 2) if raw and raw != 0.5 else 0.55
    return {
        "skill": skill,
        "exposure_score": round(exposure * 100),
        "risk_label": "High" if exposure >= 0.65 else ("Medium" if exposure >= 0.35 else "Low"),
    }


out = {
    "skill_risks": [score_skill(s) for s in SKILLS],
    "job_exposure": {t: round(occupation_exposure(t), 4) for t in JOB_TITLES},
}
path = ROOT / "frontend" / "src" / "lib" / "demo-exposure.json"
path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
print(json.dumps(out, indent=2))
