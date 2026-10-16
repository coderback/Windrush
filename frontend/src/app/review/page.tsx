"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { BrowserFrame } from "@/components/BrowserView";
import ReviewLayout from "@/components/ReviewLayout";
import Icon from "@/components/ui/Icon";
import { Page } from "@/components/ui/TopBar";
import { buttonClass, Callout, Chip, CompanyMark, cx, EmptyState, Skeleton } from "@/components/ui/kit";
import { useResource } from "@/lib/store";
import { setStatus } from "@/lib/actions";
import { longAgo } from "@/lib/format";
import { applicationLink } from "@/lib/jobs";
import type { Application } from "@/lib/types";

/* Applications the agent filled and stopped on before the final submit (tracker status
   Pending Review). The API keeps no live browser sessions between page loads (HANDOFF gap 1),
   so the review itself runs in the job workspace; from here you can reopen it, or record
   what happened. */

function ReviewQueue() {
  const router = useRouter();
  const params = useSearchParams();
  const apps = useResource<Application[]>("/api/applications");
  const [busy, setBusy] = useState<"skip" | "done" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const waiting = (apps.data ?? []).filter((a) => a.status === "Pending Review")
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  const wanted = params.get("app");
  const current = waiting.find((a) => a.id === wanted) ?? waiting[0] ?? null;
  const oldest = waiting[0] ? longAgo(waiting[0].created_at)?.replace(/ ago$/, "") : null;

  const pick = (id: string) => router.replace(`/review?app=${encodeURIComponent(id)}`, { scroll: false });

  const record = async (kind: "skip" | "done") => {
    if (!current) return;
    setBusy(kind);
    setError(null);
    try {
      await setStatus(current.id, kind === "skip" ? "Discarded" : "Applied");
      const next = waiting.find((a) => a.id !== current.id);
      router.replace(next ? `/review?app=${encodeURIComponent(next.id)}` : "/review", { scroll: false });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't update the application.");
    } finally {
      setBusy(null);
    }
  };

  const workspace = current ? applicationLink(current) : null;

  return (
    <>
      <header className="flex flex-wrap items-center justify-between gap-3 px-4 sm:px-8 py-[10px] border-b border-border bg-surface min-h-[67px]">
        {waiting.length > 0 ? (
          <div role="tablist" aria-label="Waiting for review" className="flex gap-[6px] flex-wrap">
            {waiting.map((a) => {
              const on = a.id === current?.id;
              return (
                <button key={a.id} type="button" role="tab" aria-selected={on} onClick={() => pick(a.id)}
                  className={cx("flex items-center gap-2 h-10 px-3 rounded-control text-[13px] text-ink border",
                    on ? "border-ink bg-surface font-semibold" : "border-border bg-subtle font-medium hover:border-border-strong")}>
                  <CompanyMark name={a.company} size={24} />
                  {a.company}
                  <span aria-hidden="true" className="w-[7px] h-[7px] rounded-full bg-amber" />
                </button>
              );
            })}
          </div>
        ) : (
          <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-[13.5px] text-ink-3">
            <span>Workspace</span><span aria-hidden="true">/</span><span aria-current="page" className="text-ink font-medium">Agent review</span>
          </nav>
        )}
        {waiting.length > 0 && (
          <span className="text-[13px] text-ink-3">{waiting.length} waiting{oldest ? ` · oldest ${oldest}` : ""}</span>
        )}
      </header>

      <Page wide="feed" className="gap-4 pt-[22px] sm:pt-[22px]">
        {apps.loading ? (
          <div className="flex flex-col gap-4">
            <Skeleton className="h-16 w-96 max-w-full rounded-inner" />
            <Skeleton className="h-[420px] rounded-card" />
          </div>
        ) : apps.error ? (
          <Callout title="Couldn't load your applications">{apps.error}</Callout>
        ) : !current ? (
          <>
            <h1 className="m-0 text-[26px] font-semibold tracking-[-0.025em]">Agent review</h1>
            <EmptyState action={<Link href="/jobs" className={buttonClass("primary", "sm")}>Browse matches</Link>}>
              Nothing is waiting for your review. When the agent fills a form it stops before the final submit, and the application waits here for you.
            </EmptyState>
          </>
        ) : (
          <>
            {error && <Callout>{error}</Callout>}
            <ReviewLayout
              tone="amber"
              status="Waiting for your review"
              title={`${current.job_title} · ${current.company}`}
              subtitle="The agent filled this form and stopped before submitting. Nothing has been sent."
              meta={<span className="font-mono text-[12.5px] text-ink-2 px-[10px] py-[6px] border border-border rounded-[8px] bg-surface">
                Filled {longAgo(current.created_at)}
              </span>}
              frame={
                <BrowserFrame url={current.job_url}>
                  <div className="flex-1 min-h-[320px] flex flex-col items-center justify-center gap-3 p-6 text-center bg-subtle">
                    <span className="w-10 h-10 rounded-control bg-amber-chip text-amber-text flex items-center justify-center">
                      <Icon name="pause" size={19} strokeWidth={2.4} />
                    </span>
                    <span className="text-[14.5px] font-semibold">This form isn&apos;t open in a browser right now</span>
                    <span className="text-[13.5px] text-ink-2 max-w-[52ch]">
                      The agent&apos;s browser closes when you leave the job page. Run it again from the job workspace: it fills the
                      form again and stops before submit, so you can check and send it there.
                    </span>
                    {workspace ? (
                      <Link href={workspace.href} onClick={workspace.remember} className={buttonClass("primary", "md")}>
                        Open the job workspace<Icon name="arrowRight" size={15} strokeWidth={2} />
                      </Link>
                    ) : (
                      <span className="text-[13px] text-ink-3">This application has no link to the job.</span>
                    )}
                  </div>
                </BrowserFrame>
              }
              side={
                <aside className="flex-[1_1_340px] min-w-0 bg-surface border border-border rounded-card flex flex-col overflow-hidden">
                  <h2 className="m-0 px-4 h-[46px] flex items-center border-b border-track text-[13.5px] font-semibold">Application</h2>
                  <dl className="m-0 p-4 grid grid-cols-2 gap-2">
                    {[
                      ["Fit", current.fit_score ? `${Math.round(current.fit_score)} / 100` : "Not analysed"],
                      ["Level match", (current.fit_score ?? 0) > 0 ? ({ strong: "Strong", ok: "Reasonable", reach: "Stretch" } as Record<string, string>)[current.level_match] ?? "–" : "–"],
                      ["Location", current.location || "–"],
                      ["Filled", longAgo(current.created_at) ?? "–"],
                    ].map(([k, v]) => (
                      <div key={k} className="px-3 py-[10px] rounded-[10px] bg-subtle border border-track flex flex-col gap-[3px] min-w-0">
                        <dt className="micro text-[10px]">{k}</dt>
                        <dd className="m-0 text-[13.5px] font-medium break-words">{v}</dd>
                      </div>
                    ))}
                  </dl>
                  {current.skill_gaps.length > 0 && (
                    <div className="px-4 pb-4 flex flex-col gap-2">
                      <span className="text-[13px] font-semibold">Gaps to prepare for</span>
                      <span className="flex flex-wrap gap-[6px]">
                        {current.skill_gaps.map((g) => <Chip key={g} tone="gap" className="font-normal">{g}</Chip>)}
                      </span>
                    </div>
                  )}
                  <p className="m-0 mt-auto px-4 py-3 border-t border-track text-[12.5px] text-ink-3">
                    The agent&apos;s notes show in the job workspace while it runs.
                  </p>
                </aside>
              }
              skip={{ onClick: () => record("skip"), busy: busy === "skip", disabled: !!busy }}
              done={{ onClick: () => record("done"), busy: busy === "done", disabled: !!busy }}
              submit={{ onClick: () => { if (workspace) { workspace.remember(); router.push(workspace.href); } }, disabled: !workspace,
                label: "Submit from the workspace", hint: "Submitting needs the agent's browser open." }}
            />
          </>
        )}
      </Page>
    </>
  );
}

export default function ReviewPage() {
  return (
    <Suspense>
      <ReviewQueue />
    </Suspense>
  );
}
