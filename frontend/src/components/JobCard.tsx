"use client";

import { useRouter } from "next/navigation";

export interface Job {
  id?: string;
  job_id?: string;
  title: string;
  company: string;
  location: string;
  salary?: string;
  salary_min?: number | null;
  salary_max?: number | null;
  description?: string;
  url?: string;
  exposure_score?: number;
  source?: string;
  posted_at?: string;
}

function normalise(score?: number): number | undefined {
  if (score == null) return undefined;
  return score <= 1 ? Math.round(score * 100) : Math.round(score);
}

function riskLabel(score?: number): { label: string; color: string } {
  if (score == null) return { label: "Unknown", color: "text-zinc-500 border-zinc-700 bg-zinc-800" };
  if (score >= 70) return { label: "High Risk", color: "text-red-400 border-red-400/30 bg-red-400/10" };
  if (score >= 40) return { label: "Med Risk", color: "text-yellow-400 border-yellow-400/30 bg-yellow-400/10" };
  return { label: "Low Risk", color: "text-teal-400 border-teal-400/30 bg-teal-400/10" };
}

export default function JobCard({ job }: { job: Job }) {
  const router = useRouter();
  const pct = normalise(job.exposure_score);
  const risk = riskLabel(pct);
  const jobId = job.id ?? job.job_id ?? encodeURIComponent(`${job.company}-${job.title}`);

  const handleClick = () => {
    sessionStorage.setItem(`job_${jobId}`, JSON.stringify(job));
    router.push(`/jobs/${encodeURIComponent(jobId)}`);
  };

  return (
    <div className="group bg-zinc-900/50 border border-zinc-800 hover:border-teal-600/40 rounded-xl p-5 transition-colors cursor-pointer" onClick={handleClick}>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-zinc-100 group-hover:text-teal-300 transition-colors truncate">
            {job.title}
          </h3>
          <p className="text-xs text-zinc-500 mt-0.5">{job.company}</p>
        </div>
        <span className={`shrink-0 text-[10px] px-2 py-0.5 rounded-full border font-medium ${risk.color}`}>
          {risk.label}
        </span>
      </div>

      <div className="flex items-center gap-3 text-xs text-zinc-600 mb-3">
        <span>{job.location}</span>
        {job.salary && <><span>·</span><span>{job.salary}</span></>}
        {job.source && <><span>·</span><span className="capitalize">{job.source}</span></>}
      </div>

      {job.description && (
        <p className="text-xs text-zinc-500 line-clamp-2 mb-4">
          {job.description}
        </p>
      )}

      <div className="flex items-center justify-between">
        {pct != null && (
          <div className="flex items-center gap-2">
            <div className="w-20 h-1 bg-zinc-800 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${pct >= 70 ? "bg-red-500" : pct >= 40 ? "bg-yellow-500" : "bg-teal-500"}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="text-[10px] text-zinc-600">{pct}% AI exposure</span>
          </div>
        )}
        <span className="ml-auto text-xs text-teal-500 group-hover:underline">Analyse & Apply →</span>
      </div>
    </div>
  );
}
