"use client";

import { useEffect, useState } from "react";
import { authFetch } from "@/app/api";
import { sponsorshipBadges } from "@/components/JobCard";

interface SponsorshipView {
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
 */
export default function SponsorshipPanel({ jobId, refreshKey = 0 }: { jobId: string; refreshKey?: number }) {
  const [view, setView] = useState<SponsorshipView | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let live = true;
    authFetch(`/api/jobs/${encodeURIComponent(jobId)}/sponsorship`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => { if (live) setView(data); })
      .catch(() => {});
    return () => { live = false; };
  }, [jobId, refreshKey]);

  if (!view) return null;   // not a stored job (e.g. one pasted by link)

  const mark = async (value: string | null) => {
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

  const adSays = view.sponsorship === "offered" ? "The ad offers visa sponsorship."
    : view.sponsorship === "not_offered" ? "The ad rules sponsorship out."
    : "The ad doesn't say whether it sponsors visas.";
  const badges = sponsorshipBadges({ ...view, sponsorship_mark: view.mark, sponsorship_evidence: view.evidence });
  const button = (value: string, label: string) => (
    <button
      disabled={saving}
      onClick={() => mark(view.mark === value ? null : value)}
      className={`text-xs px-3 py-1.5 rounded-lg border transition-colors disabled:opacity-50 ${
        view.mark === value ? "border-teal-500 bg-teal-500/10 text-teal-300" : "border-zinc-800 text-zinc-400 hover:border-zinc-600"
      }`}
    >
      {view.mark === value ? `✓ ${label}` : label}
    </button>
  );

  return (
    <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
      <div className="flex items-center justify-between gap-3 mb-3">
        <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-widest">Visa sponsorship</h2>
        <div className="flex flex-wrap gap-1.5 justify-end">
          {badges.map((b) => (
            <span key={b.label} title={b.title} className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${b.cls}`}>
              {b.label}
            </span>
          ))}
        </div>
      </div>
      <div className="space-y-1.5 text-sm text-zinc-400">
        <p>{adSays}</p>
        {view.evidence && <p className="text-xs text-zinc-500 italic">&ldquo;{view.evidence}&rdquo;</p>}
        <p>
          {view.licensed_sponsor
            ? `${view.sponsor_name} is on the Home Office register of licensed Skilled Worker sponsors.`
            : "The employer isn't on the Home Office register of Skilled Worker sponsors under this name."}
        </p>
        {(view.clearance === "SC" || view.clearance === "DV") && (
          <p className="text-amber-400/90">
            Needs {view.clearance} security clearance, which usually requires years of UK residence.
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 mt-4">
        <span className="text-[10px] text-zinc-600 uppercase tracking-widest font-bold mr-1">Your call:</span>
        {button("offered", "Sponsors visas")}
        {button("not_offered", "Doesn't sponsor")}
      </div>
    </div>
  );
}
