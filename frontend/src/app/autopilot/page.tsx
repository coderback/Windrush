"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import FormQuestions from "@/components/FormQuestions";
import Icon from "@/components/ui/Icon";
import TopBar, { Page } from "@/components/ui/TopBar";
import { Segmented, TabPanel, UnderlineTabs } from "@/components/ui/Tabs";
import {
  buttonClass, Callout, Card, Chip, CompanyMark, cx, EmptyState, inputClass, labelClass, Skeleton, Spinner, Switch,
  type ChipTone,
} from "@/components/ui/kit";
import { load, useResource } from "@/lib/store";
import { jobKey, longAgo } from "@/lib/format";
import { jobHref, rememberJob } from "@/lib/jobs";
import {
  dismissRun, downloadDocument, retryRun, RUNS_URL, runNow, saveSettings, screenshotUrl, STATUS_URL,
} from "@/lib/autopilot";
import type { AutopilotOutcome, AutopilotRun, AutopilotSettings, AutopilotStatus, Job } from "@/lib/types";

type Tab = "queue" | "sent" | "practice" | "other";

const OUTCOME: Record<AutopilotOutcome, { label: string; tone: ChipTone }> = {
  running: { label: "Working on it", tone: "info" },
  submitted: { label: "Sent", tone: "positive" },
  unconfirmed: { label: "Check it went through", tone: "warn" },
  ready: { label: "Would have sent", tone: "info" },
  needs_you: { label: "Needs you", tone: "warn" },
  skipped: { label: "Skipped", tone: "neutral" },
  failed: { label: "Didn't work", tone: "danger" },
  dismissed: { label: "Dismissed", tone: "neutral" },
};

const TAB_OF: Record<AutopilotOutcome, Tab> = {
  needs_you: "queue", unconfirmed: "queue", running: "queue",
  submitted: "sent", ready: "practice",
  skipped: "other", failed: "other", dismissed: "other",
};
const RETRYABLE = new Set<AutopilotOutcome>(["needs_you", "failed", "skipped", "ready", "dismissed"]);
const DISMISSABLE = new Set<AutopilotOutcome>(["needs_you", "failed", "skipped", "ready", "unconfirmed"]);

const FIT_CHOICES = [50, 55, 60, 65, 70, 75, 80, 85, 90, 95];
const CAP_CHOICES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function whenNext(iso: string | null): string | null {
  if (!iso) return null;
  const mins = Math.round((new Date(iso).getTime() - Date.now()) / 60_000);
  if (mins <= 1) return "in the next few minutes";
  if (mins < 60) return `in ${mins} minutes`;
  return `in about ${Math.round(mins / 60)} hours`;
}

function lastRunLine(last: AutopilotStatus["last"]): string | null {
  if (!last) return null;
  const c = last.counts;
  const parts = [
    c.submitted && `${c.submitted} sent`,
    c.ready && `${c.ready} would have been sent`,
    c.needs_you && `${c.needs_you} need you`,
    c.unconfirmed && `${c.unconfirmed} to check`,
    c.skipped && `${c.skipped} skipped`,
    c.failed && `${c.failed} didn't work`,
  ].filter(Boolean);
  const what = parts.length ? parts.join(", ") : "nothing new to apply to";
  return `Last run ${longAgo(last.finished_at) ?? ""}: ${what}.${last.note ? ` ${last.note}` : ""}`;
}

/* ── Settings ──────────────────────────────────────────────────────────── */

function Settings({ settings }: { settings: AutopilotSettings }) {
  const [confirmLive, setConfirmLive] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async (changes: Partial<AutopilotSettings>) => {
    setSaving(true);
    setError(null);
    try {
      await saveSettings(changes);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the setting.");
    } finally {
      setSaving(false);
    }
  };

  const mode = confirmLive ? "live" : settings.live ? "live" : "practice";

  return (
    <Card className="p-5 flex flex-col gap-5" aria-labelledby="autopilot-settings">
      <div className="flex flex-col gap-[3px]">
        <h2 id="autopilot-settings" className="m-0 text-[16px] font-semibold">Settings</h2>
        <span className="text-[13px] text-ink-3">Autopilot works down your job feed, best match first.</span>
      </div>

      <div className="flex flex-col gap-2">
        <span className={labelClass} id="mode-label">Mode</span>
        <Segmented label="Mode" value={mode}
          items={[{ key: "practice", label: "Practice" }, { key: "live", label: "Send applications" }]}
          onChange={(k) => {
            if (k === "practice") { setConfirmLive(false); if (settings.live) save({ live: false }); }
            else if (!settings.live) setConfirmLive(true);
          }} />
        <span className="text-[12.5px] leading-[1.5] text-ink-3">
          {settings.live
            ? "Forms that pass every check below are sent to the employer without asking you."
            : "Forms are filled in but never sent. You see what would have gone and what would have waited for you."}
        </span>
        {confirmLive && (
          <Callout tone="warn" title="Send applications without asking you?"
            action={
              <span className="flex flex-wrap gap-2 pt-1">
                <button type="button" disabled={saving} className={buttonClass("commit", "sm")}
                  onClick={async () => { await save({ live: true }); setConfirmLive(false); }}>
                  {saving ? <Spinner /> : null}Turn on sending
                </button>
                <button type="button" className={buttonClass("quiet", "sm")} onClick={() => setConfirmLive(false)}>Cancel</button>
              </span>
            }>
            An application can&apos;t be taken back once it&apos;s sent. Autopilot only sends a form when every answer on it
            came from your persona or your saved answers, and stops at your daily limit.
          </Callout>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <label className="flex flex-col gap-[6px]">
          <span className={labelClass}>Lowest fit score to apply</span>
          <select className={inputClass} value={settings.min_fit} disabled={saving}
            onChange={(e) => save({ min_fit: Number(e.target.value) })}>
            {FIT_CHOICES.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-[6px]">
          <span className={labelClass}>Most applications sent a day</span>
          <select className={inputClass} value={settings.daily_cap} disabled={saving}
            onChange={(e) => save({ daily_cap: Number(e.target.value) })}>
            {CAP_CHOICES.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
      </div>

      <div className="flex flex-col gap-2">
        <Switch checked={settings.enabled} disabled={saving} label="Run on its own every 6 hours"
          onChange={(v) => save({ enabled: v })} />
        <span className="text-[12.5px] text-ink-3">Off: it only runs when you press Run now.</span>
      </div>

      {error && <Callout>{error}</Callout>}

      <div className="flex flex-col gap-2 pt-4 border-t border-track">
        <span className="text-[13px] font-semibold text-ink">A form is sent only when</span>
        <ul className="m-0 pl-5 flex flex-col gap-1 text-[12.5px] leading-[1.5] text-ink-2">
          <li>it&apos;s on Greenhouse, Lever, Ashby or Workable (never LinkedIn or Indeed);</li>
          <li>the fit is at least {settings.min_fit} and the level isn&apos;t a stretch;</li>
          <li>every answer came from your persona or your saved answers: nothing drafted, nothing left blank;</li>
          <li>no required field is empty, and the CV and cover letter say nothing your persona doesn&apos;t back;</li>
          <li>fewer than {settings.daily_cap} went out in the last 24 hours.</li>
        </ul>
        <span className="text-[12.5px] text-ink-3">
          Anything else waits for you under Needs you. Each sent form keeps a screenshot of the filled form and of the page after it went.
        </span>
      </div>
    </Card>
  );
}

/* ── Runs ──────────────────────────────────────────────────────────────── */

function Shot({ runId, which }: { runId: string; which: "form" | "confirm" }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    let made: string | null = null;
    screenshotUrl(runId, which).then((u) => { made = u; if (alive) setUrl(u); else if (u) URL.revokeObjectURL(u); });
    return () => { alive = false; if (made) URL.revokeObjectURL(made); };
  }, [runId, which]);
  const label = which === "form" ? "The filled form, before sending" : "The page after sending";
  return (
    <figure className="m-0 flex flex-col gap-[6px] min-w-0">
      {url ? (
        <a href={url} target="_blank" rel="noreferrer" className="block border border-border rounded-inner overflow-hidden bg-subtle">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={url} alt={label} className="block w-full h-auto" />
        </a>
      ) : (
        <Skeleton className="aspect-[16/10] rounded-inner" />
      )}
      <figcaption className="text-[12px] text-ink-3">{label}</figcaption>
    </figure>
  );
}

function asJob(run: AutopilotRun): Job {
  return { id: run.job_id, title: run.job_title, company: run.company, location: run.location, url: run.job_url };
}

function RunRow({ run, running }: { run: AutopilotRun; running: boolean }) {
  const [open, setOpen] = useState(run.outcome === "needs_you" || run.outcome === "unconfirmed");
  const [busy, setBusy] = useState<"retry" | "dismiss" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const meta = OUTCOME[run.outcome];
  const job = asJob(run);
  const blank = run.questions.filter((q) => q.source === "needs_you").length;

  const act = async (kind: "retry" | "dismiss") => {
    setBusy(kind);
    setError(null);
    try {
      await (kind === "retry" ? retryRun(run.id) : dismissRun(run.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work.");
    } finally {
      setBusy(null);
    }
  };

  const fileName = (kind: string) =>
    `${run.company}_${kind}.pdf`.replace(/[^A-Za-z0-9_.-]+/g, "_");
  const download = (docId: string, kind: string) =>
    downloadDocument(docId, fileName(kind)).catch((e) => setError(e instanceof Error ? e.message : "Couldn't download it."));

  return (
    <li className="flex flex-col gap-3 py-4 border-t border-track first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-start gap-3">
        <CompanyMark name={run.company} size={36} />
        <div className="flex-1 min-w-[200px] flex flex-col gap-[2px]">
          <span className="text-[14px] font-semibold text-ink leading-[1.3]">{run.job_title}</span>
          <span className="text-[12.5px] text-ink-3">
            {[run.company, run.location, longAgo(run.updated_at)].filter(Boolean).join(" · ")}
          </span>
        </div>
        <span className="flex flex-wrap items-center gap-[6px]">
          {run.fit_score != null && (
            <span className="font-mono text-[11.5px] font-semibold px-[7px] py-[2px] rounded-full bg-muted text-ink">
              {Math.round(run.fit_score)} fit
            </span>
          )}
          {run.practice && run.outcome !== "skipped" && <Chip size="sm" tone="outline">Practice</Chip>}
          <Chip size="sm" tone={meta.tone} className="font-semibold">{meta.label}</Chip>
        </span>
      </div>

      {run.reasons.length > 0 && (
        <ul className="m-0 p-0 list-none flex flex-col gap-1">
          {run.reasons.map((r) => (
            <li key={r} className="flex gap-2 text-[13px] leading-[1.45] text-ink-2">
              <Icon name="alert" size={14} className="mt-[2px] shrink-0 text-amber-text" /><span>{r}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap gap-2">
        {(run.questions.length > 0 || run.screenshots.length > 0 || run.notes) && (
          <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className={buttonClass("secondary", "xs")}>
            <Icon name={open ? "chevronUp" : "chevronDown"} size={13} />{open ? "Hide details" : "Details"}
          </button>
        )}
        {RETRYABLE.has(run.outcome) && (
          <button type="button" onClick={() => act("retry")} disabled={busy !== null || running} className={buttonClass("secondary", "xs")}
            title={running ? "Autopilot is running" : undefined}>
            {busy === "retry" ? <Spinner /> : <Icon name="refresh" size={13} />}
            {run.outcome === "needs_you" && blank > 0 ? "Try again with my answers" : "Try again"}
          </button>
        )}
        {run.outcome !== "submitted" && run.job_url && (
          <Link href={jobHref(jobKey(job))} onClick={() => rememberJob(job)} className={buttonClass("secondary", "xs")}>
            <Icon name="arrowRight" size={13} />Apply myself
          </Link>
        )}
        {run.cv_doc_id && (
          <button type="button" onClick={() => download(run.cv_doc_id!, "CV")} className={buttonClass("quiet", "xs")}>
            <Icon name="download" size={13} />CV
          </button>
        )}
        {run.letter_doc_id && (
          <button type="button" onClick={() => download(run.letter_doc_id!, "Cover_Letter")} className={buttonClass("quiet", "xs")}>
            <Icon name="download" size={13} />Cover letter
          </button>
        )}
        {DISMISSABLE.has(run.outcome) && (
          <button type="button" onClick={() => act("dismiss")} disabled={busy !== null} className={buttonClass("quiet", "xs")}>
            {busy === "dismiss" ? <Spinner /> : null}Dismiss
          </button>
        )}
      </div>
      {error && <p role="alert" className="m-0 text-[12.5px] text-red">{error}</p>}

      {open && (
        <div className="flex flex-col gap-4">
          {run.screenshots.length > 0 && (
            <div className={cx("grid gap-3", run.screenshots.length > 1 ? "grid-cols-1 md:grid-cols-2" : "grid-cols-1 max-w-[640px]")}>
              {run.screenshots.map((w) => <Shot key={w} runId={run.id} which={w} />)}
            </div>
          )}
          {run.questions.length > 0 && (
            <FormQuestions questions={run.questions} company={run.company}
              savedNote="Saved. Press Try again and autopilot fills it in, here and on later forms." />
          )}
          {run.notes && (
            <details className="text-[12.5px] text-ink-2">
              <summary className="cursor-pointer text-ink-3">The agent&apos;s notes</summary>
              <p className="m-0 mt-2 whitespace-pre-wrap leading-[1.5]">{run.notes}</p>
            </details>
          )}
        </div>
      )}
    </li>
  );
}

/* ── Page ──────────────────────────────────────────────────────────────── */

export default function AutopilotPage() {
  const status = useResource<AutopilotStatus>(STATUS_URL, { staleMs: 0 });
  const runs = useResource<AutopilotRun[]>(RUNS_URL, { staleMs: 0 });
  const [tab, setTab] = useState<Tab>("queue");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const running = status.data?.running ?? false;

  // Follow a run while it goes, and pick up what it did once it ends.
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => {
      load(STATUS_URL, { force: true }).catch(() => {});
      load(RUNS_URL, { force: true }).catch(() => {});
    }, 4000);
    return () => clearInterval(timer);
  }, [running]);
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !running) load(RUNS_URL, { force: true }).catch(() => {});
    wasRunning.current = running;
  }, [running]);

  const all = useMemo(() => runs.data ?? [], [runs.data]);
  const byTab = useMemo(() => {
    const out: Record<Tab, AutopilotRun[]> = { queue: [], sent: [], practice: [], other: [] };
    for (const r of all) out[TAB_OF[r.outcome]].push(r);
    return out;
  }, [all]);

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      await runNow();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start autopilot.");
    } finally {
      setStarting(false);
    }
  };

  const s = status.data;
  const settings = s?.settings;
  const empty: Record<Tab, string> = {
    queue: "Nothing is waiting for you. Forms autopilot holds back show up here with the reasons.",
    sent: settings?.live ? "Nothing sent yet." : "Nothing is sent in practice mode. Switch to Send applications when you're ready.",
    practice: "Practice runs show here: forms that passed every check and would have been sent.",
    other: "Jobs autopilot skipped (fit too low, a stretch) or couldn't fill show here.",
  };

  return (
    <>
      <TopBar crumbs={[{ label: "Autopilot" }]}>
        <button type="button" onClick={start} disabled={!s || running || starting} className={buttonClass("primary", "top")}>
          {running || starting ? <Spinner /> : <Icon name="play" size={15} />}
          {running ? "Running…" : "Run now"}
        </button>
      </TopBar>
      <Page className="gap-5">
        <div className="flex flex-col gap-1">
          <h1 className="m-0 text-[24px] font-[650] tracking-[-0.02em]">Autopilot</h1>
          <p className="m-0 text-[14px] text-ink-2 max-w-[70ch]">
            Applies to jobs from your feed on its own: it writes the tailored CV and cover letter, fills in the form, and
            sends it only when nothing on it needs you.
          </p>
        </div>

        {status.error && <Callout>{String(status.error)}</Callout>}
        {error && <Callout>{error}</Callout>}

        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_380px] gap-5 items-start">
          <div className="flex flex-col gap-5 min-w-0">
            <Card className="p-5 flex flex-col gap-3" aria-live="polite">
              {!s ? (
                <Skeleton className="h-[60px] rounded-inner" />
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <Chip tone={s.settings.live ? "positive" : "info"} className="font-semibold">
                      {s.settings.live ? "Sending applications" : "Practice mode"}
                    </Chip>
                    <span className="text-[13px] text-ink-2">
                      {s.settings.live
                        ? `${s.sent_last_day} of ${s.settings.daily_cap} sent in the last 24 hours`
                        : "Nothing is sent"}
                    </span>
                  </div>
                  {running ? (
                    <div className="flex items-start gap-3 text-[13.5px] text-ink">
                      <Spinner className="mt-[3px]" />
                      <span className="flex flex-col gap-[2px] min-w-0">
                        <span className="font-semibold">{s.job || "Getting started"}</span>
                        <span className="text-ink-2 break-words">{s.step}</span>
                      </span>
                    </div>
                  ) : (
                    <span className="text-[13px] text-ink-2">
                      {lastRunLine(s.last) ?? (s.last_run_at ? `Last run ${longAgo(s.last_run_at)}.` : "Autopilot hasn't run yet.")}
                      {s.settings.enabled && s.next_run_at ? ` Next run ${whenNext(s.next_run_at)}.` : ""}
                    </span>
                  )}
                </>
              )}
            </Card>

            <Card className="p-5 flex flex-col gap-4">
              <UnderlineTabs idPrefix="autopilot" label="Autopilot runs" value={tab} onChange={setTab} items={[
                { key: "queue", label: `Needs you${byTab.queue.length ? ` (${byTab.queue.length})` : ""}` },
                { key: "sent", label: `Sent${byTab.sent.length ? ` (${byTab.sent.length})` : ""}` },
                { key: "practice", label: `Practice${byTab.practice.length ? ` (${byTab.practice.length})` : ""}` },
                { key: "other", label: `Skipped${byTab.other.length ? ` (${byTab.other.length})` : ""}` },
              ]} />
              {(["queue", "sent", "practice", "other"] as Tab[]).map((k) => (
                <TabPanel key={k} idPrefix="autopilot" k={k} active={tab === k}>
                  {runs.loading ? (
                    <Skeleton className="h-[120px] rounded-inner" />
                  ) : byTab[k].length === 0 ? (
                    <EmptyState>{empty[k]}</EmptyState>
                  ) : (
                    <>
                      {k === "other" && (
                        <p className="m-0 mb-3 text-[12.5px] text-ink-3">
                          {plural(byTab.other.length, "job")}. Try again on one to have autopilot apply to it anyway.
                        </p>
                      )}
                      <ul className="m-0 p-0 list-none flex flex-col">
                        {byTab[k].map((r) => <RunRow key={r.id} run={r} running={running} />)}
                      </ul>
                    </>
                  )}
                </TabPanel>
              ))}
            </Card>
          </div>

          {settings ? <Settings settings={settings} /> : <Skeleton className="h-[420px] rounded-card" />}
        </div>
      </Page>
    </>
  );
}
