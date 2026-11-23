"use client";

import { useState } from "react";
import TopBar, { Page } from "@/components/ui/TopBar";
import { Bar, buttonClass, Callout, cx, EmptyState, Skeleton, Spinner, TextLink } from "@/components/ui/kit";
import CareerPlan, { planItemIds } from "@/components/CareerPlan";
import MarketDemandPanel from "@/components/MarketDemand";
import { requestJson, useResource } from "@/lib/store";
import { postStream } from "@/lib/sse";
import { shortDate } from "@/lib/format";
import { noScoreReason, riskLevel, RISK } from "@/lib/status";
import type { CareerExposure, MarketDemand, OccupationEvidence, Persona, RoleExposure, SavedPlan, TaskEvidence } from "@/lib/types";

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
  const market = useResource<MarketDemand>("/api/careers/market");
  const stored = useResource<SavedPlan | { plan: null }>("/api/careers/plan");
  const [mine, setMine] = useState<SavedPlan | null>(null);
  const [generating, setGenerating] = useState<string | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const saved: SavedPlan | null = mine ?? (stored.data && stored.data.plan ? (stored.data as SavedPlan) : null);

  const roles = exposure.data?.roles ?? [];
  const targetRoles = roles.filter((r) => r.kind === "target");
  const pastRoles = roles.filter((r) => r.kind === "past");
  const target = persona.data?.preferences.target_titles?.[0] ?? "";

  const generate = async () => {
    setGenerating("Starting…");
    setPlanError(null);
    let made: SavedPlan | null = null;
    let failed = "";
    try {
      await postStream("/api/careers/plan", undefined, (ev) => {
        if (typeof ev.message === "string" && (ev.type === "start" || ev.type === "status")) setGenerating(ev.message);
        if (ev.type === "plan") made = ev as unknown as SavedPlan;
        if (ev.type === "error") failed = typeof ev.message === "string" ? ev.message : "The plan couldn't be written.";
      });
      if (!made) throw new Error(failed || "The plan came back empty. Try again.");
      setMine(made);
    } catch (e) {
      setPlanError(e instanceof Error ? e.message : "The plan couldn't be written.");
    } finally {
      setGenerating(null);
    }
  };

  const toggle = async (itemId: string, done: boolean) => {
    if (!saved) return;
    const before = saved;
    const next = done ? [...saved.done.filter((d) => d !== itemId), itemId] : saved.done.filter((d) => d !== itemId);
    setMine({ ...saved, done: next });
    setPlanError(null);
    try {
      const res = await requestJson<{ done: string[] }>("/api/careers/plan/items", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: saved.id, item_id: itemId, done }),
      });
      setMine({ ...before, done: res.done });
    } catch (e) {
      setMine(before);
      setPlanError(e instanceof Error ? e.message : "That didn't save. Try again.");
    }
  };

  const total = saved ? planItemIds(saved).length : 0;
  const doneCount = saved ? saved.done.length : 0;

  return (
    <>
      <TopBar crumbs={[{ label: "Grow" }, { label: "Career plan & AI exposure" }]} />
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

        {market.error && <Callout title="Couldn't load what employers ask for">{market.error}</Callout>}
        {market.loading ? <Skeleton className="h-[220px] rounded-card" /> : market.data && <MarketDemandPanel market={market.data} />}

        <section aria-labelledby="plan" className="flex flex-col gap-[14px]">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="flex flex-col gap-1">
              <h2 id="plan" className="m-0 text-[18px] font-semibold tracking-[-0.015em]">
                {(saved?.target || target) ? `Your plan for ${saved?.target || target}` : "Your plan"}
              </h2>
              <span className="text-[13px] text-ink-3">
                From your whole profile, your target roles, what their ads ask for and how your applications are going.
                {saved ? ` Made ${shortDate(saved.created_at)} · ${doneCount} of ${total} done.` : ""}
              </span>
            </div>
            <button type="button" onClick={generate} disabled={!!generating} className={buttonClass("primary", "top")}>
              {generating ? <><Spinner /> {generating}</> : saved ? "Make a new plan" : "Make my plan"}
            </button>
          </div>
          {planError && <Callout>{planError}</Callout>}
          {stored.error && !saved && <Callout title="Couldn't load your plan">{stored.error}</Callout>}
          {generating ? (
            <div className="grid gap-[14px]" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(340px, 100%), 1fr))" }}
              aria-label="Writing your plan" role="status">
              {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[260px] rounded-card" />)}
            </div>
          ) : stored.loading && !saved ? (
            <Skeleton className="h-[260px] rounded-card" />
          ) : saved ? (
            <CareerPlan saved={saved} onToggle={toggle} />
          ) : (
            <EmptyState>
              Make a plan to {target || "the roles you want"}: where you stand, goals with dates, and for each gap a study
              guide, a project that builds on your own work and a proof point to aim for.
            </EmptyState>
          )}
        </section>
      </Page>
    </>
  );
}
