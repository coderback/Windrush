"use client";

import { cx } from "@/components/ui/kit";

export interface FeedFilterState {
  /** Effective sponsorship filter: "any" | "possible" | "likely". */
  sponsorship: string;
  remote: boolean;
  hybrid: boolean;
  level: string;
  noDegree: boolean;
  noClearance: boolean;
}

function Check({ label, checked, onChange, title }: { label: string; checked: boolean; onChange: (v: boolean) => void; title?: string }) {
  return (
    <label title={title} className="flex items-center gap-[10px] min-h-7 text-[13.5px] cursor-pointer">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)}
        className="w-4 h-4 m-0 accent-teal shrink-0" style={{ accentColor: "var(--teal)" }} />
      <span className="flex-1">{label}</span>
    </label>
  );
}

function Radio({ name, label, checked, onChange }: { name: string; label: string; checked: boolean; onChange: () => void }) {
  return (
    <label className="flex items-center gap-[10px] min-h-7 text-[13.5px] cursor-pointer">
      <input type="radio" name={name} checked={checked} onChange={onChange}
        className="w-4 h-4 m-0 shrink-0" style={{ accentColor: "var(--teal)" }} />
      <span className="flex-1">{label}</span>
    </label>
  );
}

function Group({ legend, children }: { legend: string; children: React.ReactNode }) {
  return (
    <fieldset className="border-0 m-0 p-0 min-w-0 flex flex-col gap-2">
      <legend className="p-0 pb-2 text-[13px] font-semibold">{legend}</legend>
      {children}
    </fieldset>
  );
}

const LEVELS = [
  { value: "", label: "Any level" },
  { value: "junior", label: "Graduate / Junior" },
  { value: "mid", label: "Mid-level" },
  { value: "senior", label: "Senior+" },
];

export default function FeedFilters({ value, onChange, onClear, className }: {
  value: FeedFilterState;
  onChange: (patch: Partial<FeedFilterState>) => void;
  onClear: () => void;
  className?: string;
}) {
  const possible = value.sponsorship === "possible" || value.sponsorship === "likely";
  return (
    <aside aria-label="Filters" className={cx("bg-surface border border-border rounded-card p-4 flex flex-col gap-[18px]", className)}>
      <div className="flex justify-between items-baseline">
        <span className="text-[15px] font-semibold">Filters</span>
        <button type="button" onClick={onClear} className="text-[12.5px] text-ink-3 hover:text-ink underline-offset-2 hover:underline">Clear all</button>
      </div>
      <Group legend="Visa sponsorship">
        <Check label="Possible" checked={possible}
          title="Hides jobs that say they can't sponsor or need SC/DV clearance."
          onChange={(on) => onChange({ sponsorship: on ? "possible" : "any" })} />
        <Check label="Likely only" checked={value.sponsorship === "likely"}
          title="Only jobs that offer sponsorship or whose employer is a licensed sponsor."
          onChange={(on) => onChange({ sponsorship: on ? "likely" : possible ? "possible" : "any" })} />
      </Group>
      <Group legend="Work setting">
        <Check label="Remote" checked={value.remote} onChange={(on) => onChange({ remote: on })} />
        <Check label="Hybrid" checked={value.hybrid} onChange={(on) => onChange({ hybrid: on })}
          title="Read from the ad's location and description." />
      </Group>
      <Group legend="Level">
        {LEVELS.map((l) => (
          <Radio key={l.value || "any"} name="feed-level" label={l.label} checked={value.level === l.value}
            onChange={() => onChange({ level: l.value })} />
        ))}
      </Group>
      <Group legend="Requirements">
        <Check label="No degree needed" checked={value.noDegree} onChange={(on) => onChange({ noDegree: on })}
          title="Hides jobs whose ad requires a degree; ads that only prefer one, or don't say, are kept." />
        <Check label="No security clearance" checked={value.noClearance} onChange={(on) => onChange({ noClearance: on })}
          title="Hides jobs that ask for security clearance or vetting." />
      </Group>
    </aside>
  );
}
