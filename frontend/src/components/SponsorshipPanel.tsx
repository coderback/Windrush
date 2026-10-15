"use client";

import { useEffect, useState } from "react";
import { authFetch } from "@/app/api";
import Icon from "./ui/Icon";
import { buttonClass, Chip, cx, type ChipTone } from "./ui/kit";
import { sponsorshipVerdict, type SponsorshipVerdict } from "@/lib/sponsorship";

export interface SponsorshipView {
  sponsorship: string;       // "offered" | "not_offered" | ""
  evidence: string;
  clearance: string;
  licensed_sponsor: boolean;
  sponsor_name: string;
  mark: string;              // the user's own call: "offered" | "not_offered" | ""
}

/**
 * What a job's ad says about visa sponsorship and clearance, whether the employer is a licensed
 * sponsor, and the user's own mark (which wins in the feed). `refreshKey` re-reads it, e.g. once
 * analysis has fetched the full ad, which often says what the stored snippet didn't.
 * The view is null for a job that isn't stored (e.g. one pasted by link).
 */
export function useSponsorship(jobId: string | undefined, refreshKey = 0) {
  const [view, setView] = useState<SponsorshipView | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!jobId) return;
    let live = true;
    authFetch(`/api/jobs/${encodeURIComponent(jobId)}/sponsorship`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => { if (live) setView(data); })
      .catch(() => {});
    return () => { live = false; };
  }, [jobId, refreshKey]);

  const mark = async (value: string | null) => {
    if (!jobId) return;
    setSaving(true);
    try {
      const res = await authFetch(`/api/jobs/${encodeURIComponent(jobId)}/sponsorship`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mark: value }),
      });
      if (res.ok) setView(await res.json());
    } finally {
      setSaving(false);
    }
  };

  return { view, mark, saving };
}

export function viewVerdict(view: SponsorshipView) {
  return sponsorshipVerdict({
    sponsorship: view.sponsorship, sponsorship_evidence: view.evidence, clearance: view.clearance,
    licensed_sponsor: view.licensed_sponsor, sponsorship_mark: view.mark,
  });
}

export const VERDICT_TONE: Record<SponsorshipVerdict, ChipTone> = {
  Offered: "positive", Likely: "positive", "Not stated": "neutral", "Ruled out": "danger", Unlikely: "warn",
};

function Reason({ kind, children }: { kind: "yes" | "no" | "unknown" | "warn"; children: React.ReactNode }) {
  const icon = kind === "yes" ? <Icon name="check" size={15} strokeWidth={2.4} className="text-teal mt-[2px]" />
    : kind === "no" ? <Icon name="close" size={15} strokeWidth={2.4} className="text-red mt-[2px]" />
    : kind === "warn" ? <Icon name="alert" size={15} strokeWidth={2} className="text-amber-text mt-[2px]" />
    : <span aria-hidden="true" className="w-[15px] h-[15px] mt-[2px] flex items-center justify-center shrink-0"><span className="w-[9px] h-[2px] rounded bg-stone" /></span>;
  return <li className="flex gap-2">{icon}<span className="min-w-0">{children}</span></li>;
}

export default function SponsorshipPanel({ view, onMark, saving }: {
  view: SponsorshipView; onMark: (v: string | null) => void; saving: boolean;
}) {
  const { verdict } = viewVerdict(view);
  const button = (value: string, label: string) => (
    <button type="button" disabled={saving} aria-pressed={view.mark === value}
      onClick={() => onMark(view.mark === value ? null : value)}
      className={cx(buttonClass("secondary", "xs", "font-normal"), view.mark === value && "border-teal-line bg-teal-soft text-teal-deep font-medium")}>
      {view.mark === value && <Icon name="check" size={13} strokeWidth={2.4} />}
      {label}
    </button>
  );

  return (
    <section aria-labelledby="visa" className="bg-surface border border-border rounded-card p-[18px] flex flex-col gap-3">
      <div className="flex justify-between items-center gap-2">
        <h2 id="visa" className="m-0 text-[15px] font-semibold">Visa sponsorship</h2>
        <Chip tone={VERDICT_TONE[verdict]} size="sm" className="font-semibold">{verdict}</Chip>
      </div>
      <ul className="m-0 p-0 list-none flex flex-col gap-2 text-[13px] text-ink-2 leading-[1.5]">
        {view.mark && (
          <Reason kind={view.mark === "offered" ? "yes" : "no"}>
            You marked this employer as {view.mark === "offered" ? "sponsoring" : "not sponsoring"} visas
          </Reason>
        )}
        {view.sponsorship === "offered" ? (
          <Reason kind="yes">The ad offers visa sponsorship{view.evidence && <span className="block text-ink-3 italic">&ldquo;{view.evidence}&rdquo;</span>}</Reason>
        ) : view.sponsorship === "not_offered" ? (
          <Reason kind="no">The ad rules sponsorship out{view.evidence && <span className="block text-ink-3 italic">&ldquo;{view.evidence}&rdquo;</span>}</Reason>
        ) : (
          <Reason kind="unknown">The ad doesn&apos;t say whether it sponsors visas</Reason>
        )}
        {view.licensed_sponsor ? (
          <Reason kind="yes">{view.sponsor_name || "The employer"} is on the Home Office register of licensed sponsors (Skilled Worker)</Reason>
        ) : (
          <Reason kind="unknown">Not on the Home Office register of Skilled Worker sponsors under this name</Reason>
        )}
        {(view.clearance === "SC" || view.clearance === "DV") && (
          <Reason kind="warn">Needs {view.clearance} security clearance, which usually requires years of UK residence</Reason>
        )}
      </ul>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[12.5px] text-ink-3">Know better?</span>
        {button("offered", "They sponsor")}
        {button("not_offered", "They don’t")}
      </div>
    </section>
  );
}
