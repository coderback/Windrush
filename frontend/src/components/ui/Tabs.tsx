"use client";

import { useRef } from "react";
import { cx } from "./kit";

export interface TabItem<K extends string> { key: K; label: React.ReactNode }

/** Underline tabs with arrow-key movement between them (WAI-ARIA tabs pattern). */
export function UnderlineTabs<K extends string>({ items, value, onChange, label, className, idPrefix, size = "md" }: {
  items: TabItem<K>[];
  value: K;
  onChange: (k: K) => void;
  label: string;
  className?: string;
  idPrefix: string;
  size?: "md" | "lg";
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: React.KeyboardEvent, i: number) => {
    const n = items.length;
    const j = e.key === "ArrowRight" ? (i + 1) % n : e.key === "ArrowLeft" ? (i - 1 + n) % n : -1;
    if (j < 0) return;
    e.preventDefault();
    refs.current[j]?.focus();
    onChange(items[j].key);
  };
  return (
    <div role="tablist" aria-label={label} className={cx("flex gap-1 border-b border-border", className)}>
      {items.map((t, i) => {
        const on = t.key === value;
        return (
          <button key={t.key} ref={(el) => { refs.current[i] = el; }} type="button" role="tab"
            id={`${idPrefix}-tab-${t.key}`} aria-controls={`${idPrefix}-panel-${t.key}`}
            aria-selected={on} tabIndex={on ? 0 : -1}
            onClick={() => onChange(t.key)} onKeyDown={(e) => onKey(e, i)}
            className={cx(
              "-mb-px px-3 border-b-2 bg-transparent cursor-pointer",
              size === "lg" ? "h-[46px] text-[13.5px] px-[10px]" : "h-[42px] text-[14px]",
              on ? "border-ink text-ink font-semibold" : "border-transparent text-ink-3 font-medium hover:text-ink",
            )}>
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ idPrefix, k, active, children, className }: {
  idPrefix: string; k: string; active: boolean; children: React.ReactNode; className?: string;
}) {
  if (!active) return null;
  return (
    <div role="tabpanel" id={`${idPrefix}-panel-${k}`} aria-labelledby={`${idPrefix}-tab-${k}`} className={className}>
      {children}
    </div>
  );
}

/** Pill segments (Board / Table and the like): toggle buttons with aria-pressed. */
export function Segmented<K extends string>({ items, value, onChange, label, className }: {
  items: TabItem<K>[];
  value: K;
  onChange: (k: K) => void;
  label: string;
  className?: string;
}) {
  return (
    <span role="group" aria-label={label} className={cx("inline-flex p-[3px] border border-border rounded-control bg-surface", className)}>
      {items.map((t) => {
        const on = t.key === value;
        return (
          <button key={t.key} type="button" aria-pressed={on} onClick={() => onChange(t.key)}
            className={cx(
              "h-[30px] px-3 rounded-[7px] text-[13px] inline-flex items-center gap-[6px]",
              on ? "bg-muted text-ink font-semibold" : "bg-transparent text-ink-2 hover:text-ink",
            )}>
            {t.label}
          </button>
        );
      })}
    </span>
  );
}

/** Filter pills (careers table): ink when selected. */
export function PillTabs<K extends string>({ items, value, onChange, label }: {
  items: TabItem<K>[];
  value: K;
  onChange: (k: K) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1">
      {items.map((t) => {
        const on = t.key === value;
        return (
          <button key={t.key} type="button" aria-pressed={on} onClick={() => onChange(t.key)}
            className={cx(
              "h-8 px-[11px] rounded-[8px] text-[12.5px] border",
              on ? "border-ink bg-ink text-on-ink font-semibold" : "border-border bg-surface text-ink-2 font-medium hover:text-ink",
            )}>
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
