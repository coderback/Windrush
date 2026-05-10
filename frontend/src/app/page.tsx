"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { authFetch } from "./api";

export default function RootPage() {
  const router = useRouter();

  useEffect(() => {
    const token = localStorage.getItem("windrush_token");
    if (!token) {
      router.replace("/login");
      return;
    }
    authFetch("/api/onboarding/status")
      .then((r) => r.json())
      .then((data) => {
        if (data.complete) {
          router.replace("/dashboard");
        } else {
          router.replace("/onboarding");
        }
      })
      .catch(() => router.replace("/dashboard"));
  }, [router]);

  return (
    <div className="min-h-screen flex items-center justify-center text-zinc-600 text-sm">
      Loading…
    </div>
  );
}