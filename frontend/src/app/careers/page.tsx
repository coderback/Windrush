"use client";

import { useEffect, useState } from "react";
import { authFetch } from "../api";

interface SkillRisk {
  skill: string;
  exposure_score: number;
  risk_label: string;
}

interface RoadmapItem {
  skill: string;
  action: string;
  timeline: string;
  resource: string;
}

const RISK_BAR_COLOR: Record<string, string> = {
  High: "bg-red-500",
  Medium: "bg-yellow-500",
  Low: "bg-teal-500",
};

const RISK_TEXT_COLOR: Record<string, string> = {
  High: "text-red-400",
  Medium: "text-yellow-400",
  Low: "text-teal-400",
};

export default function CareersPage() {
  const [risks, setRisks] = useState<SkillRisk[]>([]);
  const [roadmap, setRoadmap] = useState<RoadmapItem[]>([]);
  const [loadingRisks, setLoadingRisks] = useState(true);
  const [loadingRoadmap, setLoadingRoadmap] = useState(false);
  const [roadmapStarted, setRoadmapStarted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    authFetch("/api/score-skills", { method: "POST" })
      .then((r) => r.json())
      .then((data: { skill_risks?: SkillRisk[] }) => {
        setRisks((data.skill_risks ?? []).sort((a, b) => b.exposure_score - a.exposure_score));
      })
      .catch(() => setError("Failed to load skill risks"))
      .finally(() => setLoadingRisks(false));
  }, []);

  const generateRoadmap = async () => {
    setRoadmapStarted(true);
    setLoadingRoadmap(true);
    setRoadmap([]);
    setError(null);
    try {
      const res = await authFetch("/api/careers/roadmap", { method: "POST" });
      if (!res.ok) throw new Error("Roadmap generation failed");
      if (!res.body) return;

      const reader = res.body.getReader();
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
            if (ev.type === "roadmap" && ev.items) {
              setRoadmap(ev.items as RoadmapItem[]);
            }
          } catch {}
        }
      }
    } catch (err: unknown) {
      setError(String(err));
    } finally {
      setLoadingRoadmap(false);
    }
  };

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-zinc-100" style={{ fontFamily: "Playfair Display, serif" }}>
          Careers
        </h1>
        <p className="text-zinc-500 text-sm mt-1">Understand your AI exposure risk and plan your pivot</p>
      </div>

      {error && (
        <div className="p-3 bg-red-500/10 border border-red-500/20 text-red-400 text-sm rounded-lg">
          {error}
        </div>
      )}

      {/* Section A — Skill Exposure Risk */}
      <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
        <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-widest mb-5">
          AI Skill Exposure Risk
        </h2>

        {loadingRisks ? (
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-8 bg-zinc-800/50 rounded animate-pulse" />
            ))}
          </div>
        ) : risks.length === 0 ? (
          <p className="text-zinc-600 text-sm">
            No skills found in your profile. Upload a CV or fill in your Skills in Profile.
          </p>
        ) : (
          <div className="space-y-3">
            {risks.map((s) => (
              <div key={s.skill} className="flex items-center gap-4">
                <span className="text-sm text-zinc-300 w-40 truncate shrink-0">{s.skill}</span>
                <div className="flex-1 h-2 bg-zinc-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${RISK_BAR_COLOR[s.risk_label] ?? "bg-zinc-500"}`}
                    style={{ width: `${s.exposure_score}%` }}
                  />
                </div>
                <span className="text-xs text-zinc-500 w-8 text-right">{s.exposure_score}%</span>
                <span className={`text-xs font-medium w-14 ${RISK_TEXT_COLOR[s.risk_label] ?? "text-zinc-400"}`}>
                  {s.risk_label}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Section B — Skill Pivot Roadmap */}
      <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-widest">
            Skill Pivot Roadmap
          </h2>
          {!roadmapStarted && (
            <button
              onClick={generateRoadmap}
              disabled={loadingRisks || risks.length === 0}
              className="px-4 py-2 text-sm font-bold bg-white text-black rounded-lg hover:bg-zinc-200 transition-colors disabled:opacity-50"
            >
              Generate Roadmap →
            </button>
          )}
          {roadmapStarted && !loadingRoadmap && (
            <button onClick={generateRoadmap} className="text-xs text-zinc-600 hover:text-zinc-400">
              Regenerate
            </button>
          )}
        </div>

        {loadingRoadmap && (
          <div className="flex items-center gap-2 text-sm text-zinc-500 py-4">
            <span className="w-2 h-2 rounded-full bg-teal-400 animate-pulse" />
            Generating your personalised roadmap…
          </div>
        )}

        {!loadingRoadmap && roadmap.length === 0 && !roadmapStarted && (
          <p className="text-zinc-600 text-sm">
            Click "Generate Roadmap" to get a personalised 6-step pivot plan based on your skill risk profile.
          </p>
        )}

        {roadmap.length > 0 && (
          <div className="relative">
            <div className="absolute left-3.5 top-0 bottom-0 w-px bg-zinc-800" />
            <div className="space-y-6">
              {roadmap.map((item, i) => (
                <div key={i} className="relative pl-10">
                  <div className="absolute left-0 w-7 h-7 rounded-full border-2 border-teal-500 bg-zinc-900 flex items-center justify-center">
                    <span className="text-[10px] font-bold text-teal-400">{i + 1}</span>
                  </div>
                  <div className="bg-zinc-950/50 border border-zinc-800 rounded-xl p-4 space-y-2">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold text-zinc-100">{item.skill}</p>
                      <span className="text-[10px] px-2 py-0.5 border border-zinc-700 text-zinc-500 rounded-full shrink-0">
                        {item.timeline}
                      </span>
                    </div>
                    <p className="text-xs text-zinc-400">{item.action}</p>
                    {item.resource && (
                      <p className="text-xs text-teal-600">{item.resource}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}