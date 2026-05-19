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
  level?: string;
  posted_at?: string;
  created_at?: string;
}

function formatSalary(min?: number | null, max?: number | null): string | null {
  if (!min && !max) return null;
  const fmt = (n: number) => n >= 1000 ? `£${Math.round(n / 1000)}k` : `£${n}`;
  if (min && max) return `${fmt(min)} – ${fmt(max)}`;
  if (min) return `From ${fmt(min)}`;
  if (max) return `Up to ${fmt(max)}`;
  return null;
}

function levelBadge(level?: string): { label: string; cls: string } | null {
  if (!level) return null;
  switch (level.toLowerCase()) {
    case "junior": return { label: "Junior", cls: "text-teal-400 border-teal-400/30 bg-teal-400/10" };
    case "mid": return { label: "Mid-Level", cls: "text-blue-400 border-blue-400/30 bg-blue-400/10" };
    case "senior": return { label: "Senior", cls: "text-purple-400 border-purple-400/30 bg-purple-400/10" };
    default: return null;
  }
}

function timeAgo(dateStr?: string): string | null {
  if (!dateStr) return null;
  try {
    const diff = Date.now() - new Date(dateStr).getTime();
    const days = Math.floor(diff / 86400000);
    if (days === 0) return "Today";
    if (days === 1) return "1d ago";
    if (days < 7) return `${days}d ago`;
    if (days < 30) return `${Math.floor(days / 7)}w ago`;
    return `${Math.floor(days / 30)}mo ago`;
  } catch {
    return null;
  }
}

export default function JobCard({ job }: { job: Job }) {
  const router = useRouter();
  const jobId = job.id ?? job.job_id ?? encodeURIComponent(`${job.company}-${job.title}`);
  const salary = job.salary ?? formatSalary(job.salary_min, job.salary_max);
  const badge = levelBadge(job.level);
  const ago = timeAgo(job.created_at ?? job.posted_at);

  const handleClick = () => {
    sessionStorage.setItem(`job_${jobId}`, JSON.stringify(job));
    router.push(`/jobs/${encodeURIComponent(jobId)}`);
  };

  return (
    <div
      className="group bg-zinc-900/50 border border-zinc-800 hover:border-teal-600/40 rounded-xl p-5 transition-all duration-200 cursor-pointer hover:shadow-lg hover:shadow-teal-900/10"
      onClick={handleClick}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-zinc-100 group-hover:text-teal-300 transition-colors truncate">
            {job.title}
          </h3>
          <p className="text-xs text-zinc-500 mt-0.5">{job.company}</p>
        </div>
        {badge && (
          <span className={`shrink-0 text-[10px] px-2 py-0.5 rounded-full border font-medium ${badge.cls}`}>
            {badge.label}
          </span>
        )}
      </div>

      <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-xs text-zinc-600 mb-3">
        <span>{job.location}</span>
        {salary && <><span>·</span><span className="text-zinc-400">{salary}</span></>}
        {job.source && <><span>·</span><span className="capitalize">{job.source}</span></>}
        {ago && <><span>·</span><span>{ago}</span></>}
      </div>

      {job.description && (
        <p className="text-xs text-zinc-500 line-clamp-2 mb-4">{job.description}</p>
      )}

      <div className="flex items-center justify-end">
        <span className="text-xs text-teal-500 group-hover:underline">View & Apply →</span>
      </div>
    </div>
  );
}
