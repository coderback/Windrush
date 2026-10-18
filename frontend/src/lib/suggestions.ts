import { authFetch } from "@/app/api";
import { load, mutate, requestJson } from "./store";
import type { Persona, ProfileSuggestions } from "./types";

/* Profile suggestions: GitHub, the website and a LinkedIn export, read into changes the user accepts or
   dismisses (api/app/enrich.py). Nothing changes the persona without a yes. */

export const SUGGESTIONS_URL = "/api/profile/suggestions";

const post = (body?: object): RequestInit =>
  ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });

export const refreshSuggestions = () => load<ProfileSuggestions>(SUGGESTIONS_URL, { force: true });

/** Start reading GitHub or the website; it runs in the background. */
export async function readSource(source: "github" | "website") {
  await requestJson(`${SUGGESTIONS_URL}/read`, post({ source }));
  await refreshSuggestions();
}

/** Read a LinkedIn data export. Returns how many new suggestions it made. */
export async function uploadLinkedIn(file: File): Promise<number> {
  const form = new FormData();
  form.append("file", file);
  const res = await authFetch(`${SUGGESTIONS_URL}/linkedin`, { method: "POST", body: form });
  const body = await res.json().catch(() => ({}));
  await refreshSuggestions();
  if (!res.ok) throw new Error(typeof body?.detail === "string" ? body.detail : "Couldn't read that file.");
  return body.added ?? 0;
}

export interface AcceptResult { accepted: number; outdated: number; persona: Persona }

/** Add the suggestions to the persona; returns the persona as saved. */
export async function acceptSuggestions(ids: string[]): Promise<AcceptResult> {
  const result = await requestJson<AcceptResult>(`${SUGGESTIONS_URL}/accept`, post({ ids }));
  mutate<Persona>("/api/persona", result.persona);
  await refreshSuggestions();
  return result;
}

export async function dismissSuggestions(ids: string[]) {
  await requestJson(`${SUGGESTIONS_URL}/dismiss`, post({ ids }));
  await refreshSuggestions();
}
