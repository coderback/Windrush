"use client";

import { useEffect, useState } from "react";
import { buttonClass, Callout, Spinner } from "@/components/ui/kit";
import { load, requestJson } from "@/lib/store";
import { shortDate } from "@/lib/format";
import type { Application, CandidateAd } from "@/lib/types";

/* For an application tracked from email: the ad it was made through. Shows the one Windrush matched, or lets the user
   pick among the feed's ads at that employer, so it gets the fit check and job page a Windrush application has. */
export default function AdPicker({ app }: { app: Application }) {
  const [ads, setAds] = useState<CandidateAd[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [linking, setLinking] = useState<string | null>(null);
  const fromEmail = app.job_id.startsWith("email:");

  useEffect(() => {
    if (!fromEmail || app.ad_link) return;
    let live = true;
    setAds(null);
    requestJson<{ ads: CandidateAd[] }>(`/api/applications/${app.id}/ads`)
      .then((r) => { if (live) setAds(r.ads); })
      .catch((e) => { if (live) setProblem(e instanceof Error ? e.message : "Couldn't look for its ad."); });
    return () => { live = false; };
  }, [app.id, app.ad_link, fromEmail]);

  if (app.ad_link === "matched") {
    return (
      <p className="m-0 text-[12.5px] leading-[1.5] text-ink-2">
        Matched to the ad in your feed it was made through, so it has that ad&apos;s fit check and job page.
      </p>
    );
  }
  if (!fromEmail || app.ad_link) return null;

  const link = async (jobId: string) => {
    setLinking(jobId);
    setProblem(null);
    try {
      await requestJson(`/api/applications/${app.id}/ad`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_id: jobId }),
      });
      await load<Application[]>("/api/applications", { force: true });
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That didn't link.");
    } finally {
      setLinking(null);
    }
  };

  return (
    <section aria-labelledby="which-ad" className="flex flex-col gap-2">
      <h3 id="which-ad" className="m-0 text-[13px] font-semibold">Which ad was this?</h3>
      {problem && <Callout>{problem}</Callout>}
      {ads === null && !problem ? (
        <span className="text-[12.5px] text-ink-3"><Spinner /> Looking in your feed…</span>
      ) : ads && ads.length === 0 ? (
        <p className="m-0 text-[12.5px] leading-[1.5] text-ink-2">
          Your feed has no ad from {app.company} from around when you applied, so this one stays as the email described it.
        </p>
      ) : ads && (
        <>
          <p className="m-0 text-[12.5px] leading-[1.5] text-ink-2">
            Tracked from an email. Pick the ad you applied to and it gets the same fit check and job page as one made
            through Windrush.
          </p>
          <ul className="list-none m-0 p-0 flex flex-col gap-[6px]" aria-label={`Ads from ${app.company}`}>
            {ads.map((ad) => (
              <li key={ad.id} className="flex items-center justify-between gap-3 px-3 py-[8px] rounded-[10px] border border-border">
                <span className="min-w-0 flex flex-col gap-[2px]">
                  <span className="text-[13px] font-medium leading-[1.35]">{ad.title}</span>
                  <span className="text-[12px] text-ink-3">
                    {[ad.location, `in your feed from ${shortDate(ad.created_at)}`, ad.opened ? "you opened it" : ""].filter(Boolean).join(" · ")}
                  </span>
                </span>
                <button type="button" onClick={() => link(ad.id)} disabled={!!linking}
                  aria-label={`This one: ${ad.title}`} className={buttonClass("secondary", "sm", "shrink-0")}>
                  {linking === ad.id ? <Spinner /> : null}This one
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
