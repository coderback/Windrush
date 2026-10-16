import { authFetch } from "@/app/api";
import type { Analysis, Job } from "./types";

/** Read a `data: {...}` event stream, handing each parsed event to `onEvent` as it arrives. */
export async function readStream(
  response: Response,
  onEvent: (ev: Record<string, unknown>) => void,
  onReader?: (reader: ReadableStreamDefaultReader<Uint8Array>) => void,
): Promise<void> {
  if (!response.body) return;
  const reader = response.body.getReader();
  onReader?.(reader);
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as Record<string, unknown>);
      } catch {}
    }
  }
}

/** POST a JSON body to an SSE endpoint and collect its events. Throws on a non-2xx reply. */
export async function postStream(url: string, body: unknown, onEvent: (ev: Record<string, unknown>) => void) {
  const res = await authFetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const d = await res.json();
      if (typeof d?.detail === "string") detail = d.detail;
    } catch {}
    throw new Error(detail);
  }
  await readStream(res, onEvent);
}

/** Run the fit analysis (an LLM call) for one job. */
export async function analyzeJob(job: Job): Promise<Analysis> {
  const result: Analysis = {};
  await postStream("/api/jobs/analyze", { job }, (ev) => {
    if (ev.type === "job_fit" && Array.isArray(ev.ranked_jobs)) {
      const top = (ev.ranked_jobs[0] ?? {}) as Record<string, unknown>;
      result.fit_score = typeof top.fit_score === "number" ? top.fit_score : undefined;
      result.level_match = top.level_match as string | undefined;
      result.skill_gaps = (top.skill_gaps as string[] | undefined) ?? [];
      result.matched_skills = (top.matched_skills as string[] | undefined) ?? [];
      result.reasoning = top.reasoning as string | undefined;
    }
  });
  if (result.fit_score == null && !result.matched_skills) throw new Error("The analysis came back empty. Try again.");
  return result;
}
