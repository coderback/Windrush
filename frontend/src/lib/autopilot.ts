import { authFetch } from "@/app/api";
import { load, mutate, requestJson } from "./store";
import type { AutopilotRun, AutopilotSettings, AutopilotStatus } from "./types";

/* Autopilot: applies to jobs from your feed on its own, within your limits (api/app/autopilot.py). */

export const STATUS_URL = "/api/autopilot";
export const RUNS_URL = "/api/autopilot/runs";

const json = (method: string, body?: object): RequestInit =>
  ({ method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });

export async function saveSettings(changes: Partial<AutopilotSettings>) {
  const settings = await requestJson<AutopilotSettings>(`${STATUS_URL}/settings`, json("PUT", changes));
  mutate<AutopilotStatus>(STATUS_URL, (prev) => ({ ...(prev as AutopilotStatus), settings }));
  load(STATUS_URL, { force: true }).catch(() => {});
  return settings;
}

export async function runNow() {
  await requestJson(`${STATUS_URL}/run`, json("POST"));
  await load(STATUS_URL, { force: true });
}

export async function retryRun(id: string) {
  await requestJson(`${RUNS_URL}/${encodeURIComponent(id)}/retry`, json("POST"));
  await load(STATUS_URL, { force: true });
}

export async function dismissRun(id: string) {
  await requestJson(`${RUNS_URL}/${encodeURIComponent(id)}/dismiss`, json("POST"));
  mutate<AutopilotRun[]>(RUNS_URL, (prev) => (prev ?? []).map((r) => (r.id === id ? { ...r, outcome: "dismissed" } : r)));
}

/** A run's screenshot as an object URL (revoke it when done), or null. */
export async function screenshotUrl(id: string, which: "form" | "confirm"): Promise<string | null> {
  const res = await authFetch(`${RUNS_URL}/${encodeURIComponent(id)}/screenshots/${which}`);
  if (!res.ok) return null;
  return URL.createObjectURL(await res.blob());
}

function save(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function downloadDocument(docId: string, filename: string) {
  const res = await authFetch(`/api/documents/${docId}/download`);
  if (!res.ok) throw new Error("That document isn't available any more.");
  save(await res.blob(), filename);
}

/** A run's handover pack: its CV and cover letter as autopilot uploads them, and the form's answers, as a ZIP. */
export async function downloadPack(id: string) {
  const res = await authFetch(`${RUNS_URL}/${encodeURIComponent(id)}/pack`);
  if (!res.ok) throw new Error("This run's CV and cover letter aren't there any more.");
  const named = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "");
  save(await res.blob(), named?.[1] ?? "Windrush handover pack.zip");
}
