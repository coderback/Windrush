"use client";

import { useEffect, useId, useRef, useState } from "react";
import Icon from "@/components/ui/Icon";
import { buttonClass, cx, inputClass, labelClass, textareaClass } from "@/components/ui/kit";
import type { YesNo } from "@/lib/types";

export function TextField({ label, value, onChange, type = "text", placeholder, hint, autoComplete, className }: {
  label: string; value: string | number | null | undefined; onChange: (v: string) => void;
  type?: string; placeholder?: string; hint?: string; autoComplete?: string; className?: string;
}) {
  const id = useId();
  return (
    <div className={cx("flex flex-col gap-[6px] min-w-0", className)}>
      <label htmlFor={id} className={labelClass}>{label}</label>
      <input id={id} type={type} value={value ?? ""} placeholder={placeholder} autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)} className={inputClass} aria-describedby={hint ? `${id}-hint` : undefined} />
      {hint && <span id={`${id}-hint`} className="text-[12px] text-ink-3">{hint}</span>}
    </div>
  );
}

export function AreaField({ label, value, onChange, rows = 4, placeholder, hint, className }: {
  label: string; value: string | null | undefined; onChange: (v: string) => void;
  rows?: number; placeholder?: string; hint?: string; className?: string;
}) {
  const id = useId();
  return (
    <div className={cx("flex flex-col gap-[6px] min-w-0", className)}>
      <label htmlFor={id} className={labelClass}>{label}</label>
      {hint && <span id={`${id}-hint`} className="text-[12px] text-ink-3 -mt-[2px]">{hint}</span>}
      <textarea id={id} rows={rows} value={value ?? ""} placeholder={placeholder} onChange={(e) => onChange(e.target.value)}
        className={textareaClass} aria-describedby={hint ? `${id}-hint` : undefined} />
    </div>
  );
}

export function SelectField({ label, value, onChange, options, className }: {
  label: string; value: string | null | undefined; onChange: (v: string) => void;
  options: { value: string; label: string }[]; className?: string;
}) {
  const id = useId();
  return (
    <div className={cx("flex flex-col gap-[6px] min-w-0", className)}>
      <label htmlFor={id} className={labelClass}>{label}</label>
      <select id={id} value={value ?? ""} onChange={(e) => onChange(e.target.value)} className={cx(inputClass, "px-[10px]")}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

/** Yes / No / Not answered. Unanswered facts are left for you on application forms. */
export function YesNoField({ label, value, onChange }: { label: string; value: YesNo | undefined; onChange: (v: YesNo) => void }) {
  const opts: { v: YesNo; label: string }[] = [{ v: true, label: "Yes" }, { v: false, label: "No" }, { v: null, label: "Not answered" }];
  const current = value === undefined ? null : value;
  return (
    <div role="group" aria-label={label} className="flex flex-wrap items-center justify-between gap-3 px-[14px] py-[10px] border border-track rounded-inner">
      <span className="text-[13.5px] min-w-0">{label}</span>
      <span className="inline-flex p-[3px] border border-border rounded-control bg-subtle">
        {opts.map((o) => {
          const on = current === o.v;
          return (
            <button key={String(o.v)} type="button" aria-pressed={on} onClick={() => onChange(o.v)}
              className={cx("h-7 px-[10px] rounded-[7px] text-[12.5px]", on ? "bg-surface text-ink font-semibold shadow-lift" : "text-ink-3 hover:text-ink")}>
              {o.label}
            </button>
          );
        })}
      </span>
    </div>
  );
}

/**
 * A list typed as chips. A comma (or Enter) turns what you typed into a chip; the text still being
 * typed counts as the last item, so nothing is lost if you stop mid-word.
 */
export function ChipInput({ label, value, onChange, placeholder, addLabel, hideLabel }: {
  label: string; value: string[]; onChange: (items: string[]) => void; placeholder?: string; addLabel?: string; hideLabel?: boolean;
}) {
  const id = useId();
  const [text, setText] = useState("");
  const emitted = useRef<string[] | null>(null);
  const items = value ?? [];
  const pending = text.trim();
  const committed = pending ? items.slice(0, -1) : items;

  // A new list from outside (a load, a reset) drops whatever was half-typed.
  useEffect(() => {
    if (emitted.current !== value) setText("");
  }, [value]);

  const emit = (next: string[]) => {
    emitted.current = next;
    onChange(next);
  };

  const type = (t: string) => {
    if (t.includes(",")) {
      const parts = t.split(",");
      const last = parts.pop() ?? "";
      const done = parts.map((p) => p.trim()).filter(Boolean);
      const rest = last.replace(/^\s+/, "");
      setText(rest);
      emit([...committed, ...done, ...(rest.trim() ? [rest.trim()] : [])]);
    } else {
      setText(t);
      emit([...committed, ...(t.trim() ? [t.trim()] : [])]);
    }
  };

  return (
    <div className="flex flex-col gap-[6px] min-w-0">
      <label htmlFor={id} className={hideLabel ? "sr-only" : labelClass}>{label}</label>
      <div className="flex flex-wrap gap-[6px] p-2 border border-border-strong rounded-control bg-surface focus-within:border-teal">
        {committed.map((item, i) => (
          <span key={`${item}-${i}`} className="inline-flex items-center gap-[6px] h-7 pl-[10px] pr-[6px] rounded-[8px] bg-muted text-[13px]">
            {item}
            <button type="button" aria-label={`Remove ${item}`} onClick={() => emit([...committed.filter((_, j) => j !== i), ...(pending ? [pending] : [])])}
              className="w-[18px] h-[18px] rounded-[5px] flex items-center justify-center text-ink-3 hover:text-red hover:bg-red-soft">
              <Icon name="close" size={11} strokeWidth={2.4} />
            </button>
          </span>
        ))}
        <input id={id} value={text} placeholder={committed.length ? addLabel ?? "Add another" : placeholder}
          onChange={(e) => type(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (pending) setText("");
            } else if (e.key === "Backspace" && !text && committed.length) {
              emit(committed.slice(0, -1));
            }
          }}
          onBlur={() => { if (pending) setText(""); }}
          className="flex-1 min-w-[140px] h-7 border-0 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-3" />
      </div>
    </div>
  );
}

/** One entry in a repeating section (a role, a degree, a project…): a summary with Edit and Remove. */
export function EntryCard({ title, subtitle, meta, editing, onEdit, onRemove, children, form }: {
  title: string; subtitle?: string; meta?: string; editing: boolean;
  onEdit: () => void; onRemove: () => void; children?: React.ReactNode; form: React.ReactNode;
}) {
  return (
    <article className="border border-track rounded-inner p-4 flex flex-col gap-[10px]">
      {editing ? (
        <>
          {form}
          <span className="flex gap-2">
            <button type="button" onClick={onEdit} className={buttonClass("primary", "xs")}>Done</button>
            <button type="button" onClick={onRemove} className={buttonClass("destructive", "xs", "font-normal")}>Remove</button>
          </span>
        </>
      ) : (
        <>
          <span className="flex flex-wrap justify-between gap-2">
            <span className="flex flex-col gap-[2px] min-w-0">
              <span className="text-[14.5px] font-semibold">{title || "Untitled"}</span>
              {subtitle && <span className="text-[13px] text-ink-2">{subtitle}</span>}
            </span>
            {meta && <span className="font-mono text-[12px] text-ink-2">{meta}</span>}
          </span>
          {children}
          <span className="flex gap-2">
            <button type="button" onClick={onEdit} className={buttonClass("secondary", "xs", "font-normal")}>
              Edit<span className="sr-only"> {title}</span>
            </button>
            <button type="button" onClick={onRemove} className={buttonClass("destructive", "xs", "font-normal")}>
              Remove<span className="sr-only"> {title}</span>
            </button>
          </span>
        </>
      )}
    </article>
  );
}

/** "2025-06" → "Jun 2025"; anything else is shown as typed. */
export function monthLabel(d?: string): string {
  if (!d) return "";
  const m = /^(\d{4})-(\d{2})/.exec(d);
  if (!m) return d;
  return new Date(Number(m[1]), Number(m[2]) - 1, 1).toLocaleDateString("en-GB", { month: "short", year: "numeric" });
}

export function dateRange(start?: string, end?: string, current?: boolean): string {
  const a = monthLabel(start), b = current ? "Present" : monthLabel(end);
  return a || b ? `${a || "?"} – ${b || "?"}` : "";
}
