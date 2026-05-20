"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { authFetch } from "@/app/api";

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
  semantic_score?: number;
  tags?: string | string[];
  source?: string;
  level?: string;
  posted_at?: string;
  created_at?: string;
  tracker_status?: string;
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
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(job.tracker_status === "Saved");

  const jobId = job.id ?? job.job_id ?? encodeURIComponent(`${job.company}-${job.title}`);
  const salary = job.salary ?? formatSalary(job.salary_min, job.salary_max);
  const badge = levelBadge(job.level);
  const ago = timeAgo(job.created_at ?? job.posted_at);

  // Parse tags if they are a JSON string
  const tags: string[] = typeof job.tags === 'string' ? JSON.parse(job.tags) : (job.tags || []);
  const matchScore = job.semantic_score ? Math.round(job.semantic_score * 100) : null;

  const handleClick = () => {
    sessionStorage.setItem(`job_${jobId}`, JSON.stringify(job));
    router.push(`/jobs/${encodeURIComponent(jobId)}`);
  };

  const handleSave = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (saved || saving) return;
    setSaving(true);
    try {
      const res = await authFetch("/api/jobs/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job }),
      });
      if (res.ok) setSaved(true);
    } catch (err) {
      console.error("Failed to save job:", err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="group bg-zinc-900/50 border border-zinc-800 hover:border-teal-600/40 rounded-xl p-5 transition-all duration-200 cursor-pointer hover:shadow-lg hover:shadow-teal-900/10 relative"
      onClick={handleClick}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-sm font-semibold text-zinc-100 group-hover:text-teal-300 transition-colors truncate">
              {job.title}
            </h3>
            {job.tracker_status === "Saved" && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-400 border border-purple-500/30 font-bold uppercase tracking-tight shrink-0">
                Already Bookmarked
              </span>
            )}
          </div>
          <p className="text-xs text-zinc-500">{job.company}</p>
        </div>
        <div className="flex flex-col items-end gap-1.5 shrink-0">
          {badge && (
            <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${badge.cls}`}>
              {badge.label}
            </span>
          )}
          {matchScore !== null && (
             <div className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
               matchScore >= 70 ? 'border-teal-500/30 text-teal-400 bg-teal-500/10' : 
               matchScore >= 50 ? 'border-amber-500/30 text-amber-400 bg-amber-500/10' :
               'border-zinc-700 text-zinc-400 bg-zinc-800'
             }`}>
               {matchScore}% Match
             </div>
          )}
        </div>
      </div>

      <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-xs text-zinc-600 mb-3">
        <span>{job.location}</span>
        {salary && <><span>·</span><span className="text-zinc-400">{salary}</span></>}
        {job.source && <><span>·</span><span className="capitalize">{job.source}</span></>}
        {ago && <><span>·</span><span>{ago}</span></>}
      </div>

      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {tags.map(tag => (
            <span key={tag} className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700 uppercase tracking-wider">
              #{tag}
            </span>
          ))}
        </div>
      )}

      {job.description && (
        <p className="text-xs text-zinc-500 line-clamp-2 mb-4">{job.description}</p>
      )}

      <div className="flex items-center justify-between mt-auto">
        <button
          onClick={handleSave}
          disabled={saved || saving}
          className={`text-[10px] uppercase tracking-widest font-bold transition-colors ${
            saved ? 'text-zinc-500 cursor-default' : 'text-zinc-400 hover:text-teal-400'
          }`}
        >
          {saving ? "Saving..." : saved ? "✓ Saved" : "Save for Later"}
        </button>
        <div className="text-[10px] uppercase tracking-widest font-bold">
          <span className="text-teal-500 group-hover:underline">View & Apply →</span>
        </div>
      </div>
    </div>
  );
}
