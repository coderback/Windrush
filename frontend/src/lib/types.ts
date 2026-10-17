/* Shapes the API returns. Only the fields the frontend reads are listed. */

export interface Job {
  id?: string;
  job_id?: string;
  title: string;
  company: string;
  location: string;
  salary?: string;
  salary_min?: number | null;
  salary_max?: number | null;
  description?: string;
  url?: string;
  exposure_score?: number;
  semantic_score?: number;
  tags?: string | string[];
  source?: string;
  level?: string;
  posted_at?: string;
  created_at?: string;
  tracker_status?: string;
  sponsorship?: string;            // "offered" | "not_offered" | "" (the ad doesn't say)
  sponsorship_evidence?: string;
  clearance?: string;              // "DV" | "SC" | "NPPV" | "unspecified" | ""
  licensed_sponsor?: boolean;      // the employer is on the Home Office sponsor register
  sponsorship_mark?: string;       // the user's own call, which wins
  years_min?: number | null;       // minimum years of experience the ad asks for (LLM-read)
  degree?: string;                 // "required" | "preferred" | "not_mentioned" | ""
}

export interface Application {
  id: string;
  job_id: string;
  job_title: string;
  company: string;
  location: string;
  job_url: string;
  status: string;
  date_applied: string | null;
  composite_score: number | null;
  exposure_score: number | null;
  fit_score: number | null;
  skill_gaps: string[];
  level_match: string;
  notes: string | null;
  tailored_cv?: string | null;
  /** The questions the agent met on the application form, with each answer and where it came from. */
  questions?: FormAnswer[];
  created_at: string;
}

/* ── Application questions (mirrors api/app/answers.py) ─────────────── */

/** saved: your answer bank · profile: your persona · drafted: written for this job, for you to check ·
    needs_you: a fact nothing you've given states, so it was left blank. */
export type AnswerSource = "saved" | "profile" | "drafted" | "needs_you";

export interface FormAnswer {
  question: string;
  options: string[];
  kind: "fact" | "written";
  source: AnswerSource;
  answer: string;
  /** What the answer rests on, e.g. "Your profile: Notice period = 2 weeks". */
  because: string;
  bank_id: string;
  /** Claims the document check still flags in a drafted answer. */
  flags: string[];
}

export interface SavedAnswer {
  id: string;
  question: string;
  answer: string;
  kind: "fact" | "written";
  /** Set when the answer is about one employer: only that employer's forms reuse it. */
  company: string;
  created_at: string;
  updated_at: string;
}

export interface SkillRisk {
  skill: string;
  exposure_score: number;
  risk_label: string;
  reasoning?: string;
}

export interface Analysis {
  fit_score?: number;
  level_match?: string;
  skill_gaps?: string[];
  matched_skills?: string[];
  reasoning?: string;
}

/* ── Persona (mirrors api/app/models.py) ─────────────────────────────── */

// Facts stated on applications. null = not answered: the browser agent leaves those for you.
export type YesNo = boolean | null;

export interface WorkExperience {
  employer: string;
  title: string;
  start_date: string;
  end_date: string;
  is_current: boolean;
  tech_stack: string[];
  achievements: string[];
  metrics: string;
  summary: string;
}

export interface Education {
  institution: string;
  degree: string;
  start_date: string;
  end_date: string;
  grade: string;
  is_currently_enrolled: boolean;
}

export interface Project {
  name: string;
  url?: string | null;
  problem_solved: string;
  technologies: string[];
  outcomes: string;
  summary: string;
  is_ongoing: boolean;
}

export interface Certification {
  name: string;
  issuing_organization: string;
  issue_date: string;
  expiration_date: string;
  credential_id: string;
  credential_url: string;
}

export interface BehavioralStory {
  title: string;
  scenario: string;
  action: string;
  result: string;
  tags: string[];
}

export interface SkillCategory {
  category: string;
  skills: string[];
}

export interface CoreInfo {
  first_name: string;
  last_name: string;
  preferred_name: string;
  dob: string;
  email: string;
  phone: string;
  address_line_1: string;
  city: string;
  country: string;
  postcode: string;
  linkedin: string;
  github: string;
  twitter: string;
  portfolio: string;
  website: string;
  visa_status: string;
  visa_type: string;
  right_to_work_uk: YesNo;
  require_sponsorship: YesNo;
  security_clearance: string;
  has_government_ties: YesNo;
  nationality: string;
  holds_other_nationality: YesNo;
  other_nationalities: string;
  held_other_nationality: YesNo;
  previous_nationalities: string;
  job_email: string;
  job_password: string;
}

export interface Diversity {
  gender: string;
  ethnicity: string;
  disability_status: string;
  veteran_status: string;
  sexual_orientation: string;
}

export interface Screening {
  why_this_role: string;
  why_this_company: string;
  greatest_strength: string;
  biggest_weakness: string;
  leadership_example: string;
  conflict_resolution: string;
  salary_canonical: string;
  notice_period_canonical: string;
}

export interface Preferences {
  target_titles: string[];
  min_salary?: number | null;
  expected_hourly_rate?: number | null;
  remote_preference: string;
  relocation_willingness: YesNo;
  preferred_locations: string[];
  industries: string[];
  companies_to_avoid: string[];
  company_size_preference: string;
  employment_type: string;
  notice_period: string;
  can_work_in_person: YesNo;
  can_start_immediately: YesNo;
  has_reliable_transportation: YesNo;
  needs_accommodations: YesNo;
}

export interface Persona {
  core_info: CoreInfo;
  diversity: Diversity;
  screening: Screening;
  preferences: Preferences;
  history: WorkExperience[];
  education: Education[];
  projects: Project[];
  certifications: Certification[];
  story_bank: BehavioralStory[];
  custom_directives: string;
  skills: SkillCategory[];
  summary: string;
}

/* ── Autopilot (mirrors api/app/autopilot.py) ───────────────────────── */

export interface AutopilotSettings {
  /** Runs on its own every few hours. */
  enabled: boolean;
  /** Sends forms that pass every check; off = practice (fills, never sends). */
  live: boolean;
  min_fit: number;
  daily_cap: number;
}

export interface AutopilotStatus {
  settings: AutopilotSettings;
  running: boolean;
  step: string;
  job: string;
  started_at: string | null;
  sent_last_day: number;
  last_run_at: string | null;
  next_run_at: string | null;
  last: { finished_at: string; live: boolean; counts: Partial<Record<AutopilotOutcome, number>>; note: string } | null;
}

export type AutopilotOutcome =
  | "running" | "submitted" | "unconfirmed" | "ready" | "needs_you" | "skipped" | "failed" | "dismissed";

export interface AutopilotRun {
  id: string;
  job_id: string;
  job_title: string;
  company: string;
  location: string;
  job_url: string;
  outcome: AutopilotOutcome;
  /** Filled in practice mode, where nothing is sent. */
  practice: boolean;
  fit_score: number | null;
  /** Why it wasn't sent. */
  reasons: string[];
  questions: FormAnswer[];
  notes: string | null;
  cv_doc_id: string | null;
  letter_doc_id: string | null;
  application_id: string | null;
  /** Kept screenshots: "form" (filled, before sending) and "confirm" (after). */
  screenshots: ("form" | "confirm")[];
  created_at: string;
  updated_at: string;
}

/* ── Gmail tracking (mirrors api/app/gmail.py) ──────────────────────── */

export interface GmailStatus {
  /** GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are set. */
  configured: boolean;
  connected: boolean;
  email: string | null;
  /** Why it stopped (Google ended the access): connect again. */
  problem: string | null;
  last_sync_at: string | null;
  syncing: boolean;
  last: { finished_at: string; counts: Record<string, number>; error?: string } | null;
  redirect_uri: string;
}

export type EmailKind = "received" | "assessment" | "interview" | "offer" | "rejected" | "other";
export type EmailDecision = "applied" | "suggested" | "unmatched" | "noted" | "confirmed" | "dismissed" | "undone";

export interface EmailEvent {
  id: string;
  gmail_id: string;
  received_at: string;
  sender: string;
  subject: string;
  snippet: string;
  kind: EmailKind;
  company: string;
  role: string;
  summary: string;
  application_id: string | null;
  /** The status the email points to. */
  proposed: string | null;
  decision: EmailDecision;
  status_before: string | null;
  app_title: string | null;
  app_company: string | null;
  app_status: string | null;
}
