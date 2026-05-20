"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { authFetch } from "../api";
import JobCard, { Job } from "@/components/JobCard";

const LEVEL_OPTIONS = [
  { label: "All Levels", value: "" },
  { label: "Junior / Graduate", value: "junior" },
  { label: "Mid-Level", value: "mid" },
  { label: "Senior+", value: "senior" },
];

const ROLE_TAGS = {
  roles: ["software", "ml", "ai", "data", "backend", "frontend", "fullstack", "devops", "security", "analyst", "engineer", "developer"],
  domains: ["fintech", "startup", "sponsorship", "remote"]
};

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [page, setPage] = useState(1);

  // Input state
  const [queryInput, setQueryInput] = useState("");
  const [locationInput, setLocationInput] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);

  // Search state
  const [committedQuery, setCommittedQuery] = useState("");
  const [committedLocation, setCommittedLocation] = useState("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);

  // Filter state
  const [level, setLevel] = useState("");
  const [remote, setRemote] = useState(false);

  const observerRef = useRef<HTMLDivElement | null>(null);

  const fetchJobs = useCallback(
    async (pageNum: number, append = false) => {
      if (pageNum === 1) {
        setLoading(true);
      } else {
        setLoadingMore(true);
      }
      setError(null);

      try {
        const params = new URLSearchParams();
        if (committedQuery) params.set("query", committedQuery);
        if (selectedTags.length > 0) params.set("tags", selectedTags.join(","));
        if (committedLocation) params.set("location", committedLocation);
        if (level) params.set("level", level);
        if (remote) params.set("remote", "true");
        params.set("page", String(pageNum));
        params.set("limit", "20");

        const res = await authFetch(`/api/jobs?${params}`);
        if (!res.ok) throw new Error("Failed to load jobs");
        const data = await res.json();
        const incoming: Job[] = data.jobs ?? [];
        setHasMore(data.has_more ?? incoming.length === 20);

        if (append) {
          setJobs((prev) => [...prev, ...incoming]);
        } else {
          setJobs(incoming);
        }
      } catch (err: unknown) {
        setError(String(err));
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [committedQuery, selectedTags, committedLocation, level, remote]
  );

  // Fetch when committed search params or filters change
  useEffect(() => {
    setPage(1);
    fetchJobs(1);
  }, [fetchJobs]);

  // Infinite scroll observer
  useEffect(() => {
    if (!hasMore || loading || loadingMore) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loadingMore) {
          const nextPage = page + 1;
          setPage(nextPage);
          fetchJobs(nextPage, true);
        }
      },
      { threshold: 0.1 }
    );

    const el = observerRef.current;
    if (el) observer.observe(el);
    return () => {
      if (el) observer.unobserve(el);
    };
  }, [hasMore, loading, loadingMore, page, fetchJobs]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const val = queryInput.trim().toLowerCase();
    if (val) {
      addTag(val);
      setQueryInput("");
    }
    setCommittedLocation(locationInput);
    setPage(1);
  };

  const addTag = (tag: string) => {
    if (!selectedTags.includes(tag)) {
      setSelectedTags(prev => [...prev, tag]);
    }
  };

  const removeTag = (tag: string) => {
    setSelectedTags(prev => prev.filter(t => t !== tag));
  };

  const clearSearch = () => {
    setQueryInput("");
    setLocationInput("");
    setCommittedLocation("");
    setCommittedQuery("");
    setLevel("");
    setRemote(false);
    setSelectedTags([]);
    setPage(1);
  };

  const allAvailableTags = [...ROLE_TAGS.roles, ...ROLE_TAGS.domains];

  return (
    <div className="p-8 max-w-5xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <h1
          className="text-2xl font-bold text-zinc-100"
          style={{ fontFamily: "Playfair Display, serif" }}
        >
          Job Feed
        </h1>
        <p className="text-zinc-500 text-sm mt-1">
          {committedQuery || selectedTags.length > 0 || committedLocation || level
            ? "Precision search results"
            : "AI-ranked opportunities for your profile"}
        </p>
      </div>

      {/* Tokenized Search Bar */}
      <div className="relative mb-4">
        <form onSubmit={handleSearch} className="flex gap-2">
          <div className="flex-1 flex flex-wrap items-center gap-2 bg-zinc-900 border border-zinc-800 rounded-lg px-3 min-h-[44px] focus-within:border-teal-500 transition-colors">
            {selectedTags.map(tag => (
              <span key={tag} className={`flex items-center gap-1 text-[10px] font-bold px-2 py-1 rounded border uppercase tracking-wider ${
                ROLE_TAGS.roles.includes(tag) ? 'bg-teal-500/10 border-teal-500/30 text-teal-400' :
                'bg-purple-500/10 border-purple-500/30 text-purple-400'
              }`}>
                {tag}
                <button type="button" onClick={() => removeTag(tag)} className="hover:text-white ml-0.5">✕</button>
              </span>
            ))}
            <input
              value={queryInput}
              onFocus={() => setShowSuggestions(true)}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
              onChange={(e) => setQueryInput(e.target.value)}
              placeholder={selectedTags.length === 0 ? "Add roles (e.g. Software, ML, AI)..." : ""}
              className="flex-1 min-w-[120px] bg-transparent border-none outline-none py-2 text-sm text-zinc-100 placeholder:text-zinc-600"
            />
          </div>
          <input
            value={locationInput}
            onChange={(e) => setLocationInput(e.target.value)}
            placeholder="City or region"
            className="w-44 bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-teal-500 transition-colors"
          />
          <button
            type="submit"
            className="px-5 py-2.5 bg-white text-black text-sm font-bold rounded-lg hover:bg-zinc-200 transition-colors shrink-0"
          >
            Search
          </button>
        </form>

        {/* Tag Suggestions */}
        {showSuggestions && queryInput.length > 0 && (
          <div className="absolute z-10 left-0 right-0 mt-2 bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl p-2 flex flex-wrap gap-2">
            {allAvailableTags.filter(t => t.includes(queryInput.toLowerCase()) && !selectedTags.includes(t)).map(tag => (
              <button
                key={tag}
                onClick={() => { addTag(tag); setQueryInput(""); setShowSuggestions(false); }}
                className="text-[10px] px-2 py-1 rounded border border-zinc-700 bg-zinc-800 text-zinc-300 hover:border-teal-500 hover:text-teal-400 uppercase tracking-wider"
              >
                +{tag}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Filters row */}
      <div className="flex flex-wrap items-center gap-3 mb-6">
        {/* Level filter */}
        <select
          value={level}
          onChange={(e) => {
            setLevel(e.target.value);
            setPage(1);
          }}
          className="bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-1.5 text-xs text-zinc-300 focus:outline-none focus:border-teal-500 transition-colors cursor-pointer"
        >
          {LEVEL_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        {/* Remote toggle */}
        <button
          onClick={() => {
            setRemote(!remote);
            setPage(1);
          }}
          className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
            remote
              ? "border-teal-500 bg-teal-500/10 text-teal-300"
              : "border-zinc-800 text-zinc-500 hover:border-zinc-600"
          }`}
        >
          🌍 Remote
        </button>

        {/* Role Suggestion Quick-Chips (Only show when input is empty) */}
        {!queryInput && (
          <div className="flex flex-wrap gap-2 items-center">
            <span className="text-[10px] text-zinc-600 uppercase tracking-widest font-bold ml-2">Quick Add:</span>
            {allAvailableTags.slice(0, 8).filter(t => !selectedTags.includes(t)).map(tag => (
              <button
                key={tag}
                onClick={() => addTag(tag)}
                className="text-[9px] px-2 py-0.5 rounded border border-zinc-800 bg-zinc-950 text-zinc-500 hover:border-zinc-600 transition-colors uppercase tracking-tight"
              >
                {tag}
              </button>
            ))}
          </div>
        )}

        {/* Clear filters (only show when active) */}
        {(committedQuery || selectedTags.length > 0 || level || remote || committedLocation) && (
          <button
            onClick={clearSearch}
            className="text-xs px-3 py-1.5 rounded-lg border border-zinc-800 text-zinc-500 hover:text-zinc-300 hover:border-zinc-600 transition-colors ml-auto"
          >
            ✕ Clear filters
          </button>
        )}
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
            <div
              key={i}
              className="h-40 bg-zinc-900/50 border border-zinc-800 rounded-xl animate-pulse"
            />
          ))}
        </div>
      ) : jobs.length === 0 ? (
        <div className="text-center py-16 text-zinc-600">
          <p className="text-sm">
            No jobs found. Try adjusting your search or filters.
          </p>
        </div>
      ) : (
        <>
          <p className="text-xs text-zinc-600 mb-4">
            {jobs.length} job{jobs.length !== 1 ? "s" : ""}
            {hasMore ? "+" : ""}
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {jobs.map((job, i) => (
              <JobCard key={job.id ?? job.job_id ?? i} job={job} />
            ))}
          </div>

          {/* Infinite scroll sentinel */}
          {hasMore && (
            <div ref={observerRef} className="flex justify-center py-8">
              {loadingMore && (
                <div className="flex items-center gap-2 text-xs text-zinc-500">
                  <div className="w-4 h-4 border-2 border-zinc-700 border-t-teal-500 rounded-full animate-spin" />
                  Loading more…
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
