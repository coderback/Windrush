"""Job store: batched embedding, SQL filtering, location matching, pagination, ranking."""
import sqlite3
import threading
import time

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
