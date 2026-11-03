"use client";

import { useMemo, useState } from "react";
import { Segmented } from "@/components/ui/Tabs";
import { Card, cx, EmptyState } from "@/components/ui/kit";
import { buildFlow, FLOW_WIDTH, layoutFlow, NO_REPLY_DAYS, NODE_WIDTH, type FlowLink, type FlowNode } from "@/lib/flow";
import type { Application } from "@/lib/types";

type Span = "3m" | "6m" | "1y" | "2y";

const SPANS: { key: Span; label: string; days: number }[] = [
  { key: "3m", label: "3 months", days: 91 }, { key: "6m", label: "6 months", days: 182 },
  { key: "1y", label: "1 year", days: 365 }, { key: "2y", label: "2 years", days: 730 },
];

/* Three meanings, not one colour per node: moving forward, turned down, silence. Every node also says its name. */
const COLOUR: Record<FlowNode, string> = {
  Applied: "var(--blue)", Responded: "var(--blue)", Interview: "var(--blue)", Offer: "var(--blue)",
  Rejected: "var(--orange)", "No reply": "var(--ink-3)", "Still waiting": "var(--ink-3)", "Closed by you": "var(--ink-3)",
};

const linkText = (l: FlowLink) => `${l.from} to ${l.to}: ${l.value} ${l.value === 1 ? "application" : "applications"}`;

export default function ApplicationFlow({ apps }: { apps: Application[] }) {
  const [span, setSpan] = useState<Span>("6m");
  const [hover, setHover] = useState<{ link: FlowLink; x: number; y: number } | null>(null);
  const days = SPANS.find((s) => s.key === span)!.days;
  const flow = useMemo(() => buildFlow(apps, days), [apps, days]);
  const placed = useMemo(() => layoutFlow(flow), [flow]);
  const share = flow.total ? Math.round((flow.heardBack / flow.total) * 100) : 0;

  return (
    <Card className="p-5 flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1 min-w-0">
          <h2 className="m-0 text-[16px] font-semibold">How your applications went</h2>
          {flow.total > 0 && (
            <span className="text-[13px] text-ink-2">
              {flow.total} applied, {flow.heardBack} heard back ({share}%), {flow.nodes.Offer ?? 0} {flow.nodes.Offer === 1 ? "offer" : "offers"}.
            </span>
          )}
        </div>
        <Segmented label="Chart range" value={span} onChange={(s) => { setSpan(s); setHover(null); }} items={SPANS} />
      </div>

      {flow.total === 0 ? (
        <EmptyState>No applications sent in this period.</EmptyState>
      ) : (
        <>
          <div className="relative overflow-x-auto" onMouseLeave={() => setHover(null)}>
            <svg role="img" aria-label={`Sankey chart: ${flow.total} applications from Applied to where they ended up. The same figures are in the table below.`}
              viewBox={`0 0 ${FLOW_WIDTH} ${placed.height}`} className="block w-full min-w-[640px]">
              {placed.links.map((l) => {
                const on = hover?.link.from === l.from && hover.link.to === l.to;
                return (
                  <g key={`${l.from}-${l.to}`}>
                    <path d={l.path} fill="none" stroke={COLOUR[l.to]} strokeWidth={l.width} opacity={on ? 0.6 : 0.3} />
                    {/* A thicker invisible line, so a thin flow is still easy to point at. */}
                    <path d={l.path} fill="none" stroke="transparent" strokeWidth={Math.max(l.width, 12)} tabIndex={0} aria-label={linkText(l)}
                      className="outline-none"
                      onMouseMove={(e) => {
                        const box = e.currentTarget.ownerSVGElement!.parentElement!.getBoundingClientRect();
                        setHover({ link: l, x: e.clientX - box.left, y: e.clientY - box.top });
                      }}
                      onFocus={() => setHover({ link: l, x: 16, y: 16 })} onBlur={() => setHover(null)} />
                  </g>
                );
              })}
              {placed.nodes.map((n) => {
                const outcome = n.column === 3;
                return (
                  <g key={n.name}>
                    <rect x={n.x} y={n.y} width={NODE_WIDTH} height={n.height} rx={3} fill={COLOUR[n.name]} />
                    <text x={outcome ? n.x + NODE_WIDTH + 8 : n.x} y={outcome ? n.y + Math.min(n.height, 20) / 2 + 4 : n.y - 8}
                      className="fill-ink text-[13px]">
                      <tspan className="font-semibold">{n.name}</tspan>
                      <tspan className="fill-ink-2" dx={6}>{n.value}</tspan>
                    </text>
                  </g>
                );
              })}
            </svg>
            {hover && (
              <div role="status" style={{ left: hover.x + 12, top: hover.y + 12 }}
                className={cx("absolute pointer-events-none z-10 px-[10px] py-[6px] rounded-[8px] bg-ink text-on-ink text-[12.5px] whitespace-nowrap shadow-lift")}>
                {linkText(hover.link)}
              </div>
            )}
          </div>

          <details className="text-[13px]">
            <summary className="cursor-pointer text-ink-2">Show as a table</summary>
            <table className="mt-2 border-collapse text-[13px]">
              <thead>
                <tr className="text-left">
                  {["From", "To", "Applications"].map((h) => <th key={h} scope="col" className="micro font-normal pr-6 py-1">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {placed.links.map((l) => (
                  <tr key={`${l.from}-${l.to}`} className="border-t border-divider">
                    <td className="pr-6 py-1">{l.from}</td>
                    <td className="pr-6 py-1">{l.to}</td>
                    <td className="pr-6 py-1 font-mono">{l.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>

          <span className="text-[12px] leading-[1.5] text-ink-3">
            No reply means nothing has happened for {NO_REPLY_DAYS / 7} weeks. Built from your tracker and job emails, so it
            misses applications with no confirmation email and steps that happened by phone.
          </span>
        </>
      )}
    </Card>
  );
}
