import { load, requestJson } from "./store";
import type { EmailEvent, GmailStatus } from "./types";

/* Gmail tracking: read-only access to your job emails keeps your applications up to date (api/app/gmail.py). */

export const GMAIL_URL = "/api/gmail";
export const EVENTS_URL = "/api/gmail/events";

const post = (body?: object): RequestInit =>
  ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });

/** Off to Google's consent page. */
export async function connectGmail() {
  const { url } = await requestJson<{ url: string }>(`${GMAIL_URL}/connect`);
  window.location.href = url;
}

export async function disconnectGmail() {
  await requestJson(GMAIL_URL, { method: "DELETE" });
  await Promise.all([load(GMAIL_URL, { force: true }), load(EVENTS_URL, { force: true })]);
}

export async function syncGmail() {
  await requestJson(`${GMAIL_URL}/sync`, post());
  await load(GMAIL_URL, { force: true });
}

async function act(id: string, action: "confirm" | "dismiss" | "undo", body?: object) {
  await requestJson<EmailEvent>(`${EVENTS_URL}/${encodeURIComponent(id)}/${action}`, post(body));
  await Promise.all([load(EVENTS_URL, { force: true }), load("/api/applications", { force: true })]);
}

export const confirmEmail = (id: string, applicationId?: string) =>
  act(id, "confirm", applicationId ? { application_id: applicationId } : {});
export const dismissEmail = (id: string) => act(id, "dismiss");
export const undoEmail = (id: string) => act(id, "undo");
