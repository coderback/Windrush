"use client";

import Link from "next/link";
import { useState } from "react";
import Icon from "@/components/ui/Icon";
import { buttonClass, Callout, Chip, CompanyMark, cx, FactTile, FitRing, RiskBar, Spinner } from "@/components/ui/kit";
import { degreeLabel, experienceLabel, jobKey, jobSalary, levelLabel, longAgo, workSetting } from "@/lib/format";
import { fitVerdict } from "@/lib/status";
import { sponsorshipVerdict } from "@/lib/sponsorship";
import { cacheFit, cachedFit, jobHref, rememberJob } from "@/lib/jobs";
import { analyzeJob } from "@/lib/sse";
import { saveJob } from "@/lib/actions";
import type { Analysis, Job } from "@/lib/types";

/** The selected job beside the feed. Shows what is known for free (match, attributes,
    sponsorship, exposure); the LLM fit analysis only runs when asked ("Check my fit"). */
export default function JobPreview({ job, onDiscard, onOpen }: {
  job: Job;
  onDiscard: (job: Job) => Promise<void>;
  onOpen: () => void;
}) {
  const id = jobKey(job);
  const [analysis, setAnalysis] = useState<Analysis | null>(() => cachedFit(id));
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(job.tracker_status === "Saved");
  const [saving, setSaving] = useState(false);
  const [discarding, setDiscarding] = useState(false);

  const match = job.semantic_score != null ? Math.round(job.semantic_score * 100) : null;
  const setting = workSetting(job);
  const exp = experienceLabel(job.years_min);
  const level = levelLabel(job.level);
  const sponsor = sponsorshipVerdict(job);
  const posted = longAgo(job.created_at ?? job.posted_at);

  const checkFit = async () => {
    setChecking(true);
    setError(null);
    try {
      const a = await analyzeJob(job);
      cacheFit(id, a);
      setAnalysis(a);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The analysis failed.");
    } finally {
      setChecking(false);
    }
  };

  const save = async () => {
    if (saved || saving) return;
    setSaving(true);
    setError(null);
    try {
      await saveJob(job);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save this job.");
    } finally {
      setSaving(false);
    }
  };

  const discard = async () => {
    setDiscarding(true);
    setError(null);
    try {
      await onDiscard(job);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't hide this job.");
      setDiscarding(false);
    }
  };

  const fit = analysis?.fit_score;
  return (
    <aside aria-label="Selected role" className="bg-surface border border-border rounded-card overflow-hidden">
      <div className="px-5 pt-5 pb-4 flex flex-col gap-4">
        <div className="flex gap-[14px] items-start">
          <CompanyMark name={job.company} size={48} />
          <div className="flex-1 flex flex-col gap-1 min-w-0">
            <span className="text-[13px] text-ink-2">{job.company}</span>
            <h2 className="m-0 text-[19px] font-semibold tracking-[-0.015em] leading-[1.25]">{job.title}</h2>
            <span className="text-[13px] text-ink-3">{[job.location, posted && `posted ${posted}`].filter(Boolean).join(" · ")}</span>
          </div>
          <button type="button" onClick={save} disabled={saving} aria-pressed={saved}
            aria-label={saved ? "Saved to your applications" : "Save role"} title={saved ? "Saved" : "Save role"}
            className={cx("w-[38px] h-[38px] border rounded-control flex items-center justify-center shrink-0",
              saved ? "border-teal-line bg-teal-soft text-teal" : "border-border bg-surface text-ink-2 hover:text-ink")}>
            {saving ? <Spinner /> : (
              <svg width="17" height="17" viewBox="0 0 24 24" fill={saved ? "currentColor" : "none"} stroke="currentColor"
                strokeWidth="1.8" strokeLinejoin="round" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4z" /></svg>
            )}
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <FactTile tint="mint" label="Salary" value={jobSalary(job) ?? "Not listed"} />
          <FactTile tint="sky" label="Setting" value={setting ?? "Not stated"} />
          <FactTile tint="peach" label="Experience asked" value={exp ?? "Not stated"} />
          <FactTile tint="lilac" label="Degree" value={degreeLabel(job.degree)} />
        </div>
      </div>

      <div className="px-5 py-4 flex flex-col gap-4 border-t border-divider">
        {fit != null ? (
          <div className="flex gap-[14px] items-center">
            <FitRing value={fit} size={64} label="Fit" />
            <div className="flex flex-col gap-[5px] min-w-0">
              <span className="text-[15px] font-semibold">{fitVerdict(fit)}</span>
              {analysis?.reasoning && <span className="text-[13px] leading-[1.5] text-ink-2 text-pretty">{analysis.reasoning}</span>}
            </div>
          </div>
        ) : (
          <div className="flex gap-[14px] items-center">
            {match != null && <FitRing value={match} size={64} label="Match" />}
            <div className="flex flex-col gap-[6px] min-w-0">
              <span className="text-[15px] font-semibold">{match != null ? fitVerdict(match) : "Not ranked yet"}</span>
              <span className="text-[13px] leading-[1.5] text-ink-2 text-pretty">
                How closely the ad reads like your persona{level ? `, for a ${level.toLowerCase()} role` : ""}. Check your fit to see matched skills and gaps.
              </span>
              <button type="button" onClick={checkFit} disabled={checking} className={cx(buttonClass("secondary", "sm"), "self-start")}>
                {checking ? <><Spinner /> Checking your fit…</> : <><Icon name="sparkle" size={14} /> Check my fit</>}
              </button>
            </div>
          </div>
        )}
        {error && <Callout>{error}</Callout>}
        {analysis && (analysis.matched_skills?.length ?? 0) > 0 && (
          <div className="flex flex-col gap-2">
            <span className="text-[13px] font-semibold">You already have</span>
            <span className="flex flex-wrap gap-[6px]">
              {analysis.matched_skills!.map((s) => <Chip key={s} tone="matched" size="lg" className="font-normal">{s}</Chip>)}
            </span>
          </div>
        )}
        {analysis && (analysis.skill_gaps?.length ?? 0) > 0 && (
          <div className="flex flex-col gap-2">
            <span className="text-[13px] font-semibold">Gaps to address</span>
            <span className="flex flex-wrap gap-[6px]">
              {analysis.skill_gaps!.map((s) => <Chip key={s} tone="gap" size="lg" className="font-normal">{s}</Chip>)}
            </span>
          </div>
        )}
        <div className="flex flex-col gap-[6px] px-[14px] py-3 rounded-inner bg-subtle border border-divider">
          <span className="text-[13px] font-semibold">Visa sponsorship: {sponsor.verdict.toLowerCase()}</span>
          <span className="text-[13px] leading-[1.5] text-ink-2">{sponsor.why}</span>
        </div>
        {job.exposure_score != null && (
          <RiskBar label="AI exposure of this role" score={Math.round(job.exposure_score <= 1 ? job.exposure_score * 100 : job.exposure_score)} />
        )}
      </div>

      <div className="flex flex-wrap gap-2 px-5 py-[14px] border-t border-divider bg-subtle">
        <Link href={jobHref(id)} onClick={() => { rememberJob(job); onOpen(); }} className={cx(buttonClass("primary", "lg"), "flex-[1_1_180px]")}>
          Start application
          <Icon name="arrowRight" size={15} strokeWidth={2} />
        </Link>
        <Link href={jobHref(id)} onClick={() => { rememberJob(job); onOpen(); }} className={buttonClass("secondary", "lg", "px-[14px]")}>Full details</Link>
        <button type="button" onClick={discard} disabled={discarding} className={buttonClass("quiet", "lg", "px-3 font-normal")}>
          {discarding ? <><Spinner /> Hiding…</> : "Not for me"}
        </button>
      </div>
    </aside>
  );
}
