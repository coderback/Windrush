import type { ChipTone } from "@/components/ui/kit";
import type { Job } from "./types";

export interface Badge { label: string; tone: ChipTone; title?: string }

/** Visa sponsorship and clearance badges: the user's mark, else what the ad says, else the register. */
export function sponsorshipBadges(job: Pick<Job, "sponsorship" | "sponsorship_evidence" | "clearance" |
                                  "licensed_sponsor" | "sponsorship_mark">): Badge[] {
  const badges: Badge[] = [];
  const quote = job.sponsorship_evidence ? `From the ad: "${job.sponsorship_evidence}"` : undefined;
  if (job.sponsorship_mark === "offered") badges.push({ label: "Sponsors visas (your mark)", tone: "positive" });
  else if (job.sponsorship_mark === "not_offered") badges.push({ label: "No sponsorship (your mark)", tone: "danger" });
  else if (job.sponsorship === "offered") badges.push({ label: "Visa sponsorship", tone: "positive", title: quote });
  else if (job.sponsorship === "not_offered") badges.push({ label: "No sponsorship", tone: "danger", title: quote });
  else if (job.licensed_sponsor) {
    badges.push({ label: "Licensed sponsor", tone: "positive",
                  title: "On the Home Office register of Skilled Worker sponsors; the ad doesn't say whether this role is sponsored" });
  }
  if (job.clearance === "SC" || job.clearance === "DV") {
    badges.push({ label: `${job.clearance} clearance`, tone: "warn",
                  title: "Security vetting at this level usually needs years of UK residence" });
  } else if (job.clearance) {
    badges.push({ label: job.clearance === "NPPV" ? "NPPV vetting" : "Security clearance", tone: "neutral" });
  }
  return badges;
}

export type SponsorshipVerdict = "Offered" | "Likely" | "Not stated" | "Ruled out" | "Unlikely";

/** One word for the fact tile and the preview box, with the reason behind it. */
export function sponsorshipVerdict(job: Pick<Job, "sponsorship" | "sponsorship_evidence" | "clearance" |
                                   "licensed_sponsor" | "sponsorship_mark">): { verdict: SponsorshipVerdict; why: string } {
  if (job.sponsorship_mark === "offered") return { verdict: "Offered", why: "You marked this employer as sponsoring visas." };
  if (job.sponsorship_mark === "not_offered") return { verdict: "Ruled out", why: "You marked this employer as not sponsoring visas." };
  if (job.sponsorship === "not_offered") {
    return { verdict: "Ruled out", why: job.sponsorship_evidence ? `From the ad: “${job.sponsorship_evidence}”` : "The ad rules sponsorship out." };
  }
  if (job.clearance === "SC" || job.clearance === "DV") {
    return { verdict: "Unlikely", why: `Needs ${job.clearance} security clearance, which usually requires years of UK residence.` };
  }
  if (job.sponsorship === "offered") {
    return { verdict: "Offered", why: job.sponsorship_evidence ? `From the ad: “${job.sponsorship_evidence}”` : "The ad offers visa sponsorship." };
  }
  if (job.licensed_sponsor) {
    return { verdict: "Likely", why: "On the Home Office register of licensed sponsors, and the ad does not rule sponsorship out." };
  }
  return { verdict: "Not stated", why: "The ad says nothing about sponsorship and the employer is not on the register." };
}
