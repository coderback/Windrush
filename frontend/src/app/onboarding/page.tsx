"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { authFetch } from "../api";
import { Wordmark } from "@/components/AuthLayout";
import Icon from "@/components/ui/Icon";
import { buttonClass, Callout, cx, inputClass, Spinner } from "@/components/ui/kit";
import { ChipInput } from "@/components/persona/fields";
import { load, mutate } from "@/lib/store";
import type { Persona } from "@/lib/types";

const STEPS = ["Your CV", "Job-board login", "Preferences"];
const SETTINGS = [
  { value: "remote", label: "Remote only" },
  { value: "hybrid", label: "Hybrid" },
  { value: "onsite", label: "On-site" },
  { value: "", label: "No preference" },
];

const field = `${inputClass} h-11 px-[14px] text-[14.5px]`;

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [persona, setPersona] = useState<Persona | null>(null);
  const [uploading, setUploading] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [jobEmail, setJobEmail] = useState("");
  const [jobPassword, setJobPassword] = useState("");
  const [titles, setTitles] = useState<string[]>([]);
  const [locations, setLocations] = useState<string[]>([]);
  const [setting, setSetting] = useState("");
  const [sponsorship, setSponsorship] = useState<boolean | null>(null);

  const adopt = (p: Persona) => {
    setPersona(p);
    setJobEmail((v) => v || p.core_info?.job_email || "");
    setTitles(p.preferences?.target_titles ?? []);
    setLocations(p.preferences?.preferred_locations ?? []);
    setSetting(p.preferences?.remote_preference ?? "");
    setSponsorship(p.core_info?.require_sponsorship ?? null);
  };

  // Start from what's already saved, so finishing never wipes an existing persona.
  useEffect(() => {
    load<Persona>("/api/persona", { force: true }).then(adopt).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    if (file.type && file.type !== "application/pdf") {
      setError("That isn't a PDF. Export your CV as a PDF and try again.");
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
        throw new Error((data as { detail?: string }).detail ?? "We couldn't read that CV.");
      }
      const { persona: p } = await res.json() as { persona: Persona };
      if (p) adopt(p);
      setFileName(file.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const finish = async () => {
    setSaving(true);
    setError(null);
    try {
      const base = persona ?? await load<Persona>("/api/persona", { force: true });
      const updated: Persona = {
        ...base,
        core_info: {
          ...base.core_info,
          job_email: jobEmail,
          // Empty keeps whatever is saved (the API sends a placeholder for a stored password).
          job_password: jobPassword || base.core_info.job_password || "",
          require_sponsorship: sponsorship,
        },
        preferences: { ...base.preferences, target_titles: titles, preferred_locations: locations, remote_preference: setting },
      };
      const res = await authFetch("/api/persona", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updated),
      });
      if (!res.ok) throw new Error("We couldn't save your answers. Try again.");
      mutate<Persona>("/api/persona", updated);
      await authFetch("/api/onboarding/complete", { method: "POST" });
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSaving(false);
    }
  };

  const found = persona && fileName ? [
    { n: persona.history.length, label: persona.history.length === 1 ? "role" : "roles" },
    { n: persona.skills.reduce((n, g) => n + g.skills.length, 0), label: "skills" },
    { n: persona.education.length, label: persona.education.length === 1 ? "degree" : "degrees" },
    { n: persona.projects.length, label: persona.projects.length === 1 ? "project" : "projects" },
  ] : null;

  const fileInput = (
    <input id="cvfile" type="file" accept="application/pdf,.pdf" className="sr-only-input" disabled={uploading}
      onChange={(e) => { upload(e.target.files?.[0]); e.target.value = ""; }} />
  );

  return (
    <div className="min-h-screen flex flex-col bg-canvas text-ink">
      <header className="flex flex-wrap items-center justify-between gap-3 px-4 sm:px-8 py-4 bg-surface border-b border-border">
        <Wordmark size={30} />
        <ol aria-label="Setup progress" className="list-none m-0 p-0 flex flex-wrap gap-[6px]">
          {STEPS.map((label, i) => {
            const done = i < step, on = i === step;
            return (
              <li key={label} aria-current={on ? "step" : undefined}
                className={cx("flex items-center gap-2 h-[34px] pl-[6px] pr-3 rounded-full text-[13px]",
                  on ? "bg-ink text-on-ink font-semibold" : done ? "bg-teal-soft text-teal-deep font-medium" : "bg-muted text-ink-2 font-medium")}>
                <span className={cx("w-[22px] h-[22px] rounded-full flex items-center justify-center font-mono text-[11px] font-semibold",
                  on ? "bg-surface text-ink" : done ? "bg-teal text-on-ink" : "bg-surface text-ink-2")}>
                  {done ? <Icon name="check" size={12} strokeWidth={3} /> : i + 1}
                </span>
                {label}<span className="sr-only">{done ? ", done" : ""}</span>
              </li>
            );
          })}
        </ol>
        <Link href="/dashboard" className="text-[13.5px] font-medium text-ink-2 hover:text-ink underline-offset-2 hover:underline">Finish later</Link>
      </header>

      <main className="flex-1 w-full max-w-[680px] box-border mx-auto px-6 py-12 flex flex-col gap-6">
        {error && <Callout>{error}</Callout>}

        {step === 0 && (
          <>
            <div className="flex flex-col gap-2">
              <h1 className="m-0 text-[28px] font-semibold tracking-[-0.03em]">Start with your CV</h1>
              <p className="m-0 text-[15px] leading-[1.55] text-ink-2">
                We read it once to build your persona: roles, skills, education and projects. You can edit everything afterwards.
              </p>
            </div>
            {found ? (
              <div className="bg-surface border border-border rounded-card p-[18px] flex flex-col gap-[14px]" role="status">
                <span className="flex flex-wrap items-center gap-3">
                  <span className="w-10 h-10 rounded-control bg-teal-soft text-teal flex items-center justify-center shrink-0">
                    <Icon name="fileCheck" size={18} />
                  </span>
                  <span className="flex-1 min-w-0 flex flex-col gap-[2px]">
                    <span className="text-[14.5px] font-semibold truncate">{fileName}</span>
                    <span className="text-[12.5px] text-teal-deep">Read · here is what we found</span>
                  </span>
                  <label htmlFor="cvfile" className={cx(buttonClass("secondary", "sm"), "relative cursor-pointer focus-within:outline focus-within:outline-2 focus-within:outline-teal")}>
                    {uploading ? <><Spinner /> Reading…</> : "Use a different file"}
                    {fileInput}
                  </label>
                </span>
                <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(120px, 100%), 1fr))" }}>
                  {found.map((f) => (
                    <span key={f.label} className="flex flex-col gap-[2px] px-3 py-[10px] rounded-[10px] bg-subtle border border-track">
                      <span className="font-mono text-[20px] font-medium">{f.n}</span>
                      <span className="text-[12.5px] text-ink-2">{f.label}</span>
                    </span>
                  ))}
                </div>
              </div>
            ) : (
              <label htmlFor="cvfile"
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => { e.preventDefault(); setDragging(false); upload(e.dataTransfer.files?.[0]); }}
                className={cx("relative flex flex-col items-center justify-center gap-3 px-6 py-12 text-center rounded-card border-2 border-dashed cursor-pointer bg-surface",
                  "focus-within:outline focus-within:outline-2 focus-within:outline-teal focus-within:outline-offset-2",
                  dragging ? "border-teal bg-teal-soft" : "border-border-strong hover:border-teal")}>
                <span className="w-12 h-12 rounded-inner bg-teal-soft text-teal flex items-center justify-center">
                  {uploading ? <Spinner /> : <Icon name="upload" size={20} />}
                </span>
                <span className="text-[15px] font-semibold">{uploading ? "Reading your CV…" : "Drop your CV here, or choose a file"}</span>
                <span className="text-[13px] text-ink-3">PDF only. It takes about half a minute to read.</span>
                {fileInput}
              </label>
            )}
            {!found && (
              <p className="m-0 text-[13px] text-ink-3">
                No CV to hand?{" "}
                <button type="button" onClick={() => setStep(1)} className="text-teal font-medium hover:underline underline-offset-2">Skip and fill it in later</button>
              </p>
            )}
          </>
        )}

        {step === 1 && (
          <>
            <div className="flex flex-col gap-2">
              <h1 className="m-0 text-[28px] font-semibold tracking-[-0.03em]">Your job-board login</h1>
              <p className="m-0 text-[15px] leading-[1.55] text-ink-2">
                Many application sites ask you to create an account. Give the agent one email and password to use for them.
              </p>
            </div>
            <div className="bg-surface border border-border rounded-card p-5 flex flex-col gap-4">
              <div className="flex flex-col gap-[6px]">
                <label htmlFor="jbe" className="text-[13px] font-semibold">Email for job sites</label>
                <input id="jbe" type="email" placeholder="you@example.com" autoComplete="email" value={jobEmail}
                  onChange={(e) => setJobEmail(e.target.value)} className={field} />
              </div>
              <div className="flex flex-col gap-[6px]">
                <label htmlFor="jbp" className="text-[13px] font-semibold">Password for job sites</label>
                <input id="jbp" type="password" autoComplete="new-password" value={jobPassword}
                  placeholder={persona?.core_info.job_password ? "Saved. Type to replace it" : undefined}
                  onChange={(e) => setJobPassword(e.target.value)} className={field} />
              </div>
              <Callout tone="info">
                Encrypted at rest. The AI only sees a placeholder, and the real password is typed only into the job site&apos;s own login field.
              </Callout>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <div className="flex flex-col gap-2">
              <h1 className="m-0 text-[28px] font-semibold tracking-[-0.03em]">What are you looking for?</h1>
              <p className="m-0 text-[15px] leading-[1.55] text-ink-2">This shapes your feed. Discovery searches each title in each location.</p>
            </div>
            <div className="bg-surface border border-border rounded-card p-5 flex flex-col gap-[18px]">
              <ChipInput label="Job titles" value={titles} onChange={setTitles} placeholder="e.g. Software Engineer, ML Engineer" addLabel="Add a title" />
              <ChipInput label="Locations" value={locations} onChange={setLocations} placeholder="e.g. Bristol, London, Remote" addLabel="Add a location" />
              <fieldset className="border-0 p-0 m-0 flex flex-col gap-2">
                <legend className="text-[13px] font-semibold p-0 mb-2">Work setting</legend>
                <span className="flex flex-wrap gap-2">
                  {SETTINGS.map((o) => {
                    const on = setting === o.value;
                    return (
                      <button key={o.label} type="button" aria-pressed={on} onClick={() => setSetting(o.value)}
                        className={cx("h-[38px] px-[14px] rounded-control text-[13.5px] border",
                          on ? "border-teal bg-teal-soft text-teal-deep font-semibold" : "border-border bg-surface text-ink font-medium hover:border-border-strong")}>
                        {o.label}
                      </button>
                    );
                  })}
                </span>
              </fieldset>
              <fieldset className="border-0 p-0 m-0 flex flex-col gap-2">
                <legend className="text-[13px] font-semibold p-0 mb-2">Do you need visa sponsorship to work in the UK?</legend>
                <span className="flex gap-4 text-[14px]">
                  {([[true, "Yes"], [false, "No"]] as const).map(([v, label]) => (
                    <label key={label} className="flex gap-2 items-center">
                      <input type="radio" name="spon" checked={sponsorship === v} onChange={() => setSponsorship(v)}
                        className="w-4 h-4" style={{ accentColor: "var(--teal)" }} />{label}
                    </label>
                  ))}
                </span>
                <span className="text-[12.5px] text-ink-3">If yes, your feed hides roles that rule sponsorship out.</span>
              </fieldset>
            </div>
          </>
        )}

        <div className="flex justify-between items-center gap-[10px]">
          <button type="button" onClick={() => setStep((s) => Math.max(0, s - 1))}
            className={cx(buttonClass("secondary", "xl", "px-4"), step === 0 && "invisible")}>Back</button>
          {step < 2 ? (
            <button type="button" onClick={() => setStep((s) => s + 1)} disabled={uploading} className={buttonClass("primary", "xl")}>
              Continue<Icon name="arrowRight" size={15} strokeWidth={2} />
            </button>
          ) : (
            <button type="button" onClick={finish} disabled={saving} className={buttonClass("commit", "xl", "font-medium")}>
              {saving ? <><Spinner /> Setting up…</> : "Show my matches"}
            </button>
          )}
        </div>
      </main>
    </div>
  );
}
