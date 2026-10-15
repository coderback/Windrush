"use client";

import Link from "next/link";
import Icon from "./ui/Icon";
import { buttonClass, cx, Spinner } from "./ui/kit";

export interface LogLine { t: number; text: string }

export type ReviewTone = "amber" | "teal" | "neutral";

interface Action { onClick: () => void; disabled?: boolean; busy?: boolean; label?: string; hint?: string }

const PILL: Record<ReviewTone, { box: string; dot: string }> = {
  amber: { box: "bg-amber-soft text-amber-text", dot: "bg-amber" },
  teal: { box: "bg-teal-chip text-teal-deep", dot: "bg-teal" },
  neutral: { box: "bg-muted text-ink-2", dot: "bg-stone" },
};

const mmss = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** The agent's notes: its summary ("Needs your input: …" first) and what it did, with mm:ss stamps. */
export function AgentNotes({ notes, log, empty }: { notes?: string | null; log: LogLine[]; empty?: string }) {
  const needs = notes && /needs your input/i.test(notes);
  return (
    <aside className="flex-[1_1_340px] min-w-0 bg-surface border border-border rounded-card flex flex-col overflow-hidden">
      <h2 className="m-0 px-4 h-[46px] flex items-center border-b border-track text-[13.5px] font-semibold">Agent notes</h2>
      <div className="p-4 flex flex-col gap-[14px] flex-1">
        {notes && (
          <div className={cx("p-[14px] rounded-inner flex flex-col gap-2 text-[13px] leading-[1.5]",
            needs ? "bg-amber-wash-2 border border-amber-line-3 text-amber-ink" : "bg-subtle border border-divider text-ink-2")}>
            <span className={cx("text-[13.5px] font-semibold", needs ? "text-amber-ink-2" : "text-ink")}>
              {needs ? "Some fields need you" : "Summary"}
            </span>
            <p className="m-0 whitespace-pre-wrap break-words">{notes}</p>
            {needs && (
              <Link href="/profile" className="text-[13px] font-medium text-amber-text underline underline-offset-2">
                Add missing details to your persona
              </Link>
            )}
          </div>
        )}
        {log.length > 0 ? (
          <ol className="list-none m-0 p-0 flex flex-col gap-3">
            {log.map((l, i) => (
              <li key={i} className="flex gap-[10px] text-[13px] leading-[1.5] text-ink">
                <span className="font-mono text-[11.5px] text-ink-3 min-w-10 pt-[2px]">{mmss(l.t)}</span>
                <span>{l.text}</span>
              </li>
            ))}
          </ol>
        ) : !notes && (
          <p className="m-0 text-[13px] text-ink-3">{empty ?? "The agent's steps appear here as it works."}</p>
        )}
      </div>
    </aside>
  );
}

/** Review before submit: status, the live page, the agent's notes and the three final actions.
    Shared by the job workspace (step 5) and the Agent review queue. */
export default function ReviewLayout({ tone, status, title, subtitle, meta, frame, side, skip, done, submit, headingLevel = 1 }: {
  tone: ReviewTone;
  status: string;
  title: string;
  subtitle: string;
  meta?: React.ReactNode;
  frame: React.ReactNode;
  side: React.ReactNode;
  skip: Action;
  done: Action;
  submit: Action;
  headingLevel?: 1 | 2;
}) {
  const H = headingLevel === 1 ? "h1" : "h2";
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-[6px] min-w-0">
          <span role="status" className={cx("self-start flex items-center gap-[7px] h-[26px] px-[10px] rounded-full text-[12.5px] font-semibold", PILL[tone].box)}>
            <span aria-hidden="true" className={cx("w-[7px] h-[7px] rounded-full", PILL[tone].dot, tone === "teal" && "animate-pulse")} />
            {status}
          </span>
          <H className={cx("m-0 font-semibold tracking-[-0.02em]", headingLevel === 1 ? "text-[24px]" : "text-[19px]")}>{title}</H>
          <p className="m-0 text-[13.5px] text-ink-2">{subtitle}</p>
        </div>
        {meta}
      </div>
      <div className="flex flex-wrap gap-4 items-stretch">
        <div className="flex-[1.7_1_560px] min-w-0 flex">{frame}</div>
        {side}
      </div>
      <div className="md:sticky md:bottom-3 z-10 flex flex-wrap items-center gap-[10px] px-4 py-[14px] bg-surface border border-border rounded-card md:shadow-[0_8px_24px_rgba(20,20,15,0.08)]">
        <button type="button" onClick={skip.onClick} disabled={skip.disabled || skip.busy} className={buttonClass("destructive", "lg", "px-[14px] font-normal")}>
          {skip.busy ? <Spinner /> : null}{skip.label ?? "Skip this application"}
        </button>
        <span className="flex-1" />
        {(submit.hint || done.hint) && <span className="text-[12.5px] text-ink-3 basis-full sm:basis-auto order-last sm:order-none">{submit.hint || done.hint}</span>}
        <button type="button" onClick={done.onClick} disabled={done.disabled || done.busy} className={buttonClass("secondary", "lg", "px-4")}>
          {done.busy ? <Spinner /> : null}{done.label ?? "I submitted it myself"}
        </button>
        <button type="button" onClick={submit.onClick} disabled={submit.disabled || submit.busy} className={buttonClass("commit", "lg")}>
          {submit.busy ? <Spinner /> : <Icon name="check" size={16} strokeWidth={2.2} />}
          {submit.label ?? "Submit application"}
        </button>
      </div>
    </div>
  );
}
