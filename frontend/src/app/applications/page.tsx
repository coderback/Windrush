"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import Icon from "@/components/ui/Icon";
import TopBar, { Page } from "@/components/ui/TopBar";
import SlideOver from "@/components/ui/SlideOver";
import { Segmented } from "@/components/ui/Tabs";
import {
  buttonClass, Callout, Chip, CompanyMark, cx, EmptyState, labelClass, Skeleton, StatusChip, textareaClass,
} from "@/components/ui/kit";
import { useResource } from "@/lib/store";
import { setStatus } from "@/lib/actions";
import { daysSince, longAgo, shortDate } from "@/lib/format";
import { applicationLink } from "@/lib/jobs";
import { CLOSED, CLOSED_STAGES, OPEN_STAGES, STATUS_CHOICES, stageOf, statusMeta } from "@/lib/status";
import type { Application } from "@/lib/types";

type View = "board" | "table";
type Quick = "review" | "follow" | "quiet";

const FOLLOW_UP_DAYS = 7;
const QUIET_DAYS = 14;

const appliedDays = (a: Application) => (a.status === "Applied" ? daysSince(a.date_applied) : null);

const QUICK: { key: Quick; label: string; dot: string; test: (a: Application) => boolean }[] = [
  { key: "review", label: "Needs review", dot: "bg-amber", test: (a) => a.status === "Pending Review" },
  { key: "follow", label: "Follow-up due", dot: "bg-blue",
    test: (a) => { const d = appliedDays(a); return d != null && d >= FOLLOW_UP_DAYS && d < QUIET_DAYS; } },
  { key: "quiet", label: `No reply in ${QUIET_DAYS}+ days`, dot: "bg-stone",
    test: (a) => { const d = appliedDays(a); return d != null && d >= QUIET_DAYS; } },
];

const LEVEL: Record<string, string> = { strong: "Strong", ok: "Reasonable", reach: "Stretch" };
/** The level match, only when the job was analysed (unanalysed rows carry the default "ok"). */
const levelOf = (a: Application) => ((a.fit_score ?? 0) > 0 ? LEVEL[a.level_match] ?? "–" : "–");

function dateLine(a: Application): string {
  switch (a.status) {
    case "Pending Review": return `Filled ${longAgo(a.created_at) ?? ""}`;
    case "Saved":
    case "Evaluated": return `Saved ${longAgo(a.created_at) ?? ""}`;
    default: return a.date_applied ? `Applied ${shortDate(a.date_applied)}` : `Added ${shortDate(a.created_at) ?? ""}`;
  }
}

function StageAge({ days }: { days: number }) {
  const overdue = days >= QUIET_DAYS;
  return (
    <span title={`${days} days in Applied${overdue ? ", no reply yet" : ""}`}
      className={cx("flex items-center gap-1 h-5 px-[7px] rounded-[6px] font-mono text-[11px] font-semibold",
        overdue ? "bg-amber-soft text-amber-text" : "bg-muted text-ink-2")}>
      <Icon name="clock" size={11} strokeWidth={2.2} />{days}d
      <span className="sr-only"> in this stage</span>
    </span>
  );
}

function BoardCard({ app, selected, onOpen, onDragStart }: {
  app: Application; selected: boolean; onOpen: () => void; onDragStart: (e: React.DragEvent) => void;
}) {
  const days = appliedDays(app);
  return (
    <button type="button" draggable onDragStart={onDragStart} onClick={onOpen}
      aria-label={`${app.job_title} at ${app.company}, ${statusMeta(app.status).label}. Open details`}
      className={cx("flex flex-col gap-2 w-full text-left p-3 rounded-inner bg-surface text-ink border shadow-lift cursor-grab active:cursor-grabbing",
        selected ? "border-teal" : "border-border hover:border-border-strong")}>
      <span className="flex gap-2 items-center min-w-0">
        <CompanyMark name={app.company} size={22} />
        <span className="text-[12px] text-ink-2 truncate">{app.company}</span>
      </span>
      <span className="text-[13.5px] font-semibold leading-[1.3]">{app.job_title}</span>
      <span className="text-[12px] text-ink-3">{dateLine(app)}</span>
      {(days != null || (app.fit_score ?? 0) > 0) && (
        <span className="flex justify-between items-center gap-[6px]">
          {days != null ? <StageAge days={days} /> : <span />}
          {(app.fit_score ?? 0) > 0 && (
            <span className="font-mono text-[11.5px] font-semibold px-[7px] py-[2px] rounded-full bg-muted text-ink">{Math.round(app.fit_score!)} fit</span>
          )}
        </span>
      )}
    </button>
  );
}

export default function ApplicationsPage() {
  const apps = useResource<Application[]>("/api/applications");
  const [view, setView] = useState<View>("board");
  const [query, setQuery] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const [quick, setQuick] = useState<Quick | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Slide-over edits
  const [notes, setNotes] = useState("");
  const [savingNotes, setSavingNotes] = useState(false);
  const [notesSaved, setNotesSaved] = useState(false);

  const all = useMemo(() => apps.data ?? [], [apps.data]);
  const open = all.find((a) => a.id === openId) ?? null;

  useEffect(() => {
    if (open) {
      setNotes(open.notes ?? "");
      setNotesSaved(false);
    }
    // Only when a different application opens, not on each data refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openId]);

  const closedCount = all.filter((a) => CLOSED.has(a.status)).length;
  const activeCount = all.length - closedCount;

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const test = QUICK.find((x) => x.key === quick)?.test;
    return all.filter((a) =>
      (showClosed || !CLOSED.has(a.status)) &&
      (!q || a.job_title.toLowerCase().includes(q) || a.company.toLowerCase().includes(q)) &&
      (!test || test(a)));
  }, [all, query, showClosed, quick]);

  const columns = [...OPEN_STAGES, ...(showClosed ? CLOSED_STAGES : [])];

  const move = async (id: string, status: string) => {
    const app = all.find((a) => a.id === id);
    if (!app || stageOf(app.status) === status) return;
    setError(null);
    try {
      await setStatus(id, status);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't change the status.");
    }
  };

  const saveNotes = async () => {
    if (!open) return;
    setSavingNotes(true);
    setError(null);
    try {
      await setStatus(open.id, open.status, notes);
      setNotesSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the notes.");
    } finally {
      setSavingNotes(false);
    }
  };

  const avgApplied = (() => {
    const ds = all.map(appliedDays).filter((d): d is number => d != null);
    return ds.length ? Math.round(ds.reduce((n, d) => n + d, 0) / ds.length) : null;
  })();

  const link = open ? applicationLink(open) : null;

  return (
    <>
      <TopBar crumbs={[{ label: "Workspace" }, { label: "Applications" }]}>
        <Link href="/jobs?paste=1" className={buttonClass("primary", "top")}>
          <Icon name="plus" size={15} strokeWidth={2} />Track a job
        </Link>
      </TopBar>
      <Page wide="full" className="gap-4 pt-6 sm:pt-6 pb-10">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex flex-col gap-[6px]">
            <h1 className="m-0 text-[26px] font-semibold tracking-[-0.025em]">Applications</h1>
            <p className="m-0 text-[14px] text-ink-2">
              {activeCount} active, {closedCount} closed.{view === "board" && all.length > 0 ? " Drag a card to change its status." : ""}
            </p>
          </div>
          <div className="flex flex-wrap gap-2 items-center">
            <Segmented label="View" value={view} onChange={setView}
              items={[{ key: "board", label: "Board" }, { key: "table", label: "Table" }]} />
            <span className="flex items-center gap-2 h-9 px-3 border border-border rounded-control bg-surface text-ink-3 focus-within:border-teal">
              <Icon name="search" size={15} />
              <label htmlFor="app-search" className="sr-only">Search applications</label>
              <input id="app-search" type="search" placeholder="Search" value={query} onChange={(e) => setQuery(e.target.value)}
                className="w-[140px] border-0 bg-transparent text-[13px] outline-none text-ink placeholder:text-ink-3" />
            </span>
            <button type="button" aria-pressed={showClosed} onClick={() => setShowClosed((s) => !s)}
              className={cx(buttonClass("secondary", "sm", "h-9 font-normal"), showClosed && "bg-muted font-semibold")}>
              {showClosed ? "Hide closed" : `Show closed (${closedCount})`}
            </button>
          </div>
        </div>

        <div role="group" aria-label="Quick filters" className="flex flex-wrap items-center gap-2">
          <span className="text-[13px] text-ink-3 mr-[2px]">Needs attention</span>
          {QUICK.map((q) => {
            const on = quick === q.key;
            const n = all.filter(q.test).length;
            return (
              <button key={q.key} type="button" aria-pressed={on} onClick={() => setQuick(on ? null : q.key)}
                className={cx("flex items-center gap-2 h-[34px] pl-3 pr-[6px] rounded-full text-[13px] border",
                  on ? "border-ink bg-ink text-on-ink font-semibold" : "border-border bg-surface text-ink font-medium hover:border-border-strong")}>
                <span aria-hidden="true" className={cx("w-[7px] h-[7px] rounded-full", q.dot)} />{q.label}
                <span className={cx("min-w-[22px] h-[22px] px-[6px] rounded-full flex items-center justify-center font-mono text-[11.5px] font-semibold",
                  on ? "bg-white/20 text-on-ink" : "bg-muted text-ink")}>{n}</span>
              </button>
            );
          })}
        </div>

        {error && <Callout>{error}</Callout>}

        {apps.loading ? (
          <div className="grid gap-[10px] grid-cols-2 md:grid-cols-6">
            {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[260px] rounded-[14px]" />)}
          </div>
        ) : apps.error ? (
          <Callout title="Couldn't load your applications">{apps.error}</Callout>
        ) : all.length === 0 ? (
          <EmptyState action={<Link href="/jobs" className={buttonClass("primary", "sm")}>Browse matches</Link>}>
            No applications yet. Save a job from the feed or let the agent apply, and it shows up here.
          </EmptyState>
        ) : view === "board" ? (
          <div className="relative overflow-x-auto pb-[6px] -mx-1 px-1">
            <div className="grid gap-[10px] items-start"
              style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(176px, 1fr))`, minWidth: columns.length * 186 }}>
              {columns.map((col) => {
                const cards = shown.filter((a) => stageOf(a.status) === col);
                const meta = statusMeta(col);
                return (
                  <section key={col} aria-label={`${meta.label}, ${cards.length}`}
                    onDragOver={(e) => { e.preventDefault(); setDragOver(col); }}
                    onDragLeave={() => setDragOver((d) => (d === col ? null : d))}
                    onDrop={(e) => { e.preventDefault(); setDragOver(null); const id = e.dataTransfer.getData("text/plain"); if (id) move(id, col); }}
                    className={cx("min-w-0 flex flex-col gap-2 p-[10px] rounded-[14px] bg-track transition-shadow",
                      dragOver === col && "shadow-[inset_0_0_0_2px_var(--teal)]")}>
                    <h2 className="m-0 flex flex-col gap-[2px] px-1 pt-1 pb-[6px]">
                      <span className="flex items-center gap-2 text-[13.5px] font-semibold">
                        <span aria-hidden="true" className={cx("w-2 h-2 rounded-[3px]", meta.dot)} />
                        {meta.label}
                        <span className="font-mono text-[11.5px] font-medium text-ink-2">{cards.length}</span>
                      </span>
                      {col === "Applied" && avgApplied != null && (
                        <span className="pl-4 text-[11.5px] font-normal text-ink-3">avg {avgApplied}d in stage</span>
                      )}
                    </h2>
                    {cards.map((a) => (
                      <BoardCard key={a.id} app={a} selected={a.id === openId} onOpen={() => setOpenId(a.id)}
                        onDragStart={(e) => { e.dataTransfer.setData("text/plain", a.id); e.dataTransfer.effectAllowed = "move"; }} />
                    ))}
                    {cards.length === 0 && (
                      <span className="flex items-center justify-center min-h-[72px] border border-dashed border-border-strong rounded-inner text-[12.5px] text-ink-3">
                        Nothing here yet
                      </span>
                    )}
                  </section>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="relative bg-surface border border-border rounded-card overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-[13.5px]">
              <thead>
                <tr className="bg-subtle border-b border-track text-left">
                  {["Role", "Status", "Applied", "Fit", "Level match", ""].map((h) => (
                    <th key={h} scope="col" className="micro font-normal px-4 py-[10px]">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.length === 0 ? (
                  <tr><td colSpan={6} className="px-4 py-8 text-center text-ink-3">No applications match.</td></tr>
                ) : shown.map((a) => (
                  <tr key={a.id} className="border-b border-divider last:border-0 hover:bg-subtle">
                    <td className="px-4 py-3">
                      <span className="flex items-center gap-3 min-w-0">
                        <CompanyMark name={a.company} size={34} />
                        <span className="flex flex-col min-w-0">
                          <span className="font-semibold truncate">{a.job_title}</span>
                          <span className="text-[12.5px] text-ink-3 truncate">{[a.company, a.location].filter(Boolean).join(" · ")}</span>
                        </span>
                      </span>
                    </td>
                    <td className="px-4 py-3"><StatusChip status={a.status} /></td>
                    <td className="px-4 py-3 text-ink-2 whitespace-nowrap">{a.date_applied ? shortDate(a.date_applied) : "–"}</td>
                    <td className="px-4 py-3 font-mono text-[12.5px]">{(a.fit_score ?? 0) > 0 ? Math.round(a.fit_score!) : "–"}</td>
                    <td className="px-4 py-3 text-ink-2">{levelOf(a)}</td>
                    <td className="px-4 py-3 text-right">
                      <button type="button" onClick={() => setOpenId(a.id)} className={buttonClass("secondary", "xs")}>
                        Details<span className="sr-only"> for {a.job_title} at {a.company}</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Page>

      <SlideOver open={!!open} onClose={() => setOpenId(null)} label="Application details"
        header={open && (
          <div className="flex gap-3 items-start">
            <CompanyMark name={open.company} size={44} />
            <span className="flex flex-col gap-[3px] min-w-0">
              <span className="text-[17px] font-semibold leading-[1.3]">{open.job_title}</span>
              <span className="text-[13px] text-ink-2">{[open.company, open.location].filter(Boolean).join(" · ")}</span>
            </span>
          </div>
        )}
        footer={open && (
          <>
            {link ? (
              <Link href={link.href} onClick={link.remember} className={buttonClass("primary", "md", "flex-1")}>Open job workspace</Link>
            ) : <span className="flex-1" />}
            <button type="button" onClick={saveNotes} disabled={savingNotes} className={buttonClass("secondary", "md")}>
              {savingNotes ? "Saving…" : notesSaved ? "Saved" : "Save notes"}
            </button>
          </>
        )}>
        {open && (
          <>
            <div className="flex flex-col gap-[6px]">
              <label htmlFor="app-status" className={labelClass}>Status</label>
              <select id="app-status" value={open.status} onChange={(e) => move(open.id, e.target.value)}
                className="h-10 px-[10px] border border-border-strong rounded-control bg-surface text-[14px] text-ink focus:outline-none focus:border-teal">
                {STATUS_CHOICES.map((s) => <option key={s} value={s}>{statusMeta(s).label}</option>)}
                {!STATUS_CHOICES.includes(open.status) && <option value={open.status}>{statusMeta(open.status).label}</option>}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {[
                ["Added", shortDate(open.created_at) ?? "–"],
                ["Applied", open.date_applied ? shortDate(open.date_applied) ?? "–" : "Not yet"],
                ["Fit", (open.fit_score ?? 0) > 0 ? `${Math.round(open.fit_score!)} / 100` : "Not analysed"],
                ["Level match", levelOf(open)],
              ].map(([k, v]) => (
                <div key={k} className="px-3 py-[10px] rounded-[10px] bg-subtle border border-track flex flex-col gap-[3px]">
                  <span className="micro text-[10px]">{k}</span>
                  <span className="text-[13.5px] font-medium">{v}</span>
                </div>
              ))}
            </div>
            <div className="flex flex-col gap-[10px]">
              <span className="text-[13px] font-semibold">Timeline</span>
              <ol className="list-none m-0 p-0 flex flex-col gap-[10px]">
                <li className="flex gap-[10px] items-baseline text-[13px]">
                  <span aria-hidden="true" className={cx("w-2 h-2 rounded-full shrink-0", statusMeta(open.status).dot)} />
                  <span className="flex-1">Now: {statusMeta(open.status).label}</span>
                </li>
                {open.date_applied && (
                  <li className="flex gap-[10px] items-baseline text-[13px]">
                    <span aria-hidden="true" className="w-2 h-2 rounded-full shrink-0 bg-blue" />
                    <span className="flex-1">Applied</span>
                    <span className="text-[12px] text-ink-3">{shortDate(open.date_applied)}</span>
                  </li>
                )}
                <li className="flex gap-[10px] items-baseline text-[13px]">
                  <span aria-hidden="true" className="w-2 h-2 rounded-full shrink-0 bg-stone" />
                  <span className="flex-1">Added to your applications</span>
                  <span className="text-[12px] text-ink-3">{shortDate(open.created_at)}</span>
                </li>
              </ol>
            </div>
            <div className="flex flex-col gap-[6px]">
              <label htmlFor="app-notes" className="text-[13px] font-semibold">Notes</label>
              <textarea id="app-notes" rows={4} value={notes} onChange={(e) => { setNotes(e.target.value); setNotesSaved(false); }}
                placeholder="Interview dates, who you spoke to, what to prepare…" className={textareaClass} />
            </div>
            {open.skill_gaps.length > 0 && (
              <div className="flex flex-col gap-2">
                <span className="text-[13px] font-semibold">Prepare for these gaps</span>
                <span className="flex flex-wrap gap-[6px]">
                  {open.skill_gaps.map((g) => <Chip key={g} tone="gap" size="lg" className="font-normal">{g}</Chip>)}
                </span>
              </div>
            )}
            {open.job_url && (
              <a href={open.job_url} target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-[10px] px-3 py-[10px] border border-border rounded-[10px] text-ink text-[13px] hover:bg-subtle">
                <Icon name="external" size={16} className="text-ink-3" />View the original posting
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            )}
          </>
        )}
      </SlideOver>
    </>
  );
}
