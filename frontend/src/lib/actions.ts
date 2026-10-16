import { load, mutate, peek, requestJson } from "./store";
import type { Application, Job } from "./types";

const APPS = "/api/applications";

function findTracked(apps: Application[] | undefined, job: Pick<Job, "company" | "title">): Application | undefined {
  const c = (job.company || "").toLowerCase(), t = (job.title || "").toLowerCase();
  return apps?.find((a) => a.company.toLowerCase() === c && a.job_title.toLowerCase() === t);
}

/** Bookmark a job (tracker status Saved). Returns the application id, also when it was already tracked. */
export async function saveJob(job: Job): Promise<string | null> {
  const res = await requestJson<{ id?: string; status: string }>("/api/jobs/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job }),
  });
  const apps = await load<Application[]>(APPS, { force: true }).catch(() => peek<Application[]>(APPS));
  return res.id ?? findTracked(apps, job)?.id ?? null;
}

export async function setStatus(appId: string, status: string, notes?: string) {
  await requestJson(`/api/applications/${encodeURIComponent(appId)}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(notes === undefined ? { status } : { status, notes }),
  });
  mutate<Application[]>(APPS, (prev) => (prev ?? []).map((a) => {
    if (a.id !== appId) return a;
    const next: Application = { ...a, status, notes: notes === undefined ? a.notes : notes };
    if (status === "Applied" && a.status !== "Applied") next.date_applied = new Date().toISOString().slice(0, 10);
    return next;
  }));
}

/** "Not for me": track the job as Discarded, which also keeps it out of the feed from now on. */
export async function discardJob(job: Job) {
  const id = await saveJob(job);
  if (!id) throw new Error("Couldn't find this job in your tracker.");
  await setStatus(id, "Discarded");
}

export function trackedApplication(job: Pick<Job, "company" | "title">): Application | undefined {
  return findTracked(peek<Application[]>(APPS), job);
}
