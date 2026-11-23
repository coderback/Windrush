"use client";

import { Chip, cx } from "@/components/ui/kit";
import type { PlanResource, PlanTrack, PlanVenue, SavedPlan } from "@/lib/types";

const PROOF_LABEL: Record<string, string> = {
  certification: "Certification", competition: "Competition", publication: "Publication",
  open_source: "Open source", portfolio: "Portfolio", talk: "Talk",
};
const VENUE_LABEL: Record<string, string> = {
  event: "Event", hackathon: "Hackathon", conference: "Conference", meetup: "Meetup", community: "Community",
  competition: "Competition", course: "Course", programme: "Programme",
};

/** Every checkable id in a plan, for the "x of y done" count. */
export function planItemIds(saved: SavedPlan): string[] {
  const p = saved.plan;
  return [
    ...p.goals.map((g) => g.id),
    ...p.tracks.flatMap((t) => [...t.study.map((s) => s.id), ...(t.project ? [t.project.id] : []), ...(t.proof ? [t.proof.id] : [])]),
    ...(p.venues ?? []).map((v) => v.id),
  ];
}

function Check({ id, label, done, onToggle, children }: {
  id: string; label: string; done: boolean; onToggle: (id: string, done: boolean) => void; children: React.ReactNode;
}) {
  return (
    <span className="flex items-start gap-[10px] min-w-0">
      <input type="checkbox" id={`plan-${id}`} checked={done} aria-label={label}
        onChange={(e) => onToggle(id, e.target.checked)}
        className="mt-[3px] w-4 h-4 shrink-0 accent-[var(--teal)] cursor-pointer" />
      <label htmlFor={`plan-${id}`} className={cx("min-w-0 flex flex-col gap-[2px] cursor-pointer", done && "text-ink-3 line-through decoration-ink-3/60")}>
        {children}
      </label>
    </span>
  );
}

function Resource({ r }: { r: PlanResource }) {
  if (r.checked && r.url) {
    return (
      <li className="text-[12.5px] leading-[1.45]">
        <a href={r.url} target="_blank" rel="noreferrer noopener" className="text-teal-deep underline underline-offset-2">{r.name}</a>
        {r.title && r.title !== r.name && <span className="text-ink-3"> · {r.title}</span>}
      </li>
    );
  }
  return (
    <li className="text-[12.5px] leading-[1.45] text-ink-2">
      {r.name} <span className="text-ink-3">(not checked: search for it before relying on it)</span>
    </li>
  );
}

function Track({ t, n, done, onToggle }: { t: PlanTrack; n: number; done: Set<string>; onToggle: (id: string, d: boolean) => void }) {
  return (
    <li className="bg-surface border border-border rounded-card p-[18px] flex flex-col gap-3 min-w-0">
      <span className="flex items-baseline justify-between gap-3">
        <span className="flex items-baseline gap-2 min-w-0">
          <span className="font-mono text-[12px] text-ink-3">{String(n).padStart(2, "0")}</span>
          <span className="text-[16px] font-semibold leading-[1.3]">{t.skill}</span>
        </span>
        <Chip size="sm">{t.timeline}</Chip>
      </span>
      {t.market && (
        <span className="text-[12px] font-mono text-ink-3">
          Asked for in {t.market.ads} of {t.market.of} ads{t.market.shown ? " · you already show it" : ""}
        </span>
      )}
      {t.why && <span className="text-[13px] leading-[1.5] text-ink-2">{t.why}</span>}

      {t.study.length > 0 && (
        <div className="flex flex-col gap-[6px]">
          <h4 className="m-0 text-[12px] font-semibold">Study</h4>
          <ol className="list-none m-0 p-0 flex flex-col gap-[6px]">
            {t.study.map((s, i) => (
              <li key={s.id}>
                <Check id={s.id} label={`${t.skill} step ${i + 1}`} done={done.has(s.id)} onToggle={onToggle}>
                  <span className="text-[12.5px] leading-[1.45]">{s.text}</span>
                </Check>
              </li>
            ))}
          </ol>
        </div>
      )}
      {t.resources.length > 0 && (
        <div className="flex flex-col gap-[4px]">
          <h4 className="m-0 text-[12px] font-semibold">Resources</h4>
          <ul className="list-disc m-0 pl-[18px] flex flex-col gap-[2px]">{t.resources.map((r) => <Resource key={r.name} r={r} />)}</ul>
        </div>
      )}
      {t.project && (
        <div className="flex flex-col gap-[6px] px-3 py-[10px] rounded-[10px] bg-subtle border border-track">
          <Check id={t.project.id} label={`${t.skill} project`} done={done.has(t.project.id)} onToggle={onToggle}>
            <span className="text-[12px] font-semibold">Project: {t.project.title}</span>
          </Check>
          {t.project.builds_on && <span><Chip tone="matched" size="sm">Builds on {t.project.builds_on}</Chip></span>}
          {t.project.brief && <span className="text-[12.5px] leading-[1.45] text-ink-2">{t.project.brief}</span>}
          {t.project.done_when && <span className="text-[12.5px] leading-[1.45] text-ink-2"><b className="font-semibold">Done when:</b> {t.project.done_when}</span>}
        </div>
      )}
      {t.proof && (
        <div className="mt-auto flex flex-col gap-[4px]">
          <Check id={t.proof.id} label={`${t.skill} proof point`} done={done.has(t.proof.id)} onToggle={onToggle}>
            <span className="text-[12px] font-semibold">Aim for ({PROOF_LABEL[t.proof.kind] ?? t.proof.kind}): {t.proof.target}</span>
          </Check>
          {t.proof.why && <span className="pl-[26px] text-[12.5px] leading-[1.45] text-ink-2">{t.proof.why}</span>}
        </div>
      )}
    </li>
  );
}

function Venue({ v, done, onToggle }: { v: PlanVenue; done: boolean; onToggle: (id: string, d: boolean) => void }) {
  return (
    <li className="flex flex-col gap-[4px] px-5 py-[12px] border-b border-divider last:border-0">
      <Check id={v.id} label={`Went to or joined ${v.name}`} done={done} onToggle={onToggle}>
        <span className="flex flex-wrap items-center gap-2">
          <a href={v.url} target="_blank" rel="noreferrer noopener" className="text-[13.5px] font-medium text-teal-deep underline underline-offset-2">{v.name}</a>
          <Chip size="sm">{VENUE_LABEL[v.kind] ?? v.kind}</Chip>
          {v.when && <span className="text-[12px] text-ink-3">{v.when}</span>}
        </span>
      </Check>
      {v.why && <span className="pl-[26px] text-[12.5px] leading-[1.45] text-ink-2">{v.why}</span>}
    </li>
  );
}

export default function CareerPlan({ saved, onToggle }: { saved: SavedPlan; onToggle: (id: string, done: boolean) => void }) {
  const p = saved.plan;
  const done = new Set(saved.done);
  return (
    <div className="flex flex-col gap-[14px]">
      {(p.diagnosis || p.strengths.length > 0) && (
        <section aria-labelledby="plan-where" className="bg-surface border border-border rounded-card p-5 flex flex-col gap-3">
          <h3 id="plan-where" className="m-0 text-[15px] font-semibold">Where you stand</h3>
          {p.diagnosis && <p className="m-0 text-[13.5px] leading-[1.55] text-ink-2 max-w-[80ch] text-pretty">{p.diagnosis}</p>}
          {p.strengths.length > 0 && (
            <ul className="list-none m-0 p-0 flex flex-wrap gap-[6px]" aria-label="Strengths">
              {p.strengths.map((s) => <li key={s}><Chip tone="positive">{s}</Chip></li>)}
            </ul>
          )}
        </section>
      )}

      {p.goals.length > 0 && (
        <section aria-labelledby="plan-goals" className="bg-surface border border-border rounded-card p-5 flex flex-col gap-3">
          <h3 id="plan-goals" className="m-0 text-[15px] font-semibold">Goals</h3>
          <ul className="list-none m-0 p-0 flex flex-col gap-[10px]">
            {p.goals.map((g) => (
              <li key={g.id} className="flex justify-between items-start gap-3">
                <Check id={g.id} label={g.goal} done={done.has(g.id)} onToggle={onToggle}>
                  <span className="text-[13.5px] font-medium leading-[1.4]">{g.goal}</span>
                  {g.measure && <span className="text-[12.5px] leading-[1.45] text-ink-2">{g.measure}</span>}
                </Check>
                <Chip size="sm" className="shrink-0">within {g.by}</Chip>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="plan-tracks" className="flex flex-col gap-[10px]">
        <h3 id="plan-tracks" className="m-0 text-[15px] font-semibold">Gaps to close</h3>
        <ol className="list-none m-0 p-0 grid gap-[14px]" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(340px, 100%), 1fr))" }}>
          {p.tracks.map((t, i) => <Track key={t.id} t={t} n={i + 1} done={done} onToggle={onToggle} />)}
        </ol>
      </section>

      {p.venues_searched && (
        <section aria-labelledby="plan-venues" className="bg-surface border border-border rounded-card overflow-hidden">
          <div className="px-5 pt-4 pb-2 flex flex-col gap-1">
            <h3 id="plan-venues" className="m-0 text-[15px] font-semibold">Where to show up</h3>
            <p className="m-0 text-[12.5px] text-ink-3">Found by a live web search when this plan was made. Each links to the page the search returned; a date is shown only when that page&apos;s listing gave one, so check it before you go.</p>
          </div>
          {p.venues.length > 0 ? (
            <ul className="list-none m-0 p-0 border-t border-divider">
              {p.venues.map((v) => <Venue key={v.id} v={v} done={done.has(v.id)} onToggle={onToggle} />)}
            </ul>
          ) : (
            <p className="m-0 px-5 pb-4 text-[13px] text-ink-2">The search didn&apos;t find events or communities it could vouch for this time.</p>
          )}
        </section>
      )}

      {p.applications.length > 0 && (
        <section aria-labelledby="plan-apply" className="bg-surface border border-border rounded-card p-5 flex flex-col gap-2">
          <h3 id="plan-apply" className="m-0 text-[15px] font-semibold">How you apply</h3>
          <ul className="list-disc m-0 pl-[18px] flex flex-col gap-[6px]">
            {p.applications.map((a) => <li key={a} className="text-[13px] leading-[1.5] text-ink-2">{a}</li>)}
          </ul>
        </section>
      )}
    </div>
  );
}
