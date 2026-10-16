"use client";

import { useState } from "react";
import { buttonClass } from "./ui/kit";

type Block = { kind: "p"; text: string } | { kind: "h"; text: string } | { kind: "ul"; items: string[] };

const BULLET = /^\s*(?:[-*•●▪◦]|\d+[.)])\s+/;

/** Turn an ad's plain text into paragraphs, short headings ("What you'll do") and lists. */
function blocks(text: string): Block[] {
  const lines = text.replace(/\r/g, "").split("\n").map((l) => l.trim());
  const out: Block[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line) continue;
    if (BULLET.test(line)) {
      const last = out[out.length - 1];
      const item = line.replace(BULLET, "");
      if (last?.kind === "ul") last.items.push(item);
      else out.push({ kind: "ul", items: [item] });
      continue;
    }
    const next = lines.slice(i + 1).find(Boolean) ?? "";
    const heading = line.length <= 60 && !/[.!?,;]$/.test(line) && (BULLET.test(next) || /:$/.test(line));
    out.push(heading ? { kind: "h", text: line.replace(/:$/, "") } : { kind: "p", text: line });
  }
  return out;
}

const LONG = 1600;

export default function JobDescription({ text }: { text?: string }) {
  const [full, setFull] = useState(false);
  if (!text?.trim()) {
    return <p className="m-0 text-[14px] text-ink-3">The ad&apos;s text isn&apos;t stored for this job. View the posting for the details.</p>;
  }
  const long = text.length > LONG;
  const shown = long && !full ? text.slice(0, LONG).replace(/\s+\S*$/, "") + "…" : text;
  return (
    <div className="flex flex-col gap-[14px] text-[14px] leading-[1.6] text-ink-2 max-w-[72ch]">
      {blocks(shown).map((b, i) =>
        b.kind === "h" ? <h3 key={i} className="m-0 text-[14px] font-semibold text-ink">{b.text}</h3>
        : b.kind === "ul" ? (
          <ul key={i} className="m-0 pl-[18px] flex flex-col gap-1 list-disc">
            {b.items.map((it, j) => <li key={j}>{it}</li>)}
          </ul>
        ) : <p key={i} className="m-0">{b.text}</p>,
      )}
      {long && (
        <button type="button" onClick={() => setFull((f) => !f)} className={buttonClass("secondary", "xs", "self-start")}>
          {full ? "Show less" : "Show the full description"}
        </button>
      )}
    </div>
  );
}
