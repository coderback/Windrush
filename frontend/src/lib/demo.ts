// Public read-only demo, switched on at build time with NEXT_PUBLIC_DEMO_MODE=1.
//
// In demo mode authFetch answers from this file and never touches the network. There is no
// backend, no proxy route, no browser agent and nowhere for credentials to go. Anything not
// on the short list below is refused, so applications cannot be submitted.
//
// Sam Sample, the employers and the jobs are fictional. Fit results, the parsed CV, the tailored
// CV and the cover letter are hand-written samples showing what those screens look like; no model
// produced them. Exposure scores in demo-exposure.json are real output of api/app/risk_scorer.py
// on these fictional skills (see frontend/scripts/score_demo_skills.py).

import exposure from "./demo-exposure.json";
import type { Application, Job, Persona } from "./types";

export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "1";
export const GITHUB_URL = "https://github.com/coderback/Windrush";

const DISABLED = "Disabled in this read-only demo. It has no backend, so nothing can be sent, saved or submitted.";

const daysAgo = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString();

export const SAMPLE_CV_TEXT = `SAM SAMPLE (fictional person)
Exampleton, UK | sam.sample@example.com

Data analyst with three years in retail and logistics reporting.

EXPERIENCE
Data Analyst, Brightmoor Retail Group (fictional), 2023 to now
- Built weekly SQL and Tableau reporting for regional sales teams.
- Replaced a manual Excel stock report with a scheduled Python job.

Reporting Analyst, Kestrel Logistics (fictional), 2021 to 2023
- Maintained delivery performance dashboards and monthly board packs.

EDUCATION
BSc Mathematics, University of Exampleton (fictional), 2021

SKILLS
Python, SQL, Excel, Tableau, Statistics, Data Analysis, Machine Learning (coursework),
Financial Analysis, Project Management, Stakeholder Management`;

let persona: Persona = {
  core_info: {
    first_name: "Sam", last_name: "Sample", preferred_name: "Sam", dob: "", email: "sam.sample@example.com",
    phone: "+44 7700 900123", address_line_1: "", city: "Exampleton", country: "United Kingdom", postcode: "",
    linkedin: "", github: "", twitter: "", portfolio: "", website: "", visa_status: "", visa_type: "", visa_expiry: "",
    right_to_work_uk: true, require_sponsorship: false, security_clearance: "", has_government_ties: null, nationality: "",
    holds_other_nationality: null, other_nationalities: "", held_other_nationality: null, previous_nationalities: "",
    job_email: "", job_password: "",
  },
  diversity: { gender: "", ethnicity: "", disability_status: "", veteran_status: "", sexual_orientation: "" },
  screening: {
    why_this_role: "", why_this_company: "", greatest_strength: "", biggest_weakness: "", leadership_example: "",
    conflict_resolution: "", salary_canonical: "", notice_period_canonical: "1 month",
  },
  preferences: {
    target_titles: ["Data Analyst", "Analytics Engineer"], min_salary: 40000, expected_hourly_rate: null,
    remote_preference: "hybrid", relocation_willingness: false, preferred_locations: ["Exampleton", "Remote"],
    industries: ["Retail", "Logistics"], companies_to_avoid: [], company_size_preference: "", employment_type: "full-time",
    notice_period: "1 month", can_work_in_person: true, can_start_immediately: false, has_reliable_transportation: true,
    needs_accommodations: false,
  },
  history: [
    {
      employer: "Brightmoor Retail Group (fictional)", title: "Data Analyst", start_date: "2023-02", end_date: "", is_current: true,
      tech_stack: ["SQL", "Tableau", "Python"], metrics: "", summary: "Weekly reporting for regional sales teams.",
      achievements: ["Built weekly SQL and Tableau reporting for regional sales teams.", "Replaced a manual Excel stock report with a scheduled Python job."],
    },
    {
      employer: "Kestrel Logistics (fictional)", title: "Reporting Analyst", start_date: "2021-08", end_date: "2023-01", is_current: false,
      tech_stack: ["Excel", "SQL"], metrics: "", summary: "Delivery performance reporting.",
      achievements: ["Maintained delivery performance dashboards and monthly board packs."],
    },
  ],
  education: [{ institution: "University of Exampleton (fictional)", degree: "BSc Mathematics", start_date: "2018", end_date: "2021", grade: "", is_currently_enrolled: false }],
  projects: [],
  certifications: [],
  story_bank: [],
  custom_directives: "",
  skills: [
    { category: "Tools", skills: ["Python", "SQL", "Excel", "Tableau"] },
    { category: "Analysis", skills: ["Data Analysis", "Machine Learning", "Statistics", "Financial Analysis"] },
    { category: "Working with people", skills: ["Project Management", "Stakeholder Management"] },
  ],
  summary: "Data analyst with three years in retail and logistics reporting.",
};

const titleExposure = exposure.job_exposure as Record<string, number>;

const job = (id: string, title: string, company: string, location: string, match: number, days: number, extra: Partial<Job>, description: string): Job => ({
  id, job_id: id, title, company, location, description, semantic_score: match, exposure_score: titleExposure[title],
  url: `https://example.com/sample-job/${id}`, source: "sample", created_at: daysAgo(days), tags: [], ...extra,
});

const JOBS: Job[] = [
  job("sample-1", "Data Analyst", "Harbourline Analytics (sample)", "Exampleton (hybrid)", 0.86, 1,
    { salary_min: 42000, salary_max: 50000, level: "mid", years_min: 2, degree: "preferred", tags: ["data", "analytics"] },
    "Fictional listing. Join a small analytics team building reporting for logistics clients. You will write SQL, maintain Tableau dashboards and automate recurring reports in Python. Experience explaining results to non-technical stakeholders matters. dbt experience is a plus."),
  job("sample-2", "Analytics Engineer", "Quillstone Health (sample)", "Remote (UK)", 0.74, 3,
    { salary_min: 50000, salary_max: 60000, level: "mid", years_min: 3, degree: "not_mentioned", tags: ["data", "engineering"] },
    "Fictional listing. Own the transformation layer of a health-tech data warehouse. SQL and dbt daily, Python for tooling, and close work with analysts on data models and tests."),
  job("sample-3", "Business Intelligence Developer", "Brightline Retail (sample)", "Exampleton", 0.68, 5,
    { salary_min: 45000, salary_max: 52000, level: "mid", years_min: 2, degree: "not_mentioned", tags: ["data", "bi"] },
    "Fictional listing. Build and maintain Power BI reporting for store operations. Strong SQL and data modelling needed. Retail background welcome."),
  job("sample-4", "Financial Analyst", "Ashgrove Mutual (sample)", "Exampleton (hybrid)", 0.55, 2,
    { salary_min: 44000, salary_max: 54000, level: "mid", years_min: 3, degree: "required", tags: ["finance"] },
    "Fictional listing. Support monthly forecasting and variance analysis. Advanced Excel needed; part-qualified accountants preferred."),
  job("sample-5", "Data Scientist", "Fernfield Labs (sample)", "Remote (UK)", 0.49, 7,
    { salary_min: 55000, salary_max: 70000, level: "senior", years_min: 5, degree: "required", tags: ["data", "ml"] },
    "Fictional listing. Ship machine learning models for demand forecasting. Production ML experience and an advanced degree expected."),
  job("sample-6", "Operations Research Analyst", "Kestrel Freight (sample)", "Oldport", 0.43, 9,
    { salary_min: 40000, salary_max: 48000, level: "junior", years_min: 1, degree: "required", tags: ["operations"] },
    "Fictional listing. Model delivery routes and depot capacity. Linear programming experience needed; on-site three days a week."),
];

const ANALYSIS: Record<string, Record<string, unknown>> = {
  "sample-1": { fit_score: 86, level_match: "strong", matched_skills: ["SQL", "Tableau", "Python", "Stakeholder Management"], skill_gaps: ["dbt"],
    reasoning: "Hand-written sample result. Sam's reporting work lines up closely with this role: SQL, Tableau dashboards and automating reports in Python, in a logistics setting Sam already knows." },
  "sample-2": { fit_score: 74, level_match: "ok", matched_skills: ["SQL", "Python"], skill_gaps: ["dbt", "Data warehousing"],
    reasoning: "Hand-written sample result. The SQL and Python carry over, but this is more engineering than Sam's analyst work so far, and dbt is used daily." },
  "sample-3": { fit_score: 68, level_match: "ok", matched_skills: ["SQL", "Data Analysis"], skill_gaps: ["Power BI", "Data modelling"],
    reasoning: "Hand-written sample result. The retail background helps and Tableau experience transfers, but the role asks for Power BI." },
  "sample-4": { fit_score: 55, level_match: "ok", matched_skills: ["Excel", "Financial Analysis"], skill_gaps: ["Forecasting", "Accounting qualification"],
    reasoning: "Hand-written sample result. Some overlap through Excel, but the role leans on accounting experience Sam doesn't have." },
  "sample-5": { fit_score: 49, level_match: "reach", matched_skills: ["Python", "Statistics"], skill_gaps: ["Production ML", "Advanced degree"],
    reasoning: "Hand-written sample result. A stretch: Sam's machine learning is coursework, and this role expects production experience." },
  "sample-6": { fit_score: 43, level_match: "reach", matched_skills: ["Statistics"], skill_gaps: ["Linear programming", "Route optimisation"],
    reasoning: "Hand-written sample result. The logistics context fits, but the core modelling skills are missing." },
};

const CV = {
  name: "Sam Sample",
  headline: "Data Analyst",
  contact: { email: "sam.sample@example.com", phone: "+44 7700 900123", location: "Exampleton, UK" },
  summary: "Data analyst with three years building SQL and Tableau reporting for retail and logistics teams, and automating recurring reports in Python.",
  skills: [
    { category: "Data", items: ["SQL", "Python", "Tableau", "Excel"] },
    { category: "Analysis", items: ["Statistics", "Data Analysis"] },
    { category: "Working with people", items: ["Stakeholder Management", "Project Management"] },
  ],
  experience: [
    { title: "Data Analyst", employer: "Brightmoor Retail Group (fictional)", start_date: "2023", end_date: "Present",
      bullets: ["Built weekly SQL and Tableau reporting for regional sales teams.", "Replaced a manual Excel stock report with a scheduled Python job."] },
    { title: "Reporting Analyst", employer: "Kestrel Logistics (fictional)", start_date: "2021", end_date: "2023",
      bullets: ["Maintained delivery performance dashboards and monthly board packs."] },
  ],
  education: [{ degree: "BSc Mathematics", institution: "University of Exampleton (fictional)", year: "2021" }],
  projects: [],
  certifications: [],
};

const LETTER = {
  candidate_name: "Sam Sample",
  company: "Harbourline Analytics (sample)",
  company_location: "Exampleton",
  job_title: "Data Analyst",
  contact: { email: "sam.sample@example.com", phone: "+44 7700 900123", location: "Exampleton, UK" },
  salutation: "Dear Hiring Team,",
  paragraphs: [
    "I'm applying for the Data Analyst role at Harbourline. Your work with logistics clients is close to where I started: at Kestrel Logistics I maintained the delivery performance dashboards and the monthly board packs built on them.",
    "At Brightmoor Retail Group I now build the weekly SQL and Tableau reporting that regional sales teams work from. I also replaced a manual Excel stock report with a scheduled Python job, the kind of recurring automation your listing describes.",
    "I haven't used dbt yet, and I'd want to pick it up early. What I can bring from day one is a habit of asking what a report is for before building it, and explaining the results to the people who use them.",
    "I'd welcome the chance to talk through how I could help your team.",
  ],
  signoff: "Kind regards,",
};

const app = (id: string, j: Job, status: string, fit: number, days: number, history: [string, number][]): Application => ({
  id, job_id: j.id ?? "", job_title: j.title, company: j.company, location: j.location, job_url: j.url ?? "", status,
  date_applied: status === "Saved" ? null : daysAgo(days), composite_score: fit, exposure_score: null, fit_score: fit,
  skill_gaps: [], level_match: "ok", notes: "Fictional sample entry. Nothing was submitted.", created_at: daysAgo(days),
  history: history.map(([s, d]) => ({ status: s, source: "you" as const, changed_at: daysAgo(d) })),
});

const APPLICATIONS: Application[] = [
  app("app-1", JOBS[1], "Interview", 74, 21, [["Applied", 21], ["Responded", 14], ["Interview", 6]]),
  app("app-2", JOBS[2], "Applied", 68, 8, [["Applied", 8]]),
  app("app-3", JOBS[3], "Rejected", 55, 30, [["Applied", 30], ["Rejected", 18]]),
  app("app-4", JOBS[0], "Saved", 86, 1, [["Saved", 1]]),
];

function escapeHtml(s: unknown): string {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] ?? c);
}

type Doc = Record<string, unknown> & typeof CV & typeof LETTER;

/** A plain stand-in for the server's document renderer, so the preview still follows edits. */
function renderPreview(kind: string, doc: Doc): string {
  const style = `<style>body{margin:0;background:#fff;color:#222;font:13px/1.5 Georgia,serif}
.p{width:794px;min-height:1123px;box-sizing:border-box;padding:56px 64px}h1{margin:0;font-size:26px}h2{margin:20px 0 6px;font-size:13px;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid #bbb}
ul{margin:4px 0 10px;padding-left:18px}.m{color:#555}.w{color:#8a5a00;font:11px sans-serif;margin-bottom:18px}</style>`;
  const note = `<div class="w">Sample document for a fictional person. Simplified preview; the real app renders this server-side.</div>`;
  const c = (doc.contact ?? {}) as Record<string, string>;
  const contact = [c.email, c.phone, c.location].filter(Boolean).map(escapeHtml).join(" | ");
  if (kind === "cover_letter") {
    return `${style}<div class="p">${note}<h1>${escapeHtml(doc.candidate_name)}</h1><div class="m">${contact}</div><br>
<p>${escapeHtml(doc.salutation)}</p>${(doc.paragraphs ?? []).map((t) => `<p>${escapeHtml(t)}</p>`).join("")}
<p>${escapeHtml(doc.signoff)}<br>${escapeHtml(doc.candidate_name)}</p></div>`;
  }
  return `${style}<div class="p">${note}<h1>${escapeHtml(doc.name)}</h1><div class="m">${escapeHtml(doc.headline)}<br>${contact}</div>
<h2>Summary</h2><p>${escapeHtml(doc.summary)}</p>
<h2>Skills</h2>${(doc.skills ?? []).map((s) => `<div><b>${escapeHtml(s.category)}:</b> ${(s.items ?? []).map(escapeHtml).join(", ")}</div>`).join("")}
<h2>Experience</h2>${(doc.experience ?? []).map((e) => `<div><b>${escapeHtml(e.title)}</b>, ${escapeHtml(e.employer)} <span class="m">${escapeHtml(e.start_date)} to ${escapeHtml(e.end_date)}</span><ul>${(e.bullets ?? []).map((b) => `<li>${escapeHtml(b)}</li>`).join("")}</ul></div>`).join("")}
<h2>Education</h2>${(doc.education ?? []).map((e) => `<div>${escapeHtml(e.degree)}, ${escapeHtml(e.institution)} ${escapeHtml(e.year)}</div>`).join("")}</div>`;
}

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const refuse = (detail = DISABLED) => json({ detail }, 403);
const stream = (...events: Record<string, unknown>[]) =>
  new Response(events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join(""), { status: 200, headers: { "Content-Type": "text/event-stream" } });

function feed(u: URL) {
  const p = u.searchParams;
  const tags = (p.get("tags") ?? "").toLowerCase().split(",").map((t) => t.trim()).filter(Boolean);
  const location = (p.get("location") ?? "").toLowerCase();
  const level = (p.get("level") ?? "").toLowerCase();
  const maxYears = p.get("max_years");
  const matches = JOBS.filter((j) => {
    const text = `${j.title} ${j.company} ${j.description} ${(j.tags as string[]).join(" ")}`.toLowerCase();
    if (tags.length && !tags.some((t) => text.includes(t))) return false;
    if (location && !j.location.toLowerCase().includes(location)) return false;
    if (level && j.level !== level) return false;
    if (p.get("remote") === "true" && !/remote/i.test(j.location)) return false;
    if (maxYears && (j.years_min ?? 0) > Number(maxYears)) return false;
    if (p.get("no_degree") === "true" && j.degree === "required") return false;
    return true;
  });
  const page = Number(p.get("page") ?? 1);
  const limit = Number(p.get("limit") ?? 20);
  const jobs = matches.slice((page - 1) * limit, page * limit);
  return {
    jobs, total: matches.length, has_more: page * limit < matches.length, discovering: false, sponsorship: "any",
    hidden: { sponsorship: 0, dealt_with: 0 },
    collection: { running: false, finished_at: daysAgo(1), found: JOBS.length, added: 0, next_at: null },
  };
}

/** Stands in for fetch in demo mode. Reads come from the fixtures above; everything else is refused. */
export async function demoFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const method = (options.method ?? "GET").toUpperCase();
  const u = new URL(url, "https://demo.invalid");
  const path = u.pathname.replace(/^\/api/, "");
  const body = () => (typeof options.body === "string" ? JSON.parse(options.body) : {});

  if (method === "GET") {
    if (path === "/onboarding/status") return json({ complete: true });
    if (path === "/persona") return json(persona);
    if (path === "/applications") return json(APPLICATIONS);
    if (path === "/jobs") return json(feed(u));
    if (path === "/answers" || path === "/autopilot/runs" || path === "/gmail/events") return json([]);
    if (path === "/profile/suggestions") {
      return json({ suggestions: [], reading: "", sources: { github: { address: "" }, website: { address: "" }, linkedin: { address: "" } } });
    }
    return refuse();
  }

  if (method === "POST" && path === "/score-skills") return json({ skill_risks: exposure.skill_risks });
  if (method === "POST" && path === "/jobs/analyze") {
    const id = body().job?.id ?? body().job?.job_id;
    const result = ANALYSIS[id];
    return result ? stream({ type: "job_fit", ranked_jobs: [result] }) : refuse("This demo only has saved results for its sample jobs.");
  }
  if (method === "POST" && (path === "/jobs/tailored-cv" || path === "/jobs/cover-letter")) {
    if ((body().job?.id ?? body().job?.job_id) !== JOBS[0].id) {
      return refuse(`This demo only has a sample CV and cover letter for the top-ranked job, ${JOBS[0].title} at ${JOBS[0].company}.`);
    }
    return path === "/jobs/tailored-cv" ? stream({ type: "tailored_cv", cv: CV }) : stream({ type: "cover_letter", letter: LETTER });
  }
  if (method === "POST" && path === "/documents/preview") {
    const b = body();
    return json({ html: renderPreview(b.type, b.doc) });
  }
  // Persona edits stay in this tab. The job-board password never gets a field in the demo.
  if (method === "PUT" && path === "/persona") {
    const next = body() as Persona;
    persona = { ...next, core_info: { ...next.core_info, job_email: "", job_password: "" } };
    return json(persona);
  }
  if (path === "/careers/roadmap") return refuse("The roadmap is written by an LLM, so it is switched off in this read-only demo.");
  return refuse();
}
