"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Landing from "@/components/Landing";

export default function Home() {
  const router = useRouter();
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleStart = async (file?: File) => {
    if (!file) {
      router.push("/app");
      return;
    }

    setUploading(true);
    setError(null);

    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch("/api/upload", { method: "POST", body: form });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error((data as { detail?: string }).detail ?? "Upload failed");
      }
      const { cv_session_id } = await res.json() as { cv_session_id: string };
      router.push(`/app?cv=${cv_session_id}`);
    } catch (err) {
      setError(String(err));
      setUploading(false);
    }
  };

  return <Landing onStart={handleStart} uploading={uploading} error={error} />;
}
