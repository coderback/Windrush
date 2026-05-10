"use client";

import { useEffect, useState } from "react";
import { authFetch } from "../api";

interface Application {
  id: string;
  job_title: string;
  company: string;
  location: string;
  job_url: string;
  status: string;
  date_applied: string | null;
  composite_score: number | null;
  exposure_score: number | null;
  skill_gaps: string[];
  level_match: string;
  notes: string;
  created_at: string;
}

const STATUSES = ["Pending Review", "Evaluated", "Applied", "Responded", "Interview", "Offer", "Rejected", "Discarded"];

const STATUS_STYLE: Record<string, string> = {
  "Pending Review": "bg-yellow-500/20 text-yellow-400 border-yellow-500/20",
  Evaluated: "bg-zinc-700/50 text-zinc-400 border-zinc-700",
  Applied: "bg-blue-500/20 text-blue-400 border-blue-500/20",
  Responded: "bg-amber-500/20 text-amber-400 border-amber-500/20",
  Interview: "bg-teal-500/20 text-teal-400 border-teal-500/20",
  Offer: "bg-green-500/20 text-green-400 border-green-500/20",
  Rejected: "bg-red-500/20 text-red-400 border-red-500/20",
  Discarded: "bg-zinc-800 text-zinc-600 border-zinc-800",
};

export default function ApplicationsPage() {
  const [apps, setApps] = useState<Application[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [editingNotes, setEditingNotes] = useState<Record<string, string>>({});

  const fetchApps = async (status?: string) => {
    setLoading(true);
    const url = status && status !== "all" ? `/api/applications?status=${status}` : "/api/applications";
    try {
      const res = await authFetch(url);
      if (res.ok) setApps(await res.json());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchApps(); }, []);

  const handleFilterChange = (s: string) => {
    setFilter(s);
    fetchApps(s !== "all" ? s : undefined);
  };

  const handleStatusChange = async (id: string, newStatus: string) => {
    await authFetch(`/api/applications/${id}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: newStatus }),
    });
    fetchApps(filter !== "all" ? filter : undefined);
  };

  const saveNotes = async (id: string) => {
    const app = apps.find((a) => a.id === id);
    if (!app) return;
    await authFetch(`/api/applications/${id}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: app.status, notes: editingNotes[id] ?? "" }),
    });
    setApps((prev) => prev.map((a) => a.id === id ? { ...a, notes: editingNotes[id] ?? a.notes } : a));
  };

  const toggleExpand = (id: string, notes: string) => {
    if (expandedId === id) {
      setExpandedId(null);
    } else {
      setExpandedId(id);
      setEditingNotes((prev) => ({ ...prev, [id]: notes ?? "" }));
    }
  };

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-zinc-100" style={{ fontFamily: "Playfair Display, serif" }}>
          Applications
        </h1>
        <p className="text-zinc-500 text-sm mt-1">{apps.length} application{apps.length !== 1 ? "s" : ""} tracked</p>
      </div>

      {/* Filter tabs */}
      <div className="flex flex-wrap gap-2 mb-6">
        {["all", ...STATUSES].map((s) => (
          <button
            key={s}
            onClick={() => handleFilterChange(s)}
            className={`text-xs px-3 py-1 rounded-full border transition-colors ${
              filter === s
                ? "border-teal-500 text-teal-400 bg-teal-500/10"
                : "border-zinc-800 text-zinc-500 hover:border-zinc-600"
            }`}
          >
            {s === "all" ? "All" : s}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-14 bg-zinc-900/50 border border-zinc-800 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : apps.length === 0 ? (
        <div className="text-center py-16 text-zinc-600">
          <p className="text-sm">No applications yet. Apply to jobs from the Job Feed.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {apps.map((app) => (
            <div key={app.id} className="border border-zinc-800 rounded-xl overflow-hidden">
              {/* Row */}
              <div
                className="flex items-center gap-4 px-5 py-4 bg-zinc-900/50 hover:bg-zinc-900 transition-colors cursor-pointer"
                onClick={() => toggleExpand(app.id, app.notes)}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-zinc-200 truncate">{app.job_title}</span>
                    <span className="text-xs text-zinc-600">·</span>
                    <span className="text-xs text-zinc-500 truncate">{app.company}</span>
                  </div>
                  <div className="text-xs text-zinc-600 mt-0.5">{app.date_applied ?? app.created_at?.slice(0, 10)}</div>
                </div>

                <div className="flex items-center gap-3 shrink-0">
                  {app.composite_score != null && (
                    <span className="text-xs text-zinc-500">{Math.round(app.composite_score * 100)}% fit</span>
                  )}
                  <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${STATUS_STYLE[app.status] ?? "bg-zinc-700 text-zinc-400 border-zinc-700"}`}>
                    {app.status}
                  </span>
                  <select
                    value={app.status}
                    onChange={(e) => { e.stopPropagation(); handleStatusChange(app.id, e.target.value); }}
                    onClick={(e) => e.stopPropagation()}
                    className="text-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-zinc-400 focus:outline-none focus:border-teal-600"
                  >
                    {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                  <span className={`text-xs text-zinc-600 transition-transform ${expandedId === app.id ? "rotate-180" : ""}`}>▾</span>
                </div>
              </div>

              {/* Expanded row */}
              {expandedId === app.id && (
                <div className="px-5 py-4 bg-zinc-950 border-t border-zinc-800 space-y-4">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
                    <div>
                      <p className="text-zinc-600 uppercase tracking-widest mb-1">Location</p>
                      <p className="text-zinc-300">{app.location || "—"}</p>
                    </div>
                    <div>
                      <p className="text-zinc-600 uppercase tracking-widest mb-1">Level Match</p>
                      <p className="text-zinc-300">{app.level_match || "—"}</p>
                    </div>
                    <div>
                      <p className="text-zinc-600 uppercase tracking-widest mb-1">AI Exposure</p>
                      <p className="text-zinc-300">{app.exposure_score != null ? `${app.exposure_score}%` : "—"}</p>
                    </div>
                    {app.job_url && (
                      <div>
                        <p className="text-zinc-600 uppercase tracking-widest mb-1">Posting</p>
                        <a href={app.job_url} target="_blank" rel="noopener noreferrer" className="text-teal-400 hover:underline">
                          View ↗
                        </a>
                      </div>
                    )}
                  </div>

                  {app.skill_gaps && app.skill_gaps.length > 0 && (
                    <div>
                      <p className="text-xs text-zinc-600 uppercase tracking-widest mb-2">Skill Gaps</p>
                      <div className="flex flex-wrap gap-2">
                        {app.skill_gaps.map((gap) => (
                          <span key={gap} className="text-xs px-2 py-0.5 border border-yellow-500/30 bg-yellow-500/10 text-yellow-400 rounded-full">
                            {gap}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="space-y-2">
                    <p className="text-xs text-zinc-600 uppercase tracking-widest">Notes</p>
                    <textarea
                      value={editingNotes[app.id] ?? ""}
                      onChange={(e) => setEditingNotes((prev) => ({ ...prev, [app.id]: e.target.value }))}
                      rows={3}
                      placeholder="Add notes about this application…"
                      className="w-full bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2 text-xs text-zinc-300 focus:outline-none focus:border-teal-500 resize-none transition-colors"
                    />
                    <button
                      onClick={() => saveNotes(app.id)}
                      className="text-xs px-3 py-1.5 bg-teal-600 text-white rounded-lg hover:bg-teal-500 transition-colors"
                    >
                      Save Notes
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}