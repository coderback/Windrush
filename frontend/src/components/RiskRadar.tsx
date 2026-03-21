"use client";

export interface SkillRisk {
  skill: string;
  exposure: number;
  risk: "high" | "low";
}

interface Props {
  risks: SkillRisk[];
}

export default function RiskRadar({ risks }: Props) {
  if (risks.length === 0) return null;

  return (
    <div>
      <h3 className="text-xs uppercase tracking-widest text-zinc-500 mb-3">
        AI Exposure Risk
      </h3>
      <div className="space-y-2">
        {risks.map((r, i) => {
          const pct = Math.round(r.exposure * 100);
          const isHigh = r.exposure >= 0.35;
          return (
            <div key={i}>
              <div className="flex justify-between text-xs mb-0.5">
                <span className="text-zinc-300 truncate max-w-[60%]" title={r.skill}>
                  {r.skill}
                </span>
                <span className={isHigh ? "text-amber-400" : "text-teal-400"}>
                  {pct}%
                </span>
              </div>
              <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${
                    isHigh ? "bg-amber-500" : "bg-teal-500"
                  }`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
