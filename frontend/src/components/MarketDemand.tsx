"use client";

import { useState } from "react";
import { Bar, Chip, EmptyState, TextLink } from "@/components/ui/kit";
import type { FunnelCounts, MarketDemand, MarketSkill } from "@/lib/types";

const SHOWN_AT_FIRST = 12;

function pct(n: number, of: number): string {
  return of ? `${Math.round((100 * n) / of)}%` : "–";
}

function SkillRow({ skill, of }: { skill: MarketSkill; of: number }) {
  return (
    <li className="grid gap-x-3 gap-y-[6px] px-5 py-[11px] border-b border-divider last:border-0"
      style={{ gridTemplateColumns: "minmax(0, 1fr) auto" }}>
      <span className="min-w-0 text-[13.5px] font-medium">{skill.name}</span>
      <span className="font-mono text-[12px] text-ink-2 shrink-0">{skill.ads} of {of} ads</span>
      <span className="col-span-2"><Bar value={100 * skill.share} className={skill.shown ? "bg-teal" : "bg-amber"} /></span>
      <span className="col-span-2 flex flex-wrap items-center gap-[6px]">
        {skill.shown ? (
          <Chip tone="matched" size="sm">You show it: {skill.where.join(", ")}</Chip>
        ) : (
          <Chip tone="gap" size="sm">Not in your profile yet</Chip>
        )}
        {skill.required > 0 && skill.required < skill.ads && (
          <span className="text-[12px] text-ink-3">required in {skill.required}</span>
        )}
      </span>
    </li>
  );
}

function FunnelTable({ total, rows }: { total: FunnelCounts; rows: (FunnelCounts & { role: string })[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px] border-collapse">
        <caption className="sr-only">Your applications by role</caption>
        <thead>
          <tr className="text-left text-[12px] text-ink-3">
            <th scope="col" className="font-medium px-5 py-2">Role</th>
            <th scope="col" className="font-medium px-3 py-2 text-right">Sent</th>
            <th scope="col" className="font-medium px-3 py-2 text-right">Replies</th>
            <th scope="col" className="font-medium px-3 py-2 text-right">Interviews</th>
            <th scope="col" className="font-medium px-5 py-2 text-right">Reply rate</th>
          </tr>
        </thead>
        <tbody>
          {[...rows, { role: "All", ...total }].map((r) => (
            <tr key={r.role} className={r.role === "All" ? "border-t border-border font-semibold" : "border-t border-divider"}>
              <th scope="row" className="text-left font-[inherit] px-5 py-2">{r.role}</th>
              <td className="px-3 py-2 text-right font-mono">{r.applied}</td>
              <td className="px-3 py-2 text-right font-mono">{r.replies}</td>
              <td className="px-3 py-2 text-right font-mono">{r.interviews}</td>
              <td className="px-5 py-2 text-right font-mono">{pct(r.replies, r.applied)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* What the ads for the user's target roles ask for, whether their profile shows each skill, and how their own
   applications for those roles have gone. */
export default function MarketDemandPanel({ market }: { market: MarketDemand }) {
  const [all, setAll] = useState(false);
  const skills = all ? market.skills : market.skills.slice(0, SHOWN_AT_FIRST);
  const gaps = market.skills.filter((s) => !s.shown).length;
  const level = market.level ? `${market.level}-level ` : "";
  return (
    <section aria-labelledby="market" className="bg-surface border border-border rounded-card overflow-hidden">
      <div className="flex flex-col gap-1 px-5 pt-4 pb-3">
        <h2 id="market" className="m-0 text-[15.5px] font-semibold">What employers ask for</h2>
        {market.roles.length === 0 ? null : (
          <p className="m-0 text-[13px] leading-[1.5] text-ink-2 max-w-[72ch] text-pretty">
            {market.ads > 0
              ? `Counted over ${market.ads} ${level}ads for ${market.roles.join(", ")} whose requirements Windrush has read. `
              : ""}
            {market.skills.length > 0 && `${gaps} of the ${market.skills.length} most asked-for skills aren't in your profile yet. `}
            {market.waiting > 0 && `${market.waiting} more ads are still being read.`}
          </p>
        )}
      </div>
      {market.roles.length === 0 ? (
        <div className="px-5 pb-5">
          <EmptyState action={<TextLink href="/profile#prefs">Add the roles you&apos;re aiming for</TextLink>}>
            Add target roles to see what their ads ask for.
          </EmptyState>
        </div>
      ) : market.skills.length === 0 ? (
        <div className="px-5 pb-5">
          <EmptyState>Windrush hasn&apos;t read enough ads for these roles yet. Check back once the feed has collected more.</EmptyState>
        </div>
      ) : (
        <>
          <ul className="list-none m-0 p-0 border-t border-divider" aria-label="Most asked-for skills">
            {skills.map((s) => <SkillRow key={s.key} skill={s} of={market.ads} />)}
          </ul>
          {market.skills.length > SHOWN_AT_FIRST && (
            <div className="px-5 py-3 border-t border-divider">
              <button type="button" onClick={() => setAll(!all)}
                className="bg-transparent border-0 p-0 text-[13px] font-medium text-teal-deep underline underline-offset-2 cursor-pointer">
                {all ? "Show fewer" : `Show all ${market.skills.length}`}
              </button>
            </div>
          )}
        </>
      )}
      {market.funnel.total.applied > 0 && (
        <div className="border-t border-border pt-3">
          <h3 className="m-0 px-5 pb-1 text-[13.5px] font-semibold">Your applications</h3>
          <p className="m-0 px-5 pb-2 text-[12.5px] text-ink-3">A reply is a response, interview or offer. Rejections don&apos;t say why, so these show where replies come from, not what caused them.</p>
          <FunnelTable total={market.funnel.total} rows={market.funnel.by_role} />
        </div>
      )}
    </section>
  );
}
