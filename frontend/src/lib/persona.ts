import type { Persona } from "./types";

/* Persona strength (HANDOFF gap 3): scored on the client from GET /persona. Each section is
   complete, needs attention, or optional; the strength is the weight of complete required sections. */

export type SectionKey =
  | "identity" | "login" | "links" | "skills" | "work" | "education" | "projects" | "certs"
  | "stories" | "screening" | "answers" | "prefs" | "equality" | "directives" | "suggestions";

export type SectionState = "complete" | "attention" | "optional";

export interface SectionCheck {
  key: SectionKey;
  label: string;
  state: SectionState;
  /** What to do next, when it needs attention. */
  todo?: string;
  weight: number;
}

const filled = (s?: string | null) => !!(s && s.trim());

export const MIN_STORIES = 3;
export const MIN_SKILLS = 8;

export function salaryExpectation(p: Persona): string {
  if (filled(p.screening?.salary_canonical)) return p.screening.salary_canonical;
  return p.preferences?.min_salary ? `£${Math.round(p.preferences.min_salary / 1000)}k` : "";
}

export function personaChecks(p: Persona): SectionCheck[] {
  const c = p.core_info;
  const missingId = [
    !filled(c.first_name) && "first name",
    !filled(c.last_name) && "last name",
    !filled(c.email) && "email",
    !filled(c.phone) && "phone number",
    !filled(c.city) && "city",
  ].filter(Boolean) as string[];
  const skillCount = (p.skills || []).reduce((n, g) => n + (g.skills?.length || 0), 0);
  const stories = (p.story_bank || []).length;
  const salary = salaryExpectation(p);
  const screeningDone = filled(p.screening.why_this_role) && filled(p.screening.greatest_strength) &&
    filled(p.screening.notice_period_canonical);

  const check = (key: SectionKey, label: string, ok: boolean, todo: string, weight: number): SectionCheck =>
    ({ key, label, state: ok ? "complete" : "attention", todo: ok ? undefined : todo, weight });
  const optional = (key: SectionKey, label: string): SectionCheck =>
    ({ key, label, state: "optional", weight: 0 });

  return [
    check("identity", "Identity & contact", missingId.length === 0,
      `Add your ${missingId.join(", ")}`, 15),
    check("login", "Job-board login", filled(c.job_email) && filled(c.job_password),
      "Add a job-board login so the agent can create accounts", 10),
    check("links", "Links", [c.linkedin, c.github, c.portfolio, c.website].some(filled),
      "Add a LinkedIn or GitHub link", 5),
    check("skills", "Skills", skillCount >= MIN_SKILLS,
      skillCount === 0 ? "Add your skills" : `Add ${MIN_SKILLS - skillCount} more skills`, 10),
    check("work", "Work history", (p.history || []).length > 0, "Add your work history", 15),
    check("education", "Education", (p.education || []).length > 0, "Add your education", 10),
    check("projects", "Projects", (p.projects || []).length > 0, "Add a project", 10),
    optional("certs", "Certifications"),
    check("stories", "STAR stories", stories >= MIN_STORIES,
      stories === 0
        ? "Add 3 STAR stories so the agent can answer behavioural questions"
        : `Add ${MIN_STORIES - stories} more STAR ${MIN_STORIES - stories === 1 ? "story" : "stories"}`, 10),
    check("screening", "Screening answers", screeningDone && !!salary,
      !salary ? "Set a salary expectation" : "Answer the common screening questions", 10),
    optional("answers", "Saved answers"),
    check("prefs", "Job preferences",
      (p.preferences.target_titles || []).length > 0 && (p.preferences.preferred_locations || []).length > 0,
      "Add target job titles and locations", 5),
    optional("equality", "Equality monitoring"),
    optional("directives", "Custom AI directives"),
  ];
}

export function personaStrength(p: Persona): { pct: number; todos: string[] } {
  const checks = personaChecks(p);
  const total = checks.reduce((n, c) => n + c.weight, 0);
  const done = checks.filter((c) => c.state === "complete").reduce((n, c) => n + c.weight, 0);
  const todos = checks
    .filter((c) => c.state === "attention")
    .sort((a, b) => b.weight - a.weight)
    .map((c) => c.todo!)
    .filter(Boolean);
  return { pct: total ? Math.round((done / total) * 100) : 0, todos };
}

export function displayName(p?: Persona | null): string {
  if (!p) return "";
  const c = p.core_info;
  const first = filled(c.preferred_name) ? c.preferred_name : c.first_name;
  return [first, c.last_name].filter(filled).join(" ");
}

export function firstName(p?: Persona | null): string {
  if (!p) return "";
  return (filled(p.core_info.preferred_name) ? p.core_info.preferred_name : p.core_info.first_name) || "";
}
