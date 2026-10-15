import type { Job } from "./types";

const k = (n: number) => Math.round(n / 1000);

/** "£34–38k", "£32k", "From £30k", "Up to £45k", or null when the ad states no salary. */
export function formatSalary(min?: number | null, max?: number | null): string | null {
  if (!min && !max) return null;
  if (min && max) {
    if (min < 1000 || max < 1000) return `£${min}–${max}`;
    return k(min) === k(max) ? `£${k(min)}k` : `£${k(min)}–${k(max)}k`;
  }
  if (min) return min >= 1000 ? `From £${k(min)}k` : `From £${min}`;
  return max! >= 1000 ? `Up to £${k(max!)}k` : `Up to £${max}`;
}

export function jobSalary(job: Pick<Job, "salary" | "salary_min" | "salary_max">): string | null {
  return job.salary || formatSalary(job.salary_min, job.salary_max);
}

function parse(date?: string | null): number | null {
  if (!date) return null;
  const t = new Date(date).getTime();
  return Number.isNaN(t) ? null : t;
}

/** Compact age: "now", "12m", "5h", "3d", "2w", "4mo". */
export function shortAgo(date?: string | null): string | null {
  const t = parse(date);
  if (t == null) return null;
  const mins = Math.max(0, Math.floor((Date.now() - t) / 60000));
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 14) return `${days}d`;
  if (days < 60) return `${Math.floor(days / 7)}w`;
  return `${Math.floor(days / 30)}mo`;
}

/** Spelled-out age: "just now", "12 min ago", "2 hours ago", "yesterday", "5 days ago", "9 Oct". */
export function longAgo(date?: string | null): string | null {
  const t = parse(date);
  if (t == null) return null;
  const mins = Math.max(0, Math.floor((Date.now() - t) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return shortDate(date);
}

/** "9 Oct", or "9 Oct 2025" outside the current year. */
export function shortDate(date?: string | null): string | null {
  const t = parse(date);
  if (t == null) return null;
  const d = new Date(t);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }) });
}

export function daysSince(date?: string | null): number | null {
  const t = parse(date);
  return t == null ? null : Math.floor((Date.now() - t) / 86400000);
}

/** Two-letter mark for a company: initials of the first two words, or the first two letters. */
export function initials(name?: string | null): string {
  const words = (name || "").replace(/[^A-Za-z0-9À-ÿ\s]/g, " ").split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

export function greeting(now = new Date()): string {
  const h = now.getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export function levelLabel(level?: string | null): string | null {
  switch ((level || "").toLowerCase()) {
    case "junior": return "Junior";
    case "mid": return "Mid-level";
    case "senior": return "Senior";
    default: return null;
  }
}

export function experienceLabel(years?: number | null): string | null {
  if (years == null) return null;
  return years === 0 ? "None" : years === 1 ? "1 year" : `${years}+ years`;
}

export function degreeLabel(degree?: string | null): string {
  switch (degree) {
    case "required": return "Required";
    case "preferred": return "Preferred";
    case "not_mentioned": return "Not mentioned";
    default: return "Not stated";
  }
}

export type WorkSetting = "Remote" | "Hybrid" | "On-site";

/** What the ad says about where the work happens, read from the location and the description. */
export function workSetting(job: Pick<Job, "location" | "description">): WorkSetting | null {
  const loc = (job.location || "").toLowerCase();
  const text = `${loc} ${(job.description || "").toLowerCase()}`;
  if (/\bhybrid\b/.test(text)) return "Hybrid";
  if (/\b(remote|work from home|anywhere)\b/.test(loc)) return "Remote";
  if (/\b(fully remote|100% remote|remote-first|remote first)\b/.test(text)) return "Remote";
  if (/\b(on-site|onsite|in office|in-office|office based|office-based)\b/.test(text)) return "On-site";
  return null;
}

export function jobKey(job: Pick<Job, "id" | "job_id" | "company" | "title">): string {
  return job.id ?? job.job_id ?? `${job.company}-${job.title}`;
}

export function jobTags(job: Pick<Job, "tags">): string[] {
  if (Array.isArray(job.tags)) return job.tags;
  if (typeof job.tags === "string" && job.tags) {
    try { const t = JSON.parse(job.tags); return Array.isArray(t) ? t : []; } catch { return []; }
  }
  return [];
}

export function pct(n: number, of: number): number {
  return of > 0 ? Math.round((n / of) * 100) : 0;
}
