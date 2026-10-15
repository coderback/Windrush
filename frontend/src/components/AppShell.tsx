"use client";

import { usePathname } from "next/navigation";
import Sidebar from "./Sidebar";

const NO_SIDEBAR_ROUTES = ["/login", "/signup", "/onboarding"];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // "/" only redirects (to /login, /onboarding or /dashboard): no shell around its loading state.
  const showSidebar = pathname !== "/" &&
    !NO_SIDEBAR_ROUTES.some((r) => pathname === r || pathname.startsWith(r + "/"));

  if (!showSidebar) {
    return <>{children}</>;
  }

  return (
    <div className="md:flex min-h-screen bg-canvas">
      <Sidebar />
      <main className="flex-1 min-w-0 flex flex-col min-h-screen">
        {children}
      </main>
    </div>
  );
}
