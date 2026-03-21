"use client";

import { useCallback, useState } from "react";
import AgentLog, { AgentEvent } from "@/components/AgentLog";
import RiskRadar, { SkillRisk } from "@/components/RiskRadar";
import JobList, { Job } from "@/components/JobList";
import CoverLetter from "@/components/CoverLetter";
import SkillRoadmap, { RoadmapItem } from "@/components/SkillRoadmap";
import BrowserView from "@/components/BrowserView";

interface CVProfile {
  name?: string;
  email?: string;
  location?: string;
  skills?: string[];
  job_titles?: string[];
  experience_years?: number;
  summary?: string;
}

type Phase =
  | "idle"
  | "uploading"
  | "streaming"
  | "awaiting_approval"
  | "applying"
  | "browser"
  | "done";

export default function Home() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [cvProfile, setCvProfile] = useState<CVProfile | null>(null);
  const [skillRisks, setSkillRisks] = useState<SkillRisk[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [coverLetter, setCoverLetter] = useState("");
  const [roadmap, setRoadmap] = useState<RoadmapItem[]>([]);
  const [appliedConfirmation, setAppliedConfirmation] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [pendingCoverLetter, setPendingCoverLetter] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [browserScreenshot, setBrowserScreenshot] = useState<string | null>(null);
  const [browserAction, setBrowserAction] = useState("");
  const [browserBlocked, setBrowserBlocked] = useState(false);
  const [browserReason, setBrowserReason] = useState<string | null>(null);
  const [browserInteractive, setBrowserInteractive] = useState(false);
  const [showBrowser, setShowBrowser] = useState(false);

  const pushEvent = (ev: AgentEvent) => setEvents((prev) => [...prev, ev]);

  const handleEvent = useCallback(
    (ev: AgentEvent) => {
      pushEvent(ev);

      // Capture cv_profile from tool *call* inputs (score_job_fit / generate_cover_letter)
      if (ev.type === "tool_call" && ev.tool_input) {
        const input = ev.tool_input as Record<string, unknown>;
        if (
          (ev.tool_name === "score_job_fit" || ev.tool_name === "generate_cover_letter") &&
          input.cv_profile &&
          typeof input.cv_profile === "object"
        ) {
          setCvProfile(input.cv_profile as CVProfile);
        }
      }

      if (ev.type === "start" && (ev as AgentEvent & { session_id?: string }).session_id) {
        setSessionId((ev as AgentEvent & { session_id?: string }).session_id!);
      }

      if (ev.type === "browser_action") {
        setBrowserAction(ev.action ?? "");
        if (ev.screenshot) setBrowserScreenshot(ev.screenshot);
        setBrowserBlocked(false);
        setBrowserReason(null);
        setBrowserInteractive(false);
        setShowBrowser(true);
        setPhase("browser");
      }

      if (ev.type === "browser_blocked") {
        setBrowserAction(ev.action ?? "");
        if (ev.screenshot) setBrowserScreenshot(ev.screenshot);
        setBrowserBlocked(true);
        setBrowserReason(ev.reason ?? null);
        setBrowserInteractive(!!(ev as AgentEvent & { interactive?: boolean }).interactive);
        setShowBrowser(true);
        setPhase("browser");
      }

      if (ev.type === "tool_call") {
        setShowBrowser(false);
      }

      if (ev.type === "tool_result" && ev.tool_name && ev.result) {
        const result = ev.result as Record<string, unknown>;

        if (ev.tool_name === "score_ai_risk" && result.skill_risks) {
          setSkillRisks(result.skill_risks as SkillRisk[]);
        }

        if (ev.tool_name === "score_job_fit" && result.ranked_jobs) {
          const ranked = result.ranked_jobs as Job[];
          setJobs(ranked);
          if (ranked.length > 0) setSelectedJob(ranked[0]);
        }

        if (ev.tool_name === "generate_cover_letter" && result.cover_letter) {
          setPendingCoverLetter(result.cover_letter as string);
        }

        if (ev.tool_name === "generate_skill_roadmap" && result.items) {
          setRoadmap(result.items as RoadmapItem[]);
        }

        if (ev.tool_name === "apply_to_job") {
          const r = result as { message?: string };
          setAppliedConfirmation(r.message ?? "Application submitted!");
        }
      }

      if (ev.type === "done") {
        setPhase((prev) => {
          if (prev === "streaming") return "awaiting_approval";
          return "done";
        });
      }
    },
    []
  );

  const startPipeline = async (file: File) => {
    setPhase("uploading");
    setEvents([]);
    setCvProfile(null);
    setSkillRisks([]);
    setJobs([]);
    setSelectedJob(null);
    setCoverLetter("");
    setPendingCoverLetter("");
    setRoadmap([]);
    setAppliedConfirmation("");

    const form = new FormData();
    form.append("file", file);

    let response: Response;
    try {
      response = await fetch("/api/stream", { method: "POST", body: form });
    } catch (err) {
      pushEvent({
        type: "text",
        timestamp: Date.now() / 1000,
        text: `Connection error: ${err}`,
      });
      setPhase("idle");
      return;
    }

    setPhase("streaming");

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const ev = JSON.parse(line.slice(6)) as AgentEvent;
            handleEvent(ev);
          } catch {
            // Partial JSON — ignore
          }
        }
      }
    }

    setCoverLetter((cl) => cl || "");
    setPendingCoverLetter((cl) => { if (cl) setCoverLetter(cl); return cl; });
  };

  const handleApprove = async () => {
    if (!selectedJob) return;
    const cl = coverLetter || pendingCoverLetter;
    setPhase("applying");
    setCoverLetter("");

    const form = new FormData();
    form.append("job_id", selectedJob.job_id);
    form.append("job_url", selectedJob.url ?? "");
    form.append("cover_letter", cl);
    form.append("cv_profile", JSON.stringify(cvProfile ?? {}));
    form.append("skill_risks", JSON.stringify(skillRisks));

    const response = await fetch("/api/apply", { method: "POST", body: form });
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const ev = JSON.parse(line.slice(6)) as AgentEvent;
            handleEvent(ev);
          } catch {}
        }
      }
    }
    setPhase("done");
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file?.type === "application/pdf") startPipeline(file);
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) startPipeline(file);
  };

  const isStreaming = phase === "streaming" || phase === "uploading" || phase === "applying";
  const showApproval = phase === "awaiting_approval" && (coverLetter || pendingCoverLetter) && selectedJob;
  const isApplying = phase === "applying";

  return (
    <main className="min-h-screen flex flex-col" style={{ fontFamily: "IBM Plex Mono, monospace" }}>
      {/* Header */}
      <header className="border-b border-zinc-800 px-6 py-4 flex items-center justify-between">
        <div>
          <h1
            className="text-2xl font-bold text-zinc-100"
            style={{ fontFamily: "Playfair Display, serif" }}
          >
            Windrush
          </h1>
          <p className="text-xs text-zinc-500 mt-0.5">AI-powered career transition navigator</p>
        </div>
        <div className="flex items-center gap-2">
          {isStreaming && (
            <span className="flex items-center gap-1.5 text-xs text-teal-400">
              <span className="w-2 h-2 rounded-full bg-teal-400 animate-pulse" />
              Agent running
            </span>
          )}
          {phase === "done" && appliedConfirmation && (
            <span className="text-xs text-teal-400">{appliedConfirmation}</span>
          )}
        </div>
      </header>

      {/* Body — 3-column layout */}
      <div className="flex-1 flex overflow-hidden" style={{ height: "calc(100vh - 73px)" }}>
        {/* Left column (1/3): upload + results */}
        <div className="w-1/3 border-r border-zinc-800 flex flex-col overflow-y-auto">
          {/* Upload zone */}
          <div className="p-6 border-b border-zinc-800">
            <label
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              className={`flex flex-col items-center justify-center border-2 border-dashed rounded-lg p-8 cursor-pointer transition-colors ${
                dragOver
                  ? "border-teal-500 bg-teal-500/5"
                  : "border-zinc-700 hover:border-zinc-500"
              } ${isStreaming ? "opacity-50 pointer-events-none" : ""}`}
            >
              <input
                type="file"
                accept=".pdf"
                className="hidden"
                onChange={handleFileInput}
                disabled={isStreaming}
              />
              <div className="text-3xl mb-2">📄</div>
              <div className="text-sm text-zinc-300 font-medium">Drop CV here</div>
              <div className="text-xs text-zinc-600 mt-1">PDF only · click or drag</div>
            </label>
          </div>

          {/* CV Profile */}
          {cvProfile && (
            <div className="p-6 border-b border-zinc-800 space-y-1">
              <h3 className="text-xs uppercase tracking-widest text-zinc-500 mb-3">Profile</h3>
              {cvProfile.name && <div className="text-sm font-semibold">{cvProfile.name}</div>}
              {cvProfile.email && <div className="text-xs text-zinc-400">{cvProfile.email}</div>}
              {cvProfile.location && <div className="text-xs text-zinc-400">{cvProfile.location}</div>}
              {cvProfile.experience_years != null && (
                <div className="text-xs text-zinc-400">{cvProfile.experience_years} yrs exp</div>
              )}
              {cvProfile.skills && cvProfile.skills.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {cvProfile.skills.slice(0, 8).map((s) => (
                    <span key={s} className="text-xs px-2 py-0.5 bg-zinc-800 rounded text-zinc-300">
                      {s}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Risk Radar */}
          {skillRisks.length > 0 && (
            <div className="p-6 border-b border-zinc-800">
              <RiskRadar risks={skillRisks} />
            </div>
          )}

          {/* Job List */}
          {jobs.length > 0 && (
            <div className="p-6 border-b border-zinc-800">
              <JobList
                jobs={jobs}
                onSelect={setSelectedJob}
                selectedId={selectedJob?.job_id}
              />
            </div>
          )}

          {/* Skill Roadmap */}
          {roadmap.length > 0 && (
            <div className="p-6">
              <SkillRoadmap items={roadmap} />
            </div>
          )}

          {/* Empty state */}
          {!cvProfile && !skillRisks.length && !jobs.length && phase === "idle" && (
            <div className="p-6 text-center text-zinc-600 text-xs">
              Upload a CV PDF to begin
            </div>
          )}
        </div>

        {/* Right column (2/3): Agent Log */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="p-4 border-b border-zinc-800 flex items-center justify-between shrink-0">
            <h2 className="text-xs uppercase tracking-widest text-zinc-500">Agent Log</h2>
            {events.length > 0 && (
              <button
                onClick={() => { setEvents([]); setPhase("idle"); }}
                className="text-xs text-zinc-600 hover:text-zinc-400 transition-colors"
              >
                Clear
              </button>
            )}
          </div>
          <div className="flex-1 p-4 overflow-hidden">
            <AgentLog events={events} />
          </div>
        </div>
      </div>

      {/* Cover Letter Approval Modal */}
      {showBrowser && (
        <BrowserView
          action={browserAction}
          screenshot={browserScreenshot}
          blocked={browserBlocked}
          reason={browserReason}
          sessionId={sessionId}
          interactive={browserInteractive}
          onInstructionSent={() => setBrowserBlocked(false)}
        />
      )}

      {showApproval && (
        <CoverLetter
          coverLetter={coverLetter || pendingCoverLetter}
          jobTitle={selectedJob!.title}
          company={selectedJob!.company}
          onApprove={handleApprove}
          onSkip={() => { setCoverLetter(""); setPendingCoverLetter(""); setPhase("done"); }}
          applying={isApplying}
        />
      )}
    </main>
  );
}
