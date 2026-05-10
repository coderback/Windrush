"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { authFetch } from "../api";

interface Application {
  id: string;
  job_title: string;
  company: string;
  status: string;
  applied_at: string;
  fit_score?: number;
}

interface SkillRisk {
  skill: string;
  exposure_score: number;
  risk_label: string;
}

interface Stats {
  total: number;
  active: number;
  this_week: number;
  avg_fit: number | null;
}

const STATUS_COLORS: Record<string, string> = {
  "Pending Review": "text-yellow-400 bg-yellow-400/10 border-yellow-400/20",
  Applied: "text-blue-400 bg-blue-400/10 border-blue-400/20",
  Interview: "text-teal-400 bg-teal-400/10 border-teal-400/20",
  Offer: "text-green-400 bg-green-400/10 border-green-400/20",
  Rejected: "text-red-400 bg-red-400/10 border-red-400/20",
  Evaluated: "text-zinc-400 bg-zinc-400/10 border-zinc-400/20",
};

const RISK_COLORS: Record<string, string> = {
  High: "text-red-400",
  Medium: "text-yellow-400",
  Low: "text-teal-400",
};

export default function DashboardPage() {
  const router = useRouter();
  const [applications, setApplications] = useState<Application[]>([]);
  const [skills, setSkills] = useState<SkillRisk[]>([]);
  const [stats, setStats] = useState<Stats>({ total: 0, active: 0, this_week: 0, avg_fit: null });
  const [loadingApps, setLoadingApps] = useState(true);
  const [loadingSkills, setLoadingSkills] = useState(true);

  useEffect(() => {
    authFetch("/api/applications")
      .then((r) => r.json())
      .then((data: Application[]) => {
        setApplications(data);
        const now = new Date();
        const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        const active = data.filter((a) => ["Interview", "Offer"].includes(a.status)).length;
        const thisWeek = data.filter((a) => new Date(a.applied_at) >= weekAgo).length;
        const scores = data.map((a) => a.fit_score).filter((s): s is number => s != null);
        const avgFit = scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null;
        setStats({ total: data.length, active, this_week: thisWeek, avg_fit: avgFit });
      })
      .catch(() => {})
      .finally(() => setLoadingApps(false));

    authFetch("/api/score-skills", { method: "POST" })
      .then((r) => r.json())
      .then((data: { skill_risks?: SkillRisk[] }) => {
        const risks = (data.skill_risks ?? [])
          .sort((a, b) => b.exposure_score - a.exposure_score)
          .slice(0, 5);
        setSkills(risks);
      })
      .catch(() => {})
      .finally(() => setLoadingSkills(false));
  }, []);

  const recentApps = applications.slice(0, 5);

  return (
    <div className="p-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-zinc-100" style={{ fontFamily: "Playfair Display, serif" }}>
          Dashboard
        </h1>
        <p className="text-zinc-500 text-sm mt-1">Your career at a glance</p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        {[
          { label: "Total Applications", value: loadingApps ? "—" : stats.total },
          { label: "Active (Interview / Offer)", value: loadingApps ? "—" : stats.active },
          { label: "Applied This Week", value: loadingApps ? "—" : stats.this_week },
          { label: "Avg Fit Score", value: loadingApps ? "—" : stats.avg_fit != null ? `${stats.avg_fit}%` : "N/A" },
        ].map(({ label, value }) => (
          <div key={label} className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-5">
            <p className="text-xs text-zinc-600 uppercase tracking-widest mb-2">{label}</p>
            <p className="text-2xl font-bold text-zinc-100">{value}</p>
          </div>
        ))}
      </div>

      {/* Main content grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        {/* Recent Applications — 2/3 width */}
        <div className="lg:col-span-2 bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-widest">Recent Applications</h2>
            <button
              onClick={() => router.push("/applications")}
              className="text-xs text-teal-500 hover:underline"
            >
              View all →
            </button>
          </div>
          {loadingApps ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="h-12 bg-zinc-800/50 rounded-lg animate-pulse" />
              ))}
            </div>
          ) : recentApps.length === 0 ? (
            <div className="text-center py-10">
              <p className="text-zinc-600 text-sm">No applications yet.</p>
              <button
                onClick={() => router.push("/jobs")}
                className="mt-3 text-xs text-teal-500 hover:underline"
              >
                Browse jobs to get started →
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              {recentApps.map((app) => (
                <div
                  key={app.id}
                  className="flex items-center justify-between py-3 border-b border-zinc-800 last:border-0"
                >
                  <div>
                    <p className="text-sm text-zinc-200 font-medium">{app.job_title}</p>
                    <p className="text-xs text-zinc-500">{app.company}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    {app.fit_score != null && (
                      <span className="text-xs text-zinc-500">{app.fit_score}% fit</span>
                    )}
                    <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${STATUS_COLORS[app.status] ?? "text-zinc-400 bg-zinc-800 border-zinc-700"}`}>
                      {app.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* AI Risk Summary — 1/3 width */}
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-widest">AI Exposure Risk</h2>
            <button
              onClick={() => router.push("/careers")}
              className="text-xs text-teal-500 hover:underline"
            >
              Full analysis →
            </button>
          </div>
          {loadingSkills ? (
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="h-8 bg-zinc-800/50 rounded animate-pulse" />
              ))}
            </div>
          ) : skills.length === 0 ? (
            <p className="text-zinc-600 text-sm text-center py-8">Upload a CV to see skill risk analysis.</p>
          ) : (
            <div className="space-y-3">
              {skills.map((s) => (
                <div key={s.skill} className="flex items-center justify-between">
                  <span className="text-xs text-zinc-400 truncate max-w-[120px]">{s.skill}</span>
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${s.risk_label === "High" ? "bg-red-500" : s.risk_label === "Medium" ? "bg-yellow-500" : "bg-teal-500"}`}
                        style={{ width: `${s.exposure_score}%` }}
                      />
                    </div>
                    <span className={`text-[10px] font-medium ${RISK_COLORS[s.risk_label] ?? "text-zinc-400"}`}>
                      {s.risk_label}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          {
            label: "Browse Jobs",
            description: "Find new opportunities matching your profile",
            href: "/jobs",
            icon: "⊕",
          },
          {
            label: "View Applications",
            description: "Track and manage all your applications",
            href: "/applications",
            icon: "◫",
          },
          {
            label: "Update Profile",
            description: "Refine your persona and credentials",
            href: "/profile",
            icon: "◉",
          },
        ].map(({ label, description, href, icon }) => (
          <button
            key={href}
            onClick={() => router.push(href)}
            className="group text-left bg-zinc-900/50 border border-zinc-800 hover:border-teal-600/50 rounded-xl p-5 transition-colors"
          >
            <span className="text-xl mb-3 block">{icon}</span>
            <p className="text-sm font-semibold text-zinc-200 group-hover:text-teal-300 transition-colors">{label}</p>
            <p className="text-xs text-zinc-600 mt-1">{description}</p>
          </button>
        ))}
      </div>
    </div>
  );
}