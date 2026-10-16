"""
Checks a tailored CV or cover letter before it goes out, against the candidate's own data and
the job ad. Deterministic, no model calls, so it can run on every edit:

- keywords: the ad's technical terms, split into those the document has, those the candidate has
  but the document leaves out (worth adding), and real gaps (never add those);
- facts: numbers, technologies, employers and project names in the document that the
  candidate's data doesn't contain, so they may have been invented;
- style: words recruiters read as machine-written;
- ats: the rendered PDF read back as plain text, the way an applicant tracking system reads it.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Vocabulary ────────────────────────────────────────────────────────────────────────────────
# Canonical name → extra spellings. Matching is case-insensitive and on word boundaries, except
# for the names in _CASE_SENSITIVE, which are also ordinary English words ("go", "swift", "spark").

_TERMS: dict[str, tuple[str, ...]] = {
    # Languages
    "Python": (), "Java": (), "JavaScript": ("JS",), "TypeScript": ("TS",), "C++": ("cpp",), "C#": ("csharp",),
    "Go": ("Golang",), "Rust": (), "Ruby": (), "PHP": (), "Kotlin": (), "Swift": (), "Scala": (), "R": (),
    "MATLAB": (), "SQL": (), "Bash": ("shell scripting",), "Haskell": (), "Elixir": (), "Dart": (), "Julia": (),
    # Web
    "React": ("React.js", "ReactJS"), "Next.js": ("NextJS",), "Vue": ("Vue.js", "VueJS"), "Angular": (),
    "Svelte": (), "Node.js": ("NodeJS", "Node"), "Express.js": ("ExpressJS",), "Django": (), "Flask": (),
    "FastAPI": (), "Spring Boot": ("Spring Framework",), "Ruby on Rails": ("Rails",), ".NET": ("dotnet", "ASP.NET"),
    "GraphQL": (), "REST": ("RESTful", "REST API", "REST APIs"), "HTML": ("HTML5",), "CSS": ("CSS3",),
    "Tailwind CSS": ("Tailwind",), "Redux": (), "WebSockets": ("WebSocket",),
    # Data
    "PostgreSQL": ("Postgres",), "MySQL": (), "SQLite": (), "MongoDB": ("Mongo",), "Redis": (),
    "Elasticsearch": (), "DynamoDB": (), "Snowflake": (), "BigQuery": (), "Redshift": (), "Kafka": (),
    "Spark": ("PySpark", "Apache Spark"), "Hadoop": (), "Airflow": ("Apache Airflow",), "dbt": (),
    "pandas": (), "NumPy": (), "Databricks": (), "Tableau": (), "Power BI": ("PowerBI",), "Excel": (),
    "Looker": (), "ETL": ("ELT",), "data pipelines": ("data pipeline",), "data modelling": ("data modeling",),
    "data warehousing": ("data warehouse",), "statistics": ("statistical",),
    # ML / AI
    "PyTorch": (), "TensorFlow": (), "Keras": (), "scikit-learn": ("sklearn", "scikit learn"), "XGBoost": (),
    "LightGBM": (), "Hugging Face": ("HuggingFace",), "LangChain": (), "LlamaIndex": (), "OpenCV": (),
    "spaCy": (), "NLTK": (), "JAX": (), "MLflow": (), "machine learning": ("ML",), "deep learning": (),
    "NLP": ("natural language processing",), "computer vision": (), "LLMs": ("LLM", "large language models",
    "large language model"), "RAG": ("retrieval-augmented generation", "retrieval augmented generation"),
    "reinforcement learning": (), "embeddings": ("embedding",),
    # Cloud / DevOps
    "AWS": ("Amazon Web Services",), "Azure": ("Microsoft Azure",), "GCP": ("Google Cloud", "Google Cloud Platform"),
    "Docker": (), "Kubernetes": ("k8s",), "Terraform": (), "Ansible": (), "Jenkins": (),
    "GitHub Actions": (), "GitLab CI": (), "CI/CD": ("CI CD", "continuous integration", "continuous delivery"),
    "Linux": (), "Nginx": (), "serverless": (), "Prometheus": (), "Grafana": (), "Datadog": (),
    "microservices": ("microservice",), "distributed systems": (),
    # Testing / tools / practice
    "pytest": (), "Jest": (), "Playwright": (), "Cypress": (), "Selenium": (), "JUnit": (),
    "unit testing": ("unit tests",), "TDD": ("test-driven development",), "Git": (), "Jira": (),
    "Figma": (), "Agile": (), "Scrum": (), "system design": (), "data structures": (), "algorithms": (),
    "OOP": ("object-oriented programming", "object oriented programming"), "API design": (),
}

# Ordinary words as well as technology names: matched only with this exact capitalisation.
_CASE_SENSITIVE = {"Go", "Swift", "Spark", "R", "Rust", "Ruby", "Dart", "Julia", "Excel", "Node", "Rails",
                   "Agile", "Scrum", "React", "Angular", "Flask", "Jest", "Looker", "Snowflake", "JS", "TS",
                   "ML", "REST", "RESTful", "Redux", "Elixir", "Scala", "Kotlin"}


# Practices and fields rather than tools: they count as the ad's keywords, but naming one isn't a
# factual claim the persona has to back word for word ("data pipelines" for a project that loads data).
_CONCEPTS = {"data pipelines", "data modelling", "data warehousing", "statistics", "machine learning",
             "deep learning", "computer vision", "reinforcement learning", "NLP", "embeddings", "microservices",
             "distributed systems", "unit testing", "TDD", "system design", "data structures", "algorithms",
             "OOP", "API design", "Agile", "Scrum", "serverless", "ETL", "REST"}


def _pattern(name: str) -> str:
    # \b doesn't work next to symbols (C++, C#, .NET, CI/CD), so look for non-word-ish neighbours.
    body = re.escape(name).replace(r"\ ", r"[\s-]+")
    return rf"(?<![\w.+#/]){body}(?![\w+#]|\.\w)"


def _compile():
    out = []
    for canon, aliases in _TERMS.items():
        for spelling in (canon, *aliases):
            flags = 0 if spelling in _CASE_SENSITIVE else re.IGNORECASE
            extra = ""
            if spelling == "R":
                extra = r"(?![&'’])"           # R&D, R's
            if spelling == "Go":
                extra = r"(?!-)"               # go-to-market, Go-live
            out.append((canon, re.compile(_pattern(spelling) + extra, flags)))
    return out


_MATCHERS = _compile()


def terms_in(text: str) -> set[str]:
    """Canonical technical terms that appear in the text."""
    found = set()
    if not text:
        return found
    for canon, rx in _MATCHERS:
        if canon not in found and rx.search(text):
            found.add(canon)
    return found


# ── Numbers ───────────────────────────────────────────────────────────────────────────────────

_NUMBER_RE = re.compile(
    r"(?<![\w.,:/\-–—])([£$€])?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?"
    r"(\s?(?:%|percent|per cent|x|×|k|K|m|M|bn|million|billion|thousand)|\+)?(?![\w])"
)
_MULTIPLIER = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}


def numbers_in(text: str) -> list[tuple[str, float]]:
    """(as written, value) for each number in the text, leaving out years and calendar dates."""
    out = []
    text = text or ""
    for m in _NUMBER_RE.finditer(text):
        if re.match(r"/\d", text[m.end():m.end() + 2]):
            continue                                   # the month of a date like 06/2024
        whole = m.group(2).replace(",", "")
        value = float(f"{whole}.{m.group(3)}" if m.group(3) else whole)
        suffix = (m.group(4) or "").strip().lower()
        value *= _MULTIPLIER.get(suffix, 1)
        if not m.group(3) and not suffix and "," not in m.group(2) and 1950 <= value <= 2099 and len(whole) == 4:
            continue                                   # a year
        out.append((m.group(0).strip(), value))
    return out


def _same_number(a: float, b: float) -> bool:
    return abs(a - b) <= max(1e-9, abs(b) * 1e-6)


# ── The candidate's own data ──────────────────────────────────────────────────────────────────

def _flatten(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _flatten(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _flatten(v)]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [str(value)]
    return []


def persona_text(persona: dict) -> str:
    """Everything the candidate has told us about their work: the source a document may draw on.
    Contact details, credentials and equality data are left out; they're never claims."""
    parts = [persona.get("summary", ""), persona.get("custom_directives", "")]
    for key in ("history", "education", "projects", "certifications", "story_bank", "skills"):
        parts += _flatten(persona.get(key) or [])
    parts += _flatten(persona.get("screening") or {})
    return "\n".join(p for p in parts if p)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


# ── Document text, field by field ─────────────────────────────────────────────────────────────

def _cv_fields(cv: dict) -> list[tuple[str, str, str]]:
    """(field id, human label, text) for every free-text field of a CV."""
    fields = [("summary", "Summary", cv.get("summary") or ""), ("headline", "Headline", cv.get("headline") or "")]
    for i, r in enumerate(cv.get("experience") or []):
        where = " at ".join(x for x in (r.get("title"), r.get("employer")) if x) or f"role {i + 1}"
        for j, b in enumerate(r.get("bullets") or []):
            fields.append((f"experience.{i}.bullets.{j}", f"Experience: {where}", b or ""))
    for i, p in enumerate(cv.get("projects") or []):
        name = p.get("name") or f"project {i + 1}"
        fields.append((f"projects.{i}.description", f"Project: {name}", p.get("description") or ""))
        fields.append((f"projects.{i}.tech", f"Project: {name} (technologies)", ", ".join(p.get("tech") or [])))
    return [f for f in fields if f[2].strip()]


def _letter_fields(letter: dict) -> list[tuple[str, str, str]]:
    return [(f"paragraphs.{i}", f"Paragraph {i + 1}", p) for i, p in enumerate(letter.get("paragraphs") or [])
            if (p or "").strip()]


def document_text(doc_type: str, doc: dict) -> str:
    """All the words in the document, including the skills section and names."""
    if doc_type == "cover_letter":
        return "\n".join(_flatten([doc.get("paragraphs"), doc.get("job_title"), doc.get("headline")]))
    return "\n".join(_flatten([doc.get(k) for k in ("summary", "headline", "skills", "experience",
                                                     "projects", "education", "certifications")]))


# ── Style ─────────────────────────────────────────────────────────────────────────────────────

BANNED_WORDS = ("delve", "testament", "tapestry", "landscape", "foster", "underscore", "beacon", "synergy",
                "pivotal", "intricate", "unleash", "elevate", "seamless", "robust", "leverage", "spearhead",
                "cutting-edge", "passionate", "results-driven", "detail-oriented", "highly motivated")
_BANNED_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in BANNED_WORDS) + r")\w*", re.IGNORECASE)


# ── The checks ────────────────────────────────────────────────────────────────────────────────

def check_keywords(doc_type: str, doc: dict, persona: dict, job: dict) -> dict:
    ad = terms_in(f"{job.get('title', '')}\n{job.get('description', '')}")
    have_doc = terms_in(document_text(doc_type, doc))
    have_persona = terms_in(persona_text(persona))
    matched = sorted(ad & have_doc, key=str.lower)
    missing_have = sorted((ad - have_doc) & have_persona, key=str.lower)
    gaps = sorted(ad - have_doc - have_persona, key=str.lower)
    in_reach = len(matched) + len(missing_have)
    return {
        "matched": matched,
        "missing_have": missing_have,
        "gaps": gaps,
        "in_ad": len(ad),
        # The share of the ad's terms the candidate has that the document shows.
        "score": round(100 * len(matched) / in_reach) if in_reach else None,
    }


def check_facts(doc_type: str, doc: dict, persona: dict, job: dict, extra_source: str = "") -> list[dict]:
    """Claims the candidate's data doesn't support. Each finding names the field and the text.
    `extra_source` is other material the document may quote, such as research on the company."""
    source = persona_text(persona)
    source_numbers = [v for _, v in numbers_in(source)]
    # A letter may also quote the ad (its team size, its founding year…); a CV shouldn't need to.
    if doc_type == "cover_letter":
        source_numbers += [v for _, v in numbers_in(job.get("description", ""))]
        source_numbers += [v for _, v in numbers_in(extra_source)]
    source_terms = terms_in(source)
    where = "your persona or the ad" if doc_type == "cover_letter" else "your persona"
    findings: list[dict] = []
    fields = _letter_fields(doc) if doc_type == "cover_letter" else _cv_fields(doc)
    ad_terms = terms_in(f"{job.get('title', '')}\n{job.get('description', '')}")
    for field, label, text in fields:
        for written, value in numbers_in(text):
            if not any(_same_number(value, v) for v in source_numbers):
                findings.append({"kind": "number", "field": field, "label": label, "value": written,
                                 "message": f"“{written}” isn't in {where}"})
        for term in sorted(terms_in(text) - source_terms - _CONCEPTS):
            # Naming the employer's own stack in a letter ("your Kafka platform") isn't a claim.
            if doc_type == "cover_letter" and term in ad_terms:
                continue
            findings.append({"kind": "technology", "field": field, "label": label, "value": term,
                             "message": f"{term} isn't in your persona"})
    if doc_type != "cover_letter":
        employers = {_norm(r.get("employer", "")) for r in persona.get("history") or []}
        for i, r in enumerate(doc.get("experience") or []):
            if r.get("employer") and _norm(r["employer"]) not in employers:
                findings.append({"kind": "employer", "field": f"experience.{i}.employer", "label": "Experience",
                                 "value": r["employer"], "message": f"{r['employer']} isn't an employer in your persona"})
        projects = {_norm(p.get("name", "")) for p in persona.get("projects") or []}
        for i, p in enumerate(doc.get("projects") or []):
            name = _norm(p.get("name", ""))
            if name and name not in projects and not any(name in q or q in name for q in projects if q):
                findings.append({"kind": "project", "field": f"projects.{i}.name", "label": "Projects",
                                 "value": p.get("name"), "message": f"“{p.get('name')}” isn't a project in your persona"})
    return findings


def check_style(doc_type: str, doc: dict) -> list[dict]:
    fields = _letter_fields(doc) if doc_type == "cover_letter" else _cv_fields(doc)
    out = []
    for field, label, text in fields:
        for m in _BANNED_RE.finditer(text):
            out.append({"kind": "word", "field": field, "label": label, "value": m.group(0),
                        "message": f"“{m.group(0)}” reads as machine-written"})
    return out


# ── ATS read-back ─────────────────────────────────────────────────────────────────────────────

def _squash(text: str) -> str:
    # PDF text breaks lines and may hyphenate; compare letters and digits only.
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def check_ats(doc_type: str, doc: dict, template_id: str | None = None) -> dict | None:
    """Render the document to a PDF and read it back as plain text, as an ATS would.
    None where the PDF renderer isn't available."""
    from . import doc_render
    from .cv_parser import extract_text

    weasy = doc_render._weasyprint_html()
    if weasy is None:
        return None
    html = doc_render.render_html(doc_type, doc, template_id)
    document = weasy(string=html, base_url=doc_render._TEMPLATES_DIR).render()
    pages = len(document.pages)
    text = extract_text(document.write_pdf())
    flat = _squash(text)
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    words = len(text.split())
    add("Text can be read", words >= 40, f"{words} words read from the PDF")
    if doc_type == "cover_letter":
        data = doc_render.build_letter_template_data(doc)
        add("Your name is on it", _squash(data["candidate_name"]) in flat, data["candidate_name"] or "No name")
        missing = [i + 1 for i, p in enumerate(data["paragraphs"]) if _squash(p)[:60] not in flat]
        add("Every paragraph reads back", not missing,
            "All paragraphs found" if not missing else f"Paragraph {', '.join(map(str, missing))} not found")
        add("Fits on one page", pages <= data["page_target"], f"{pages} page{'s' if pages != 1 else ''}")
        return {"pages": pages, "checks": checks}

    data = doc_render.build_cv_template_data(doc)
    add("Your name is at the top", _squash(data["name"]) in _squash(text[:300]), data["name"] or "No name")
    contact = doc.get("contact") or {}
    for key, label in (("email", "Email"), ("phone", "Phone")):
        if contact.get(key):
            add(f"{label} can be read", _squash(contact[key]) in flat, contact[key])
    headings = re.findall(r"<h2>(.*?)</h2>", html)
    headings = [re.sub(r"&amp;", "&", h) for h in headings]
    # Each heading must come after the one before it (the word "experience" in a summary is no heading).
    at, in_order = 0, True
    for h in headings:
        found = flat.find(_squash(h), at)
        if found < 0:
            in_order = False
            break
        at = found + len(_squash(h))
    add("Standard section headings, in order", in_order, ", ".join(headings) or "No headings")
    skills = [s for g in data["skills"] for s in g["items"]]
    lost = [s for s in skills if _squash(s) and _squash(s) not in flat]
    add("Every skill reads back", not lost, f"{len(skills)} skills" if not lost else f"Not found: {', '.join(lost[:6])}")
    roles = data["experience"]
    undated = [r["title"] for r in roles if r.get("dates") and _squash(r["dates"]) not in flat]
    add("Role dates read back", not undated, f"{len(roles)} roles" if not undated else f"Missing dates: {', '.join(undated)}")
    target = data["page_target"]
    add(f"Fits on {target} page{'s' if target != 1 else ''}", pages <= target, f"{pages} page{'s' if pages != 1 else ''}")
    return {"pages": pages, "checks": checks}


def check_document(doc_type: str, doc: dict, persona: dict, job: dict | None = None,
                   template_id: str | None = None, ats: bool = True) -> dict:
    job = job or {}
    report = {
        "keywords": check_keywords(doc_type, doc, persona, job),
        "facts": check_facts(doc_type, doc, persona, job),
        "style": check_style(doc_type, doc),
        "ats": None,
    }
    if ats:
        try:
            report["ats"] = check_ats(doc_type, doc, template_id)
        except Exception:
            logger.exception("ATS read-back failed (%s)", doc_type)
    return report
