"use client";

import { usePathname, useRouter } from "next/navigation";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: "▣" },
  { href: "/jobs", label: "Job Feed", icon: "⊕" },
  { href: "/applications", label: "Applications", icon: "◫" },
  { href: "/careers", label: "Careers", icon: "◈" },
];

const BOTTOM_NAV = [
  { href: "/profile", label: "Profile", icon: "◉" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();

  const logout = () => {
    localStorage.removeItem("windrush_token");
    router.push("/login");
  };

  const isActive = (href: string) => pathname === href || pathname.startsWith(href + "/");

  return (
    <aside className="w-56 shrink-0 flex flex-col border-r border-zinc-800 bg-zinc-950 h-screen sticky top-0">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-zinc-800">
        <h1
          className="text-xl font-bold text-zinc-100 cursor-pointer"
          style={{ fontFamily: "Playfair Display, serif" }}
          onClick={() => router.push("/dashboard")}
        >
          Windrush
        </h1>
        <p className="text-[10px] text-zinc-600 mt-0.5 uppercase tracking-widest">Career Navigator</p>
      </div>

      {/* Main nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV.map(({ href, label, icon }) => (
          <a
            key={href}
            href={href}
            className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
              isActive(href)
                ? "bg-zinc-800 text-teal-400 font-semibold"
                : "text-zinc-500 hover:text-zinc-200 hover:bg-zinc-900"
            }`}
          >
            <span className="text-base leading-none">{icon}</span>
            {label}
          </a>
        ))}
      </nav>

      {/* Bottom nav */}
      <div className="px-3 py-4 border-t border-zinc-800 space-y-0.5">
        {BOTTOM_NAV.map(({ href, label, icon }) => (
          <a
            key={href}
            href={href}
            className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
              isActive(href)
                ? "bg-zinc-800 text-teal-400 font-semibold"
                : "text-zinc-500 hover:text-zinc-200 hover:bg-zinc-900"
            }`}
          >
            <span className="text-base leading-none">{icon}</span>
            {label}
          </a>
        ))}
        <button
          onClick={logout}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-zinc-600 hover:text-zinc-300 hover:bg-zinc-900 transition-colors text-left"
        >
          <span className="text-base leading-none">→</span>
          Logout
        </button>
      </div>
    </aside>
  );
}