"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import ApplicationTracker from "@/components/ApplicationTracker";

export default function TrackerPage() {
  const router = useRouter();

  useEffect(() => {
    const token = localStorage.getItem("windrush_token");
    if (!token) {
      router.push("/login");
    }
  }, [router]);

  return <ApplicationTracker />;
}
