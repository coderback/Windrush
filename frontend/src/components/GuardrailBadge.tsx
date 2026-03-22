"use client";

import { useEffect, useState } from "react";

interface GuardrailEvent {
  fired: boolean;
  check: string;
  detail?: string;
}

interface Props {
  lastGuardrailEvent?: GuardrailEvent | null;
}

export default function GuardrailBadge({ lastGuardrailEvent }: Props) {
  const [flashing, setFlashing] = useState(false);
  const [lastCheck, setLastCheck] = useState<string | null>(null);

  useEffect(() => {
    if (!lastGuardrailEvent?.fired) return;
    setFlashing(true);
    setLastCheck(lastGuardrailEvent.check);
    const t = setTimeout(() => setFlashing(false), 2000);
    return () => clearTimeout(t);
  }, [lastGuardrailEvent]);

  return (
    <div
      title={lastCheck ? `Last guardrail: ${lastCheck}` : "Civic guardrails active"}
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-semibold transition-all duration-300 ${
        flashing
          ? "border-red-500 bg-red-500/15 text-red-400 shadow-[0_0_8px_rgba(239,68,68,0.35)]"
          : "border-teal-700 bg-teal-500/10 text-teal-400"
      }`}
    >
      <svg
        width="11" height="11" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2.5"
        strokeLinecap="round" strokeLinejoin="round"
        className={flashing ? "animate-bounce" : ""}
      >
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      </svg>
      <span>Civic Guardrails</span>
      {flashing && lastCheck && (
        <span className="text-red-300 text-[10px] ml-0.5">⚠ {lastCheck}</span>
      )}
    </div>
  );
}
