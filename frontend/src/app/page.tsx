"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { authFetch } from "./api";
import Icon from "@/components/ui/Icon";

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
    <div className="min-h-screen flex items-center justify-center bg-canvas" role="status">
      <span className="w-8 h-8 rounded-[9px] bg-teal text-surface flex items-center justify-center">
        <Icon name="wind" size={18} strokeWidth={2} />
      </span>
      <span className="sr-only">Loading</span>
    </div>
  );
}
