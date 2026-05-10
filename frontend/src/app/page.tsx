"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Landing from "@/components/Landing";
import { authFetch } from "./api";

export default function Home() {
  const router = useRouter();
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAuth, setIsAuth] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("windrush_token");
    if (!token) {
      router.push("/login");
    } else {
      setIsAuth(true);
    }
  }, [router]);

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
      const res = await authFetch("/api/upload", { method: "POST", body: form });
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

  return (
    <>
      {isAuth && (
        <div className="absolute top-4 right-6 flex gap-4 z-20">
          <a href="/profile" className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">Persona Profile</a>
          <button 
            onClick={() => { localStorage.removeItem("windrush_token"); router.push("/login"); }}
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          >Logout</button>
        </div>
      )}
      <Landing onStart={handleStart} uploading={uploading} error={error} />
    </>
  );
}
