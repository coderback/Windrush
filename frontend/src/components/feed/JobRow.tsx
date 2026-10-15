"use client";

import { Chip, CompanyMark, cx, FitRing } from "@/components/ui/kit";
import { jobSalary, levelLabel, shortAgo } from "@/lib/format";
import { sponsorshipBadges, type Badge } from "@/lib/sponsorship";
import type { Job } from "@/lib/types";

/** The chips under a job: sponsorship and clearance first, then level, experience and degree. */
export function jobChips(job: Job): Badge[] {
  const chips = sponsorshipBadges(job).slice(0, 3);
  const level = levelLabel(job.level);
  if (level) chips.push({ label: level, tone: "neutral" });
  if (job.years_min != null) {
    chips.push({ label: job.years_min === 0 ? "No experience needed" : `${job.years_min}+ yrs exp`, tone: "neutral" });
  }
  if (job.degree === "required") chips.push({ label: "Degree required", tone: "neutral" });
  if (job.tracker_status === "Saved") chips.push({ label: "Saved", tone: "outline" });
  return chips;
}

export default function JobRow({ job, selected, onSelect }: { job: Job; selected: boolean; onSelect: () => void }) {
  const salary = jobSalary(job);
  const match = job.semantic_score != null ? Math.round(job.semantic_score * 100) : null;
  const posted = shortAgo(job.created_at ?? job.posted_at);
  return (
    <button type="button" onClick={onSelect} aria-pressed={selected}
      className={cx(
        "flex flex-col gap-[10px] w-full text-left px-4 py-[14px] rounded-[14px] bg-surface text-ink border",
        selected ? "border-border min-[1000px]:border-teal min-[1000px]:shadow-selected" : "border-border hover:border-border-strong",
      )}>
      <span className="flex gap-3 items-start w-full">
        <CompanyMark name={job.company} size={40} />
        <span className="flex-1 min-w-0 flex flex-col gap-[3px]">
          <span className="text-[14.5px] font-semibold leading-[1.3]">{job.title}</span>
          <span className="text-[13px] text-ink-2">{[job.company, job.location].filter(Boolean).join(" · ")}</span>
        </span>
        {match != null && <FitRing value={match} size={42} label="Match" />}
      </span>
      {jobChips(job).length > 0 && (
        <span className="flex flex-wrap gap-[6px]">
          {jobChips(job).map((c) => <Chip key={c.label} tone={c.tone} size="sm" title={c.title}>{c.label}</Chip>)}
        </span>
      )}
      <span className="flex justify-between items-baseline gap-3 pt-[10px] border-t border-divider w-full">
        {salary ? <span className="text-[14px] font-semibold">{salary}</span>
          : <span className="text-[13px] text-ink-3">Salary not listed</span>}
        {posted && <span className="text-[12px] text-ink-3">{posted === "now" ? "just now" : `${posted} ago`}</span>}
      </span>
    </button>
  );
}
