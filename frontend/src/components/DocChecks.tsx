"use client";

import { useEffect, useId, useState } from "react";
import { authFetch } from "@/app/api";
import Icon from "./ui/Icon";
import { Chip, cx, Spinner } from "./ui/kit";
import type { Job } from "@/lib/types";

interface Finding { kind: string; field: string; label: string; value: string; message: string }
interface AtsCheck { check: string; ok: boolean; detail: string }
export interface DocReport {
  keywords: { matched: string[]; missing_have: string[]; gaps: string[]; in_ad: number; score: number | null };
  facts: Finding[];
  style: Finding[];
  ats: { pages: number; checks: AtsCheck[] } | null;
}

function Pill({ tone, children }: { tone: "ok" | "warn" | "neutral"; children: React.ReactNode }) {
  return (
    <span className={cx("inline-flex items-center gap-[6px] h-7 px-[10px] rounded-full text-[12.5px] font-medium whitespace-nowrap",
      tone === "ok" ? "bg-teal-chip text-teal-deep" : tone === "warn" ? "bg-amber-soft text-amber-text" : "bg-muted text-ink-2")}>
      {tone === "ok" ? <Icon name="check" size={12} strokeWidth={2.6} /> : tone === "warn" ? <Icon name="alert" size={12} strokeWidth={2.2} /> : null}
      {children}
    </span>
  );
}

/**
 * The document check for a tailored CV or cover letter: the ad's keywords it shows (CV only),
 * claims your persona doesn't back, machine-sounding words, and the PDF read back as an applicant
 * tracking system reads it. Re-runs a moment after each edit.
 */
export default function DocChecks({ kind, doc, job, templateId = "classic" }: {
  kind: "cv" | "cover_letter"; doc: object; job: Job; templateId?: string;
}) {
  const [report, setReport] = useState<DocReport | null>(null);
  const [checking, setChecking] = useState(false);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const panelId = useId();

  useEffect(() => {
    let live = true;
    const t = setTimeout(async () => {
      setChecking(true);
      try {
        const res = await authFetch("/api/documents/check", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: kind, doc, template_id: templateId,
            job: { title: job.title, company: job.company, description: job.description ?? "" } }),
        });
        if (!live) return;
        if (res.ok) {
          setReport(await res.json());
          setFailed(false);
        } else {
          setFailed(true);
        }
      } catch {
        if (live) setFailed(true);
      } finally {
        if (live) setChecking(false);
      }
    }, 1200);
    return () => { live = false; clearTimeout(t); };
  }, [kind, doc, job.title, job.company, job.description, templateId]);

  if (!report) {
    return (
      <div className="flex items-center gap-2 px-5 py-3 border-b border-track text-[13px] text-ink-3" role="status">
        {failed ? "The checks couldn't run. Your document is unaffected." : <><Spinner className="w-3 h-3" /> Checking the document…</>}
      </div>
    );
  }

  const kw = report.keywords;
  const claims = [...report.facts, ...report.style];
  const atsFails = report.ats?.checks.filter((c) => !c.ok) ?? [];
  const showKeywords = kind === "cv" && kw.in_ad > 0;

  return (
    <div className="border-b border-track">
      <button type="button" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((o) => !o)}
        className="w-full flex flex-wrap items-center gap-2 px-5 py-3 text-left hover:bg-subtle">
        <span className="text-[13px] font-semibold mr-1">Checks</span>
        {showKeywords && (
          <Pill tone={kw.missing_have.length ? "warn" : "ok"}>
            Keywords {kw.matched.length} of {kw.matched.length + kw.missing_have.length} you have
          </Pill>
        )}
        <Pill tone={claims.length ? "warn" : "ok"}>
          {claims.length ? `${claims.length} ${claims.length === 1 ? "thing" : "things"} to check` : "Every claim is in your persona"}
        </Pill>
        {report.ats ? (
          <Pill tone={atsFails.length ? "warn" : "ok"}>
            {atsFails.length ? `ATS: ${atsFails.length} ${atsFails.length === 1 ? "problem" : "problems"}` : "Reads cleanly in an ATS"}
          </Pill>
        ) : <Pill tone="neutral">ATS check unavailable</Pill>}
        <span className="ml-auto flex items-center gap-2 text-[12.5px] text-ink-3">
          {checking && <Spinner className="w-3 h-3" />}
          {open ? "Hide" : "Details"}
          <Icon name={open ? "chevronUp" : "chevronDown"} size={14} strokeWidth={2} />
        </span>
      </button>

      {open && (
        <div id={panelId} className="px-5 pb-4 grid gap-4 md:grid-cols-2">
          {showKeywords && (
            <section className="flex flex-col gap-2 min-w-0">
              <h3 className="m-0 text-[13px] font-semibold">Keywords from the ad</h3>
              {kw.matched.length > 0 && (
                <span className="flex flex-wrap gap-[6px]">
                  {kw.matched.map((t) => <Chip key={t} tone="matched" className="font-normal">{t}</Chip>)}
                </span>
              )}
              {kw.missing_have.length > 0 && (
                <>
                  <span className="text-[12.5px] text-ink-2">In your persona but not on this CV. Add them where they’re true:</span>
                  <span className="flex flex-wrap gap-[6px]">
                    {kw.missing_have.map((t) => <Chip key={t} tone="warn" className="font-normal">{t}</Chip>)}
                  </span>
                </>
              )}
              {kw.gaps.length > 0 && (
                <>
                  <span className="text-[12.5px] text-ink-2">Not in your persona, so left out:</span>
                  <span className="flex flex-wrap gap-[6px]">
                    {kw.gaps.map((t) => <Chip key={t} tone="gap" className="font-normal">{t}</Chip>)}
                  </span>
                </>
              )}
            </section>
          )}
          <section className="flex flex-col gap-2 min-w-0">
            <h3 className="m-0 text-[13px] font-semibold">Claims and wording</h3>
            {claims.length === 0 ? (
              <p className="m-0 text-[13px] text-ink-2">Every number, technology, employer and project is in your persona, and no
                words read as machine-written.</p>
            ) : (
              <ul className="m-0 p-0 list-none flex flex-col gap-2">
                {claims.map((f, i) => (
                  <li key={`${f.field}-${f.value}-${i}`} className="flex gap-2 text-[13px] leading-[1.45]">
                    <Icon name="alert" size={14} className="text-amber-text mt-[2px]" />
                    <span><span className="font-medium">{f.label}:</span> {f.message}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {report.ats && (
            <section className="flex flex-col gap-2 min-w-0">
              <h3 className="m-0 text-[13px] font-semibold">Read back from the PDF</h3>
              <ul className="m-0 p-0 list-none flex flex-col gap-[6px]">
                {report.ats.checks.map((c) => (
                  <li key={c.check} className="flex gap-2 text-[13px] leading-[1.45]">
                    <Icon name={c.ok ? "check" : "alert"} size={14} strokeWidth={c.ok ? 2.4 : 2}
                      className={cx("mt-[2px]", c.ok ? "text-teal" : "text-amber-text")} />
                    <span>{c.check}<span className="text-ink-3"> · {c.detail}</span></span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
