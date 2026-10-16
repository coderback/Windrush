"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { authFetch } from "../api";
import Icon from "@/components/ui/Icon";
import TopBar, { Page } from "@/components/ui/TopBar";
import { buttonClass, Callout, cx, EmptyState, Skeleton, Spinner } from "@/components/ui/kit";
import SearchBand, { SALARY_MAX, SALARY_MIN } from "@/components/feed/SearchBand";
import FeedFilters, { type FeedFilterState } from "@/components/feed/FeedFilters";
import JobRow from "@/components/feed/JobRow";
import JobPreview from "@/components/feed/JobPreview";
import { parseCommaList } from "@/components/CommaListInput";
import { jobKey, workSetting } from "@/lib/format";
import { jobHref, rememberFeed, rememberJob } from "@/lib/jobs";
import { discardJob } from "@/lib/actions";
import { useResource } from "@/lib/store";
import type { Job, Persona } from "@/lib/types";

const PAGE_SIZE = 20;
const WIDE = "(min-width: 1000px)";

const NO_FILTERS: FeedFilterState = { sponsorship: "", remote: false, hybrid: false, level: "", noDegree: false, noClearance: false };

/** Paste any job link: POST /jobs/from-url, then open that job. Lives in the top bar. */
function PasteLink({ focus }: { focus: boolean }) {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { if (focus) input.current?.focus(); }, [focus]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const link = url.trim();
    if (!link) return;
    if (!/^https?:\/\//i.test(link)) {
      setError("Paste a full link starting with http:// or https://");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await authFetch("/api/jobs/from-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: link }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || "Couldn't read that listing");
      const job: Job = data.job;
      if (!(job.id ?? job.job_id)) throw new Error("The listing came back without an id");
      router.push(jobHref(rememberJob(job)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't read that listing. Try a direct job-posting link.");
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-1 flex-[0_1_420px] min-w-0 w-full sm:w-auto">
      <div className="flex items-center gap-2 min-w-0">
        <label htmlFor="joblink" className="sr-only">Paste a job link</label>
        <span className="flex-1 min-w-0 flex items-center gap-2 h-[38px] px-3 border border-border rounded-control bg-subtle text-ink-3 focus-within:border-teal">
          <Icon name="link" size={16} />
          <input id="joblink" ref={input} type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)}
            placeholder="Paste any job link to analyse it"
            className="flex-1 min-w-0 border-0 bg-transparent text-[13.5px] text-ink outline-none placeholder:text-ink-3" />
        </span>
        <button type="submit" disabled={busy} className={buttonClass("secondary", "top")}>
          {busy ? <><Spinner /> Reading…</> : "Analyse"}
        </button>
      </div>
      {error && <p role="alert" className="m-0 text-[12.5px] text-red">{error}</p>}
    </form>
  );
}

function FeedPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [page, setPage] = useState(1);

  // Search band: typed values, and what was last searched.
  const [roleInput, setRoleInput] = useState("");
  const [locationInput, setLocationInput] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [location, setLocation] = useState("");
  // Experience asked for, as read from each ad; ads that don't say are always shown.
  const [maxYears, setMaxYears] = useState("");
  // Filtered on the loaded page (the API takes no salary range yet); jobs with no salary are kept.
  const [salary, setSalary] = useState<[number, number]>([SALARY_MIN, SALARY_MAX]);
  // "" for sponsorship lets the server choose: "possible" when the profile needs sponsorship, else "any".
  const [filters, setFilters] = useState<FeedFilterState>(NO_FILTERS);
  const [sponsorshipApplied, setSponsorshipApplied] = useState("any");
  const [showFilters, setShowFilters] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const persona = useResource<Persona>("/api/persona");
  const hasTitles = (persona.data?.preferences.target_titles?.length ?? 0) > 0;

  // Live discovery runs server-side in the background when the feed is thin; while it does,
  // re-poll page 1 quietly so new matches appear without a manual refresh.
  const [discovering, setDiscovering] = useState(false);
  const discoveryPolls = useRef(0);
  const observerRef = useRef<HTMLDivElement | null>(null);

  // Remote alone is an API filter; with Hybrid as well both are matched on the page instead.
  const remoteParam = filters.remote && !filters.hybrid;

  const fetchJobs = useCallback(
    async (pageNum: number, append = false, silent = false) => {
      if (pageNum === 1) {
        if (!silent) setLoading(true);
      } else {
        setLoadingMore(true);
      }
      setError(null);
      try {
        const q = new URLSearchParams();
        if (tags.length > 0) q.set("tags", tags.join(","));
        if (location) q.set("location", location);
        if (filters.level) q.set("level", filters.level);
        if (remoteParam) q.set("remote", "true");
        if (filters.sponsorship) q.set("sponsorship", filters.sponsorship);
        if (maxYears) q.set("max_years", maxYears);
        if (filters.noDegree) q.set("no_degree", "true");
        q.set("page", String(pageNum));
        q.set("limit", String(PAGE_SIZE));

        const res = await authFetch(`/api/jobs?${q}`);
        if (!res.ok) throw new Error("Couldn't load jobs. Try again in a moment.");
        const data = await res.json();
        const incoming: Job[] = data.jobs ?? [];
        setHasMore(data.has_more ?? incoming.length === PAGE_SIZE);
        if (pageNum === 1) {
          setDiscovering(!!data.discovering);
          setSponsorshipApplied(data.sponsorship ?? "any");
        }
        setJobs((prev) => (append ? [...prev, ...incoming] : incoming));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [tags, location, filters.level, remoteParam, filters.sponsorship, maxYears, filters.noDegree],
  );

  // Fetch when the search or a server-side filter changes.
  useEffect(() => {
    setPage(1);
    discoveryPolls.current = 0;
    fetchJobs(1);
  }, [fetchJobs]);

  // While discovery is running, refresh page 1: every 15s for the first 2 minutes, then every 60s,
  // since a run queued behind others can finish minutes later. After 20 polls (~14 min, past the
  // background embedding budget) give up and drop the indicator rather than leave it up for good.
  // Skipped once the user has scrolled past page 1 so a refresh can't wipe the pages they've loaded.
  useEffect(() => {
    if (!discovering || page !== 1) return;
    if (discoveryPolls.current >= 20) {
      setDiscovering(false);
      return;
    }
    const t = setTimeout(() => {
      discoveryPolls.current += 1;
      fetchJobs(1, false, true);
    }, discoveryPolls.current < 8 ? 15000 : 60000);
    return () => clearTimeout(t);
  }, [discovering, page, jobs, fetchJobs]);

  // Infinite scroll.
  useEffect(() => {
    if (!hasMore || loading || loadingMore) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loadingMore) {
          const next = page + 1;
          setPage(next);
          fetchJobs(next, true);
        }
      },
      { threshold: 0.1 },
    );
    const el = observerRef.current;
    if (el) observer.observe(el);
    return () => { if (el) observer.unobserve(el); };
  }, [hasMore, loading, loadingMore, page, fetchJobs]);

  // Filters the API can't apply yet, matched on the loaded jobs.
  const visible = useMemo(() => jobs.filter((j) => {
    const [lo, hi] = salary;
    if (lo > SALARY_MIN || hi < SALARY_MAX) {
      const min = j.salary_min || j.salary_max || 0, max = j.salary_max || j.salary_min || 0;
      if (min || max) {
        if (max < lo) return false;
        if (hi < SALARY_MAX && min > hi) return false;
      }
    }
    if (filters.noClearance && j.clearance) return false;
    if (filters.hybrid) {
      const s = workSetting(j);
      if (!(s === "Hybrid" || (filters.remote && s === "Remote"))) return false;
    }
    return true;
  }), [jobs, salary, filters.noClearance, filters.hybrid, filters.remote]);

  const current = visible.find((j) => jobKey(j) === selected) ?? visible[0] ?? null;

  const search = () => {
    setTags(parseCommaList(roleInput.toLowerCase()));
    setLocation(locationInput.trim());
  };

  const clearAll = () => {
    setRoleInput("");
    setLocationInput("");
    setTags([]);
    setLocation("");
    setMaxYears("");
    setSalary([SALARY_MIN, SALARY_MAX]);
    setFilters(NO_FILTERS);
  };

  const filterState = { ...filters, sponsorship: filters.sponsorship || sponsorshipApplied };
  const activeCount = [tags.length > 0, !!location, !!maxYears, salary[0] > SALARY_MIN || salary[1] < SALARY_MAX,
    !!filters.sponsorship, filters.remote, filters.hybrid, !!filters.level, filters.noDegree, filters.noClearance].filter(Boolean).length;

  const select = (job: Job) => {
    const id = jobKey(job);
    // Narrow screens have no preview pane: a card opens the job itself.
    if (!window.matchMedia(WIDE).matches) {
      rememberFeed(visible);
      router.push(jobHref(id));
      return;
    }
    setSelected(id);
  };

  const notForMe = async (job: Job) => {
    await discardJob(job);
    setJobs((prev) => prev.filter((j) => jobKey(j) !== jobKey(job)));
  };

  const filtersPanel = (
    <FeedFilters value={filterState} onChange={(patch) => setFilters((f) => ({ ...f, ...patch }))} onClear={clearAll} />
  );

  return (
    <>
      <TopBar crumbs={[{ label: "Workspace" }, { label: "Job feed" }]}>
        <PasteLink focus={params.get("paste") === "1"} />
      </TopBar>
      <Page wide="feed" className="gap-[18px] pt-[22px] sm:pt-[22px] pb-12">
        <SearchBand role={roleInput} onRole={setRoleInput} location={locationInput} onLocation={setLocationInput}
          maxYears={maxYears} onMaxYears={setMaxYears} salary={salary} onSalary={setSalary} onSubmit={search} />

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-[10px]">
            <h1 className="m-0 text-[22px] font-semibold tracking-[-0.02em]">Roles for you</h1>
            {!loading && (
              <span className="font-mono text-[12px] font-semibold px-[10px] py-[3px] rounded-full border border-border bg-surface">
                {visible.length}{hasMore ? "+" : ""}<span className="sr-only"> {visible.length === 1 ? "job" : "jobs"}</span>
              </span>
            )}
            <span className="text-[13px] text-ink-3">
              ranked by match to your persona{discovering ? " · searching job boards now" : ""}
            </span>
          </div>
          <button type="button" onClick={() => setShowFilters((s) => !s)} aria-expanded={showFilters} aria-controls="feed-filters-narrow"
            className={cx(buttonClass("secondary", "sm"), "min-[1200px]:hidden")}>
            <Icon name="filter" size={15} />
            Filters{activeCount > 0 ? ` (${activeCount})` : ""}
          </button>
        </div>

        {showFilters && <div id="feed-filters-narrow" className="min-[1200px]:hidden">{filtersPanel}</div>}

        <div className="grid gap-4 items-start grid-cols-1 min-[1000px]:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] min-[1200px]:grid-cols-[230px_minmax(0,1fr)_minmax(0,1.2fr)]">
          <div className="hidden min-[1200px]:block">{filtersPanel}</div>

          <section aria-label="Roles" className="min-w-0 flex flex-col gap-2">
            {error && <Callout title="The feed didn't load" action={
              <button type="button" onClick={() => fetchJobs(1)} className={cx(buttonClass("secondary", "xs"), "self-start mt-1")}>Try again</button>
            }>{error}</Callout>}
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-[150px] rounded-[14px]" />)
            ) : visible.length === 0 && !discovering ? (
              <EmptyState action={activeCount > 0 ? (
                <button type="button" onClick={clearAll} className={buttonClass("secondary", "sm")}>Clear filters</button>
              ) : !hasTitles && persona.data ? (
                <Link href="/profile#prefs" className={buttonClass("secondary", "sm")}>Add target titles</Link>
              ) : undefined}>
                {activeCount > 0 ? "No roles match these filters."
                  : hasTitles ? "No roles here yet. Discovery looks again each time the feed runs low."
                  : "No roles yet. Add target job titles to your persona so discovery knows what to look for."}
              </EmptyState>
            ) : (
              visible.map((job) => (
                <JobRow key={jobKey(job)} job={job} selected={current != null && jobKey(job) === jobKey(current)} onSelect={() => select(job)} />
              ))
            )}

            {discovering && !loading && (
              <div role="status" className="flex flex-col gap-[10px] p-4 border border-dashed border-border-strong rounded-[14px] bg-subtle">
                <span className="text-[13px] text-ink-2">
                  Searching Greenhouse, Lever, Ashby and company boards for more roles. New matches slot in as they are found.
                </span>
                <span className="block h-1 rounded-full bg-border overflow-hidden" aria-hidden="true">
                  <span className="indeterminate block w-[40%] h-full bg-teal rounded-full" />
                </span>
              </div>
            )}

            {hasMore && !loading && (
              <div ref={observerRef} className="flex justify-center py-6">
                {loadingMore && (
                  <span className="flex items-center gap-2 text-[12.5px] text-ink-3"><Spinner /> Loading more…</span>
                )}
              </div>
            )}
          </section>

          <div className="hidden min-[1000px]:block min-w-0 sticky top-4 max-h-[calc(100vh-2rem)] overflow-y-auto rounded-card">
            {loading ? <Skeleton className="h-[560px] rounded-card" /> : current ? (
              <JobPreview key={jobKey(current)} job={current} onDiscard={notForMe} onOpen={() => rememberFeed(visible)} />
            ) : null}
          </div>
        </div>
      </Page>
    </>
  );
}

export default function JobsPage() {
  return (
    <Suspense>
      <FeedPage />
    </Suspense>
  );
}
