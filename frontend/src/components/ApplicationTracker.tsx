"use client";

import { useEffect, useState } from "react";
import { authFetch } from "@/app/api";

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

const STATUSES = ["Evaluated", "Applied", "Responded", "Interview", "Offer", "Rejected", "Discarded"];

const statusStyle: Record<string, string> = {
  Evaluated:  "bg-zinc-700 text-zinc-300",
  Applied:    "bg-blue-500/20 text-blue-400",
  Responded:  "bg-amber-500/20 text-amber-400",
  Interview:  "bg-teal-500/20 text-teal-400",
  Offer:      "bg-green-500/20 text-green-400",
  Rejected:   "bg-red-500/20 text-red-400",
  Discarded:  "bg-zinc-800 text-zinc-600",
};

export default function ApplicationTracker() {
  const [apps, setApps] = useState<Application[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [loading, setLoading] = useState(true);

  const fetchApps = async (status?: string) => {
    setLoading(true);
    const url = status && status !== "all" ? `/api/applications?status=${status}` : "/api/applications";
    const res = await authFetch(url);
    if (res.ok) {
      setApps(await res.json());
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchApps();
  }, []);

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

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 p-6">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <a href="/app" className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
            ← Back to Windrush
          </a>
          <h1 className="mt-3 text-2xl font-bold" style={{ fontFamily: "Playfair Display, serif" }}>
            Application Tracker
          </h1>
          <p className="text-sm text-zinc-500 mt-1">{apps.length} application{apps.length !== 1 ? "s" : ""}</p>
        </div>

        {/* Status filter */}
        <div className="flex flex-wrap gap-2 mb-5">
          {["all", ...STATUSES].map((s) => (
            <button
              key={s}
              onClick={() => handleFilterChange(s)}
              className={`text-xs px-3 py-1 rounded border transition-colors ${
                filter === s
                  ? "border-teal-500 text-teal-400 bg-teal-500/10"
                  : "border-zinc-800 text-zinc-500 hover:border-zinc-600"
              }`}
            >
              {s === "all" ? "All" : s}
            </button>
          ))}
        </div>

        {/* Table */}
        {loading ? (
          <p className="text-zinc-500 text-sm">Loading…</p>
        ) : apps.length === 0 ? (
          <p className="text-zinc-500 text-sm">No applications yet. Start applying from the main app.</p>
        ) : (
          <div className="overflow-x-auto rounded border border-zinc-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800 text-xs uppercase tracking-widest text-zinc-500">
                  <th className="text-left px-4 py-3">Date</th>
                  <th className="text-left px-4 py-3">Company</th>
                  <th className="text-left px-4 py-3">Role</th>
                  <th className="text-left px-4 py-3">Score</th>
                  <th className="text-left px-4 py-3">Status</th>
                  <th className="text-left px-4 py-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {apps.map((app) => (
                  <tr key={app.id} className="border-b border-zinc-900 hover:bg-zinc-900/50 transition-colors">
                    <td className="px-4 py-3 text-zinc-500 whitespace-nowrap">
                      {app.date_applied ?? app.created_at?.slice(0, 10)}
                    </td>
                    <td className="px-4 py-3 font-medium text-zinc-200">{app.company}</td>
                    <td className="px-4 py-3">
                      {app.job_url ? (
                        <a
                          href={app.job_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-teal-400 hover:text-teal-300 underline underline-offset-2"
                        >
                          {app.job_title}
                        </a>
                      ) : (
                        <span className="text-zinc-300">{app.job_title}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-zinc-400">
                      {app.composite_score != null
                        ? `${Math.round(app.composite_score * 100)}`
                        : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`text-xs px-2 py-0.5 rounded font-semibold ${
                          statusStyle[app.status] ?? "bg-zinc-700 text-zinc-400"
                        }`}
                      >
                        {app.status}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <select
                        value={app.status}
                        onChange={(e) => handleStatusChange(app.id, e.target.value)}
                        className="text-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-zinc-300 focus:outline-none focus:border-teal-600"
                      >
                        {STATUSES.map((s) => (
                          <option key={s} value={s}>{s}</option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
