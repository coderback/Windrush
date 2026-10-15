"use client";

import { useEffect, useMemo, useState } from "react";
import TopBar, { Page } from "@/components/ui/TopBar";
import { PillTabs } from "@/components/ui/Tabs";
import { buttonClass, Callout, cx, EmptyState, Skeleton, Spinner, TextLink } from "@/components/ui/kit";
import Icon from "@/components/ui/Icon";
import { useResource } from "@/lib/store";
import { postStream } from "@/lib/sse";
import { shortDate } from "@/lib/format";
import { riskLevel, RISK, type RiskLevel } from "@/lib/status";
import type { Persona, SkillRisk } from "@/lib/types";

interface RoadmapItem { skill: string; reason?: string; action?: string; timeline?: string; resource?: string }
interface SavedRoadmap { items: RoadmapItem[]; at: string; target: string }

type Filter = "All" | RiskLevel;

/* The last roadmap is kept in this browser, per account, so it survives a reload. */
function roadmapKey(): string | null {
  try {
    const token = localStorage.getItem("windrush_token") || "";
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return payload.user_id ? `windrush_roadmap_${payload.user_id}` : null;
  } catch {
    return null;
  }
}

function SummaryCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="bg-surface border border-border rounded-card p-[18px] flex flex-col gap-[10px]">
      <span className="micro">{label}</span>
      {children}
    </section>
  );
}

export default function CareersPage() {
  const risks = useResource<{ skill_risks?: SkillRisk[] }>("/api/score-skills", { init: { method: "POST" }, staleMs: Infinity });
  const persona = useResource<Persona>("/api/persona");
  const [filter, setFilter] = useState<Filter>("All");
  const [roadmap, setRoadmap] = useState<SavedRoadmap | null>(null);
  const [generating, setGenerating] = useState(false);
  const [roadmapError, setRoadmapError] = useState<string | null>(null);

  useEffect(() => {
    const key = roadmapKey();
    if (!key) return;
    try {
      const raw = localStorage.getItem(key);
      if (raw) setRoadmap(JSON.parse(raw));
    } catch {}
  }, []);

  const all = useMemo(() => [...(risks.data?.skill_risks ?? [])].sort((a, b) => b.exposure_score - a.exposure_score),
    [risks.data]);
  const groupOf = useMemo(() => {
    const m = new Map<string, string>();
    persona.data?.skills.forEach((g) => g.skills.forEach((s) => m.set(s.toLowerCase(), g.category)));
    persona.data?.history.forEach((h) => { if (h.title && !m.has(h.title.toLowerCase())) m.set(h.title.toLowerCase(), "Job title"); });
    return m;
  }, [persona.data]);

  const counts = { All: all.length, High: 0, Medium: 0, Low: 0 } as Record<Filter, number>;
  all.forEach((r) => { counts[riskLevel(r.exposure_score)] += 1; });
  const rows = filter === "All" ? all : all.filter((r) => riskLevel(r.exposure_score) === filter);

  const overall = all.length ? Math.round(all.reduce((n, r) => n + r.exposure_score, 0) / all.length) : null;
  const resilient = all.length ? all[all.length - 1] : null;
  const target = persona.data?.preferences.target_titles?.[0] ?? "";
  const targetScore = target ? all.find((r) => r.skill.toLowerCase() === target.toLowerCase()) : undefined;

  const generate = async () => {
    setGenerating(true);
    setRoadmapError(null);
    let items: RoadmapItem[] = [];
    try {
      await postStream("/api/careers/roadmap", undefined, (ev) => {
        if (ev.type === "roadmap" && Array.isArray(ev.items)) items = ev.items as RoadmapItem[];
      });
      if (!items.length) throw new Error("The roadmap came back empty. Try again.");
      const saved = { items, at: new Date().toISOString(), target };
      setRoadmap(saved);
      const key = roadmapKey();
      if (key) try { localStorage.setItem(key, JSON.stringify(saved)); } catch {}
    } catch (e) {
      setRoadmapError(e instanceof Error ? e.message : "Roadmap generation failed.");
    } finally {
      setGenerating(false);
    }
  };

  const level = overall != null ? riskLevel(overall) : null;

  return (
    <>
      <TopBar crumbs={[{ label: "Grow" }, { label: "AI exposure & roadmap" }]}>
        <button type="button" onClick={() => risks.reload().catch(() => {})} disabled={risks.refreshing}
          className={buttonClass("secondary", "top")}>
          {risks.refreshing ? <Spinner /> : <Icon name="refresh" size={15} />}Rescore my skills
        </button>
      </TopBar>
      <Page className="gap-5 pt-[26px] sm:pt-[26px]">
        <div className="flex flex-col gap-[6px]">
          <h1 className="m-0 text-[26px] font-semibold tracking-[-0.025em]">How exposed is your work to AI?</h1>
          <p className="m-0 text-[14px] text-ink-2 max-w-[72ch] text-pretty">
            Scores are looked up in the Anthropic Economic Index and about 18,000 O*NET tasks. The model only writes the
            explanations, it does not pick the numbers.
          </p>
        </div>

        {risks.error && <Callout title="Couldn't score your skills">{risks.error}</Callout>}

        {risks.loading ? (
          <div className="grid gap-[14px]" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(280px, 100%), 1fr))" }}>
            {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-[150px] rounded-card" />)}
          </div>
        ) : !risks.error && all.length === 0 ? (
          <EmptyState action={<TextLink href="/profile#skills">Add skills to your persona</TextLink>}>
            Your persona has no skills to score yet.
          </EmptyState>
        ) : all.length > 0 && (
          <div className="grid gap-[14px]" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(280px, 100%), 1fr))" }}>
            <SummaryCard label="Your skill mix">
              <span className="flex items-baseline gap-[10px] mt-1">
                <span className="font-mono text-[38px] font-medium tracking-[-0.04em] leading-none">{overall}%</span>
                {level && <span className={cx("text-[14px] font-semibold", RISK[level].text)}>{level}</span>}
              </span>
              <div className="flex flex-col gap-[6px] mt-1">
                <span className="relative block">
                  <span className="flex h-2 rounded-full overflow-hidden gap-[2px]" aria-hidden="true">
                    <span className="bg-scale-low" style={{ flex: 35 }} />
                    <span className="bg-scale-mid" style={{ flex: 30 }} />
                    <span className="bg-scale-high" style={{ flex: 35 }} />
                  </span>
                  <span aria-hidden="true" className="absolute -top-[2px] w-[3px] h-3 rounded-[2px] bg-ink -translate-x-1/2"
                    style={{ left: `${overall}%` }} />
                </span>
                <span className="flex justify-between font-mono text-[11px] text-ink-3">
                  <span>Low &lt;35</span><span>Medium</span><span>High ≥65</span>
                </span>
              </div>
            </SummaryCard>
            <SummaryCard label="Target role">
              <span className="text-[17px] font-semibold">{target || "No target role set"}</span>
              {targetScore ? (
                <span className="flex items-baseline gap-2">
                  <span className="font-mono text-[26px] font-medium">{targetScore.exposure_score}%</span>
                  <span className={cx("text-[13px] font-semibold", RISK[riskLevel(targetScore.exposure_score)].text)}>{riskLevel(targetScore.exposure_score)}</span>
                </span>
              ) : (
                <span className="text-[13px] leading-[1.5] text-ink-2">
                  {target
                    ? "Target roles aren't scored yet; the scores cover your skills and past job titles."
                    : <>Add the roles you&apos;re aiming for in <TextLink href="/profile#prefs" className="text-[13px]">Job preferences</TextLink>.</>}
                </span>
              )}
              {targetScore?.reasoning && <span className="text-[13px] leading-[1.5] text-ink-2">{targetScore.reasoning}</span>}
            </SummaryCard>
            <SummaryCard label="Most resilient skill">
              {resilient && (
                <>
                  <span className="text-[17px] font-semibold">{resilient.skill}</span>
                  <span className="flex items-baseline gap-2">
                    <span className="font-mono text-[26px] font-medium">{resilient.exposure_score}%</span>
                    <span className={cx("text-[13px] font-semibold", RISK[riskLevel(resilient.exposure_score)].text)}>{riskLevel(resilient.exposure_score)}</span>
                  </span>
                  <span className="text-[13px] leading-[1.5] text-ink-2">Lead with it on your CV and in interviews.</span>
                </>
              )}
            </SummaryCard>
          </div>
        )}

        {all.length > 0 && (
          <section aria-labelledby="skills" className="bg-surface border border-border rounded-card overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4">
              <h2 id="skills" className="m-0 text-[15.5px] font-semibold">Skill by skill</h2>
              <PillTabs label="Filter by level" value={filter} onChange={setFilter}
                items={(["All", "High", "Medium", "Low"] as Filter[]).map((k) => ({ key: k, label: `${k} ${counts[k]}` }))} />
            </div>
            <div className="relative overflow-x-auto mt-3">
              <table className="w-full min-w-[760px] border-collapse text-[13.5px]">
                <thead>
                  <tr className="bg-subtle border-y border-track text-left">
                    <th scope="col" className="micro font-normal px-5 py-[10px] w-[24%]">Skill</th>
                    <th scope="col" className="micro font-normal px-3 py-[10px] w-[16%]">Group</th>
                    <th scope="col" className="micro font-normal px-3 py-[10px] w-[240px]">Exposure</th>
                    <th scope="col" className="micro font-normal pl-3 pr-5 py-[10px]">Why</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const l = riskLevel(r.exposure_score);
                    return (
                      <tr key={r.skill} className="border-b border-divider last:border-0 align-middle">
                        <td className="px-5 py-[13px] font-medium">{r.skill}</td>
                        <td className="px-3 py-[13px] text-ink-2">{groupOf.get(r.skill.toLowerCase()) ?? "–"}</td>
                        <td className="px-3 py-[13px]">
                          <span className="flex items-center gap-[10px]">
                            <span className="flex-1 block h-[6px] rounded-full bg-track overflow-hidden" aria-hidden="true">
                              <span className={cx("block h-full rounded-full", RISK[l].bar)} style={{ width: `${r.exposure_score}%` }} />
                            </span>
                            <span className={cx("font-mono text-[12px] font-semibold min-w-20", RISK[l].text)}>{r.exposure_score} {l}</span>
                          </span>
                        </td>
                        <td className="pl-3 pr-5 py-[13px] text-ink-2 leading-[1.45]">{r.reasoning || "–"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        <section aria-labelledby="road" className="flex flex-col gap-[14px]">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="flex flex-col gap-1">
              <h2 id="road" className="m-0 text-[18px] font-semibold tracking-[-0.015em]">
                {(roadmap?.target || target) ? `Roadmap to ${roadmap?.target || target}` : "Your roadmap"}
              </h2>
              <span className="text-[13px] text-ink-3">
                Six skills that hold their value as AI takes on routine work.
                {roadmap ? ` Generated ${shortDate(roadmap.at)} from your persona.` : ""}
              </span>
            </div>
            <button type="button" onClick={generate} disabled={generating} className={buttonClass("primary", "top")}>
              {generating ? <><Spinner /> Generating…</> : roadmap ? "Regenerate roadmap" : "Generate roadmap"}
            </button>
          </div>
          {roadmapError && <Callout>{roadmapError}</Callout>}
          {generating ? (
            <ol className="list-none m-0 p-0 grid gap-[14px]" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(300px, 100%), 1fr))" }}
              aria-label="Generating your roadmap" role="status">
              {Array.from({ length: 6 }).map((_, i) => <li key={i}><Skeleton className="h-[210px] rounded-card" /></li>)}
            </ol>
          ) : roadmap ? (
            <ol className="list-none m-0 p-0 grid gap-[14px]" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(300px, 100%), 1fr))" }}>
              {roadmap.items.map((r, i) => (
                <li key={i} className="bg-surface border border-border rounded-card p-[18px] flex flex-col gap-3">
                  <span className="font-mono text-[12px] text-ink-3">{String(i + 1).padStart(2, "0")}</span>
                  <span className="text-[16px] font-semibold leading-[1.3]">{r.skill}</span>
                  {r.reason && <span className="text-[13px] leading-[1.5] text-ink-2">{r.reason}</span>}
                  {(r.action || r.resource) && (
                    <span className="flex flex-col gap-1 px-3 py-[10px] rounded-[10px] bg-subtle border border-track">
                      <span className="text-[12px] font-semibold">Start with</span>
                      {r.action && <span className="text-[12.5px] leading-[1.45] text-ink-2">{r.action}</span>}
                      {r.resource && <span className="text-[12.5px] leading-[1.45] text-teal-deep">{r.resource}</span>}
                    </span>
                  )}
                  {r.timeline && <span className="mt-auto text-[12px] text-ink-3">{r.timeline}</span>}
                </li>
              ))}
            </ol>
          ) : (
            <EmptyState>
              Generate a six-step plan built on your strongest skills and aimed at {target || "the roles you want"}.
            </EmptyState>
          )}
        </section>
      </Page>
    </>
  );
}
