"use client";

import { useState } from "react";
import { buttonClass, Callout, Spinner } from "@/components/ui/kit";
import { requestJson } from "@/lib/store";
import type { Job } from "@/lib/types";

/* Logs a job Windrush read badly, as it read it (title, employer, level, how much ad text), with what the user says
   is wrong, so jobs like it can be read right later. */
export default function ReportReading({ job, onClose }: { job: Job; onClose: () => void }) {
  const [note, setNote] = useState("");
  const [state, setState] = useState<"writing" | "sending" | "sent">("writing");
  const [problem, setProblem] = useState<string | null>(null);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    setState("sending");
    setProblem(null);
    try {
      await requestJson("/api/jobs/report", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job: { id: job.id ?? job.job_id, title: job.title, company: job.company, level: job.level, source: job.source,
                 url: job.url, description: job.description },
          note,
        }),
      });
      setState("sent");
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "That didn't send. Try again.");
      setState("writing");
    }
  };

  if (state === "sent") {
    return (
      <p role="status" className="basis-full m-0 text-[13px] text-ink-2">
        Reported, with what Windrush read for this job.{" "}
        <button type="button" onClick={onClose}
          className="bg-transparent border-0 p-0 text-[13px] font-medium text-teal-deep underline underline-offset-2 cursor-pointer">
          Close
        </button>
      </p>
    );
  }
  return (
    <form onSubmit={send} className="basis-full flex flex-col gap-2 max-w-[640px]">
      <label htmlFor="report-note" className="text-[13.5px] font-medium">What did Windrush get wrong? (optional)</label>
      <textarea id="report-note" rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)}
        placeholder="e.g. It's a Machine Learning Engineer job, not “Careers List”, and the ad's text is missing."
        className="w-full px-3 py-2 border border-border rounded-control bg-surface text-[13.5px] leading-[1.5] text-ink outline-none focus:border-teal" />
      {problem && <Callout>{problem}</Callout>}
      <span className="flex flex-wrap gap-2">
        <button type="submit" disabled={state === "sending"} className={buttonClass("primary", "sm")}>
          {state === "sending" ? <Spinner /> : null}Send report
        </button>
        <button type="button" onClick={onClose} className={buttonClass("quiet", "sm")}>Cancel</button>
      </span>
    </form>
  );
}
