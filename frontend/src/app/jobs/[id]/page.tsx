"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { authFetch } from "@/app/api";
import BrowserView, { BrowserFrame, sendInstruction } from "@/components/BrowserView";
import SponsorshipPanel, { useSponsorship, VERDICT_TONE, viewVerdict } from "@/components/SponsorshipPanel";
import DocEditor, { CVDoc, LetterDoc, letterToText } from "@/components/DocEditor";
import ReviewLayout, { AgentNotes, type LogLine } from "@/components/ReviewLayout";
import JobDescription from "@/components/JobDescription";
import DocChecks from "@/components/DocChecks";
import FormQuestions from "@/components/FormQuestions";
import Icon from "@/components/ui/Icon";
import TopBar, { Page } from "@/components/ui/TopBar";
import StepTracker from "@/components/ui/StepTracker";
import { UnderlineTabs, TabPanel } from "@/components/ui/Tabs";
import {
  Bar, buttonClass, Callout, Card, Chip, CompanyMark, cx, EmptyState, FactTile, FitRing, Skeleton, Spinner,
} from "@/components/ui/kit";
import { degreeLabel, experienceLabel, jobSalary, levelLabel, longAgo, workSetting } from "@/lib/format";
import { cacheFit, cachedFit, feedNeighbours, jobHref, recallJob } from "@/lib/jobs";
import { analyzeJob, postStream, readStream } from "@/lib/sse";
import { discardJob, saveJob, trackedApplication } from "@/lib/actions";
import { load, useResource } from "@/lib/store";
import { fitVerdict, riskLevel, RISK } from "@/lib/status";
import { sponsorshipVerdict } from "@/lib/sponsorship";
import type { Analysis, Application, FormAnswer, Job } from "@/lib/types";

type CvChoice = "tailored" | "original";

const STEPS = [
  { key: "analyse", title: "Fit analysis" },
  { key: "cv", title: "Tailored CV" },
  { key: "letter", title: "Cover letter" },
  { key: "apply", title: "Agent fills form" },
  { key: "review", title: "You review & submit" },
];

async function downloadPdf(docId: string, filename: string) {
  const token = localStorage.getItem("windrush_token");
  const res = await fetch(`/api/documents/${docId}/download`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) return;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** The issues a kept critique rewrite fixed, from the generation event's `review`. */
function keptIssues(review: unknown): string[] {
  const r = review as { issues?: unknown; kept?: unknown } | undefined;
  return r?.kept === true && Array.isArray(r.issues) ? r.issues.filter((i): i is string => typeof i === "string") : [];
}

const LEVEL_MATCH: Record<string, string> = { strong: "strong", ok: "reasonable", reach: "a stretch" };

const EXPOSURE_NOTE = {
  Low: "Most of this role's work is hard to automate.",
  Medium: "Routine parts of this role are automatable; judgement and ownership are not. Lean on the second in interviews.",
  High: "Much of this role's routine work is automatable. Show judgement, ownership and people skills in interviews.",
};

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const decodedId = decodeURIComponent(id);

  const [job, setJob] = useState<Job | null>(null);
  const [missing, setMissing] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  // Bumped when an analysis finishes: it fetches the full ad, which can change the sponsorship signals.
  const [analysisRuns, setAnalysisRuns] = useState(0);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  const [step, setStep] = useState(0);
  const [reached, setReached] = useState(0);
  const [cvDoc, setCvDoc] = useState<CVDoc | null>(null);
  const [letterDoc, setLetterDoc] = useState<LetterDoc | null>(null);
  const [templateId] = useState("classic");
  const [streamingCv, setStreamingCv] = useState(false);
  const [streamingLetter, setStreamingLetter] = useState(false);
  const [cvError, setCvError] = useState<string | null>(null);
  const [letterError, setLetterError] = useState<string | null>(null);
  const [cvChoice, setCvChoice] = useState<CvChoice>("tailored");
  // What the critique-and-revise pass found and fixed, when its rewrite was kept.
  const [reviewed, setReviewed] = useState<{ cv: string[]; letter: string[] }>({ cv: [], letter: [] });

  // PDF state
  const [cvDocId, setCvDocId] = useState<string | null>(null);
  const [letterDocId, setLetterDocId] = useState<string | null>(null);
  const [savingCvPdf, setSavingCvPdf] = useState(false);
  const [savingLetterPdf, setSavingLetterPdf] = useState(false);

  // Browser state
  const [sessionId, setSessionId] = useState("");
  const [browserAction, setBrowserAction] = useState("");
  const [browserScreenshot, setBrowserScreenshot] = useState<string | null>(null);
  const [browserBlocked, setBrowserBlocked] = useState(false);
  const [browserReason, setBrowserReason] = useState<string | null>(null);
  const [browserInteractive, setBrowserInteractive] = useState(false);
  // The agent's summary ("Needs your input: …" first); sent once, kept for the whole review.
  const [browserNotes, setBrowserNotes] = useState<string | null>(null);
  // The form's questions, each with its answer and where it came from; sent with the notes.
  const [browserQuestions, setBrowserQuestions] = useState<FormAnswer[]>([]);
  const [log, setLog] = useState<LogLine[]>([]);
  const [started, setStarted] = useState(false);
  const [applying, setApplying] = useState(false);
  const [ended, setEnded] = useState<{ submitted: boolean } | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [sending, setSending] = useState<string | null>(null);
  const startTs = useRef<number | null>(null);
  const applyReaderRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);

  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [about, setAbout] = useState<"desc" | "company">("desc");
  const [actionError, setActionError] = useState<string | null>(null);

  const apps = useResource<Application[]>("/api/applications");
  const sponsorship = useSponsorship(job?.id, analysisRuns);

  // Load job from sessionStorage
  useEffect(() => {
    const stored = recallJob(decodedId);
    if (stored) {
      setJob(stored);
      setSaved(stored.tracker_status === "Saved");
      const cached = cachedFit(decodedId);
      if (cached) setAnalysis(cached);
    } else {
      setMissing(true);
    }
  }, [decodedId]);

  useEffect(() => {
    if (job && apps.data && trackedApplication(job)) setSaved(true);
  }, [job, apps.data]);

  const runAnalysis = useCallback(async () => {
    if (!job) return;
    setAnalyzing(true);
    setAnalysisError(null);
    try {
      const result = await analyzeJob(job);
      cacheFit(decodedId, result);
      setAnalysis(result);
      setAnalysisRuns((n) => n + 1);
    } catch (err) {
      setAnalysisError(err instanceof Error ? err.message : String(err));
    } finally {
      setAnalyzing(false);
    }
  }, [job, decodedId]);

  // Run the analysis when the job loads, unless this session already has it.
  useEffect(() => {
    if (!job || analysis || analyzing || analysisError) return;
    runAnalysis();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job]);

  // Leaving the page ends the agent's browser session: warn first, and cancel the stream on unmount.
  useEffect(() => {
    if (!applying) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [applying]);
  useEffect(() => () => { applyReaderRef.current?.cancel().catch(() => {}); }, []);

  const goTo = (i: number) => {
    setStep(i);
    setReached((r) => Math.max(r, i));
  };

  const generateCv = async () => {
    if (!job) return;
    setStreamingCv(true);
    setCvError(null);
    setCvDoc(null);
    setCvDocId(null);
    let got = false;
    try {
      await postStream("/api/jobs/tailored-cv", { job }, (ev) => {
        if (ev.type === "tailored_cv" && ev.cv) {
          setCvDoc(ev.cv as CVDoc);
          setReviewed((r) => ({ ...r, cv: keptIssues(ev.review) }));
          got = true;
        }
      });
      if (!got) setCvError("The tailored CV didn't come through.");
    } catch (e) {
      setCvError(e instanceof Error ? e.message : "CV generation failed.");
    }
    setStreamingCv(false);
  };

  const generateLetter = async () => {
    if (!job) return;
    setStreamingLetter(true);
    setLetterError(null);
    setLetterDoc(null);
    setLetterDocId(null);
    let got = false;
    try {
      await postStream("/api/jobs/cover-letter", { job }, (ev) => {
        if (ev.type === "cover_letter" && ev.letter) {
          setLetterDoc(ev.letter as LetterDoc);
          setReviewed((r) => ({ ...r, letter: keptIssues(ev.review) }));
          got = true;
        }
      });
      if (!got) setLetterError("The cover letter didn't come through.");
    } catch (e) {
      setLetterError(e instanceof Error ? e.message : "Cover letter generation failed.");
    }
    setStreamingLetter(false);
  };

  const goCv = () => {
    if (!cvDoc && !streamingCv) generateCv();
    goTo(1);
  };
  const goLetter = () => {
    if (!letterDoc && !streamingLetter) generateLetter();
    goTo(2);
  };

  const savePdf = async (type: "cv" | "cover_letter"): Promise<string | null> => {
    const doc = type === "cv" ? cvDoc : letterDoc;
    if (!doc) return null;
    const setBusy = type === "cv" ? setSavingCvPdf : setSavingLetterPdf;
    setBusy(true);
    try {
      const res = await authFetch("/api/documents/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type, doc, template_id: templateId,
          metadata: { job_title: job?.title ?? "", company: job?.company ?? "" },
        }),
      });
      if (!res.ok) throw new Error("PDF generation failed");
      const data = await res.json() as { doc_id: string };
      if (type === "cv") setCvDocId(data.doc_id); else setLetterDocId(data.doc_id);
      return data.doc_id;
    } catch {
      setActionError("The PDF couldn't be made. Try again.");
      return null;
    } finally {
      setBusy(false);
    }
  };

  const download = async (type: "cv" | "cover_letter") => {
    const existing = type === "cv" ? cvDocId : letterDocId;
    const docId = existing ?? await savePdf(type);
    if (docId) await downloadPdf(docId, `${type === "cv" ? "CV" : "CoverLetter"}_${job?.company ?? "Windrush"}.pdf`);
  };

  const handleBrowserEvent = (ev: Record<string, unknown>) => {
    if (typeof ev.timestamp === "number" && startTs.current == null) startTs.current = ev.timestamp;
    if (ev.type === "start" && ev.session_id) setSessionId(ev.session_id as string);
    if (ev.type === "browser_action" || ev.type === "browser_blocked") {
      const action = (ev.action as string) ?? "";
      setBrowserAction(action);
      if (ev.screenshot) setBrowserScreenshot(ev.screenshot as string);
      const blocked = ev.type === "browser_blocked";
      setBrowserBlocked(blocked);
      setBrowserReason(blocked ? (ev.reason as string) ?? null : null);
      setBrowserInteractive(blocked && !!ev.interactive);
      if (action) {
        const t = typeof ev.timestamp === "number" && startTs.current != null ? ev.timestamp - startTs.current : 0;
        setLog((prev) => (prev[prev.length - 1]?.text === action ? prev : [...prev, { t, text: action }]));
      }
    }
    if (typeof ev.notes === "string") setBrowserNotes(ev.notes);
    if (Array.isArray(ev.questions)) setBrowserQuestions(ev.questions as FormAnswer[]);
    if (ev.type === "done") {
      setEnded({ submitted: ev.submitted === true });
      setBrowserBlocked(false);
      setBrowserInteractive(false);
    }
  };

  const handleApply = async () => {
    if (!job) return;
    goTo(4);
    setStarted(true);
    setApplying(true);
    setEnded(null);
    setApplyError(null);
    setBrowserNotes(null);
    setBrowserQuestions([]);
    setBrowserScreenshot(null);
    setBrowserAction("");
    setBrowserBlocked(false);
    setSessionId("");
    setLog([]);
    startTs.current = null;

    // If using tailored CV, ensure PDF exists first
    let effectiveCvDocId = cvDocId;
    if (cvChoice === "tailored" && cvDoc && !cvDocId) {
      effectiveCvDocId = await savePdf("cv");
    }

    const form = new FormData();
    form.append("job_id", job.id ?? job.job_id ?? decodedId);
    form.append("job_url", job.url ?? "");
    form.append("job_title", job.title ?? "");
    form.append("company", job.company ?? "");
    form.append("location", job.location ?? "");
    // For written answers to the form's questions.
    form.append("job_description", job.description ?? "");
    form.append("cover_letter", letterDoc ? letterToText(letterDoc) : "");
    form.append("tailored_cv", cvDoc ? JSON.stringify(cvDoc) : "");
    form.append("cv_doc_id", cvChoice === "tailored" && effectiveCvDocId ? effectiveCvDocId : "");
    // For forms that take the letter as a file: the PDF you saved, else rendered from this document.
    form.append("cover_letter_doc", letterDoc ? JSON.stringify(letterDoc) : "");
    form.append("letter_doc_id", letterDocId ?? "");
    form.append("template_id", templateId ?? "");
    form.append("job_email", "");
    form.append("job_password", "");
    form.append("cv_profile", JSON.stringify({}));
    form.append("skill_risks", JSON.stringify([]));
    if (analysis?.fit_score != null) form.append("fit_score", String(analysis.fit_score));
    if (analysis?.level_match) form.append("level_match", analysis.level_match);
    if (analysis?.skill_gaps) form.append("skill_gaps", JSON.stringify(analysis.skill_gaps));

    try {
      const response = await authFetch("/api/apply", { method: "POST", body: form });
      if (!response.ok) {
        let detail = "The agent couldn't start.";
        try { const d = await response.json(); if (typeof d?.detail === "string") detail = d.detail; } catch {}
        throw new Error(detail);
      }
      await readStream(response, handleBrowserEvent, (r) => { applyReaderRef.current = r; });
    } catch (e) {
      setApplyError(e instanceof Error ? e.message : "The agent stopped unexpectedly.");
    }
    applyReaderRef.current = null;
    setApplying(false);
    setEnded((prev) => prev ?? { submitted: false });
    load("/api/applications", { force: true }).catch(() => {});
  };

  const instruct = async (word: "submit" | "done" | "skip") => {
    if (!sessionId) return;
    setSending(word);
    try {
      await sendInstruction(sessionId, word);
      setBrowserBlocked(false);
    } catch (e) {
      setApplyError(e instanceof Error ? e.message : "Couldn't reach the agent.");
    } finally {
      setSending(null);
    }
  };

  const save = async () => {
    if (!job || saved) return;
    setSaving(true);
    setActionError(null);
    try {
      await saveJob(job);
      setSaved(true);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Couldn't save this job.");
    } finally {
      setSaving(false);
    }
  };

  const discard = async () => {
    if (!job) return;
    setDiscarding(true);
    setActionError(null);
    try {
      await discardJob(job);
      router.push("/jobs");
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Couldn't discard this job.");
      setDiscarding(false);
    }
  };

  if (missing) {
    return (
      <>
        <TopBar crumbs={[{ label: "Job feed", href: "/jobs" }, { label: "Job" }]} />
        <Page wide="job">
          <EmptyState action={<Link href="/jobs" className={buttonClass("primary", "sm")}>Back to the job feed</Link>}>
            This job isn&apos;t open in this tab any more. Open it again from the feed or your applications.
          </EmptyState>
        </Page>
      </>
    );
  }

  if (!job) {
    return (
      <>
        <TopBar crumbs={[{ label: "Job feed", href: "/jobs" }, { label: "Loading" }]} />
        <Page wide="job" className="gap-4">
          <Skeleton className="h-[200px] rounded-card" />
          <Skeleton className="h-[64px] rounded-card" />
          <Skeleton className="h-[360px] rounded-card" />
        </Page>
      </>
    );
  }

  const { prev, next } = feedNeighbours(decodedId);
  const salary = jobSalary(job);
  const setting = workSetting(job);
  const level = levelLabel(job.level);
  const exp = experienceLabel(job.years_min);
  const sponsor = sponsorship.view ? viewVerdict(sponsorship.view) : sponsorshipVerdict(job);
  const posted = longAgo(job.created_at ?? job.posted_at);
  const exposure = job.exposure_score != null ? Math.round(job.exposure_score <= 1 ? job.exposure_score * 100 : job.exposure_score) : null;
  const otherHere = (apps.data ?? []).filter((a) =>
    a.company.toLowerCase() === job.company.toLowerCase() && a.job_title.toLowerCase() !== job.title.toLowerCase()).length;

  const stepSub = (i: number): string | undefined => {
    if (i === 0 && analyzing) return "Analysing…";
    if (i === 1 && streamingCv) return "Writing…";
    if (i === 2 && streamingLetter) return "Writing…";
    if (i === 4 && started) {
      if (ended) return ended.submitted ? "Submitted" : "Session ended";
      return browserBlocked ? "Waiting for you" : "Agent working";
    }
    return undefined;
  };

  const stepper = (
    <StepTracker steps={STEPS.map((s, i) => ({ ...s, sub: stepSub(i) }))} current={step} reached={reached} onPick={setStep} />
  );

  const fitCard = (
    <section aria-labelledby="fit" className="bg-surface border border-border rounded-card p-[18px] flex flex-col gap-[14px]">
      {analyzing && !analysis ? (
        <div className="flex gap-[14px] items-center">
          <Skeleton className="w-16 h-16 rounded-full" />
          <span className="flex flex-col gap-2 flex-1">
            <h2 id="fit" className="m-0 text-[15px] font-semibold">Checking your fit…</h2>
            <Skeleton className="h-4 w-3/4 rounded-[6px]" />
          </span>
        </div>
      ) : analysis?.fit_score != null ? (
        <>
          <div className="flex gap-[14px] items-center">
            <FitRing value={analysis.fit_score} size={64} />
            <span className="flex flex-col gap-1 min-w-0">
              <h2 id="fit" className="m-0 text-[15px] font-semibold">{fitVerdict(analysis.fit_score).replace("match", "fit")}</h2>
              <span className="text-[13px] text-ink-2">
                {[analysis.level_match && `Level match: ${LEVEL_MATCH[analysis.level_match] ?? analysis.level_match}`,
                  analysis.matched_skills && `${analysis.matched_skills.length} of ${analysis.matched_skills.length + (analysis.skill_gaps?.length ?? 0)} skills`]
                  .filter(Boolean).join(" · ")}
              </span>
            </span>
          </div>
          {((analysis.matched_skills?.length ?? 0) + (analysis.skill_gaps?.length ?? 0)) > 0 && (
            <span className="flex flex-wrap gap-[6px]">
              {analysis.matched_skills?.map((s) => <Chip key={`m-${s}`} tone="matched" className="font-normal">{s}</Chip>)}
              {analysis.skill_gaps?.map((s) => <Chip key={`g-${s}`} tone="gap" className="font-normal" title="A gap to address">{s}</Chip>)}
            </span>
          )}
        </>
      ) : (
        <div className="flex flex-col gap-2">
          <h2 id="fit" className="m-0 text-[15px] font-semibold">Fit</h2>
          {analysisError ? <Callout>{analysisError}</Callout> : <p className="m-0 text-[13px] text-ink-2">Not analysed yet.</p>}
          <button type="button" onClick={runAnalysis} disabled={analyzing} className={buttonClass("secondary", "sm", "self-start")}>
            {analyzing ? <Spinner /> : <Icon name="refresh" size={14} />} Run the analysis
          </button>
        </div>
      )}
    </section>
  );

  const docToolbar = (type: "cv" | "cover_letter") => {
    const streaming = type === "cv" ? streamingCv : streamingLetter;
    const has = type === "cv" ? !!cvDoc : !!letterDoc;
    const busy = type === "cv" ? savingCvPdf : savingLetterPdf;
    return (
      <div className="flex items-center gap-2">
        <button type="button" onClick={type === "cv" ? generateCv : generateLetter} disabled={streaming}
          className={buttonClass("secondary", "sm", "text-[12.5px] font-normal")}>
          <Icon name="refresh" size={14} />Regenerate
        </button>
        <button type="button" onClick={() => download(type)} disabled={!has || streaming || busy}
          className={buttonClass("secondary", "sm", "text-[12.5px] font-normal")}>
          {busy ? <Spinner /> : <Icon name="download" size={14} />}Download PDF
        </button>
      </div>
    );
  };

  const docSkeleton = (label: string) => (
    <div className="flex flex-wrap" role="status">
      <div className="flex-[1_1_300px] p-5 flex flex-col gap-[10px]">
        <span className="text-[13px] text-ink-2 flex items-center gap-2"><Spinner />{label}</span>
        {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-[52px] rounded-inner" />)}
      </div>
      <div className="flex-[1.1_1_340px] p-5 bg-track"><Skeleton className="h-[420px] max-w-[440px] mx-auto rounded-[4px] bg-surface" /></div>
    </div>
  );

  const panel = (() => {
    switch (STEPS[step].key) {
      case "analyse":
        return (
          <div className="p-[22px] flex flex-col gap-[14px]">
            <h2 className="m-0 text-[17px] font-semibold">Fit analysis</h2>
            {analyzing && !analysis ? (
              <div className="flex flex-col gap-2" role="status">
                <p className="m-0 text-[14px] text-ink-2 flex items-center gap-2"><Spinner />Reading the full ad and comparing it with your persona…</p>
                <Skeleton className="h-4 w-full max-w-[560px] rounded-[6px]" />
                <Skeleton className="h-4 w-4/5 max-w-[480px] rounded-[6px]" />
              </div>
            ) : analysisError && !analysis ? (
              <Callout title="The analysis didn't finish">{analysisError}</Callout>
            ) : (
              <p className="m-0 text-[14px] leading-[1.6] text-ink-2 max-w-[64ch]">
                {analysis?.reasoning || "The analysis compares this role with your persona: the skills you already have, the gaps, and whether the level suits you."}
                {analysis?.skill_gaps?.length ? ` Gaps to address: ${analysis.skill_gaps.join(", ")}.` : ""}
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={goCv} className={buttonClass("primary", "md")}>
                Continue to tailored CV<Icon name="arrowRight" size={15} strokeWidth={2} />
              </button>
              {(analysis || analysisError) && (
                <button type="button" onClick={runAnalysis} disabled={analyzing} className={buttonClass("quiet", "md")}>
                  {analyzing ? <Spinner /> : null}Run it again
                </button>
              )}
            </div>
          </div>
        );
      case "cv":
        return (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-b border-track">
              <div className="flex flex-col gap-[3px]">
                <h2 className="m-0 text-[16px] font-semibold">Tailored CV</h2>
                <span className="text-[13px] text-ink-3">Aimed at this role. Edit anything; the preview updates as you type.</span>
              </div>
              {docToolbar("cv")}
            </div>
            {cvDoc && !streamingCv && <DocChecks kind="cv" doc={cvDoc} job={job} templateId={templateId} reviewed={reviewed.cv} />}
            {streamingCv ? docSkeleton("Tailoring your CV for this role…") : cvDoc ? (
              <DocEditor kind="cv" templateId={templateId} cv={cvDoc} onCvChange={(c) => { setCvDoc(c); setCvDocId(null); }} />
            ) : (
              <div className="p-5">
                <Callout title="No tailored CV yet" action={
                  <button type="button" onClick={generateCv} className={buttonClass("secondary", "xs", "self-start mt-1")}>Try again</button>
                }>{cvError ?? "Generate one for this role."}</Callout>
              </div>
            )}
            <div className="flex flex-wrap justify-between items-center gap-[10px] px-5 py-[14px] border-t border-track bg-subtle">
              <span className="text-[13px] text-ink-2">Edits stay with this application. Download the PDF to keep a copy.</span>
              <button type="button" onClick={goLetter} disabled={!cvDoc || streamingCv} className={buttonClass("primary", "md")}>
                Looks good — write the cover letter<Icon name="arrowRight" size={15} strokeWidth={2} />
              </button>
            </div>
          </>
        );
      case "letter":
        return (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-b border-track">
              <div className="flex flex-col gap-[3px]">
                <h2 className="m-0 text-[16px] font-semibold">Cover letter</h2>
                <span className="text-[13px] text-ink-3">Written for {job.company}. Edit the paragraphs; the page fits itself to one sheet.</span>
              </div>
              {docToolbar("cover_letter")}
            </div>
            {letterDoc && !streamingLetter && <DocChecks kind="cover_letter" doc={letterDoc} job={job} templateId={templateId} reviewed={reviewed.letter} />}
            {streamingLetter ? docSkeleton("Writing your cover letter…") : letterDoc ? (
              <DocEditor kind="cover_letter" templateId={templateId} letter={letterDoc}
                onLetterChange={(l) => { setLetterDoc(l); setLetterDocId(null); }} />
            ) : (
              <div className="p-5">
                <Callout title="No cover letter yet" action={
                  <button type="button" onClick={generateLetter} className={buttonClass("secondary", "xs", "self-start mt-1")}>Try again</button>
                }>{letterError ?? "Write one for this role."}</Callout>
              </div>
            )}
            <div className="flex flex-wrap justify-between items-center gap-[10px] px-5 py-[14px] border-t border-track bg-subtle">
              <span className="text-[13px] text-ink-2">You can skip the letter; the agent then leaves any cover-letter field for you.</span>
              <button type="button" onClick={() => goTo(3)} disabled={streamingLetter} className={buttonClass("primary", "md")}>
                Looks good — set up the agent<Icon name="arrowRight" size={15} strokeWidth={2} />
              </button>
            </div>
          </>
        );
      case "apply":
        return (
          <div className="p-[22px] flex flex-col gap-4">
            <h2 className="m-0 text-[17px] font-semibold">Let the agent fill the form</h2>
            <p className="m-0 text-[14px] leading-[1.6] text-ink-2 max-w-[62ch]">
              The agent opens the application in a private browser, fills every field from your persona and attaches your
              documents. It stops before the final submit button and waits for you.
            </p>
            <fieldset className="border border-border rounded-inner px-[14px] py-3 m-0 flex flex-col gap-[10px] max-w-[520px]">
              <legend className="text-[13px] font-semibold px-1">CV to attach</legend>
              <label className={cx("flex gap-[10px] items-center text-[13.5px]", !cvDoc && "text-ink-3")}>
                <input type="radio" name="cv" checked={cvChoice === "tailored" && !!cvDoc} disabled={!cvDoc}
                  onChange={() => setCvChoice("tailored")} className="w-4 h-4" style={{ accentColor: "var(--teal)" }} />
                Tailored CV for {job.company}{!cvDoc && " (not written yet)"}
              </label>
              <label className="flex gap-[10px] items-center text-[13.5px]">
                <input type="radio" name="cv" checked={cvChoice === "original" || !cvDoc}
                  onChange={() => setCvChoice("original")} className="w-4 h-4" style={{ accentColor: "var(--teal)" }} />
                Original uploaded CV
              </label>
              {cvChoice === "tailored" && cvDoc && !cvDocId && (
                <span className="text-[12.5px] text-ink-3">The PDF is made when the agent starts.</span>
              )}
            </fieldset>
            {!letterDoc && <p className="m-0 text-[13px] text-ink-3">No cover letter: the agent leaves any cover-letter field for you.</p>}
            {!job.url && <Callout tone="warn" title="No application link">This job has no link to apply through, so the agent can&apos;t open it.</Callout>}
            <button type="button" onClick={() => { if (!cvDoc) setCvChoice("original"); handleApply(); }} disabled={applying || !job.url}
              className={buttonClass("commit", "lg", "self-start")}>
              {applying ? <><Spinner /> Starting…</> : <><Icon name="play" size={14} /> Start the agent</>}
            </button>
          </div>
        );
      default:
        if (!started) {
          return (
            <div className="p-[22px] flex flex-col gap-3">
              <h2 className="m-0 text-[17px] font-semibold">Review and submit</h2>
              <p className="m-0 text-[14px] text-ink-2">Opens once the agent has filled the form.</p>
              <button type="button" onClick={() => goTo(3)} className={buttonClass("secondary", "sm", "self-start")}>Set up the agent</button>
            </div>
          );
        }
        return null;
    }
  })();

  const review = started && step === 4 && (
    <ReviewLayout
      headingLevel={2}
      tone={ended ? (ended.submitted ? "teal" : "neutral") : browserBlocked ? "amber" : "teal"}
      status={ended ? (ended.submitted ? "Submitted" : "Session ended") : browserBlocked ? "Paused before the final submit" : "The agent is filling the form"}
      title={`${job.title} · ${job.company}`}
      subtitle={ended
        ? ended.submitted ? "Sent. It's in your applications as Applied." : "Nothing was sent from this session. You can run the agent again."
        : browserBlocked ? "Check what the agent entered. You can click and type on the page yourself at any point."
        : "It stops before the final submit button and waits for you. Leaving this page closes its browser."}
      frame={sessionId && !ended ? (
        <BrowserView action={browserAction} screenshot={browserScreenshot} blocked={browserBlocked} reason={browserReason}
          sessionId={sessionId} interactive={browserInteractive} url={job.url} onInstructionSent={() => setBrowserBlocked(false)} />
      ) : (
        <BrowserFrame url={job.url}>
          <div className="flex-1 min-h-[280px] flex flex-col items-center justify-center gap-3 p-6 text-center bg-subtle">
            {!ended && !applyError ? (
              <span className="flex items-center gap-2 text-[13.5px] text-ink-2"><Spinner />Starting the agent&apos;s browser…</span>
            ) : (
              <>
                {applyError && <Callout className="max-w-[440px] text-left">{applyError}</Callout>}
                <span className="text-[13.5px] text-ink-2 max-w-[44ch]">
                  {ended?.submitted ? "The application was sent." : "The agent's browser has closed."}
                </span>
                {!ended?.submitted && (
                  <button type="button" onClick={handleApply} className={buttonClass("commit", "md")}>
                    <Icon name="play" size={14} />Run the agent again
                  </button>
                )}
              </>
            )}
          </div>
        </BrowserFrame>
      )}
      side={<AgentNotes notes={browserNotes} log={log} />}
      skip={{ onClick: () => instruct("skip"), disabled: !browserBlocked || !!ended, busy: sending === "skip" }}
      done={{ onClick: () => instruct("done"), disabled: !browserBlocked || !!ended, busy: sending === "done" }}
      submit={{ onClick: () => instruct("submit"), disabled: !browserBlocked || !!ended, busy: sending === "submit",
        hint: !ended && !browserBlocked ? "Available once the agent pauses." : undefined }}
    />
  );

  return (
    <>
      <TopBar crumbs={[{ label: "Job feed", href: "/jobs" }, { label: job.title }]}>
        <Link href={prev ? jobHref(prev) : "#"} aria-disabled={!prev} tabIndex={prev ? undefined : -1}
          className={cx(buttonClass("secondary", "sm", "h-9 text-[13px] font-normal"), !prev && "opacity-50 pointer-events-none")}>
          <Icon name="chevronLeft" size={14} strokeWidth={2} />Previous
        </Link>
        <Link href={next ? jobHref(next) : "#"} aria-disabled={!next} tabIndex={next ? undefined : -1}
          className={cx(buttonClass("secondary", "sm", "h-9 text-[13px] font-normal"), !next && "opacity-50 pointer-events-none")}>
          Next match<Icon name="chevronRight" size={14} strokeWidth={2} />
        </Link>
      </TopBar>
      <Page wide="job" className="gap-4 pt-6 sm:pt-6">
        <Card className="flex flex-wrap gap-[18px] items-center px-[22px] py-5">
          <CompanyMark name={job.company} size={56} />
          <div className="flex-[1_1_360px] flex flex-col gap-[7px] min-w-0">
            <h1 className="m-0 text-[24px] font-semibold tracking-[-0.02em]">{job.title}</h1>
            <span className="flex flex-wrap gap-x-[14px] gap-y-[6px] text-[13.5px] text-ink-2">
              <span>{job.company}</span>
              {job.location && <span>{job.location}</span>}
              {salary && <span>{salary}</span>}
              {posted && <span>Posted {posted}</span>}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {job.url && (
              <a href={job.url} target="_blank" rel="noopener noreferrer" className={buttonClass("secondary", "top")}>
                View posting<Icon name="external" size={14} strokeWidth={2} /><span className="sr-only"> (opens in a new tab)</span>
              </a>
            )}
            <button type="button" onClick={save} disabled={saving || saved} aria-pressed={saved}
              className={buttonClass("secondary", "top", saved ? "disabled:opacity-100 text-teal-deep" : undefined)}>
              {saving ? <Spinner /> : saved ? <Icon name="check" size={14} strokeWidth={2.4} /> : <Icon name="bookmark" size={14} />}
              {saved ? "Saved" : "Save"}
            </button>
            <button type="button" onClick={discard} disabled={discarding} className={buttonClass("quiet", "top", "px-3 font-normal")}>
              {discarding ? <Spinner /> : null}Discard
            </button>
          </div>
          {actionError && <div className="basis-full"><Callout>{actionError}</Callout></div>}
          <div className="basis-full grid gap-[10px]" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(170px, 100%), 1fr))" }}>
            <FactTile large tint="mint" label="Salary" value={salary ?? "Not listed"} note={salary ? "per year" : "the ad doesn't say"} />
            <FactTile large tint="sky" label="Setting" value={setting ?? "Not stated"} note={job.location || undefined} />
            <FactTile large tint="peach" label="Experience asked" value={exp ?? "Not stated"}
              note={[level && `${level} level`, job.degree === "required" ? "degree required" : job.degree === "preferred" ? "degree preferred"
                : job.degree === "not_mentioned" ? "no degree mentioned" : null].filter(Boolean).join(" · ") || degreeLabel(job.degree)} />
            <FactTile large tint="lilac" label="Visa sponsorship" value={sponsor.verdict}
              note={sponsorship.view?.licensed_sponsor || job.licensed_sponsor ? "Licensed sponsor" : sponsor.verdict === "Offered" ? "Stated in the ad" : "Not on the register"} />
          </div>
        </Card>

        {stepper}

        {review}
        {review && (
          <FormQuestions questions={browserQuestions} company={job.company}
            savedNote={sessionId && !ended ? "Saved for your next form." : "Saved for your next form. Fill it in on the page too, then submit."}
            onFill={sessionId && !ended ? async (answers) => {
              if (!browserInteractive) throw new Error("Wait until the agent has paused on the form, then try again.");
              await sendInstruction(sessionId, { type: "answers", answers });
              setBrowserBlocked(false);
              setBrowserInteractive(false);
            } : undefined} />
        )}

        <div className="grid gap-4 items-start grid-cols-1 lg:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
          <div className="min-w-0 flex flex-col gap-4">
            {!review && <Card className="overflow-hidden min-w-0">{panel}</Card>}
            <Card aria-label="About the role" className="px-[22px] pt-2 pb-[22px] flex flex-col gap-4 min-w-0">
              <UnderlineTabs idPrefix="about" label="Role details" className="mt-[14px]" value={about} onChange={setAbout}
                items={[{ key: "desc", label: "Description" }, { key: "company", label: "Company" }]} />
              <TabPanel idPrefix="about" k="desc" active={about === "desc"}>
                <JobDescription text={job.description} />
              </TabPanel>
              <TabPanel idPrefix="about" k="company" active={about === "company"} className="flex flex-col gap-[14px]">
                <div className="grid gap-[10px]" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(150px, 100%), 1fr))" }}>
                  <div className="px-[14px] py-3 rounded-inner bg-subtle border border-divider flex flex-col gap-1">
                    <span className="text-[12px] text-ink-3">Visa sponsor licence</span>
                    <span className={cx("text-[14px] font-semibold", (sponsorship.view?.licensed_sponsor ?? job.licensed_sponsor) && "text-teal")}>
                      {(sponsorship.view?.licensed_sponsor ?? job.licensed_sponsor) ? "Yes, Skilled Worker" : "Not on the register"}
                    </span>
                  </div>
                  {job.source && (
                    <div className="px-[14px] py-3 rounded-inner bg-subtle border border-divider flex flex-col gap-1">
                      <span className="text-[12px] text-ink-3">Found on</span>
                      <span className="text-[14px] font-semibold capitalize">{job.source}</span>
                    </div>
                  )}
                </div>
                <span className="text-[13px] text-ink-2">
                  You&apos;ve applied to <strong className="text-ink">{otherHere}</strong> other {otherHere === 1 ? "role" : "roles"} at {job.company}.
                </span>
              </TabPanel>
            </Card>
          </div>

          <aside className="min-w-0 flex flex-col gap-[14px]">
            {fitCard}
            {sponsorship.view && <SponsorshipPanel view={sponsorship.view} onMark={sponsorship.mark} saving={sponsorship.saving} />}
            {!sponsorship.view && (
              <section aria-labelledby="visa-ad" className="bg-surface border border-border rounded-card p-[18px] flex flex-col gap-2">
                <div className="flex justify-between items-center gap-2">
                  <h2 id="visa-ad" className="m-0 text-[15px] font-semibold">Visa sponsorship</h2>
                  <Chip tone={VERDICT_TONE[sponsor.verdict]} size="sm" className="font-semibold">{sponsor.verdict}</Chip>
                </div>
                <p className="m-0 text-[13px] leading-[1.5] text-ink-2">{sponsor.why}</p>
              </section>
            )}
            {exposure != null && (
              <section aria-labelledby="exposure" className="bg-surface border border-border rounded-card p-[18px] flex flex-col gap-[10px]">
                <div className="flex justify-between items-center gap-2">
                  <h2 id="exposure" className="m-0 text-[15px] font-semibold">AI exposure of this role</h2>
                  <span className={cx("font-mono text-[13px] font-semibold", RISK[riskLevel(exposure)].text)}>{exposure}% · {riskLevel(exposure)}</span>
                </div>
                <Bar value={exposure} className={RISK[riskLevel(exposure)].bar} />
                <p className="m-0 text-[13px] leading-[1.5] text-ink-2">{EXPOSURE_NOTE[riskLevel(exposure)]}</p>
              </section>
            )}
          </aside>
        </div>
      </Page>
    </>
  );
}
