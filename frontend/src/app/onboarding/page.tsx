"use client";

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { authFetch } from "../api";

type Step = "cv" | "credentials" | "persona";

interface PersonaCore {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  city: string;
  job_email: string;
  job_password: string;
}

interface PersonaPrefs {
  target_titles: string[];
  preferred_locations: string[];
  remote_preference: string;
}

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("cv");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Credential step
  const [jobEmail, setJobEmail] = useState("");
  const [jobPassword, setJobPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  // Persona step — pre-filled from CV extraction
  const [core, setCore] = useState<PersonaCore>({
    first_name: "", last_name: "", email: "", phone: "", city: "",
    job_email: "", job_password: "",
  });
  const [prefs, setPrefs] = useState<PersonaPrefs>({
    target_titles: [], preferred_locations: [], remote_preference: "hybrid",
  });
  const [fullPersona, setFullPersona] = useState<Record<string, unknown>>({});

  // Step 1: CV upload
  const handleCvUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await authFetch("/api/upload", { method: "POST", body: form });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error((data as { detail?: string }).detail ?? "Upload failed");
      }
      const { persona } = await res.json() as { cv_session_id: string; persona: Record<string, unknown> };
      // Pre-fill persona step from extracted data
      if (persona) {
        setFullPersona(persona);
        const c = (persona.core_info ?? {}) as Record<string, string>;
        setCore((prev) => ({
          ...prev,
          first_name: c.first_name || "",
          last_name: c.last_name || "",
          email: c.email || "",
          phone: c.phone || "",
          city: c.city || "",
        }));
        const p = (persona.preferences ?? {}) as Record<string, unknown>;
        setPrefs((prev) => ({
          ...prev,
          target_titles: (p.target_titles as string[]) || [],
          preferred_locations: (p.preferred_locations as string[]) || [],
        }));
      }
      setStep("credentials");
    } catch (err: unknown) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  // Step 2: Save credentials → proceed to persona review
  const handleCredentials = () => {
    setCore((prev) => ({ ...prev, job_email: jobEmail, job_password: jobPassword }));
    setStep("persona");
  };

  // Step 3: Save persona + mark onboarding complete
  const handleFinish = async () => {
    setLoading(true);
    setError(null);
    try {
      const updatedPersona = {
        ...fullPersona,
        core_info: {
          ...(fullPersona.core_info ?? {}),
          first_name: core.first_name,
          last_name: core.last_name,
          email: core.email,
          phone: core.phone,
          city: core.city,
          job_email: core.job_email,
          job_password: core.job_password,
        },
        preferences: {
          ...(fullPersona.preferences ?? {}),
          target_titles: prefs.target_titles,
          preferred_locations: prefs.preferred_locations,
          remote_preference: prefs.remote_preference,
        },
      };

      const personaRes = await authFetch("/api/persona", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updatedPersona),
      });
      if (!personaRes.ok) throw new Error("Failed to save profile");

      await authFetch("/api/onboarding/complete", { method: "POST" });
      router.replace("/dashboard");
    } catch (err: unknown) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  const steps: { key: Step; label: string }[] = [
    { key: "cv", label: "Upload CV" },
    { key: "credentials", label: "Credentials" },
    { key: "persona", label: "Your Profile" },
  ];
  const stepIdx = steps.findIndex((s) => s.key === step);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 bg-[#0a0a0a]">
      <div className="w-full max-w-lg">
        {/* Header */}
        <div className="text-center mb-10">
          <h1 className="text-3xl font-bold text-white mb-2" style={{ fontFamily: "Playfair Display, serif" }}>
            Welcome to Windrush
          </h1>
          <p className="text-zinc-500 text-sm">Let&apos;s set up your career profile in 3 steps</p>
        </div>

        {/* Step indicators */}
        <div className="flex items-center justify-center gap-2 mb-8">
          {steps.map((s, i) => (
            <div key={s.key} className="flex items-center gap-2">
              <div className={`flex items-center gap-1.5 text-xs px-3 py-1 rounded-full border transition-colors ${
                i < stepIdx ? "border-teal-600 bg-teal-600/20 text-teal-400" :
                i === stepIdx ? "border-teal-500 bg-teal-500/10 text-teal-300 font-semibold" :
                "border-zinc-800 text-zinc-600"
              }`}>
                <span>{i < stepIdx ? "✓" : i + 1}</span>
                <span>{s.label}</span>
              </div>
              {i < steps.length - 1 && <div className="w-4 h-px bg-zinc-800" />}
            </div>
          ))}
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 text-red-400 text-sm rounded-lg">
            {error}
          </div>
        )}

        {/* Step panels */}
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-2xl p-8">

          {/* Step 1 — CV Upload */}
          {step === "cv" && (
            <div className="space-y-6 text-center">
              <div className="text-5xl">📄</div>
              <div>
                <h2 className="text-lg font-bold text-zinc-100 mb-2">Upload your CV</h2>
                <p className="text-sm text-zinc-500">We&apos;ll extract your experience, skills, and contact info automatically.</p>
              </div>
              <label className={`block border-2 border-dashed rounded-xl p-10 cursor-pointer transition-colors ${
                loading ? "border-teal-600 opacity-60" : "border-zinc-700 hover:border-teal-600"
              }`}>
                <input ref={fileRef} type="file" accept=".pdf" className="hidden" onChange={handleCvUpload} disabled={loading} />
                <p className="text-sm text-zinc-400">{loading ? "Extracting your profile…" : "Click to select a PDF"}</p>
                <p className="text-xs text-zinc-600 mt-1">PDF only</p>
              </label>
              <p className="text-xs text-zinc-600">
                Don&apos;t have a CV?{" "}
                <button className="text-teal-500 hover:underline" onClick={() => setStep("credentials")}>
                  Skip and fill in manually →
                </button>
              </p>
            </div>
          )}

          {/* Step 2 — Credentials */}
          {step === "credentials" && (
            <div className="space-y-6">
              <div>
                <h2 className="text-lg font-bold text-zinc-100 mb-1">Job-board credentials</h2>
                <p className="text-sm text-zinc-500">
                  Store your login details once. Windrush uses them to auto-fill forms when applying — never shared externally.
                </p>
              </div>
              <div className="space-y-4">
                <div className="space-y-2">
                  <label className="text-xs text-zinc-400 uppercase tracking-widest">Email used to log in to job boards</label>
                  <input
                    type="email"
                    value={jobEmail}
                    onChange={(e) => setJobEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-4 py-2.5 text-sm text-zinc-100 focus:outline-none focus:border-teal-500 transition-colors"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-400 uppercase tracking-widest">Master password</label>
                  <div className="relative">
                    <input
                      type={showPassword ? "text" : "password"}
                      value={jobPassword}
                      onChange={(e) => setJobPassword(e.target.value)}
                      placeholder="••••••••"
                      className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-4 py-2.5 text-sm text-zinc-100 focus:outline-none focus:border-teal-500 transition-colors pr-12"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-zinc-600 hover:text-zinc-300"
                    >
                      {showPassword ? "Hide" : "Show"}
                    </button>
                  </div>
                </div>
              </div>
              <div className="flex gap-3">
                <button onClick={() => setStep("cv")} className="flex-1 py-2.5 text-sm text-zinc-500 border border-zinc-800 rounded-lg hover:border-zinc-600 transition-colors">
                  Back
                </button>
                <button onClick={handleCredentials} className="flex-1 py-2.5 text-sm font-bold bg-white text-black rounded-lg hover:bg-zinc-200 transition-colors">
                  Continue →
                </button>
              </div>
              <p className="text-xs text-zinc-600 text-center">
                You can skip this and add credentials later in Profile settings.{" "}
                <button className="text-teal-500 hover:underline" onClick={handleCredentials}>Skip →</button>
              </p>
            </div>
          )}

          {/* Step 3 — Persona basics */}
          {step === "persona" && (
            <div className="space-y-6">
              <div>
                <h2 className="text-lg font-bold text-zinc-100 mb-1">Confirm your details</h2>
                <p className="text-sm text-zinc-500">Check the info we extracted — you can edit everything later in Profile.</p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {(["first_name", "last_name", "email", "phone", "city"] as (keyof PersonaCore)[]).map((field) => (
                  <div key={field} className={`space-y-1 ${field === "email" || field === "city" ? "col-span-2" : ""}`}>
                    <label className="text-[10px] text-zinc-500 uppercase tracking-widest">
                      {field.replace("_", " ")}
                    </label>
                    <input
                      value={core[field] as string}
                      onChange={(e) => setCore((p) => ({ ...p, [field]: e.target.value }))}
                      className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-teal-500 transition-colors"
                    />
                  </div>
                ))}
              </div>

              <div className="space-y-2">
                <label className="text-[10px] text-zinc-500 uppercase tracking-widest">Target job titles (comma separated)</label>
                <input
                  value={prefs.target_titles.join(", ")}
                  onChange={(e) => setPrefs((p) => ({ ...p, target_titles: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) }))}
                  placeholder="Software Engineer, ML Engineer"
                  className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-teal-500 transition-colors"
                />
              </div>

              <div className="space-y-2">
                <label className="text-[10px] text-zinc-500 uppercase tracking-widest">Preferred locations (comma separated)</label>
                <input
                  value={prefs.preferred_locations.join(", ")}
                  onChange={(e) => setPrefs((p) => ({ ...p, preferred_locations: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) }))}
                  placeholder="London, Remote"
                  className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-teal-500 transition-colors"
                />
              </div>

              <div className="space-y-2">
                <label className="text-[10px] text-zinc-500 uppercase tracking-widest">Work setting preference</label>
                <select
                  value={prefs.remote_preference}
                  onChange={(e) => setPrefs((p) => ({ ...p, remote_preference: e.target.value }))}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-teal-500"
                >
                  <option value="remote">Remote only</option>
                  <option value="hybrid">Hybrid</option>
                  <option value="onsite">On-site</option>
                </select>
              </div>

              <div className="flex gap-3">
                <button onClick={() => setStep("credentials")} className="flex-1 py-2.5 text-sm text-zinc-500 border border-zinc-800 rounded-lg hover:border-zinc-600 transition-colors">
                  Back
                </button>
                <button
                  onClick={handleFinish}
                  disabled={loading}
                  className="flex-1 py-2.5 text-sm font-bold bg-white text-black rounded-lg hover:bg-zinc-200 transition-colors disabled:opacity-50"
                >
                  {loading ? "Saving…" : "Go to Dashboard →"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}