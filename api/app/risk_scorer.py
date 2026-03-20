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


def lookup_by_title(title: str) -> dict:
    """Fuzzy match by occupation name when no ONET code is available."""
    title_lower = title.lower()
    best = None
    for code, data in ECONOMIC_INDEX.items():
        occ = data.get("occupation_name", "").lower()
        if title_lower in occ or occ in title_lower:
            best = {"onet_code": code, **data}
            break
    return best or {"occupation_name": title, "overall_exposure": 0.5}
