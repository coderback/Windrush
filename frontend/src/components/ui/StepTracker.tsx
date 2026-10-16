"use client";

import { cx } from "./kit";

export interface Step {
  key: string;
  title: string;
  /** Overrides the default Done / In progress / Up next line. */
  sub?: string;
}

/** Steps as a row of buttons: done steps show a teal check, the current one an ink dot, later
    ones an outlined number. Only done steps (and the current one) can be picked. */
export default function StepTracker({ steps, current, reached, onPick, label = "Application steps" }: {
  steps: Step[];
  current: number;
  /** Highest step index the user has reached; steps up to it can be revisited. */
  reached: number;
  onPick: (i: number) => void;
  label?: string;
}) {
  return (
    <ol aria-label={label}
      className="list-none m-0 p-[6px] grid gap-1 bg-surface border border-border rounded-card"
      style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(170px, 100%), 1fr))" }}>
      {steps.map((s, i) => {
        const done = i < reached && i !== current;
        const on = i === current;
        const pickable = i <= reached;
        return (
          <li key={s.key} className="flex">
            <button type="button" disabled={!pickable} onClick={() => onPick(i)} aria-current={on ? "step" : undefined}
              className={cx(
                "flex-1 flex items-center gap-[10px] px-3 py-[10px] rounded-[11px] text-left text-ink",
                on ? "bg-muted" : "bg-transparent", pickable && !on && "hover:bg-subtle", !pickable && "cursor-default",
              )}>
              <span aria-hidden="true" className={cx(
                "w-7 h-7 rounded-full flex items-center justify-center font-mono text-[12px] font-semibold shrink-0 border",
                done ? "bg-teal border-teal text-on-ink" : on ? "bg-ink border-ink text-on-ink" : "bg-surface border-border-strong text-ink-2",
              )}>
                {done ? (
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"
                    strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5 9-10" /></svg>
                ) : i + 1}
              </span>
              <span className="flex flex-col gap-px min-w-0">
                <span className="text-[13.5px] font-semibold">{s.title}</span>
                <span className={cx("text-[12px]", done ? "text-teal" : on ? "text-ink" : "text-ink-3")}>
                  {s.sub ?? (done ? "Done" : on ? "In progress" : "Up next")}
                  <span className="sr-only">{done ? ", completed" : on ? ", current step" : ""}</span>
                </span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
