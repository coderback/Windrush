"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { authFetch } from "@/app/api";
import { Job } from "@/components/JobCard";
import BrowserView from "@/components/BrowserView";

interface AnalysisResult {
  fit_score?: number;
  level_match?: string;
  skill_gaps?: string[];
  matched_skills?: string[];
}

type AppStep = "idle" | "cv" | "cv_done" | "letter" | "letter_done" | "apply";
type CvChoice = "tailored" | "original";

function readStream(
  response: Response,
  onChunk: (chunk: string) => void,
  onEvent: (ev: Record<string, unknown>) => void,
): Promise<void> {
  return new Promise(async (resolve) => {
    if (!response.body) { resolve(); return; }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        try {
          const ev = JSON.parse(line.slice(6)) as Record<string, unknown>;
          if (ev.type === "text" && typeof ev.text === "string") onChunk(ev.text);
          else onEvent(ev);
        } catch {}
      }
    }
    resolve();
  });
}

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

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const decodedId = decodeURIComponent(id);

  const [job, setJob] = useState<Job | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisDone, setAnalysisDone] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  const [appStep, setAppStep] = useState<AppStep>("idle");
  const [tailoredCv, setTailoredCv] = useState("");
  const [coverLetter, setCoverLetter] = useState("");
  const [streamingCv, setStreamingCv] = useState(false);
  const [streamingLetter, setStreamingLetter] = useState(false);
  const [cvChoice, setCvChoice] = useState<CvChoice>("tailored");

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
  const [showBrowser, setShowBrowser] = useState(false);
  const [minimised, setMinimised] = useState(false);
  const [applying, setApplying] = useState(false);
  const applyReaderRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);

  // Load job from sessionStorage
  useEffect(() => {
    const raw = sessionStorage.getItem(`job_${decodedId}`);
    if (raw) {
      try { setJob(JSON.parse(raw) as Job); } catch {}
    }
  }, [decodedId]);

  // Auto-run analysis when job is loaded
  useEffect(() => {
    if (!job || analysisDone || analyzing) return;
    runAnalysis();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job]);

  const runAnalysis = async () => {
    if (!job) return;
    setAnalyzing(true);
    setAnalysisError(null);
    const result: AnalysisResult = {};
    try {
      const res = await authFetch("/api/jobs/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job }),
      });
      if (!res.ok) throw new Error("Analysis failed");
      await readStream(
        res,
        () => {},
        (ev) => {
          if (ev.type === "job_fit" && ev.ranked_jobs) {
            const top = (ev.ranked_jobs as Record<string, unknown>[])[0] ?? {};
            result.fit_score = top.fit_score as number;
            result.level_match = top.level_match as string;
            result.skill_gaps = top.skill_gaps as string[];
            result.matched_skills = top.matched_skills as string[];
          }
        },
      );
      setAnalysis(result);
      setAnalysisDone(true);
    } catch (err: unknown) {
      setAnalysisError(String(err));
    } finally {
      setAnalyzing(false);
    }
  };

  const generateCv = async () => {
    if (!job) return;
    setAppStep("cv");
    setStreamingCv(true);
    setTailoredCv("");
    setCvDocId(null);
    try {
      const res = await authFetch("/api/jobs/tailored-cv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job }),
      });
      if (!res.ok) throw new Error("CV generation failed");
      await readStream(res, (chunk) => setTailoredCv((p) => p + chunk), (ev) => {
        if (ev.type === "tailored_cv" && ev.cv_text) setTailoredCv(ev.cv_text as string);
      });
    } catch {}
    setStreamingCv(false);
    setAppStep("cv_done");
  };

  const generateLetter = async () => {
    setAppStep("letter");
    setStreamingLetter(true);
    setCoverLetter("");
    setLetterDocId(null);
    try {
      const res = await authFetch("/api/jobs/cover-letter", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job }),
      });
      if (!res.ok) throw new Error("Cover letter generation failed");
      await readStream(res, (chunk) => setCoverLetter((p) => p + chunk), (ev) => {
        if (ev.type === "cover_letter" && ev.cover_letter) setCoverLetter(ev.cover_letter as string);
      });
    } catch {}
    setStreamingLetter(false);
    setAppStep("letter_done");
  };

  const saveCvAsPdf = async (): Promise<string | null> => {
    if (!tailoredCv) return null;
    setSavingCvPdf(true);
    try {
      const res = await authFetch("/api/documents/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "cv",
          text: tailoredCv,
          metadata: { job_title: job?.title ?? "", company: job?.company ?? "" },
        }),
      });
      if (!res.ok) throw new Error("PDF generation failed");
      const data = await res.json() as { doc_id: string };
      setCvDocId(data.doc_id);
      await downloadPdf(data.doc_id, `CV_${job?.company ?? "Windrush"}.pdf`);
      return data.doc_id;
    } catch {
      return null;
    } finally {
      setSavingCvPdf(false);
    }
  };

  const saveLetterAsPdf = async () => {
    if (!coverLetter) return;
    setSavingLetterPdf(true);
    try {
      const res = await authFetch("/api/documents/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "cover_letter",
          text: coverLetter,
          metadata: { job_title: job?.title ?? "", company: job?.company ?? "" },
        }),
      });
      if (!res.ok) throw new Error("PDF generation failed");
      const data = await res.json() as { doc_id: string };
      setLetterDocId(data.doc_id);
      await downloadPdf(data.doc_id, `CoverLetter_${job?.company ?? "Windrush"}.pdf`);
    } catch {}
    setSavingLetterPdf(false);
  };

  const handleApply = async () => {
    if (!job) return;
    setAppStep("apply");
    setApplying(true);
    setShowBrowser(true);
    setMinimised(false);

    // If using tailored CV, ensure PDF exists first
    let effectiveCvDocId = cvDocId;
    if (cvChoice === "tailored" && tailoredCv && !cvDocId) {
      effectiveCvDocId = await saveCvAsPdf();
    }

    const form = new FormData();
    form.append("job_id", job.id ?? job.job_id ?? decodedId);
    form.append("job_url", job.url ?? "");
    form.append("job_title", job.title ?? "");
    form.append("company", job.company ?? "");
    form.append("location", job.location ?? "");
    form.append("cover_letter", coverLetter);
    form.append("tailored_cv", tailoredCv);
    form.append("cv_doc_id", cvChoice === "tailored" && effectiveCvDocId ? effectiveCvDocId : "");
    form.append("job_email", "");
    form.append("job_password", "");
    form.append("cv_session_id", "");
    form.append("cv_profile", JSON.stringify({}));
    form.append("skill_risks", JSON.stringify([]));
    if (analysis?.fit_score != null) form.append("fit_score", String(analysis.fit_score));
    if (analysis?.level_match) form.append("level_match", analysis.level_match);
    if (analysis?.skill_gaps) form.append("skill_gaps", JSON.stringify(analysis.skill_gaps));

    try {
      const response = await authFetch("/api/apply", { method: "POST", body: form });
      if (!response.body) { setApplying(false); return; }
      const reader = response.body.getReader();
      applyReaderRef.current = reader;
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(line.slice(6)) as Record<string, unknown>;
            handleBrowserEvent(ev);
          } catch {}
        }
      }
    } catch {}
    setApplying(false);
  };

  const handleBrowserEvent = (ev: Record<string, unknown>) => {
    if (ev.type === "start" && ev.session_id) setSessionId(ev.session_id as string);
    if (ev.type === "browser_action") {
      setBrowserAction(ev.action as string ?? "");
      if (ev.screenshot) setBrowserScreenshot(ev.screenshot as string);
      setBrowserBlocked(false);
      setBrowserReason(null);
      setBrowserInteractive(false);
    }
    if (ev.type === "browser_blocked") {
      setBrowserAction(ev.action as string ?? "");
      if (ev.screenshot) setBrowserScreenshot(ev.screenshot as string);
      setBrowserBlocked(true);
      setBrowserReason(ev.reason as string ?? null);
      setBrowserInteractive(!!(ev.interactive));
      setMinimised(false);
    }
  };

  if (!job) {
    return (
      <div className="p-8 text-zinc-600 text-sm">
        Loading job…{" "}
        <button className="text-teal-500 hover:underline" onClick={() => router.push("/jobs")}>
          Back to Job Feed
        </button>
      </div>
    );
  }

  const fitPct = analysis?.fit_score ?? 0;
  const fitColor = fitPct >= 70 ? "text-teal-400" : fitPct >= 40 ? "text-yellow-400" : "text-red-400";
  const levelBadge: Record<string, string> = {
    strong: "bg-teal-500/10 text-teal-400 border-teal-500/30",
    ok: "bg-yellow-500/10 text-yellow-400 border-yellow-500/30",
    reach: "bg-red-500/10 text-red-400 border-red-500/30",
  };

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-6 pb-24">
      {/* Back */}
      <button onClick={() => router.push("/jobs")} className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
        ← Back to Job Feed
      </button>

      {/* Panel A — Job Info */}
      <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h1 className="text-xl font-bold text-zinc-100" style={{ fontFamily: "Playfair Display, serif" }}>
              {job.title}
            </h1>
            <p className="text-sm text-zinc-400 mt-1">{job.company} · {job.location}</p>
            {job.salary && <p className="text-sm text-zinc-500 mt-0.5">{job.salary}</p>}
          </div>
          {job.url && (
            <a href={job.url} target="_blank" rel="noopener noreferrer" className="shrink-0 text-xs text-teal-500 hover:underline">
              View posting ↗
            </a>
          )}
        </div>
        {job.description && (
          <p className="text-sm text-zinc-400 leading-relaxed whitespace-pre-line line-clamp-6">
            {job.description}
          </p>
        )}
      </div>

      {/* Panel B — Analysis */}
      <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-widest">Agent Analysis</h2>
          {analysisDone && (
            <button onClick={runAnalysis} className="text-xs text-zinc-600 hover:text-zinc-400">Re-run</button>
          )}
        </div>

        {analysisError && <p className="text-sm text-red-400">{analysisError}</p>}

        {analyzing && (
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            <span className="w-2 h-2 rounded-full bg-teal-400 animate-pulse" />
            Analysing job against your profile…
          </div>
        )}

        {analysisDone && analysis && (
          <div className="space-y-5">
            {/* Fit score + level */}
            <div className="flex items-center gap-8">
              {analysis.fit_score != null && (
                <div>
                  <p className="text-xs text-zinc-600 uppercase tracking-widest mb-1">Fit Score</p>
                  <p className={`text-3xl font-bold ${fitColor}`}>{analysis.fit_score}%</p>
                </div>
              )}
              {analysis.level_match && (
                <div>
                  <p className="text-xs text-zinc-600 uppercase tracking-widest mb-1">Experience Level</p>
                  <span className={`text-xs px-2 py-0.5 border rounded-full capitalize ${levelBadge[analysis.level_match] ?? "border-zinc-700 text-zinc-400"}`}>
                    {analysis.level_match === "strong" ? "Good match" : analysis.level_match === "ok" ? "Reasonable match" : "Stretch role"}
                  </span>
                </div>
              )}
            </div>

            {/* Skills grid */}
            <div className="grid grid-cols-2 gap-4">
              {/* Skills possessed */}
              {analysis.matched_skills && analysis.matched_skills.length > 0 && (
                <div>
                  <p className="text-xs text-zinc-600 uppercase tracking-widest mb-2">Skills Matched</p>
                  <div className="flex flex-wrap gap-1.5">
                    {analysis.matched_skills.map((s) => (
                      <span key={s} className="text-xs px-2 py-0.5 border border-teal-500/30 bg-teal-500/10 text-teal-400 rounded-full capitalize">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Skills lacking */}
              {analysis.skill_gaps && analysis.skill_gaps.length > 0 && (
                <div>
                  <p className="text-xs text-zinc-600 uppercase tracking-widest mb-2">Skills to Develop</p>
                  <div className="flex flex-wrap gap-1.5">
                    {analysis.skill_gaps.map((gap) => (
                      <span key={gap} className="text-xs px-2 py-0.5 border border-yellow-500/30 bg-yellow-500/10 text-yellow-400 rounded-full capitalize">
                        {gap}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {appStep === "idle" && (
              <button
                onClick={generateCv}
                className="w-full py-2.5 text-sm font-bold bg-white text-black rounded-lg hover:bg-zinc-200 transition-colors"
              >
                Prepare Application →
              </button>
            )}
          </div>
        )}

        {/* Prepare button when analysis done but no score yet */}
        {analysisDone && !analysis && appStep === "idle" && (
          <button
            onClick={generateCv}
            className="w-full mt-4 py-2.5 text-sm font-bold bg-white text-black rounded-lg hover:bg-zinc-200 transition-colors"
          >
            Prepare Application →
          </button>
        )}
      </div>

      {/* Panel C — Application Preparation */}
      {appStep !== "idle" && (
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6 space-y-6">
          <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-widest">Application Preparation</h2>

          {/* Step C1 — Tailored CV */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className={`w-5 h-5 rounded-full text-[10px] flex items-center justify-center font-bold border ${
                  appStep === "cv" ? "border-teal-500 text-teal-400" : "border-teal-600 bg-teal-600/20 text-teal-400"
                }`}>
                  {appStep === "cv" ? "1" : "✓"}
                </span>
                <span className="text-sm font-medium text-zinc-300">Tailored CV</span>
                {streamingCv && <span className="text-xs text-zinc-500 animate-pulse">Generating…</span>}
              </div>
              {tailoredCv && !streamingCv && (
                <div className="flex items-center gap-2">
                  {cvDocId && (
                    <button
                      onClick={() => downloadPdf(cvDocId, `CV_${job?.company ?? "Windrush"}.pdf`)}
                      className="text-xs text-zinc-500 hover:text-zinc-300"
                    >
                      ↓ Re-download
                    </button>
                  )}
                  <button
                    onClick={() => saveCvAsPdf()}
                    disabled={savingCvPdf}
                    className={`text-xs px-3 py-1 rounded-lg border transition-colors ${
                      cvDocId
                        ? "border-teal-600 text-teal-400 bg-teal-600/10"
                        : "border-zinc-700 text-zinc-400 hover:border-teal-600 hover:text-teal-400"
                    } disabled:opacity-50`}
                  >
                    {savingCvPdf ? "Generating PDF…" : cvDocId ? "✓ Saved as PDF" : "Save as PDF"}
                  </button>
                </div>
              )}
            </div>
            {(["cv", "cv_done", "letter", "letter_done", "apply"] as AppStep[]).includes(appStep) && (
              <textarea
                value={tailoredCv}
                onChange={(e) => { setTailoredCv(e.target.value); setCvDocId(null); }}
                rows={14}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-4 py-3 text-xs text-zinc-300 font-mono focus:outline-none focus:border-teal-500 resize-y transition-colors"
                placeholder="Your tailored CV will appear here — you can edit it freely before saving."
              />
            )}
            {appStep === "cv_done" && (
              <button
                onClick={generateLetter}
                className="py-2 px-5 text-sm font-bold bg-white text-black rounded-lg hover:bg-zinc-200 transition-colors"
              >
                Looks good — Generate Cover Letter →
              </button>
            )}
          </div>

          {/* Step C2 — Cover Letter */}
          {(["letter", "letter_done", "apply"] as AppStep[]).includes(appStep) && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={`w-5 h-5 rounded-full text-[10px] flex items-center justify-center font-bold border ${
                    appStep === "letter" ? "border-teal-500 text-teal-400" : "border-teal-600 bg-teal-600/20 text-teal-400"
                  }`}>
                    {appStep === "letter" ? "2" : "✓"}
                  </span>
                  <span className="text-sm font-medium text-zinc-300">Cover Letter</span>
                  {streamingLetter && <span className="text-xs text-zinc-500 animate-pulse">Generating…</span>}
                </div>
                {coverLetter && !streamingLetter && (
                  <div className="flex items-center gap-2">
                    {letterDocId && (
                      <button
                        onClick={() => downloadPdf(letterDocId, `CoverLetter_${job?.company ?? "Windrush"}.pdf`)}
                        className="text-xs text-zinc-500 hover:text-zinc-300"
                      >
                        ↓ Re-download
                      </button>
                    )}
                    <button
                      onClick={saveLetterAsPdf}
                      disabled={savingLetterPdf}
                      className={`text-xs px-3 py-1 rounded-lg border transition-colors ${
                        letterDocId
                          ? "border-teal-600 text-teal-400 bg-teal-600/10"
                          : "border-zinc-700 text-zinc-400 hover:border-teal-600 hover:text-teal-400"
                      } disabled:opacity-50`}
                    >
                      {savingLetterPdf ? "Generating PDF…" : letterDocId ? "✓ Saved as PDF" : "Save as PDF"}
                    </button>
                  </div>
                )}
              </div>
              <textarea
                value={coverLetter}
                onChange={(e) => { setCoverLetter(e.target.value); setLetterDocId(null); }}
                rows={10}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-4 py-3 text-xs text-zinc-300 font-mono focus:outline-none focus:border-teal-500 resize-y transition-colors"
                placeholder="Your cover letter will appear here — edit freely before applying."
              />

              {appStep === "letter_done" && (
                <div className="space-y-4">
                  {/* CV choice */}
                  <div>
                    <p className="text-xs text-zinc-500 uppercase tracking-widest mb-2">CV to submit</p>
                    <div className="flex gap-3">
                      <button
                        onClick={() => setCvChoice("tailored")}
                        className={`flex-1 py-2 px-3 text-xs rounded-lg border transition-colors ${
                          cvChoice === "tailored"
                            ? "border-teal-500 bg-teal-500/10 text-teal-300"
                            : "border-zinc-700 text-zinc-500 hover:border-zinc-600"
                        }`}
                      >
                        Tailored CV (generated above)
                      </button>
                      <button
                        onClick={() => setCvChoice("original")}
                        className={`flex-1 py-2 px-3 text-xs rounded-lg border transition-colors ${
                          cvChoice === "original"
                            ? "border-teal-500 bg-teal-500/10 text-teal-300"
                            : "border-zinc-700 text-zinc-500 hover:border-zinc-600"
                        }`}
                      >
                        Original uploaded CV
                      </button>
                    </div>
                    {cvChoice === "tailored" && !cvDocId && (
                      <p className="text-xs text-zinc-600 mt-1.5">PDF will be auto-generated when you click Apply.</p>
                    )}
                  </div>

                  <button
                    onClick={handleApply}
                    disabled={applying}
                    className="w-full py-2.5 text-sm font-bold bg-teal-600 text-white rounded-lg hover:bg-teal-500 transition-colors disabled:opacity-50"
                  >
                    {applying ? "Launching browser agent…" : "Apply with Browser Agent →"}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Floating minimised pill */}
      {showBrowser && minimised && (
        <button
          onClick={() => setMinimised(false)}
          className="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-2.5 bg-zinc-900 border border-teal-600/50 rounded-full text-sm text-teal-300 shadow-lg hover:bg-zinc-800 transition-colors"
        >
          <span className={`w-2 h-2 rounded-full ${browserBlocked ? "bg-amber-400" : "bg-teal-400 animate-pulse"}`} />
          {browserBlocked ? "Agent waiting — Resume →" : "Agent running… · Resume →"}
        </button>
      )}

      {/* Browser View */}
      {showBrowser && !minimised && (
        <div className="fixed inset-0 z-50">
          <BrowserView
            action={browserAction}
            screenshot={browserScreenshot}
            blocked={browserBlocked}
            reason={browserReason}
            sessionId={sessionId}
            interactive={browserInteractive}
            onInstructionSent={() => setBrowserBlocked(false)}
          />
          <button
            onClick={() => setMinimised(true)}
            className="fixed top-4 right-4 z-[60] px-3 py-1.5 text-xs text-zinc-400 bg-zinc-900 border border-zinc-700 rounded-lg hover:border-zinc-500 transition-colors"
          >
            Minimise
          </button>
        </div>
      )}
    </div>
  );
}