import { mutate, requestJson } from "./store";
import type { AnswerSource, SavedAnswer } from "./types";

/* The answer bank: your own answers to application-form questions, reused on later forms. */

export const ANSWERS_URL = "/api/answers";

export const SOURCE_LABEL: Record<AnswerSource, string> = {
  needs_you: "Only you can answer",
  drafted: "Drafted for this job",
  saved: "Saved answer",
  profile: "From your persona",
};

const json = (method: string, body: object): RequestInit =>
  ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/** Save your answer to a question; `company` keeps it for that employer only when either names it. */
export async function saveAnswer(question: string, answer: string, kind: "fact" | "written", company = "") {
  const saved = await requestJson<SavedAnswer>(ANSWERS_URL, json("POST", { question, answer, kind, company }));
  mutate<SavedAnswer[]>(ANSWERS_URL, (prev) => [saved, ...(prev ?? []).filter((a) => a.id !== saved.id)]);
  return saved;
}

export async function updateAnswer(id: string, answer: string) {
  const saved = await requestJson<SavedAnswer>(`${ANSWERS_URL}/${encodeURIComponent(id)}`, json("PUT", { answer }));
  mutate<SavedAnswer[]>(ANSWERS_URL, (prev) => (prev ?? []).map((a) => (a.id === id ? saved : a)));
  return saved;
}

export async function deleteAnswer(id: string) {
  await requestJson(`${ANSWERS_URL}/${encodeURIComponent(id)}`, { method: "DELETE" });
  mutate<SavedAnswer[]>(ANSWERS_URL, (prev) => (prev ?? []).filter((a) => a.id !== id));
}
