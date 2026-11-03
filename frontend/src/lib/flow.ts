import { daysSince } from "./format";
import { SENT } from "./status";
import type { Application } from "./types";

/* How applications went, for the Sankey on the Applications page: each one's path from Applied through the steps its
   history shows to where it ended up. */

export const NO_REPLY_DAYS = 28;

export type FlowNode = "Applied" | "Responded" | "Interview" | "Offer" | "Rejected" | "No reply" | "Still waiting" | "Closed by you";
export interface FlowLink { from: FlowNode; to: FlowNode; value: number }
export interface Flow {
  total: number;
  /** Got any reply: went past Applied, or was turned down. */
  heardBack: number;
  nodes: Partial<Record<FlowNode, number>>;
  links: FlowLink[];
}

const appliedOn = (a: Application): string | null =>
  a.date_applied ?? a.history?.find((s) => SENT.has(s.status))?.changed_at ?? (SENT.has(a.status) ? a.created_at : null);

/** Where it ended up. With nothing final, what counts is how long since anything happened to it. */
function outcome(a: Application, applied: string): FlowNode {
  if (a.status === "Offer") return "Offer";
  if (a.status === "Rejected") return "Rejected";
  if (a.status === "Discarded") return "Closed by you";
  const last = a.history?.length ? a.history[a.history.length - 1].changed_at : applied;
  return (daysSince(last) ?? 0) >= NO_REPLY_DAYS ? "No reply" : "Still waiting";
}

/** Applications applied to within the last `days` days, as flows between steps. Ones never sent aren't in it. */
export function buildFlow(apps: Application[], days: number): Flow {
  const links = new Map<string, FlowLink>();
  const nodes: Flow["nodes"] = {};
  let total = 0;
  let heardBack = 0;
  for (const a of apps) {
    const applied = appliedOn(a);
    if (!applied || (daysSince(applied) ?? 0) > days) continue;
    const reached = new Set([a.status, ...(a.history ?? []).map((s) => s.status)]);
    const end = outcome(a, applied);
    const path: FlowNode[] = ["Applied", ...(["Responded", "Interview"] as const).filter((s) => reached.has(s)), end];
    total += 1;
    if (path.length > 2 || end === "Rejected" || end === "Offer") heardBack += 1;
    path.forEach((node, i) => {
      nodes[node] = (nodes[node] ?? 0) + 1;
      if (i === 0) return;
      const key = `${path[i - 1]}>${node}`;
      const link = links.get(key) ?? { from: path[i - 1], to: node, value: 0 };
      link.value += 1;
      links.set(key, link);
    });
  }
  return { total, heardBack, nodes, links: Array.from(links.values()) };
}

/* Where everything goes on the page: fixed columns in reading order, heights to one scale. */

const COLUMNS: FlowNode[][] = [["Applied"], ["Responded"], ["Interview"],
  ["Offer", "Rejected", "No reply", "Still waiting", "Closed by you"]];
const ORDER: FlowNode[] = COLUMNS.flat();
export const FLOW_WIDTH = 900;
export const NODE_WIDTH = 12;
const LEFT = 8;
const LABELS_RIGHT = 150;   // room for the outcomes' labels
const TOP = 30;
const GAP = 30;             // keeps neighbouring labels apart, however small the nodes
const BODY = 280;
const MIN_NODE = 4;
const MIN_LINK = 1.5;

export interface PlacedNode { name: FlowNode; value: number; x: number; y: number; height: number; column: number }
export interface PlacedLink extends FlowLink { width: number; path: string }

export function layoutFlow(flow: Flow): { nodes: PlacedNode[]; links: PlacedLink[]; height: number } {
  const scale = flow.total ? BODY / flow.total : 0;
  const step = (FLOW_WIDTH - LEFT - LABELS_RIGHT - NODE_WIDTH) / (COLUMNS.length - 1);
  const placed = new Map<FlowNode, PlacedNode>();
  let height = TOP;
  COLUMNS.forEach((names, column) => {
    let y = TOP;
    for (const name of names) {
      const value = flow.nodes[name];
      if (!value) continue;
      const nodeHeight = Math.max(MIN_NODE, value * scale);
      placed.set(name, { name, value, x: LEFT + column * step, y, height: nodeHeight, column });
      y += nodeHeight + GAP;
    }
    height = Math.max(height, y - GAP);
  });
  // Links leave and arrive stacked, in the order of the nodes at their other end, so fewer of them cross.
  const out = new Map<FlowNode, number>();
  const into = new Map<FlowNode, number>();
  const sorted = [...flow.links].sort((a, b) => ORDER.indexOf(a.from) - ORDER.indexOf(b.from) || ORDER.indexOf(a.to) - ORDER.indexOf(b.to));
  const links = sorted.map((link) => {
    const from = placed.get(link.from)!;
    const to = placed.get(link.to)!;
    const share = (node: PlacedNode) => Math.max(MIN_LINK, link.value * (node.height / node.value));
    const fromShare = share(from);
    const toShare = share(to);
    const y0 = from.y + (out.get(link.from) ?? 0) + fromShare / 2;
    const y1 = to.y + (into.get(link.to) ?? 0) + toShare / 2;
    out.set(link.from, (out.get(link.from) ?? 0) + fromShare);
    into.set(link.to, (into.get(link.to) ?? 0) + toShare);
    const x0 = from.x + NODE_WIDTH;
    const x1 = to.x;
    const mid = (x0 + x1) / 2;
    return { ...link, width: Math.max(fromShare, toShare), path: `M${x0},${y0} C${mid},${y0} ${mid},${y1} ${x1},${y1}` };
  });
  return { nodes: Array.from(placed.values()), links, height: height + 8 };
}
