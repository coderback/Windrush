"use client";

export interface Job {
  job_id: string;
  title: string;
  company: string;
  location: string;
  description: string;
  url: string;
  fit_score: number;
  exposure_score: number;
  composite_score: number;
}

interface Props {
  jobs: Job[];
  onSelect: (job: Job) => void;
  selectedId?: string;
}

export default function JobList({ jobs, onSelect, selectedId }: Props) {
  if (jobs.length === 0) return null;

  return (
    <div>
      <h3 className="text-xs uppercase tracking-widest text-zinc-500 mb-3">
        Matched Roles
      </h3>
      <div className="space-y-2">
        {jobs.map((job) => {
          const score = Math.round(job.composite_score * 100);
          const isSelected = job.job_id === selectedId;
          return (
            <button
              key={job.job_id}
              onClick={() => onSelect(job)}
              className={`w-full text-left p-3 rounded border transition-colors ${
                isSelected
                  ? "border-teal-500 bg-teal-500/10"
                  : "border-zinc-800 hover:border-zinc-600 bg-zinc-900/50"
              }`}
            >
              <div className="flex justify-between items-start gap-2">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-zinc-100 truncate">
                    {job.title}
                  </div>
                  <div className="text-xs text-zinc-400 mt-0.5">
                    {job.company} · {job.location}
                  </div>
                </div>
                <div
                  className={`shrink-0 text-xs font-bold px-2 py-0.5 rounded ${
                    score >= 60
                      ? "bg-teal-500/20 text-teal-400"
                      : score >= 40
                      ? "bg-amber-500/20 text-amber-400"
                      : "bg-zinc-700 text-zinc-400"
                  }`}
                >
                  {score}
                </div>
              </div>
              <p className="text-xs text-zinc-500 mt-1.5 line-clamp-2">
                {job.description}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
