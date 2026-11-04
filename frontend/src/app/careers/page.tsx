"use client";

import { useEffect, useState } from "react";
import TopBar, { Page } from "@/components/ui/TopBar";
import { Bar, buttonClass, Callout, cx, EmptyState, Skeleton, Spinner, TextLink } from "@/components/ui/kit";
import { useResource } from "@/lib/store";
import { postStream } from "@/lib/sse";
import { shortDate } from "@/lib/format";
import { noScoreReason, riskLevel, RISK } from "@/lib/status";
import type { CareerExposure, OccupationEvidence, Persona, RoleExposure, TaskEvidence } from "@/lib/types";

interface RoadmapItem { skill: string; reason?: string; action?: string; timeline?: string; resource?: string }
interface SavedRoadmap { items: RoadmapItem[]; at: string; target: string }

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

function monthName(month: string): string {
  return new Date(`${month}-01T00:00:00Z`).toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
}

function RoleRow({ role }: { role: RoleExposure }) {
  const level = role.exposure != null ? riskLevel(role.exposure) : null;
  return (
    <li className="flex flex-col gap-[6px] px-5 py-[13px] border-b border-divider last:border-0">
      <span className="flex justify-between items-baseline gap-3">
        <span className="min-w-0 text-[13.5px] font-medium">{role.title}</span>
        {level ? (
          <span className={cx("font-mono text-[12px] font-semibold shrink-0", RISK[level].text)}>{role.exposure}% · {level}</span>
        ) : (
          <span className="text-[12px] text-ink-3 shrink-0">Not enough data</span>
        )}
      </span>
      {level && <Bar value={role.exposure as number} className={RISK[level].bar} />}
      <span className="text-[12.5px] leading-[1.45] text-ink-2">
        {level ? `Published figure for ${role.occupation}.` : noScoreReason(role.occupation)}
      </span>
    </li>
  );
}

function RoleList({ id, title, roles }: { id: string; title: string; roles: RoleExposure[] }) {
  return (
    <section aria-labelledby={id} className="bg-surface border border-border rounded-card overflow-hidden">
      <h2 id={id} className="m-0 px-5 pt-4 pb-2 text-[15.5px] font-semibold">{title}</h2>
      <ul className="list-none m-0 p-0">
        {roles.map((r) => <RoleRow key={r.title} role={r} />)}
      </ul>
    </section>
  );
}

function TaskList({ title, tasks }: { title: string; tasks: TaskEvidence[] }) {
  return (
    <div className="flex flex-col gap-2 min-w-0">
      <h3 className="m-0 text-[13.5px] font-semibold">{title}</h3>
      <ul className="list-none m-0 p-0 flex flex-col gap-2">
        {tasks.map((t) => (
          <li key={t.task} className="flex justify-between gap-3 text-[12.5px] leading-[1.45] text-ink-2">
            <span className="min-w-0">{t.task}</span>
            <span className="font-mono text-[12px] shrink-0">{t.handed_to_ai}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Evidence({ evidence }: { evidence: OccupationEvidence }) {
  return (
    <section aria-labelledby="evidence" className="bg-surface border border-border rounded-card p-5 flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id="evidence" className="m-0 text-[15.5px] font-semibold">What people hand to AI in {evidence.occupation}</h2>
        <p className="m-0 text-[13px] leading-[1.5] text-ink-2 max-w-[72ch] text-pretty">
          The share of conversations about each task where the work was handed to AI rather than done with it. From
          Claude chat in {monthName(evidence.month)}, so coding tools and API use aren&apos;t included, and only {evidence.tasks_seen} of
          this occupation&apos;s {evidence.tasks_listed} listed tasks had enough conversations. The tasks are generic US
          descriptions. The roadmap below uses this as a hint.
        </p>
      </div>
      <div className="grid gap-5" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(280px, 100%), 1fr))" }}>
        <TaskList title="Handed to AI most" tasks={evidence.most_handed_to_ai} />
        <TaskList title="Handed to AI least" tasks={evidence.least_handed_to_ai} />
      </div>
    </section>
  );
}

export default function CareersPage() {
  const exposure = useResource<CareerExposure>("/api/careers/exposure");
  const persona = useResource<Persona>("/api/persona");
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

  const roles = exposure.data?.roles ?? [];
  const targetRoles = roles.filter((r) => r.kind === "target");
  const pastRoles = roles.filter((r) => r.kind === "past");
  const target = persona.data?.preferences.target_titles?.[0] ?? "";

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

  return (
    <>
      <TopBar crumbs={[{ label: "Grow" }, { label: "AI exposure & roadmap" }]} />
      <Page className="gap-5 pt-[26px] sm:pt-[26px]">
        <div className="flex flex-col gap-[6px]">
          <h1 className="m-0 text-[26px] font-semibold tracking-[-0.025em]">How exposed are your roles to AI?</h1>
          <p className="m-0 text-[14px] text-ink-2 max-w-[72ch] text-pretty">
            Each score is the figure the Anthropic Economic Index publishes for the occupation a role belongs to: how much
            of that work AI is already seen doing, based on Claude usage in 2025 and US occupation data. It isn&apos;t a
            forecast, and Anthropic found only a slight link to projected job growth. A low score means little use seen so
            far, not that a job is safe.
          </p>
        </div>

        {exposure.error && <Callout title="Couldn't load AI exposure">{exposure.error}</Callout>}

        {exposure.loading ? (
          <Skeleton className="h-[180px] rounded-card" />
        ) : !exposure.error && roles.length === 0 ? (
          <EmptyState action={<TextLink href="/profile#prefs">Add the roles you&apos;re aiming for</TextLink>}>
            Your persona has no roles to look up yet.
          </EmptyState>
        ) : (
          <>
            {targetRoles.length > 0 && <RoleList id="target-roles" title="Roles you're aiming for" roles={targetRoles} />}
            {exposure.data?.evidence && <Evidence evidence={exposure.data.evidence} />}
            {pastRoles.length > 0 && <RoleList id="past-roles" title="Roles you've done" roles={pastRoles} />}
          </>
        )}

        <section aria-labelledby="road" className="flex flex-col gap-[14px]">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="flex flex-col gap-1">
              <h2 id="road" className="m-0 text-[18px] font-semibold tracking-[-0.015em]">
                {(roadmap?.target || target) ? `Roadmap to ${roadmap?.target || target}` : "Your roadmap"}
              </h2>
              <span className="text-[13px] text-ink-3">
                Six skills to build next, based on your persona and target role.
                {roadmap ? ` Generated ${shortDate(roadmap.at)}.` : ""}
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
