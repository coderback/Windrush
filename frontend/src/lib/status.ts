/* Backend application status → label and colours (HANDOFF section 2). The statuses themselves
   stay as the API has them; only what the user sees changes. */

export interface StatusMeta {
  label: string;
  dot: string;   // background class for the colour dot / bar
  chip: string;  // background + text classes for the chip
}

export const STATUS: Record<string, StatusMeta> = {
  Saved: { label: "Saved", dot: "bg-stone", chip: "bg-muted text-ink-2" },
  Evaluated: { label: "Saved", dot: "bg-stone", chip: "bg-muted text-ink-2" },
  "Pending Review": { label: "Needs review", dot: "bg-amber", chip: "bg-amber-soft text-amber-text" },
  Applied: { label: "Applied", dot: "bg-blue", chip: "bg-blue-soft text-blue-text" },
  Responded: { label: "Responded", dot: "bg-violet", chip: "bg-violet-soft text-violet-text" },
  Interview: { label: "Interview", dot: "bg-teal", chip: "bg-teal-chip text-teal-deep" },
  Offer: { label: "Offer", dot: "bg-green", chip: "bg-green-soft text-green-text" },
  Rejected: { label: "Rejected", dot: "bg-orange", chip: "bg-red-soft text-red" },
  Discarded: { label: "Discarded", dot: "bg-border-strong", chip: "bg-surface border border-border text-ink-3" },
};

export function statusMeta(status: string): StatusMeta {
  return STATUS[status] ?? { label: status, dot: "bg-stone", chip: "bg-muted text-ink-2" };
}

/** Board columns, in order. "Saved" also holds Evaluated; closed columns show on request. */
export const OPEN_STAGES = ["Saved", "Pending Review", "Applied", "Responded", "Interview", "Offer"] as const;
export const CLOSED_STAGES = ["Rejected", "Discarded"] as const;
export const CLOSED = new Set<string>(CLOSED_STAGES);

/** Which board column a status belongs in. */
export function stageOf(status: string): string {
  return status === "Evaluated" ? "Saved" : status;
}

/** Statuses offered in the status <select>, as backend values. */
export const STATUS_CHOICES = ["Saved", "Pending Review", "Applied", "Responded", "Interview", "Offer", "Rejected", "Discarded"];

/** Sent applications (for reply rates): everything that left the building. */
export const SENT = new Set(["Applied", "Responded", "Interview", "Offer", "Rejected"]);
export const REPLIED = new Set(["Responded", "Interview", "Offer"]);

/* AI exposure thresholds, matching the backend: Low < 35, Medium 35–65, High ≥ 65. */
export type RiskLevel = "Low" | "Medium" | "High";

export function riskLevel(score: number): RiskLevel {
  return score >= 65 ? "High" : score >= 35 ? "Medium" : "Low";
}

export const RISK: Record<RiskLevel, { bar: string; text: string; chip: string }> = {
  Low: { bar: "bg-teal", text: "text-teal", chip: "bg-teal-chip text-teal-deep" },
  Medium: { bar: "bg-amber", text: "text-amber-text", chip: "bg-amber-soft text-amber-text" },
  High: { bar: "bg-orange", text: "text-orange-text", chip: "bg-red-soft text-orange-text" },
};

/** Fit ring stroke: ≥ 80 teal, 70–79 blue, < 70 amber. */
export function fitColor(value: number): string {
  return value >= 80 ? "var(--teal)" : value >= 70 ? "var(--blue)" : "var(--amber)";
}

export function fitVerdict(value: number): string {
  return value >= 80 ? "Strong match" : value >= 70 ? "Good match" : value >= 50 ? "Partial match" : "Weak match";
}
