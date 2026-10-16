"use client";

import Link from "next/link";
import { useMemo } from "react";
import Icon from "@/components/ui/Icon";
import TopBar, { AnalyseLinkButton, Page } from "@/components/ui/TopBar";
import {
  buttonClass, Callout, Card, Chip, CompanyMark, cx, DateTile, FitRing, RiskBar, SectionTitle, Skeleton, TextLink,
} from "@/components/ui/kit";
import { useResource } from "@/lib/store";
import { daysSince, greeting, longAgo, pct, shortAgo } from "@/lib/format";
import { firstName } from "@/lib/persona";
import { riskLevel, RISK, REPLIED, SENT, statusMeta, stageOf } from "@/lib/status";
import { sponsorshipBadges } from "@/lib/sponsorship";
import { levelLabel } from "@/lib/format";
import { jobHref, rememberFeed } from "@/lib/jobs";
import type { Application, Job, Persona, SkillRisk } from "@/lib/types";

interface JobsPage { jobs: Job[]; sponsorship?: string }

const WEEK = 7 * 86400000;
const FOLLOW_UP_DAYS = 7;

/** Counts per week for the last `n` weeks, oldest first, bucketed by `dateOf`. */
function weekly<T>(items: T[], dateOf: (t: T) => string | null | undefined, n = 10): number[] {
  const out = Array<number>(n).fill(0);
  const now = Date.now();
  for (const it of items) {
    const d = dateOf(it);
    if (!d) continue;
    const age = now - new Date(d).getTime();
    if (Number.isNaN(age) || age < 0) continue;
    const w = Math.floor(age / WEEK);
    if (w < n) out[n - 1 - w] += 1;
  }
  return out;
}

function MiniBars({ values, accent }: { values: number[]; accent: "ink" | "teal" }) {
  const max = Math.max(1, ...values);
  return (
    <span className="flex items-end gap-[3px] h-[30px]" aria-hidden="true">
      {values.map((v, i) => (
        <span key={i}
          className={cx("w-1 rounded-[2px]", i === values.length - 1 ? (accent === "teal" ? "bg-teal" : "bg-ink") : "bg-bar-idle")}
          style={{ height: Math.max(3, Math.round((v / max) * 26) + 2) }} />
      ))}
    </span>
  );
}

function Kpi({ label, value, bars, accent = "ink", delta, deltaTone = "teal", note }: {
  label: string; value: string; bars: number[]; accent?: "ink" | "teal";
  delta?: string; deltaTone?: "teal" | "orange" | "ink"; note: string;
}) {
  return (
    <div className="bg-surface border border-border rounded-[14px] px-[18px] py-4 flex flex-col gap-3">
      <span className="micro">{label}</span>
      <div className="flex items-end justify-between gap-[10px]">
        <span className="font-mono text-[28px] font-medium tracking-[-0.03em] leading-none">{value}</span>
        <MiniBars values={bars} accent={accent} />
      </div>
      <span className="text-[12.5px] text-ink-2">
        {delta && <span className={cx("font-semibold", deltaTone === "teal" ? "text-teal" : deltaTone === "orange" ? "text-orange-text" : "text-ink")}>{delta} </span>}
        {note}
      </span>
    </div>
  );
}

export default function DashboardPage() {
  const persona = useResource<Persona>("/api/persona");
  const apps = useResource<Application[]>("/api/applications");
  const risks = useResource<{ skill_risks?: SkillRisk[] }>("/api/score-skills", { init: { method: "POST" }, staleMs: Infinity });
  const feed = useResource<JobsPage>("/api/jobs?page=1&limit=4");

  const list = useMemo(() => apps.data ?? [], [apps.data]);
  const waiting = list.filter((a) => a.status === "Pending Review");

  const stats = useMemo(() => {
    const now = Date.now();
    const within = (d: string | null, from: number, to: number) => {
      if (!d) return false;
      const t = now - new Date(d).getTime();
      return t >= from && t < to;
    };
    const thisWeek = list.filter((a) => within(a.date_applied, 0, WEEK)).length;
    const lastWeek = list.filter((a) => within(a.date_applied, WEEK, 2 * WEEK)).length;
    const sent = list.filter((a) => SENT.has(a.status));
    const replied = list.filter((a) => REPLIED.has(a.status));
    const interviews = list.filter((a) => a.status === "Interview");
    const fits = list.filter((a) => (a.fit_score ?? 0) > 0);
    const avgFit = fits.length ? Math.round(fits.reduce((n, a) => n + (a.fit_score ?? 0), 0) / fits.length) : null;
    const fitWeeks = Array.from({ length: 10 }, (_, i) => {
      const inWeek = fits.filter((a) => {
        const age = now - new Date(a.created_at).getTime();
        return Math.floor(age / WEEK) === 9 - i;
      });
      return inWeek.length ? inWeek.reduce((n, a) => n + (a.fit_score ?? 0), 0) / inWeek.length : 0;
    });
    const stages = [
      { key: "Saved", count: list.filter((a) => stageOf(a.status) === "Saved").length },
      { key: "Pending Review", count: list.filter((a) => a.status === "Pending Review").length },
      { key: "Applied", count: list.filter((a) => a.status === "Applied").length },
      { key: "Responded", count: list.filter((a) => a.status === "Responded").length },
      { key: "Interview", count: interviews.length },
      { key: "Offer", count: list.filter((a) => a.status === "Offer").length },
    ];
    const closed = list.filter((a) => a.status === "Rejected" || a.status === "Discarded").length;
    // Applied a week or more ago and still Applied: nothing has come back, so a follow-up is due.
    const followUps = list
      .filter((a) => a.status === "Applied" && (daysSince(a.date_applied) ?? 0) >= FOLLOW_UP_DAYS)
      .map((a) => ({ app: a, due: new Date(new Date(a.date_applied!).getTime() + FOLLOW_UP_DAYS * 86400000) }))
      .sort((x, y) => x.due.getTime() - y.due.getTime());
    return {
      thisWeek, lastWeek, sent: sent.length, replied: replied.length, interviews: interviews.length, avgFit, fits: fits.length,
      appliedBars: weekly(list, (a) => a.date_applied),
      replyBars: weekly(replied, (a) => a.date_applied),
      interviewBars: weekly(interviews, (a) => a.date_applied),
      fitBars: fitWeeks, stages, closed, active: list.length - closed, followUps,
    };
  }, [list]);

  const name = firstName(persona.data);
  const delta = stats.thisWeek - stats.lastWeek;
  const summary = [
    waiting.length
      ? `${waiting.length} ${waiting.length === 1 ? "application is" : "applications are"} waiting for your review.`
      : "Nothing is waiting for your review.",
    stats.followUps.length ? `${stats.followUps.length} follow-up${stats.followUps.length === 1 ? " is" : "s are"} due.` : "",
  ].filter(Boolean).join(" ");

  const skillRisks = risks.data?.skill_risks ?? [];
  const overall = skillRisks.length
    ? Math.round(skillRisks.reduce((n, s) => n + s.exposure_score, 0) / skillRisks.length) : null;
  const topRisks = [...skillRisks].sort((a, b) => b.exposure_score - a.exposure_score).slice(0, 4);

  const matches = feed.data?.jobs ?? [];

  return (
    <>
      <TopBar crumbs={[{ label: "Workspace" }, { label: "Home" }]}>
        <AnalyseLinkButton />
      </TopBar>
      <Page className="gap-[22px]">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-col gap-[6px]">
            <h1 className="m-0 text-[28px] font-semibold tracking-[-0.025em]">
              {greeting()}{name ? `, ${name}` : ""}
            </h1>
            {apps.loading ? <Skeleton className="h-5 w-80 rounded-[6px]" /> :
              <p className="m-0 text-[14.5px] text-ink-2 text-pretty">{summary}</p>}
          </div>
          <Link href="/jobs" className={buttonClass("primary", "top")}>
            Browse matches
            <Icon name="arrowRight" size={15} strokeWidth={2} />
          </Link>
        </div>

        {apps.error && <Callout title="Couldn't load your applications">{apps.error}</Callout>}

        {waiting.length > 0 && (
          <section aria-labelledby="needs-you" className="bg-surface border border-amber-line rounded-card overflow-hidden">
            <div className="flex flex-wrap items-center gap-[14px] px-5 py-[18px] bg-amber-wash border-b border-amber-line-2">
              <span className="w-[38px] h-[38px] rounded-control bg-amber-chip text-amber-text flex items-center justify-center shrink-0">
                <Icon name="pause" size={19} strokeWidth={2.4} />
              </span>
              <div className="flex-[1_1_320px] flex flex-col gap-[3px] min-w-0">
                <h2 id="needs-you" className="m-0 text-[15.5px] font-semibold">
                  {waiting.length} {waiting.length === 1 ? "application is" : "applications are"} paused before submit
                </h2>
                <p className="m-0 text-[13.5px] text-amber-ink">
                  The agent filled these forms and stopped at the final button. Nothing is sent until you approve it.
                </p>
              </div>
              <Link href="/review" className="text-[13.5px] font-medium text-amber-text underline underline-offset-2">Open review queue</Link>
            </div>
            {waiting.map((a) => (
              <div key={a.id} className="flex flex-wrap items-center gap-[14px] px-5 py-[14px] border-t border-divider">
                <CompanyMark name={a.company} size={36} />
                <div className="flex-[1_1_240px] flex flex-col gap-[2px] min-w-0">
                  <span className="text-[14px] font-semibold">{a.job_title}</span>
                  <span className="text-[13px] text-ink-3">{[a.company, a.location].filter(Boolean).join(" · ")}</span>
                </div>
                {(a.fit_score ?? 0) > 0 && <span className="font-mono text-[12px] text-ink-2">Fit {Math.round(a.fit_score!)}</span>}
                <span className="text-[12.5px] text-ink-3 min-w-16">{longAgo(a.created_at)}</span>
                <Link href={`/review?app=${encodeURIComponent(a.id)}`} className={buttonClass("primary", "sm")}>Review &amp; submit</Link>
              </div>
            ))}
          </section>
        )}

        {stats.followUps.length > 0 && (
          <section aria-labelledby="week" className="bg-surface border border-border rounded-card px-5 pt-[18px] pb-2 flex flex-col">
            <div className="flex justify-between items-center pb-[14px]">
              <SectionTitle id="week">This week</SectionTitle>
              <span className="text-[13px] text-ink-3">
                {stats.followUps.length} {stats.followUps.length === 1 ? "thing" : "things"} due
              </span>
            </div>
            {stats.followUps.slice(0, 4).map(({ app, due }) => (
              <Link key={app.id} href="/applications" className="flex items-center gap-[14px] py-[10px] border-t border-divider text-ink no-underline hover:bg-subtle -mx-2 px-2 rounded-[10px]">
                <DateTile date={due} tint="sky" />
                <span className="flex-1 min-w-0 flex flex-col gap-[2px]">
                  <span className="text-[14px] font-semibold">Follow up with {app.company}</span>
                  <span className="text-[12.5px] text-ink-3">
                    {app.job_title} · applied {daysSince(app.date_applied)} days ago, no reply yet
                  </span>
                </span>
                <Chip tone="info">Follow-up</Chip>
              </Link>
            ))}
          </section>
        )}

        <div className="grid gap-[14px]" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(220px, 100%), 1fr))" }}>
          {apps.loading ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[124px] rounded-[14px]" />) : (
            <>
              <Kpi label="Applied this week" value={String(stats.thisWeek)} bars={stats.appliedBars}
                delta={`${delta >= 0 ? "+" : ""}${delta}`} deltaTone={delta > 0 ? "teal" : delta < 0 ? "orange" : "ink"} note="vs last week" />
              <Kpi label="Replies" value={String(stats.replied)} bars={stats.replyBars}
                delta={`${pct(stats.replied, stats.sent)}%`} note="of sent applications" />
              <Kpi label="Interviews" value={String(stats.interviews)} bars={stats.interviewBars}
                note={stats.interviews ? "in progress" : "none yet"} />
              <Kpi label="Average fit" value={stats.avgFit != null ? String(stats.avgFit) : "–"} bars={stats.fitBars} accent="teal"
                note={stats.fits ? `across ${stats.fits} analysed ${stats.fits === 1 ? "role" : "roles"}` : "no roles analysed yet"} />
            </>
          )}
        </div>

        <div className="flex flex-wrap gap-[14px] items-stretch">
          <section aria-labelledby="pipe" className="flex-[2_1_560px] min-w-0 bg-surface border border-border rounded-card p-5 flex flex-col gap-[18px]">
            <div className="flex justify-between items-center gap-3">
              <div className="flex flex-col gap-[3px]">
                <SectionTitle id="pipe">Application pipeline</SectionTitle>
                <span className="text-[13px] text-ink-3">{stats.active} active · {stats.closed} closed</span>
              </div>
              <TextLink href="/applications">Open board</TextLink>
            </div>
            <div className="flex h-3 rounded-full overflow-hidden gap-[3px] bg-track" role="img"
              aria-label={`Pipeline: ${stats.stages.map((s) => `${s.count} ${statusMeta(s.key).label.toLowerCase()}`).join(", ")}`}>
              {stats.active > 0 && stats.stages.map((s) => (
                <span key={s.key} className={cx("h-full", statusMeta(s.key).dot)} style={{ flex: s.count || 0.4 }} />
              ))}
            </div>
            <div className="grid gap-[10px]" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(90px, 100%), 1fr))" }}>
              {stats.stages.map((s) => (
                <div key={s.key} className="flex flex-col gap-[6px] p-3 rounded-inner bg-subtle border border-track">
                  <span className="flex items-center gap-[7px] text-[12.5px] text-ink-2">
                    <span className={cx("w-2 h-2 rounded-[3px] shrink-0", statusMeta(s.key).dot)} />
                    {statusMeta(s.key).label}
                  </span>
                  <span className="font-mono text-[22px] font-medium">{s.count}</span>
                </div>
              ))}
            </div>
            <p className="m-0 text-[13px] text-ink-2">
              {stats.sent
                ? `${stats.replied} of ${stats.sent} sent applications got a reply.`
                : "Nothing sent yet. Applications you submit show up here."}
              {stats.followUps.length > 0 && ` ${stats.followUps.length} follow-up${stats.followUps.length === 1 ? " is" : "s are"} due.`}
            </p>
          </section>

          <section aria-labelledby="risk" className="flex-[1_1_300px] min-w-0 bg-surface border border-border rounded-card p-5 flex flex-col gap-4">
            <div className="flex justify-between items-center">
              <SectionTitle id="risk">AI exposure</SectionTitle>
              <TextLink href="/careers">Roadmap</TextLink>
            </div>
            {risks.loading ? (
              <div className="flex flex-col gap-3">
                <Skeleton className="h-10 w-40 rounded-[8px]" />
                {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-7 rounded-[6px]" />)}
              </div>
            ) : risks.error ? (
              <Callout title="Couldn't score your skills">{risks.error}</Callout>
            ) : overall == null ? (
              <p className="m-0 text-[13.5px] text-ink-2">
                Add skills to your persona to see how exposed they are. <TextLink href="/profile#skills">Add skills</TextLink>
              </p>
            ) : (
              <>
                <div className="flex items-center gap-3">
                  <span className="font-mono text-[40px] font-medium tracking-[-0.04em] leading-none">{overall}%</span>
                  <span className="flex flex-col gap-1">
                    <span className={cx("self-start h-[22px] px-[9px] rounded-full text-[12px] font-semibold flex items-center", RISK[riskLevel(overall)].chip)}>
                      {riskLevel(overall)}
                    </span>
                    <span className="text-[12.5px] text-ink-3">across {skillRisks.length} skills in your persona</span>
                  </span>
                </div>
                <div className="flex flex-col gap-3">
                  {topRisks.map((r) => <RiskBar key={r.skill} label={r.skill} score={r.exposure_score} />)}
                </div>
              </>
            )}
          </section>
        </div>

        <section aria-labelledby="matches" className="bg-surface border border-border rounded-card overflow-hidden">
          <div className="flex justify-between items-center gap-3 px-5 pt-[18px] pb-3">
            <div className="flex flex-col gap-[3px]">
              <SectionTitle id="matches">Top matches today</SectionTitle>
              <span className="text-[13px] text-ink-3">
                Ranked by match to your persona{feed.data?.sponsorship && feed.data.sponsorship !== "any" ? ", sponsorship filter on" : ""}
              </span>
            </div>
            <TextLink href="/jobs">See all</TextLink>
          </div>
          {feed.loading ? (
            <div className="flex flex-col gap-2 px-5 pb-4">
              {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[54px] rounded-inner" />)}
            </div>
          ) : feed.error ? (
            <div className="px-5 pb-5"><Callout title="Couldn't load your matches">{feed.error}</Callout></div>
          ) : matches.length === 0 ? (
            <div className="px-5 pb-5">
              <p className="m-0 text-[13.5px] text-ink-2">
                No matches yet. Discovery is looking for roles that fit your persona. <TextLink href="/jobs">Open the feed</TextLink>
              </p>
            </div>
          ) : matches.map((j) => {
            const id = j.id ?? j.job_id ?? "";
            const badge = sponsorshipBadges(j)[0];
            const level = levelLabel(j.level);
            const match = j.semantic_score != null ? Math.round(j.semantic_score * 100) : null;
            return (
              <Link key={id} href={jobHref(id)} onClick={() => rememberFeed(matches)}
                className="flex flex-wrap items-center gap-[14px] px-5 py-[13px] border-t border-divider text-ink no-underline hover:bg-subtle">
                {match != null ? <FitRing value={match} size={42} label="Match" /> : <CompanyMark name={j.company} size={40} />}
                <div className="flex-[1_1_220px] flex flex-col gap-[3px] min-w-0">
                  <span className="text-[14px] font-semibold">{j.title}</span>
                  <span className="text-[13px] text-ink-3">{[j.company, j.location].filter(Boolean).join(" · ")}</span>
                </div>
                {badge ? <Chip tone={badge.tone} title={badge.title}>{badge.label}</Chip> : level ? <Chip>{level}</Chip> : null}
                <span className="text-[12.5px] text-ink-3 min-w-[52px] text-right">{shortAgo(j.created_at ?? j.posted_at)}</span>
              </Link>
            );
          })}
        </section>
      </Page>
    </>
  );
}
