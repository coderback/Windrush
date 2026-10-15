import type { Analysis, Application, Job } from "./types";
import { jobKey } from "./format";

/* The job workspace reads its job from sessionStorage (there is no GET /jobs/{id}), so every link
   into it stores the job first. The feed also stores its order for Previous / Next match. */

const JOB = (id: string) => `job_${id}`;
const FEED_ORDER = "feed_order";
const FIT = (id: string) => `fit_${id}`;

function write(key: string, value: unknown) {
  try { sessionStorage.setItem(key, JSON.stringify(value)); } catch {}
}

function read<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export function rememberJob(job: Job): string {
  const id = jobKey(job);
  write(JOB(id), job);
  return id;
}

export function recallJob(id: string): Job | null {
  return read<Job>(JOB(id));
}

/** Keep the feed's current order (and each job) so the workspace can walk it. */
export function rememberFeed(jobs: Job[]) {
  const ids = jobs.map((j) => rememberJob(j));
  write(FEED_ORDER, ids);
}

export function feedNeighbours(id: string): { prev: string | null; next: string | null } {
  const ids = read<string[]>(FEED_ORDER) ?? [];
  const i = ids.indexOf(id);
  if (i < 0) return { prev: null, next: null };
  return { prev: ids[i - 1] ?? null, next: ids[i + 1] ?? null };
}

export function jobHref(id: string) {
  return `/jobs/${encodeURIComponent(id)}`;
}

/** A tracked application as a Job the workspace can open (the tracker keeps the job's id and link). */
export function jobFromApplication(app: Application): Job | null {
  const id = app.job_id || "";
  const job: Job = { id: id || undefined, title: app.job_title, company: app.company, location: app.location || "", url: app.job_url || "" };
  if (!id && !job.url) return null;
  return job;
}

/** Where a tracked application's job opens, and the call that stores the job for that page. */
export function applicationLink(app: Application): { href: string; remember: () => void } | null {
  const job = jobFromApplication(app);
  if (!job) return null;
  return { href: jobHref(jobKey(job)), remember: () => { rememberJob(job); } };
}

/* "Check my fit" results, cached per job for this session: the analysis is an LLM call. */
export function cachedFit(id: string): Analysis | null {
  return read<Analysis>(FIT(id));
}

export function cacheFit(id: string, analysis: Analysis) {
  write(FIT(id), analysis);
}
