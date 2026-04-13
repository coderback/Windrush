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
  level_match?: string;
  skill_gaps?: string[];
}

interface Props {
  jobs: Job[];
  onSelect: (job: Job) => void;
  selectedId?: string;
}

const levelDot: Record<string, string> = {
  strong: "bg-teal-400",
  ok: "bg-amber-400",
  reach: "bg-red-400",
};

const levelLabel: Record<string, string> = {
  strong: "Good fit",
  ok: "Stretch",
  reach: "Reach",
};

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
          const level = job.level_match ?? "ok";
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
                <div className="flex items-center gap-1.5 shrink-0">
                  {/* Level indicator dot */}
                  <span
                    title={levelLabel[level]}
                    className={`w-2 h-2 rounded-full ${levelDot[level] ?? "bg-zinc-500"}`}
                  />
                  {/* Composite score badge */}
                  <div
                    className={`text-xs font-bold px-2 py-0.5 rounded ${
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
              </div>

              <p className="text-xs text-zinc-500 mt-1.5 line-clamp-2">
                {job.description}
              </p>

              {/* Skill gaps — only show when selected */}
              {isSelected && job.skill_gaps && job.skill_gaps.length > 0 && (
                <div className="mt-2 pt-2 border-t border-zinc-800">
                  <span className="text-xs text-zinc-500 mr-1.5">Skill gaps:</span>
                  <span className="inline-flex flex-wrap gap-1">
                    {job.skill_gaps.map((gap) => (
                      <span
                        key={gap}
                        className="text-xs px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700"
                      >
                        {gap}
                      </span>
                    ))}
                  </span>
                </div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
