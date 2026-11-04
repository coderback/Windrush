"""Build data/occupation_titles.csv: every job title O*NET knows, and the occupation it belongs to.

Reads O*NET's Occupation Data, Alternate Titles and Sample of Reported Titles, reduces codes to the six-digit SOC
codes the Economic Index uses, and leaves deciding what to do with ambiguous titles to risk_scorer.py.

O*NET database by the U.S. Department of Labor, Employment and Training Administration, used under CC BY 4.0.
"""
import csv
import io
import re
import urllib.request
from pathlib import Path

VERSION = "30_2"
BASE = f"https://www.onetcenter.org/dl_files/database/db_{VERSION}_text/"
FILES = {"Occupation%20Data.txt": ("Title",), "Alternate%20Titles.txt": ("Alternate Title", "Short Title"),
         "Sample%20of%20Reported%20Titles.txt": ("Reported Job Title",)}
OUTPUT = Path(__file__).parent.parent / "data" / "occupation_titles.csv"


def _spellings(title: str) -> list[str]:
    """'AI Engineer (Artificial Intelligence Engineer)' is both of those titles."""
    title = title.strip()
    inner = re.search(r"\(([^)]+)\)", title)
    outer = re.sub(r"\s*\([^)]*\)", "", title).strip()
    return [t for t in {outer, inner.group(1).strip() if inner else ""} if t and t.lower() != "n/a"]


rows: set[tuple[str, str]] = set()
for name, columns in FILES.items():
    with urllib.request.urlopen(BASE + name) as response:
        text = response.read().decode("utf-8")
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        code = row["O*NET-SOC Code"][:7]
        for column in columns:
            rows.update((code, title) for title in _spellings(row[column]))

with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f, lineterminator="\n")
    writer.writerow(["soc", "title"])
    writer.writerows(sorted(rows))
print(f"Saved {len(rows)} titles for {len({code for code, _ in rows})} occupations to {OUTPUT}")
