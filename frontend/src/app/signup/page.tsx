"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import AuthLayout from "@/components/AuthLayout";
import { buttonClass, Callout, inputClass, Spinner } from "@/components/ui/kit";
import { authFetch } from "../api";
import { clearStore } from "@/lib/store";

const field = `${inputClass} h-11 px-[14px] text-[14.5px]`;

export default function SignupPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** The API's signup takes only email and password; the name goes into the new persona. */
  const saveName = async () => {
    const [first, ...rest] = name.trim().split(/\s+/);
    if (!first) return;
    try {
      const res = await authFetch("/api/persona");
      if (!res.ok) return;
      const persona = await res.json();
      persona.core_info = { ...persona.core_info, first_name: first, last_name: rest.join(" ") };
      await authFetch("/api/persona", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(persona),
      });
    } catch {}
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const form = new FormData();
      form.append("email", email);
      form.append("password", password);

      const res = await fetch("/api/signup", {
        method: "POST",
        body: form,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Sign up failed");
      }

      // Sign straight in after signing up.
      const loginForm = new FormData();
      loginForm.append("username", email);
      loginForm.append("password", password);

      const loginRes = await fetch("/api/login", {
        method: "POST",
        body: loginForm,
      });

      if (loginRes.ok) {
        const { access_token } = await loginRes.json();
        clearStore();
        localStorage.setItem("windrush_token", access_token);
        await saveName();
        router.push("/");
      } else {
        router.push("/login");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign up failed");
      setLoading(false);
    }
  };

  return (
    <AuthLayout>
      <form onSubmit={handleSubmit} className="flex flex-col gap-[22px]">
        <div className="flex flex-col gap-2">
          <h1 className="m-0 text-[30px] font-semibold tracking-[-0.03em]">Create your account</h1>
          <p className="m-0 text-[14.5px] text-ink-2">Three short steps after this and your feed is ready.</p>
        </div>

        {error && <Callout>{error}</Callout>}

        <div className="flex flex-col gap-[6px]">
          <label htmlFor="name" className="text-[13px] font-semibold">Name</label>
          <input id="name" type="text" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} className={field} />
        </div>
        <div className="flex flex-col gap-[6px]">
          <label htmlFor="email" className="text-[13px] font-semibold">Email</label>
          <input id="email" type="email" required autoComplete="email" placeholder="you@example.com"
            value={email} onChange={(e) => setEmail(e.target.value)} className={field} />
        </div>
        <div className="flex flex-col gap-[6px]">
          <label htmlFor="password" className="text-[13px] font-semibold">Password</label>
          <input id="password" type="password" required minLength={8} autoComplete="new-password" aria-describedby="pw-hint"
            value={password} onChange={(e) => setPassword(e.target.value)} className={field} />
          <span id="pw-hint" className="text-[12px] text-ink-3">At least 8 characters.</span>
        </div>

        <button type="submit" disabled={loading} className={buttonClass("primary", "xl", "h-[46px] text-[15px]")}>
          {loading ? <><Spinner /> Creating your account…</> : "Create account"}
        </button>

        <p className="m-0 text-[14px] text-ink-2 text-center">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-teal hover:text-teal-deep underline-offset-2 hover:underline">Sign in</Link>
        </p>
      </form>
    </AuthLayout>
  );
}
