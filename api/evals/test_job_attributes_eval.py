"""
How well the LLM reads job adverts (job_attributes.extract), scored against labelled data.

- Seniority: seniority_holdout.json, 523 hand-written titles and short adverts labelled junior / mid /
  senior (53 marked ambiguous are left out). It was written blind, without looking at the regex or
  the prompt, so the regex's score on it is a fair baseline.
- Sponsorship: the labelled sentences from tests/test_sponsorship.py, each set inside a short advert.

The bars sit under the first three runs (October 2026, Azure gpt-6-luna: 96.4%, 96.0% and 95.7%
seniority; junior recall 95.5%, 94.4% and 92.7%; no failed calls), leaving room for run-to-run noise,
so a prompt or model change that makes things clearly worse fails here. Every run writes
evals/last_run.json with each item's answer, for looking into misses.
"""
import asyncio
import collections
import json
import pathlib
import time

import pytest

from app import job_attributes, seniority, sponsorship
from test_sponsorship import CASES

HERE = pathlib.Path(__file__).parent
HOLDOUT = [x for x in json.loads((HERE / "seniority_holdout.json").read_text(encoding="utf-8")) if not x["ambiguous"]]
SPONSORSHIP_ADS = [(f"We are hiring a Graduate Engineer to join our London team. You will build software with us. "
                    f"{text} Apply with your CV.", expected) for text, expected in CASES if text]
_CONCURRENCY = 6


async def _extract_all(items: list[tuple[str, str]]) -> list[tuple[dict | None, float]]:
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(title, description):
        async with sem:
            t0 = time.perf_counter()
            return await job_attributes.extract(title, "", description), time.perf_counter() - t0
    return await asyncio.gather(*(one(t, d) for t, d in items))


@pytest.fixture(scope="module")
def run():
    """One pass over every item; the tests below each check one aspect of it."""
    async def both():
        return (await _extract_all([(x["title"], x["description"]) for x in HOLDOUT]),
                await _extract_all([("Graduate Engineer", ad) for ad, _ in SPONSORSHIP_ADS]))
    holdout, ads = asyncio.run(both())
    rows = [{**x, "llm": (got or {}).get("seniority"), "regex": seniority.infer_level(x["title"], x["description"]),
             "failed": got is None, "secs": round(secs, 2)} for x, (got, secs) in zip(HOLDOUT, holdout)]
    sponsor_rows = [{"ad": ad, "label": expected, "llm": (got or {}).get("sponsorship"),
                     "regex": sponsorship.classify("Graduate Engineer", ad).sponsorship, "failed": got is None}
                    for (ad, expected), (got, _) in zip(SPONSORSHIP_ADS, ads)]
    (HERE / "last_run.json").write_text(json.dumps({"seniority": rows, "sponsorship": sponsor_rows},
                                                   indent=1, ensure_ascii=False), encoding="utf-8")
    return rows, sponsor_rows


def _accuracy(rows: list[dict], key: str = "llm") -> float:
    return sum(r[key] == r["label"] for r in rows) / len(rows)


def test_report(run):
    rows, sponsor_rows = run
    print(f"\nseniority  LLM {_accuracy(rows):.1%}  regex {_accuracy(rows, 'regex'):.1%}  ({len(rows)} items, "
          f"median {sorted(r['secs'] for r in rows)[len(rows) // 2]} s per call)")
    for level in job_attributes.LEVELS:
        subset = [r for r in rows if r["label"] == level]
        print(f"  {level:6} recall  LLM {_accuracy(subset):.1%}  regex {_accuracy(subset, 'regex'):.1%}")
    print("  misses (label → LLM):", dict(collections.Counter((r["label"], r["llm"]) for r in rows
                                                           if r["llm"] != r["label"])))
    print(f"sponsorship  LLM {_accuracy(sponsor_rows):.1%}  regex {_accuracy(sponsor_rows, 'regex'):.1%}  "
          f"({len(sponsor_rows)} statements)")
    for r in sponsor_rows:
        if r["llm"] != r["label"]:
            print(f"  LLM said {r['llm']}, expected {r['label']}: {r['ad'].split('. ', 2)[-1][:100]}")


def test_calls_succeed(run):
    rows, sponsor_rows = run
    failed = sum(r["failed"] for r in rows + sponsor_rows)
    assert failed <= 0.01 * len(rows + sponsor_rows), f"{failed} calls failed"


def test_seniority_accuracy(run):
    rows, _ = run
    assert _accuracy(rows) >= 0.94


@pytest.mark.parametrize("level", job_attributes.LEVELS)
def test_each_level_is_recalled(run, level):
    assert _accuracy([r for r in run[0] if r["label"] == level]) >= 0.90


def test_junior_roles_are_not_read_as_senior(run):
    # The costly miss: it hides a role the candidate should see.
    assert sum(r["label"] == "junior" and r["llm"] == "senior" for r in run[0]) <= 1


def test_sponsorship_statements(run):
    assert _accuracy(run[1]) >= 0.90
