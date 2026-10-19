"""Job store: batched embedding, SQL filtering, location matching, pagination, ranking."""
import sqlite3
import threading
import time

import numpy as np
import pytest
from conftest import fake_vector, make_job

from app import jobs_db, semantic


def _count(where="1=1"):
    return sqlite3.connect(jobs_db._DB_PATH).execute(f"SELECT COUNT(*) FROM jobs WHERE {where}").fetchone()[0]


# ── ingestion ─────────────────────────────────────────────────────────────────

def test_new_jobs_are_embedded_in_batches(db, ollama):
    added, _ = jobs_db.add_jobs([make_job(i, f"Role {i}") for i in range(70)])
    assert added == 70 and ollama.calls == [("embed", 32), ("embed", 32), ("embed", 6)]


def test_existing_jobs_are_refreshed_without_re_embedding(db, ollama):
    jobs = [make_job(i, f"Role {i}") for i in range(10)]
    jobs_db.add_jobs(jobs)
    ollama.calls.clear()
    added, updated = jobs_db.add_jobs(jobs)
    assert (added, updated) == (0, 10) and ollama.calls == []


def test_only_rows_missing_a_vector_are_embedded(db, ollama):
    jobs = [make_job(i, f"Role {i}") for i in range(5)]
    jobs_db.add_jobs(jobs)
    con = sqlite3.connect(jobs_db._DB_PATH)
    con.execute("UPDATE jobs SET semantic_vector=NULL WHERE job_id='3'")
    con.commit()
    con.close()
    semantic._embedding_cache.clear()
    ollama.calls.clear()
    jobs_db.add_jobs(jobs)
    assert ollama.calls == [("embed", 1)] and _count("semantic_vector IS NULL") == 0


def test_in_batch_duplicates_are_inserted_once(db, ollama):
    jobs_db.add_jobs([make_job(1, "Dup"), make_job(1, "Dup")])
    assert _count("title='Dup'") == 1


def test_slow_embedding_does_not_hold_the_db_write_lock(db, ollama):
    jobs_db.add_jobs([make_job("seed", "Seed")])
    ollama.delay = 2.0
    t = threading.Thread(target=jobs_db.add_jobs, args=([make_job(i, f"Slow {i}") for i in range(5)],))
    t.start()
    time.sleep(0.5)
    t0 = time.time()
    jobs_db.update_description(jobs_db.get_jobs(limit=1)[0][0]["id"], "x" * 10)
    waited = time.time() - t0
    t.join()
    assert waited < 0.5


def test_falls_back_to_single_embedding_endpoint_on_old_ollama(ollama):
    ollama.embed_404 = True
    assert all(semantic.get_embeddings_sync(["a", "b"]))
    assert [c[0] for c in ollama.calls] == ["embeddings", "embeddings"]


# ── querying ──────────────────────────────────────────────────────────────────

SEED = [
    make_job("A", "Machine Learning Engineer", "DeepCo", "London, UK", "PyTorch models"),
    make_job("B", "Backend Engineer", "FinBank", "London, United Kingdom", "fintech payments, visa sponsorship available"),
    make_job("C", "Data Analyst", "Aussie Ltd", "Sydney, Australia", "dashboards"),
    make_job("D", "Software Engineer", "USCo", "Austin, TX, US", "services"),
    make_job("E", "Frontend Developer", "Remote Inc", "Remote", "react"),
    make_job("F", "Platform Engineer", "Canuck", "London, Ontario, Canada", "infra"),
    make_job("G", "Graduate Software Engineer", "GradCo", "Manchester, England", "training", level="junior"),
    make_job("H", "Senior Business Analyst", "Bizco", "Houston", "business reporting"),
]


@pytest.fixture
def seeded(db, ollama):
    jobs_db.add_jobs(SEED)
    con = sqlite3.connect(jobs_db._DB_PATH)
    for n, job in enumerate(SEED):  # deterministic recency: A newest … H oldest
        con.execute("UPDATE jobs SET updated_at=? WHERE job_id=?", (f"2026-10-0{9 - n}T00:00:00", job["job_id"]))
    con.commit()
    con.close()


def ids(**kwargs):
    jobs, _ = jobs_db.get_jobs(limit=100, **kwargs)
    return sorted(j["job_id"] for j in jobs)


@pytest.mark.parametrize("kwargs, expected", [
    ({"tags": ["machine learning"]}, ["A"]),                       # free-text tag
    ({"tags": ["ml", "data"]}, ["A", "C"]),                       # role tags are OR'd
    ({"tags": ["fintech", "sponsorship"]}, ["B"]),                # domain tags are AND'd
    ({"tags": ["fintech", "startup"]}, []),
    ({"query": "backend fintech"}, ["B"]),                        # query words AND'd
    ({"category": "frontend"}, ["E"]),
    ({"tags": ["100%"]}, []),                                     # LIKE wildcards escaped
    ({"tags": ["_"]}, []),
    ({"location": "us"}, ["D"]),                                  # not Australia / Houston / "business"
    ({"location": "uk"}, ["A", "B", "G"]),                        # not London, Ontario
    ({"location": "London"}, ["A", "B"]),
    ({"location": "London, Ontario"}, ["F"]),
    ({"remote": True}, ["E"]),
    ({"location": "London", "remote": True}, ["A", "B", "E"]),
    ({"level": "junior"}, ["G"]),
])
def test_filters(seeded, kwargs, expected):
    assert ids(**kwargs) == expected


@pytest.mark.parametrize("location, expected", [
    ("London", ["UK1", "UK2"]),
    (["London", "Toronto"], ["TO", "UK1", "UK2"]),  # Toronto keeps its Ontario rows
])
def test_london_ontario_rows_cannot_crowd_uk_jobs_out_of_the_candidate_pool(db, ollama, monkeypatch,
                                                                            location, expected):
    monkeypatch.setattr(jobs_db, "_CANDIDATE_POOL", 3)
    older = [make_job("UK1", "Analyst", location="London, UK"),
             make_job("UK2", "Engineer", location="London, England"),
             make_job("TO", "Developer", location="Toronto, Ontario, Canada")]
    newer = [make_job(f"ON{i}", f"Analyst {i}", location="London, Ontario, Canada") for i in range(5)]
    jobs_db.add_jobs(older + newer)
    con = sqlite3.connect(jobs_db._DB_PATH)
    for n, job in enumerate(newer + older):  # the Ontario rows are the newest
        con.execute("UPDATE jobs SET updated_at=? WHERE job_id=?", (f"2026-10-{20 - n}T00:00:00", job["job_id"]))
    con.commit()
    con.close()
    assert ids(location=location) == expected


@pytest.mark.parametrize("job_location, locations, expected", [
    ("London, United Kingdom (Hybrid)", ["London", "United Kingdom"], True),
    ("Cambridge, UK", ["United Kingdom"], True),
    ("Austin, TX", ["London", "United Kingdom"], False),
    ("London, Ontario, Canada", ["London"], False),
    ("Remote - US", ["London"], True),  # the feed's remote filter decides
    ("", ["London"], True),             # the source didn't say where
    ("Austin, TX", [], True),
    ("Austin, TX", ["Remote"], True),
])
def test_in_locations(job_location, locations, expected):
    assert jobs_db.in_locations(job_location, locations) is expected


def test_exclusions_apply_before_pagination(seeded):
    seen, page, more = [], 0, True
    while more:
        jobs, more = jobs_db.get_jobs(limit=3, offset=page * 3, exclude={("deepco", "machine learning engineer")})
        if more:
            assert len(jobs) == 3
        seen += [j["job_id"] for j in jobs]
        page += 1
    assert sorted(seen) == ["B", "C", "D", "E", "F", "G", "H"] and len(seen) == len(set(seen))


def test_without_a_vector_newest_first(seeded):
    jobs, _ = jobs_db.get_jobs(limit=3)
    assert [j["job_id"] for j in jobs] == ["A", "B", "C"]


def test_semantic_ranking_puts_the_closest_job_first(seeded):
    jobs, _ = jobs_db.get_jobs(limit=8, persona_vector=fake_vector(jobs_db._job_text(SEED[3])))
    assert jobs[0]["job_id"] == "D" and jobs[0]["semantic_score"] > 0.99


def test_vector_dimension_mismatch_is_tolerated(seeded):
    jobs, _ = jobs_db.get_jobs(limit=8, persona_vector=[0.1] * 10)
    assert len(jobs) == 8 and all(j["semantic_score"] == 0.0 for j in jobs)


# ── searching by words ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, groups", [
    ("ML engineer", [("ml", "machine learning"), ("engineer",)]),
    ("machine learning engineer", [("ml", "machine learning"), ("engineer",)]),
    ("front-end developer", [("frontend", "front end"), ("dev", "developer")]),
    ("Quant Developer in London", [("quant", "quantitative"), ("dev", "developer"), ("london",)]),
    ("C++ developer", [("c++",), ("dev", "developer")]),
    ("engineer engineer", [("engineer",)]),
    ("", []),
])
def test_search_groups(text, groups):
    assert jobs_db.search_groups(text) == groups


WORDS = [
    make_job("M1", "Machine Learning Engineer", "DeepCo", description="models"),
    make_job("M2", "ML Engineer", "TinyCo", description="pipelines"),
    make_job("M3", "HTML Engineer", "WebCo", description="web pages"),
    make_job("Q1", "Quantitative Developer", "HedgeCo", description="pricing"),
    make_job("F1", "Frontend Engineer", "UiCo", description="react"),
    make_job("F2", "Front-End Developer", "UiCo2", description="vue"),
    make_job("G1", "Engineering Graduate Programme", "BigCo", description="Python and SQL"),
]


@pytest.fixture
def worded(db, ollama):
    jobs_db.add_jobs(WORDS)


@pytest.mark.parametrize("kwargs, expected", [
    ({"tags": ["ml engineer"]}, ["M1", "M2"]),                 # a synonym, and not the end of "HTML"
    ({"tags": ["machine learning"]}, ["M1", "M2"]),
    ({"tags": ["quant developer"]}, ["Q1"]),
    ({"tags": ["front end"]}, ["F1", "F2"]),
    ({"tags": ["graduate engineer"]}, ["G1"]),                 # any order; "engineer" runs on to "engineering"
    ({"tags": ["python sql"]}, ["G1"]),                        # the description counts
    ({"tags": ["ml engineer", "deepco"]}, ["M1"]),             # every term
    ({"query": "machine learning"}, ["M1", "M2"]),
])
def test_search_matches_words(worded, kwargs, expected):
    assert ids(**kwargs) == expected


# ── ranking ───────────────────────────────────────────────────────────────────

RANKED = [
    make_job("JR", "Graduate Data Engineer", "A", level="junior"),
    make_job("MD", "Data Engineer", "B", level="mid"),
    make_job("SR", "Data Engineer II", "C", level="senior"),
    make_job("SP", "Data Platform Engineer", "D", level="mid", description="Visa sponsorship is available."),
]


@pytest.fixture
def ranked(db, ollama):
    jobs_db.add_jobs(RANKED)
    # Every job equally similar, so only the nudges order them.
    con = sqlite3.connect(jobs_db._DB_PATH)
    con.execute("UPDATE jobs SET semantic_vector = ?", (np.array(fake_vector("same"), dtype=np.float32).tobytes(),))
    con.commit()
    con.close()
    return fake_vector("same")


def order(vector, **kwargs):
    return [j["job_id"] for j in jobs_db.get_jobs(limit=10, persona_vector=vector, **kwargs)[0]]


def test_a_junior_sees_junior_jobs_first_and_senior_ones_last(ranked):
    got = order(ranked, career_stage="junior")
    assert got[0] == "JR" and got[-1] == "SR"


def test_someone_who_needs_sponsorship_sees_sponsoring_jobs_higher(ranked):
    assert order(ranked, needs_sponsorship=True)[0] == "SP"
    # The user's own "doesn't sponsor" mark wins over the ad.
    sp_id = next(j["id"] for j in jobs_db.get_jobs(limit=10)[0] if j["job_id"] == "SP")
    assert order(ranked, needs_sponsorship=True, marks={sp_id: "not_offered"})[0] != "SP"


def test_searched_words_in_the_title_rank_higher(ranked):
    jobs_db.add_jobs([make_job("DESC", "Platform Engineer", "E", description="graduate scheme")])
    con = sqlite3.connect(jobs_db._DB_PATH)
    con.execute("UPDATE jobs SET semantic_vector = ?", (np.array(ranked, dtype=np.float32).tobytes(),))
    con.commit()
    con.close()
    assert order(ranked, tags=["graduate"]) == ["JR", "DESC"]


def test_the_match_score_stays_the_plain_similarity(ranked):
    jobs = jobs_db.get_jobs(limit=10, persona_vector=ranked, career_stage="junior", needs_sponsorship=True)[0]
    assert all(j["semantic_score"] == 1.0 for j in jobs)
    assert max(j["rank_score"] for j in jobs) > 1.0
