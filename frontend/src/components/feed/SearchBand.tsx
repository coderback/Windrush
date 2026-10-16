"use client";

import Icon, { type IconName } from "@/components/ui/Icon";

export const SALARY_MIN = 0;
export const SALARY_MAX = 150_000;
const SALARY_STEP = 5_000;

const k = (n: number) => `£${Math.round(n / 1000)}k`;

export function salaryLabel([lo, hi]: [number, number]): string {
  if (lo <= SALARY_MIN && hi >= SALARY_MAX) return "Any";
  if (hi >= SALARY_MAX) return `${k(lo)}+`;
  if (lo <= SALARY_MIN) return `Up to ${k(hi)}`;
  return `${k(lo)} – ${k(hi)}`;
}

export const EXPERIENCE_OPTIONS = [
  { value: "", label: "Any experience" },
  { value: "0", label: "No experience required" },
  { value: "1", label: "Up to 1 year" },
  { value: "2", label: "Up to 2 years" },
  { value: "3", label: "Up to 3 years" },
  { value: "5", label: "Up to 5 years" },
];

function Segment({ icon, label, htmlFor, children }: { icon: IconName; label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <span className="flex-[1_1_180px] min-w-0 flex items-center gap-3 px-[14px] py-[10px] rounded-inner bg-white/[.06]">
      <span className="w-[34px] h-[34px] rounded-control flex items-center justify-center shrink-0 bg-white/10">
        <Icon name={icon} size={16} />
      </span>
      <span className="flex-1 min-w-0 flex flex-col gap-[2px]">
        <label htmlFor={htmlFor} className="text-[11.5px] opacity-75">{label}</label>
        {children}
      </span>
    </span>
  );
}

const fieldClass = "w-full border-0 p-0 bg-transparent text-[14px] font-medium text-inherit outline-none placeholder:text-white/50";

/** The segmented search bar on the dark band: role, location, experience asked and a salary range. */
export default function SearchBand({ role, onRole, location, onLocation, maxYears, onMaxYears, salary, onSalary, onSubmit }: {
  role: string; onRole: (v: string) => void;
  location: string; onLocation: (v: string) => void;
  maxYears: string; onMaxYears: (v: string) => void;
  salary: [number, number]; onSalary: (v: [number, number]) => void;
  onSubmit: () => void;
}) {
  const [lo, hi] = salary;
  const left = ((lo - SALARY_MIN) / (SALARY_MAX - SALARY_MIN)) * 100;
  const right = ((hi - SALARY_MIN) / (SALARY_MAX - SALARY_MIN)) * 100;
  return (
    <form role="search" aria-label="Search jobs"
      onSubmit={(e) => { e.preventDefault(); onSubmit(); }}
      className="flex flex-wrap items-stretch gap-1 p-2 rounded-[18px] bg-band text-[#FAFAF7]">
      <Segment icon="search" label="Role or skill" htmlFor="seg-role">
        <input id="seg-role" value={role} onChange={(e) => onRole(e.target.value)}
          placeholder="e.g. Backend, ML" className={fieldClass} />
      </Segment>
      <Segment icon="pin" label="Location" htmlFor="seg-where">
        <input id="seg-where" value={location} onChange={(e) => onLocation(e.target.value)}
          placeholder="Your locations" className={fieldClass} />
      </Segment>
      <Segment icon="briefcase" label="Experience asked" htmlFor="seg-exp">
        <select id="seg-exp" value={maxYears} onChange={(e) => onMaxYears(e.target.value)}
          title="Hides jobs whose ad asks for more experience; ads that don't say are kept."
          className={`${fieldClass} cursor-pointer -ml-[2px]`} style={{ colorScheme: "dark" }}>
          {EXPERIENCE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </Segment>
      <span className="flex-[1.3_1_240px] min-w-0 flex flex-col justify-center gap-[10px] px-4 py-[10px] rounded-inner bg-white/[.06]">
        <span className="flex justify-between text-[11.5px]">
          <span className="opacity-75" id="salary-label">Salary (per year)</span>
          <span className="font-mono font-semibold">{salaryLabel(salary)}</span>
        </span>
        <span role="group" aria-labelledby="salary-label" className="relative block h-4">
          <span className="absolute left-0 right-0 top-1/2 -translate-y-1/2 h-1 rounded-full bg-white/[.18]" aria-hidden="true" />
          <span className="absolute top-1/2 -translate-y-1/2 h-1 rounded-full bg-amber" aria-hidden="true"
            style={{ left: `${left}%`, right: `${100 - right}%` }} />
          <input type="range" className="dual-range" min={SALARY_MIN} max={SALARY_MAX} step={SALARY_STEP} value={lo}
            aria-label="Minimum salary" aria-valuetext={lo <= SALARY_MIN ? "No minimum" : k(lo)}
            onChange={(e) => onSalary([Math.min(Number(e.target.value), hi - SALARY_STEP), hi])} />
          <input type="range" className="dual-range" min={SALARY_MIN} max={SALARY_MAX} step={SALARY_STEP} value={hi}
            aria-label="Maximum salary" aria-valuetext={hi >= SALARY_MAX ? "No maximum" : k(hi)}
            onChange={(e) => onSalary([lo, Math.max(Number(e.target.value), lo + SALARY_STEP)])} />
        </span>
      </span>
      <button type="submit"
        className="flex-[0_0_auto] max-sm:flex-1 flex items-center justify-center gap-2 min-h-[52px] px-[22px] rounded-inner bg-teal text-on-ink text-[14px] font-semibold hover:opacity-90">
        <Icon name="search" size={16} strokeWidth={2} />
        Search
      </button>
    </form>
  );
}
