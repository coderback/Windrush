"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function AppRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/jobs"); }, [router]);
  return (
    <div className="min-h-screen flex items-center justify-center text-zinc-600 text-sm">
      Redirecting…
    </div>
  );
}
