"use client";

import { useEffect, useState, useCallback } from "react";
import { authFetch } from "../api";
import JobCard, { Job } from "@/components/JobCard";

const FILTER_CHIPS = [
  { label: "Remote", keyword: "remote" },
  { label: "Junior", keyword: "junior" },
  { label: "AI / ML", keyword: "ai" },
  { label: "SWE", keyword: "software engineer" },
  { label: "Finance", keyword: "finance" },
];

type SortKey = "fit" | "risk" | "recent";

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");
  const [activeFilters, setActiveFilters] = useState<string[]>([]);
  const [sort, setSort] = useState<SortKey>("fit");

  const fetchJobs = useCallback(async (q?: string, loc?: string) => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (q) params.set("query", q);
      if (loc) params.set("location", loc);
      const res = await authFetch(`/api/jobs?${params}`);
      if (!res.ok) throw new Error("Failed to load jobs");
      const data = await res.json() as { jobs?: Job[] } | Job[];
      setJobs(Array.isArray(data) ? data : (data as { jobs?: Job[] }).jobs ?? []);
    } catch (err: unknown) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    fetchJobs(query, location);
  };

  const toggleFilter = (keyword: string) => {
    setActiveFilters((prev) =>
      prev.includes(keyword) ? prev.filter((f) => f !== keyword) : [...prev, keyword]
    );
  };

  const filtered = jobs.filter((job) => {
    if (activeFilters.length === 0) return true;
    const text = `${job.title} ${job.description ?? ""} ${job.location}`.toLowerCase();
    return activeFilters.every((kw) => text.includes(kw));
  });

  const norm = (s?: number) => s == null ? 50 : s <= 1 ? s * 100 : s;
  const sorted = [...filtered].sort((a, b) => {
    if (sort === "fit") return norm(b.exposure_score) - norm(a.exposure_score);
    if (sort === "risk") return norm(a.exposure_score) - norm(b.exposure_score);
    return 0;
  });

  return (
    <div className="p-8 max-w-5xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-zinc-100" style={{ fontFamily: "Playfair Display, serif" }}>
          Job Feed
        </h1>
        <p className="text-zinc-500 text-sm mt-1">Browse opportunities matched to your profile</p>
      </div>

      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex gap-2 mb-5">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Job title or keywords"
          className="flex-1 bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-2.5 text-sm text-zinc-100 focus:outline-none focus:border-teal-500 transition-colors"
        />
        <input
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder="Location"
          className="w-44 bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-2.5 text-sm text-zinc-100 focus:outline-none focus:border-teal-500 transition-colors"
        />
        <button
          type="submit"
          className="px-5 py-2.5 bg-white text-black text-sm font-bold rounded-lg hover:bg-zinc-200 transition-colors"
        >
          Search
        </button>
      </form>

      {/* Filters + Sort */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div className="flex flex-wrap gap-2">
          {FILTER_CHIPS.map(({ label, keyword }) => (
            <button
              key={keyword}
              onClick={() => toggleFilter(keyword)}
              className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                activeFilters.includes(keyword)
                  ? "border-teal-500 bg-teal-500/10 text-teal-300"
                  : "border-zinc-800 text-zinc-500 hover:border-zinc-600"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <span>Sort:</span>
          {(["fit", "risk", "recent"] as SortKey[]).map((key) => (
            <button
              key={key}
              onClick={() => setSort(key)}
              className={`px-2 py-0.5 rounded transition-colors ${sort === key ? "text-teal-400" : "hover:text-zinc-300"}`}
            >
              {key === "fit" ? "Best Fit" : key === "risk" ? "Lowest Risk" : "Most Recent"}
            </button>
          ))}
        </div>
      </div>

      {/* Results */}
      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 text-red-400 text-sm rounded-lg">
          {error}
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-40 bg-zinc-900/50 border border-zinc-800 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : sorted.length === 0 ? (
        <div className="text-center py-16 text-zinc-600">
          <p className="text-sm">No jobs found. Try adjusting your search or filters.</p>
        </div>
      ) : (
        <>
          <p className="text-xs text-zinc-600 mb-4">{sorted.length} jobs found</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {sorted.map((job, i) => (
              <JobCard key={job.job_id ?? job.id ?? i} job={job} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}