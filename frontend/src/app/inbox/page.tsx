"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Icon from "@/components/ui/Icon";
import TopBar, { Page } from "@/components/ui/TopBar";
import { TabPanel, UnderlineTabs } from "@/components/ui/Tabs";
import {
  buttonClass, Callout, Card, Chip, CompanyMark, EmptyState, inputClass, Skeleton, Spinner, StatusChip, type ChipTone,
} from "@/components/ui/kit";
import { load, useResource } from "@/lib/store";
import { longAgo, shortDate } from "@/lib/format";
import {
  confirmEmail, connectGmail, disconnectGmail, dismissEmail, EVENTS_URL, GMAIL_URL, syncGmail, undoEmail,
} from "@/lib/gmail";
import type { Application, EmailEvent, EmailKind, GmailStatus } from "@/lib/types";

type Tab = "needs" | "updated" | "other";

const KIND: Record<EmailKind, { label: string; tone: ChipTone }> = {
  received: { label: "Application received", tone: "neutral" },
  assessment: { label: "Assessment", tone: "info" },
  interview: { label: "Interview", tone: "positive" },
  offer: { label: "Offer", tone: "positive" },
  rejected: { label: "Rejected", tone: "danger" },
  other: { label: "Update", tone: "neutral" },
};

const TAB_OF: Record<EmailEvent["decision"], Tab> = {
  suggested: "needs", unmatched: "needs",
  applied: "updated", confirmed: "updated",
  noted: "other", dismissed: "other", undone: "other",
};

function Setup({ redirect }: { redirect: string }) {
  return (
    <Callout tone="warn" title="Gmail tracking isn't set up yet">
      It needs a Google OAuth client of your own (free, a few minutes):
      <ol className="m-0 mt-2 pl-5 flex flex-col gap-1">
        <li>In Google Cloud Console, create a project and enable the <b>Gmail API</b>.</li>
        <li>OAuth consent screen: External, Testing, add your Gmail address as a test user, and the scope
          <code className="mx-1">gmail.readonly</code>.</li>
        <li>Credentials: create an OAuth client ID (Web application) with the redirect URI
          <code className="mx-1 break-all">{redirect}</code>.</li>
        <li>Put its ID and secret in <code>.env</code> as <code>GOOGLE_CLIENT_ID</code> and
          <code className="ml-1">GOOGLE_CLIENT_SECRET</code>, then restart the API container.</li>
      </ol>
    </Callout>
  );
}

function Connection({ status }: { status: GmailStatus }) {
  const [busy, setBusy] = useState<"connect" | "disconnect" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = async (kind: "connect" | "disconnect") => {
    setBusy(kind);
    setError(null);
    try {
      await (kind === "connect" ? connectGmail() : disconnectGmail());
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work.");
    } finally {
      if (kind === "disconnect") setBusy(null);
    }
  };

  if (!status.configured) return <Setup redirect={status.redirect_uri} />;
  return (
    <Card className="p-5 flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1 min-w-0 max-w-[70ch]">
          <h2 className="m-0 text-[16px] font-semibold">Gmail</h2>
          {status.connected && !status.problem ? (
            <span className="text-[13px] text-ink-2">
              Connected as <b>{status.email}</b>.{" "}
              {status.syncing ? "Reading your job emails now…"
                : status.last_sync_at ? `Last checked ${longAgo(status.last_sync_at)}; checked every 30 minutes.`
                : "Checked every 30 minutes."}
            </span>
          ) : (
            <span className="text-[13px] text-ink-2">
              Windrush reads your job emails and keeps your applications up to date: replies, assessments, interviews,
              offers and rejections. Read-only: it can&apos;t send, delete or change anything.
            </span>
          )}
        </div>
        {status.connected && !status.problem ? (
          <button type="button" onClick={() => run("disconnect")} disabled={busy !== null} className={buttonClass("quiet", "sm")}>
            {busy === "disconnect" ? <Spinner /> : null}Disconnect
          </button>
        ) : (
          <button type="button" onClick={() => run("connect")} disabled={busy !== null} className={buttonClass("primary", "sm")}>
            {busy === "connect" ? <Spinner /> : <Icon name="link" size={14} />}
            {status.problem ? "Connect again" : "Connect Gmail"}
          </button>
        )}
      </div>
      {status.problem && <Callout tone="warn">{status.problem}</Callout>}
      {status.last?.error && !status.problem && <Callout>{status.last.error}</Callout>}
      {error && <Callout>{error}</Callout>}
      <span className="text-[12px] leading-[1.5] text-ink-3">
        It only looks at mail from applicant tracking systems, mail naming a company you&apos;ve applied to, and
        application-style subjects. A clear step forward (say an interview invite) updates the application at once and
        can be undone; anything less certain waits here for you. It keeps each job email&apos;s sender, subject and a
        short snippet, nothing of other mail.
      </span>
    </Card>
  );
}

function EventRow({ event, apps }: { event: EmailEvent; apps: Application[] }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState("");
  const kind = KIND[event.kind];
  const company = event.app_company || event.company || event.sender.replace(/<.*>/, "").trim();

  const act = async (name: string, fn: () => Promise<void>) => {
    setBusy(name);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <li className="flex flex-col gap-2 py-4 border-t border-track first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-start gap-3">
        <CompanyMark name={company || "?"} size={34} />
        <div className="flex-1 min-w-[200px] flex flex-col gap-[2px]">
          <span className="text-[14px] font-semibold text-ink leading-[1.3]">
            {event.summary || event.subject}
          </span>
          <span className="text-[12.5px] text-ink-3">
            {[event.app_title ? `${event.app_title} at ${event.app_company}` : company, shortDate(event.received_at)]
              .filter(Boolean).join(" · ")}
          </span>
        </div>
        <Chip size="sm" tone={kind.tone} className="font-semibold">{kind.label}</Chip>
      </div>
      <details className="text-[12.5px] text-ink-2">
        <summary className="cursor-pointer text-ink-3">The email</summary>
        <p className="m-0 mt-1"><b>{event.subject}</b> from {event.sender}</p>
        {event.snippet && <p className="m-0 mt-1 text-ink-3">{event.snippet}…</p>}
      </details>

      {(event.decision === "applied" || event.decision === "confirmed") && (
        <div className="flex flex-wrap items-center gap-2 text-[13px] text-ink-2">
          <span>Moved from</span>{event.status_before && <StatusChip status={event.status_before} size="sm" />}
          <span>to</span>{event.proposed && <StatusChip status={event.proposed} size="sm" />}
          <button type="button" onClick={() => act("undo", () => undoEmail(event.id))} disabled={busy !== null}
            className={buttonClass("quiet", "xs")}>
            {busy === "undo" ? <Spinner /> : <Icon name="refresh" size={12} />}Undo
          </button>
        </div>
      )}

      {event.decision === "suggested" && (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => act("confirm", () => confirmEmail(event.id))} disabled={busy !== null}
            className={buttonClass("commit", "xs")}>
            {busy === "confirm" ? <Spinner /> : <Icon name="check" size={12} />}
            Mark {event.app_title ?? "it"} as {event.proposed}
          </button>
          <button type="button" onClick={() => act("dismiss", () => dismissEmail(event.id))} disabled={busy !== null}
            className={buttonClass("quiet", "xs")}>Leave it</button>
          {event.app_status && <span className="text-[12px] text-ink-3">It&apos;s {event.app_status} now.</span>}
        </div>
      )}

      {event.decision === "unmatched" && (
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="Which application is this about?" className={`${inputClass} max-w-[360px] h-8 text-[13px]`}
            value={link} onChange={(e) => setLink(e.target.value)}>
            <option value="">Which application is this about?</option>
            {apps.map((a) => <option key={a.id} value={a.id}>{a.company}: {a.job_title}</option>)}
          </select>
          <button type="button" disabled={!link || busy !== null} onClick={() => act("confirm", () => confirmEmail(event.id, link))}
            className={buttonClass("commit", "xs")}>
            {busy === "confirm" ? <Spinner /> : null}{event.proposed ? `Link and mark as ${event.proposed}` : "Link it"}
          </button>
          <button type="button" onClick={() => act("dismiss", () => dismissEmail(event.id))} disabled={busy !== null}
            className={buttonClass("quiet", "xs")}>Not mine</button>
        </div>
      )}
      {error && <p role="alert" className="m-0 text-[12.5px] text-red">{error}</p>}
    </li>
  );
}

function Inbox() {
  const params = useSearchParams();
  const status = useResource<GmailStatus>(GMAIL_URL, { staleMs: 0 });
  const events = useResource<EmailEvent[]>(EVENTS_URL, { staleMs: 0 });
  const apps = useResource<Application[]>("/api/applications");
  const [tab, setTab] = useState<Tab>("needs");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const syncing = status.data?.syncing ?? false;

  useEffect(() => {
    if (!syncing) return;
    const timer = setInterval(() => load(GMAIL_URL, { force: true }).catch(() => {}), 3000);
    return () => clearInterval(timer);
  }, [syncing]);
  const wasSyncing = useRef(false);
  useEffect(() => {
    if (wasSyncing.current && !syncing) {
      load(EVENTS_URL, { force: true }).catch(() => {});
      load("/api/applications", { force: true }).catch(() => {});
    }
    wasSyncing.current = syncing;
  }, [syncing]);

  const byTab = useMemo(() => {
    const out: Record<Tab, EmailEvent[]> = { needs: [], updated: [], other: [] };
    for (const e of events.data ?? []) out[TAB_OF[e.decision]].push(e);
    return out;
  }, [events.data]);

  const sync = async () => {
    setStarting(true);
    setError(null);
    try {
      await syncGmail();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start a sync.");
    } finally {
      setStarting(false);
    }
  };

  const s = status.data;
  const flag = params.get("gmail");
  const live = s?.connected && !s.problem;
  const empty: Record<Tab, string> = {
    needs: "Nothing waiting for you. Emails Windrush isn't sure about show up here.",
    updated: "No applications updated from your inbox yet.",
    other: "Emails that changed nothing, and ones you left or undid.",
  };

  return (
    <>
      <TopBar crumbs={[{ label: "Inbox" }]}>
        {live && (
          <button type="button" onClick={sync} disabled={syncing || starting} className={buttonClass("secondary", "top")}>
            {syncing || starting ? <Spinner /> : <Icon name="refresh" size={15} />}
            {syncing ? "Checking…" : "Check now"}
          </button>
        )}
      </TopBar>
      <Page className="gap-5 max-w-[960px]">
        <div className="flex flex-col gap-1">
          <h1 className="m-0 text-[24px] font-[650] tracking-[-0.02em]">Inbox</h1>
          <p className="m-0 text-[14px] text-ink-2 max-w-[70ch]">
            What employers have emailed you, and what it changed on your{" "}
            <Link href="/applications" className="text-teal hover:underline">applications</Link>.
          </p>
        </div>
        {flag === "connected" && <Callout tone="info">Gmail is connected. Reading your job emails now.</Callout>}
        {flag === "error" && <Callout>{params.get("reason") || "Connecting Gmail didn't work."}</Callout>}
        {error && <Callout>{error}</Callout>}

        {s ? <Connection status={s} /> : <Skeleton className="h-[120px] rounded-card" />}

        {(live || (events.data?.length ?? 0) > 0) && (
          <Card className="p-5 flex flex-col gap-4">
            <UnderlineTabs idPrefix="inbox" label="Email updates" value={tab} onChange={setTab} items={[
              { key: "needs", label: `Needs you${byTab.needs.length ? ` (${byTab.needs.length})` : ""}` },
              { key: "updated", label: `Updated${byTab.updated.length ? ` (${byTab.updated.length})` : ""}` },
              { key: "other", label: "Other" },
            ]} />
            {(["needs", "updated", "other"] as Tab[]).map((k) => (
              <TabPanel key={k} idPrefix="inbox" k={k} active={tab === k}>
                {events.loading ? <Skeleton className="h-[100px] rounded-inner" />
                  : byTab[k].length === 0 ? <EmptyState>{empty[k]}</EmptyState>
                  : (
                    <ul className="m-0 p-0 list-none flex flex-col">
                      {byTab[k].map((e) => <EventRow key={e.id} event={e} apps={apps.data ?? []} />)}
                    </ul>
                  )}
              </TabPanel>
            ))}
          </Card>
        )}
      </Page>
    </>
  );
}

export default function InboxPage() {
  return (
    <Suspense fallback={null}>
      <Inbox />
    </Suspense>
  );
}
