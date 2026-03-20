"use client";

export interface RoadmapItem {
  skill: string;
  action: string;
  timeline: string;
  resource: string;
}

interface Props {
  items: RoadmapItem[];
}

const TIMELINE_ORDER = ["1 month", "2 months", "3 months", "6 months", "12 months"];

export default function SkillRoadmap({ items }: Props) {
  if (items.length === 0) return null;

  return (
    <div>
      <h3 className="text-xs uppercase tracking-widest text-zinc-500 mb-3">
        Skill Pivot Roadmap
      </h3>
      <div className="relative">
        <div className="absolute left-3 top-0 bottom-0 w-px bg-zinc-800" />
        <div className="space-y-4">
          {items.map((item, i) => (
            <div key={i} className="relative pl-8">
              <div className="absolute left-0 w-6 h-6 rounded-full border-2 border-teal-500 bg-zinc-900 flex items-center justify-center">
                <div className="w-2 h-2 rounded-full bg-teal-500" />
              </div>
              <div className="text-xs text-teal-400 font-semibold mb-0.5">{item.timeline}</div>
              <div className="text-sm text-zinc-200 font-medium">{item.skill}</div>
              <div className="text-xs text-zinc-400 mt-0.5">{item.action}</div>
              {item.resource && (
                <div className="text-xs text-zinc-600 mt-0.5 italic">{item.resource}</div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
