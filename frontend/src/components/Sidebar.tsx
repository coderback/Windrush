"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Icon, { type IconName } from "@/components/ui/Icon";
import { cx } from "@/components/ui/kit";
import { clearStore, useResource } from "@/lib/store";
import { displayName, personaStrength } from "@/lib/persona";
import { applyTheme, readTheme, saveTheme, type ThemeChoice } from "@/lib/theme";
import type { Application, AutopilotRun, EmailEvent, Persona, ProfileSuggestions } from "@/lib/types";

interface NavItem {
  href: string;
  label: string;
  icon: IconName;
  badge?: number;
  badgeTone?: "teal" | "amber";
  /** Other paths that light this item up (the job workspace belongs to the feed). */
  match?: string[];
}

const SENIORITY = /^(graduate|junior|senior|lead|principal|intern|entry)/i;

function Logo() {
  return (
    <Link href="/dashboard" className="flex items-center gap-[10px] px-[6px] py-[2px] text-ink no-underline">
      <span className="w-8 h-8 rounded-[9px] bg-teal text-surface flex items-center justify-center shrink-0">
        <Icon name="wind" size={18} strokeWidth={2} />
      </span>
      <span className="flex flex-col gap-px">
        <span className="text-[16px] font-[650] tracking-[-0.02em] leading-tight">windrush</span>
        <span className="text-[11.5px] text-ink-3 leading-tight">Career navigator</span>
      </span>
    </Link>
  );
}

function NavGroup({ title, items, isActive }: { title: string; items: NavItem[]; isActive: (i: NavItem) => boolean }) {
  return (
    <div className="flex flex-col gap-[2px]">
      <span className="micro px-[10px] pb-[6px]">{title}</span>
      {items.map((item) => {
        const on = isActive(item);
        return (
          <Link key={item.href} href={item.href} aria-current={on ? "page" : undefined}
            className={cx(
              "flex items-center gap-[10px] h-[38px] px-[10px] rounded-[9px] text-[14px] no-underline",
              on ? "bg-muted text-ink font-semibold" : "text-ink-2 font-medium hover:bg-subtle hover:text-ink",
            )}>
            <Icon name={item.icon} size={18} strokeWidth={1.7} className={on ? "text-teal" : "text-ink-3"} />
            <span className="flex-1 min-w-0 truncate">{item.label}</span>
            {!!item.badge && (
              <span className={cx(
                "min-w-5 h-5 px-[6px] rounded-full font-mono text-[11px] font-semibold flex items-center justify-center",
                item.badgeTone === "amber" ? "bg-amber-chip text-amber-text" : "bg-teal-logo text-teal",
              )}>
                {item.badge}
                <span className="sr-only">{item.badgeTone === "amber" ? " waiting" : " new"}</span>
              </span>
            )}
          </Link>
        );
      })}
    </div>
  );
}

function ThemeSwitch() {
  const [choice, setChoice] = useState<ThemeChoice>("system");
  useEffect(() => setChoice(readTheme()), []);
  // Follow the OS while on "System".
  useEffect(() => {
    if (choice !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [choice]);
  const opts: { key: ThemeChoice; label: string; icon: IconName }[] = [
    { key: "light", label: "Light", icon: "sun" },
    { key: "dark", label: "Dark", icon: "moon" },
    { key: "system", label: "System", icon: "monitor" },
  ];
  return (
    <div role="group" aria-label="Theme" className="flex p-[3px] border border-border rounded-control bg-subtle">
      {opts.map((o) => {
        const on = o.key === choice;
        return (
          <button key={o.key} type="button" aria-pressed={on}
            onClick={() => { setChoice(o.key); saveTheme(o.key); }}
            className={cx(
              "flex-1 h-7 rounded-[7px] inline-flex items-center justify-center gap-[5px] text-[12px]",
              on ? "bg-surface text-ink font-semibold shadow-lift" : "text-ink-3 hover:text-ink",
            )}>
            <Icon name={o.icon} size={13} />
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const persona = useResource<Persona>("/api/persona");
  const apps = useResource<Application[]>("/api/applications");

  useEffect(() => setOpen(false), [pathname]);

  const waiting = (apps.data ?? []).filter((a) => a.status === "Pending Review").length;
  const autopilot = useResource<AutopilotRun[]>("/api/autopilot/runs");
  const held = (autopilot.data ?? []).filter((r) =>
    r.outcome === "needs_you" || r.outcome === "unconfirmed" || r.outcome === "awaiting_code").length;
  const emails = useResource<EmailEvent[]>("/api/gmail/events");
  const emailsWaiting = (emails.data ?? []).filter((e) => e.decision === "suggested" || e.decision === "unmatched").length;
  const suggestions = useResource<ProfileSuggestions>("/api/profile/suggestions");
  const suggested = suggestions.data?.suggestions.length ?? 0;
  const workspace: NavItem[] = [
    { href: "/dashboard", label: "Home", icon: "home" },
    { href: "/jobs", label: "Job feed", icon: "feed" },
    { href: "/autopilot", label: "Autopilot", icon: "play", badge: held, badgeTone: "amber" },
    { href: "/review", label: "Agent review", icon: "eye", badge: waiting, badgeTone: "amber" },
    { href: "/applications", label: "Applications", icon: "board" },
    { href: "/inbox", label: "Inbox", icon: "mail", badge: emailsWaiting, badgeTone: "amber" },
  ];
  const grow: NavItem[] = [
    { href: "/careers", label: "AI exposure & roadmap", icon: "trend" },
    { href: "/profile", label: "Persona", icon: "user", badge: suggested },
  ];
  const isActive = (i: NavItem) => pathname === i.href || pathname.startsWith(i.href + "/");

  const p = persona.data;
  const strength = p ? personaStrength(p) : null;
  const name = displayName(p) || "Your account";
  const userInitials = name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "?";
  const level = p?.preferences?.target_titles?.[0]?.match(SENIORITY)?.[0];
  const line = [level && level[0].toUpperCase() + level.slice(1).toLowerCase(), p?.core_info.city].filter(Boolean).join(" · ")
    || p?.core_info.email || "";

  const logout = () => {
    localStorage.removeItem("windrush_token");
    clearStore();
    router.push("/login");
  };

  return (
    <aside className="md:w-[240px] md:shrink-0 md:h-screen md:sticky md:top-0 bg-surface border-b md:border-b-0 md:border-r border-border">
      <nav aria-label="Main" className="h-full md:overflow-y-auto box-border px-[14px] pt-4 md:pt-5 pb-4 md:pb-[18px] flex flex-col gap-[22px]">
        <div className="flex items-center justify-between gap-2">
          <Logo />
          <button type="button" aria-expanded={open} aria-controls="sidebar-menu" onClick={() => setOpen((o) => !o)}
            className="md:hidden inline-flex items-center gap-2 h-11 px-3 rounded-control border border-border text-[13.5px] font-medium text-ink">
            <Icon name={open ? "close" : "menu"} size={17} />
            Menu
            {waiting > 0 && <span className="w-[7px] h-[7px] rounded-full bg-amber" aria-label={`${waiting} waiting for review`} />}
          </button>
        </div>

        <div id="sidebar-menu" className={cx("flex-col gap-[22px] flex-1", open ? "flex" : "hidden md:flex")}>
          <NavGroup title="Workspace" items={workspace} isActive={isActive} />
          <NavGroup title="Grow" items={grow} isActive={isActive} />

          <div className="flex-1" />

          {strength && (
            <Link href="/profile" className="flex flex-col gap-[10px] p-[14px] border border-border rounded-inner bg-subtle text-ink no-underline hover:border-border-strong">
              <span className="flex justify-between items-baseline">
                <span className="text-[13px] font-semibold">Persona strength</span>
                <span className="font-mono text-[12px] font-semibold text-teal">{strength.pct}%</span>
              </span>
              <span className="block h-[6px] rounded-full bg-border overflow-hidden" aria-hidden="true">
                <span className="block h-full rounded-full bg-teal" style={{ width: `${strength.pct}%` }} />
              </span>
              <span className="text-[12px] leading-[1.45] text-ink-2">
                {strength.todos[0] ? `${strength.todos[0]}.` : "Your persona is complete. The agent has what it needs."}
              </span>
            </Link>
          )}

          <div className="flex flex-col gap-3 border-t border-track pt-[14px]">
            <div className="flex items-center gap-[10px] px-[6px]">
              <span aria-hidden="true" className="w-[34px] h-[34px] rounded-full bg-ink text-surface flex items-center justify-center text-[12.5px] font-semibold shrink-0">
                {userInitials}
              </span>
              <span className="flex flex-col gap-px flex-1 min-w-0">
                <span className="text-[13.5px] font-semibold truncate">{name}</span>
                {line && <span className="text-[12px] text-ink-3 truncate">{line}</span>}
              </span>
              <button type="button" aria-label="Log out" title="Log out" onClick={logout}
                className="w-[34px] h-[34px] rounded-[8px] text-ink-3 hover:text-ink hover:bg-muted flex items-center justify-center shrink-0">
                <Icon name="logout" size={17} strokeWidth={1.7} />
              </button>
            </div>
            <ThemeSwitch />
          </div>
        </div>
      </nav>
    </aside>
  );
}
