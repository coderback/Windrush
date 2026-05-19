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

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [page, setPage] = useState(1);

  // Input state (what the user is typing — does NOT trigger fetches)
  const [queryInput, setQueryInput] = useState("");
  const [locationInput, setLocationInput] = useState("");

  // Committed search state (only updated on form submit — triggers fetches)
  const [committedQuery, setCommittedQuery] = useState("");
  const [committedLocation, setCommittedLocation] = useState("");

  // Filter state (discrete selections — trigger fetches immediately)
  const [level, setLevel] = useState("");
  const [remote, setRemote] = useState(false);

  // Track whether user has actively searched
  const [activeSearch, setActiveSearch] = useState(false);

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
    [committedQuery, committedLocation, level, remote]
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
    // Commit the typed values — this triggers the fetch via useEffect
    setCommittedQuery(queryInput);
    setCommittedLocation(locationInput);
    setActiveSearch(true);
    setPage(1);
  };

  const clearSearch = () => {
    setQueryInput("");
    setLocationInput("");
    setCommittedQuery("");
    setCommittedLocation("");
    setLevel("");
    setRemote(false);
    setActiveSearch(false);
    setPage(1);
  };

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
          {activeSearch
            ? "Search results"
            : "Opportunities tailored to your profile"}
        </p>
      </div>

      {/* Search bar — only fires on submit, NOT on each keystroke */}
      <form onSubmit={handleSearch} className="flex gap-2 mb-4">
        <input
          value={queryInput}
          onChange={(e) => setQueryInput(e.target.value)}
          placeholder="Job title, company, or keywords"
          className="flex-1 bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-teal-500 transition-colors"
        />
        <input
          value={locationInput}
          onChange={(e) => setLocationInput(e.target.value)}
          placeholder="City or region"
          className="w-44 bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-teal-500 transition-colors"
        />
        <button
          type="submit"
          className="px-5 py-2.5 bg-white text-black text-sm font-bold rounded-lg hover:bg-zinc-200 transition-colors"
        >
          Search
        </button>
      </form>

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

        {/* Clear filters (only show when active) */}
        {activeSearch && (
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