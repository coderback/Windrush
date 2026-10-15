"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import AuthLayout from "@/components/AuthLayout";
import { buttonClass, Callout, inputClass, Spinner } from "@/components/ui/kit";
import { clearStore } from "@/lib/store";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const form = new FormData();
      form.append("username", email);
      form.append("password", password);

      const res = await fetch("/api/login", {
        method: "POST",
        body: form,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Sign in failed");
      }

      const { access_token } = await res.json();
      clearStore();
      localStorage.setItem("windrush_token", access_token);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed");
      setLoading(false);
    }
  };

  return (
    <AuthLayout>
      <form onSubmit={handleSubmit} className="flex flex-col gap-[22px]">
        <div className="flex flex-col gap-2">
          <h1 className="m-0 text-[30px] font-semibold tracking-[-0.03em]">Welcome back</h1>
          <p className="m-0 text-[14.5px] text-ink-2">Sign in to see your matches and anything waiting for your review.</p>
        </div>

        {error && <Callout>{error}</Callout>}

        <div className="flex flex-col gap-[6px]">
          <label htmlFor="email" className="text-[13px] font-semibold">Email</label>
          <input id="email" type="email" required autoComplete="email" placeholder="you@example.com"
            value={email} onChange={(e) => setEmail(e.target.value)} className={`${inputClass} h-11 px-[14px] text-[14.5px]`} />
        </div>

        <div className="flex flex-col gap-[6px]">
          {/* "Forgot password?" goes here once there is a reset flow. */}
          <label htmlFor="password" className="text-[13px] font-semibold">Password</label>
          <input id="password" type="password" required autoComplete="current-password"
            value={password} onChange={(e) => setPassword(e.target.value)} className={`${inputClass} h-11 px-[14px] text-[14.5px]`} />
        </div>

        <button type="submit" disabled={loading} className={buttonClass("primary", "xl", "h-[46px] text-[15px]")}>
          {loading ? <><Spinner /> Signing in…</> : "Sign in"}
        </button>

        <p className="m-0 text-[14px] text-ink-2 text-center">
          New to Windrush?{" "}
          <Link href="/signup" className="font-medium text-teal hover:text-teal-deep underline-offset-2 hover:underline">Create an account</Link>
        </p>
      </form>
    </AuthLayout>
  );
}
