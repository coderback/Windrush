"use client";

import { useState } from "react";
import { buttonClass, Callout, Chip, cx, DateTile, SectionTitle } from "@/components/ui/kit";
import { requestJson, useResource } from "@/lib/store";
import type { AssessmentRecord, Assessments, OpenAssessment } from "@/lib/types";

const URL = "/api/assessments";

function howLong(minutes: number): string {
  if (minutes < 60) return `about ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `about ${hours} h${rest ? ` ${rest} min` : ""}`;
}

function dueLabel(days: number | null): { text: string; tone: "danger" | "warn" | "neutral" } {
  if (days == null) return { text: "No deadline given", tone: "neutral" };
  if (days < 0) return { text: `${-days} ${days === -1 ? "day" : "days"} late, it may still open`, tone: "neutral" };
  if (days === 0) return { text: "Due today", tone: "danger" };
  if (days === 1) return { text: "Due tomorrow", tone: "danger" };
  return { text: `Due in ${days} days`, tone: days <= 3 ? "warn" : "neutral" };
}

function recordLine(r: AssessmentRecord): string {
  const parts = [
    r.moved_on ? `${r.moved_on} moved on` : "",
    r.not_passed ? `${r.not_passed} not passed` : "",
    r.waiting ? `${r.waiting} waiting` : "",
  ].filter(Boolean);
  const done = r.done ? `${r.done} done${parts.length ? ` (${parts.join(", ")})` : ""}` : "";
  return [done, r.missed ? `${r.missed} missed` : ""].filter(Boolean).join(" · ");
}

function Row({ test, onMark, busy }: { test: OpenAssessment; onMark: (state: "done" | "skipped") => void; busy: boolean }) {
  const due = dueLabel(test.days_left);
  const urgent = test.days_left != null && test.days_left >= 0 && test.days_left <= 1;
  return (
    <li className="flex flex-wrap items-center gap-[14px] py-3 border-t border-divider">
      {test.deadline
        ? <DateTile date={new Date(`${test.deadline}T12:00:00`)} tint={urgent ? "peach" : "sky"} />
        : <span aria-hidden="true" className="w-[46px] h-[46px] rounded-inner bg-subtle border border-track flex items-center justify-center font-mono text-ink-3 shrink-0">–</span>}
      <div className="flex-[1_1_260px] flex flex-col gap-[3px] min-w-0">
        <span className="flex flex-wrap items-center gap-2">
          <span className="text-[14px] font-semibold">{test.company}</span>
          <Chip tone={due.tone} size="sm">{due.text}</Chip>
          {test.minutes ? <span className="text-[12.5px] text-ink-3">{howLong(test.minutes)}</span> : null}
        </span>
        {test.role && <span className="text-[12.5px] text-ink-3 truncate">{test.role}</span>}
        {test.summary && <span className="text-[13px] leading-[1.45] text-ink-2">{test.summary}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <a href={`https://mail.google.com/mail/u/0/#all/${encodeURIComponent(test.gmail_id)}`} target="_blank" rel="noopener noreferrer"
          className={buttonClass("secondary", "sm")}>Open email</a>
        <button type="button" disabled={busy} onClick={() => onMark("done")} className={buttonClass("primary", "sm")}
          aria-label={`Mark the ${test.company} test as done`}>Done</button>
        <button type="button" disabled={busy} onClick={() => onMark("skipped")} className={buttonClass("secondary", "sm")}
          aria-label={`Not taking the ${test.company} test`}>Not doing it</button>
      </div>
    </li>
  );
}

/* Tests employers have asked for, soonest first. Hidden when there's nothing to do and nothing to report. */
export default function AssessmentsCard() {
  const tests = useResource<Assessments>(URL);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [last, setLast] = useState<{ key: string; company: string; state: string } | null>(null);

  const send = async (key: string, state: string) => {
    setBusy(true);
    setProblem(null);
    try {
      await requestJson(`${URL}/mark`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key, state }) });
      await tests.reload();
      return true;
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That didn't save. Try again.");
      return false;
    } finally {
      setBusy(false);
    }
  };

  const mark = async (test: OpenAssessment, state: "done" | "skipped") => {
    if (await send(test.key, state)) setLast({ key: test.key, company: test.company, state });
  };

  const open = tests.data?.open ?? [];
  const record = tests.data?.record;
  const line = record ? recordLine(record) : "";
  if (tests.error) return <Callout title="Couldn't load your assessments">{tests.error}</Callout>;
  if (!open.length && !line && !last) return null;

  return (
    <section aria-labelledby="assessments" className={cx("bg-surface border rounded-card px-5 pt-[18px] pb-2 flex flex-col", open.some((t) => (t.days_left ?? 9) >= 0 && (t.days_left ?? 9) <= 1) ? "border-amber-line" : "border-border")}>
      <div className="flex flex-wrap justify-between items-center gap-2 pb-[14px]">
        <SectionTitle id="assessments">Assessments to do</SectionTitle>
        {line && <span className="text-[13px] text-ink-3">{line}</span>}
      </div>
      {problem && <div className="pb-3"><Callout>{problem}</Callout></div>}
      {open.length > 0 ? (
        <ul className="list-none m-0 p-0">
          {open.map((t) => <Row key={t.key} test={t} busy={busy} onMark={(state) => mark(t, state)} />)}
        </ul>
      ) : (
        <p className="m-0 py-3 border-t border-divider text-[13.5px] text-ink-2">Nothing to do right now.</p>
      )}
      {last && (
        <p role="status" className="m-0 py-3 border-t border-divider text-[13px] text-ink-2">
          {last.company} marked as {last.state === "done" ? "done" : "not being taken"}.{" "}
          <button type="button" disabled={busy} className="bg-transparent border-0 p-0 text-[13px] font-medium text-teal-deep underline underline-offset-2 cursor-pointer"
            onClick={async () => { if (await send(last.key, "open")) setLast(null); }}>Undo</button>
        </p>
      )}
    </section>
  );
}
