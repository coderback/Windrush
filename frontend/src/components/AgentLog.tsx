"use client";

import { useEffect, useRef } from "react";

export interface AgentEvent {
  type: "start" | "tool_call" | "tool_result" | "text" | "done";
  timestamp: number;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  result?: unknown;
  text?: string;
  message?: string;
}

interface Props {
  events: AgentEvent[];
}

function truncate(val: unknown, max = 200): string {
  const s = typeof val === "string" ? val : JSON.stringify(val, null, 2);
  return s.length > max ? s.slice(0, max) + "…" : s;
}

export default function AgentLog({ events }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  if (events.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-600 text-sm">
        Upload a CV to start the agent pipeline
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto space-y-2 pr-1">
      {events.map((ev, i) => (
        <div key={i} className="text-xs leading-relaxed">
          {ev.type === "start" && (
            <div className="text-zinc-500">
              <span className="text-zinc-600 mr-2">[{new Date(ev.timestamp * 1000).toLocaleTimeString()}]</span>
              <span className="text-teal-400">▶ {ev.message}</span>
            </div>
          )}

          {ev.type === "tool_call" && (
            <div className="border-l-2 border-amber-500 pl-2 py-0.5">
              <div className="text-amber-400 font-semibold">
                <span className="text-zinc-600 mr-2">[{new Date(ev.timestamp * 1000).toLocaleTimeString()}]</span>
                ⚙ {ev.tool_name}
              </div>
              {ev.tool_input && (
                <pre className="text-amber-300/70 mt-0.5 whitespace-pre-wrap break-all">
                  {truncate(ev.tool_input)}
                </pre>
              )}
            </div>
          )}

          {ev.type === "tool_result" && (
            <div className="border-l-2 border-teal-600 pl-2 py-0.5">
              <div className="text-teal-400 font-semibold">
                <span className="text-zinc-600 mr-2">[{new Date(ev.timestamp * 1000).toLocaleTimeString()}]</span>
                ✓ {ev.tool_name}
              </div>
              {ev.result !== undefined && (
                <pre className="text-teal-300/70 mt-0.5 whitespace-pre-wrap break-all">
                  {truncate(ev.result)}
                </pre>
              )}
            </div>
          )}

          {ev.type === "text" && ev.text && (
            <div className="text-zinc-300 pl-2 py-0.5 italic border-l-2 border-zinc-700">
              <span className="text-zinc-600 mr-2">[{new Date(ev.timestamp * 1000).toLocaleTimeString()}]</span>
              {ev.text}
            </div>
          )}

          {ev.type === "done" && (
            <div className="text-teal-400 font-bold">
              <span className="text-zinc-600 mr-2">[{new Date(ev.timestamp * 1000).toLocaleTimeString()}]</span>
              ✔ {ev.message ?? "Pipeline complete"}
            </div>
          )}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
