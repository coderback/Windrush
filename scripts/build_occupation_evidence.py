"""Build data/occupation_evidence.json: for each occupation, which of its tasks people hand to AI most and least.

Reads the Anthropic Economic Index's chat usage (the newest month in the release) and takes each task's occupation from
the same dataset's O*NET task list. Only tasks with enough conversations count: quiet ones move a lot from month to month.

Usage: python scripts/build_occupation_evidence.py [folder for the downloads, about 320 MB; otherwise a temporary one]
"""
import csv
import json
import sys
import tempfile
import urllib.request
from collections import defaultdict
from pathlib import Path

RELEASE = "release_2026_06_26"
BASE = "https://huggingface.co/datasets/Anthropic/EconomicIndex/resolve/main/"
USAGE = f"{RELEASE}/data/aei_claude_ai_2026-06-26.csv"
TASKS = "robot_exposure/robot_exposure_tasks.csv"
OUTPUT = Path(__file__).parent.parent / "data" / "occupation_evidence.json"

MIN_SHARE_OF_USAGE = 0.01   # % of all conversations; below this a task's figures aren't steady
MIN_TASKS = 4               # fewer than this can't show a most and a least
SHOWN = 3
USE, AUTOMATION = "pct", "collaboration_bucket_automation_pct"

csv.field_size_limit(10**9)


def fetch(folder: Path, path: str) -> Path:
    target = folder / Path(path).name
    if not target.exists():
        print(f"Downloading {path} ...")
        urllib.request.urlretrieve(BASE + path, target)
    return target


def build(folder: Path) -> dict:
    usage = defaultdict(dict)   # (month start, task id) -> metric -> value
    months = set()
    with open(fetch(folder, USAGE), newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r["geo_id"] == "GLOBAL" and r["category_name"] == "onet" and r["hierarchy_level"] == "0"
                    and r["metric_id"] in (USE, AUTOMATION) and r["value"]):
                usage[(r["date_start"], r["node_external_id"])][r["metric_id"]] = float(r["value"])
                months.add(r["date_start"])
    month = max(months)

    occupations = defaultdict(dict)  # SOC code -> task id -> task text
    with open(fetch(folder, TASKS), newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            occupations[r["onetsoc_code"][:7]][r["task_id"]] = r["task_statement"].strip()

    evidence = {}
    for code, tasks in occupations.items():
        seen = [(usage[(month, t)][AUTOMATION], text) for t, text in tasks.items()
                if usage.get((month, t), {}).get(USE, 0) >= MIN_SHARE_OF_USAGE and AUTOMATION in usage[(month, t)]]
        if len(seen) < MIN_TASKS:
            continue
        seen.sort(key=lambda x: -x[0])
        shown = min(SHOWN, len(seen) // 2)
        entry = lambda x: {"task": x[1], "handed_to_ai": round(x[0])}
        evidence[code] = {"most_handed_to_ai": [entry(x) for x in seen[:shown]],
                          "least_handed_to_ai": [entry(x) for x in seen[-shown:][::-1]],
                          "tasks_seen": len(seen), "tasks_listed": len(tasks), "month": month[:7]}
    return evidence


with tempfile.TemporaryDirectory() as temporary:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(temporary)
    result = build(folder)
with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=1, ensure_ascii=False)
print(f"Saved evidence for {len(result)} occupations to {OUTPUT}")
