"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { authFetch } from "../api";
import Icon from "@/components/ui/Icon";
import TopBar, { Page } from "@/components/ui/TopBar";
import { buttonClass, Callout, Card, cx, Skeleton, Spinner } from "@/components/ui/kit";
import {
  AreaField, ChipInput, dateRange, EntryCard, monthLabel, SelectField, TextField, YesNoField,
} from "@/components/persona/fields";
import AnswerBank from "@/components/persona/AnswerBank";
import Suggestions from "@/components/persona/Suggestions";
import { load, mutate, requestJson, useResource } from "@/lib/store";
import { SUGGESTIONS_URL } from "@/lib/suggestions";
import { MIN_STORIES, personaChecks, personaStrength, type SectionKey } from "@/lib/persona";
import type {
  BehavioralStory, Certification, Education, Persona, ProfileSuggestions, Project, SkillCategory, WorkExperience,
} from "@/lib/types";

type SaveState = "saved" | "pending" | "saving" | "error";

const SAVE_DELAY = 800;

const EMPTY_ROLE: WorkExperience = { employer: "", title: "", start_date: "", end_date: "", is_current: false, tech_stack: [], achievements: [], metrics: "", summary: "" };
const EMPTY_EDU: Education = { institution: "", degree: "", start_date: "", end_date: "", grade: "", is_currently_enrolled: false };
const EMPTY_PROJECT: Project = { name: "", url: "", problem_solved: "", technologies: [], outcomes: "", summary: "", is_ongoing: false };
const EMPTY_CERT: Certification = { name: "", issuing_organization: "", issue_date: "", expiration_date: "", credential_id: "", credential_url: "" };
const EMPTY_STORY: BehavioralStory = { title: "", scenario: "", action: "", result: "", tags: [] };

const grid2 = "grid gap-[14px] grid-cols-1 sm:grid-cols-2";

function SectionCard({ title, intro, action, children }: { title: string; intro?: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card className="p-5 flex flex-col gap-4">
      <div className="flex flex-wrap justify-between items-start gap-[10px]">
        <div className="flex flex-col gap-[3px] min-w-0">
          <h2 className="m-0 text-[16px] font-semibold">{title}</h2>
          {intro && <span className="text-[13px] text-ink-3 max-w-[70ch]">{intro}</span>}
        </div>
        {action}
      </div>
      {children}
    </Card>
  );
}

function AddButton({ onClick, children, dashed }: { onClick: () => void; children: React.ReactNode; dashed?: boolean }) {
  return (
    <button type="button" onClick={onClick}
      className={dashed
        ? "self-start h-[38px] px-[14px] border border-dashed border-stone rounded-control bg-subtle text-[13.5px] font-medium text-ink hover:border-ink-3 inline-flex items-center gap-2"
        : buttonClass("secondary", "sm")}>
      <Icon name="plus" size={14} strokeWidth={2} />{children}
    </button>
  );
}

function ExportMenu() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const download = async (format: "json" | "pdf" | "md") => {
    setOpen(false);
    setBusy(true);
    setError(null);
    try {
      const res = await authFetch(`/api/persona/export?format=${format}`);
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `windrush_persona.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Couldn't export your persona.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div ref={wrap} className="relative">
      <button type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)} disabled={busy}
        className={buttonClass("secondary", "top")}>
        {busy ? <Spinner /> : null}Export<Icon name="chevronDown" size={13} strokeWidth={2} />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 mt-2 w-52 bg-surface border border-border rounded-inner shadow-slideover z-30 overflow-hidden py-1">
          {([["json", "JSON (data backup)"], ["pdf", "PDF (as a CV)"], ["md", "Markdown"]] as const).map(([fmt, label]) => (
            <button key={fmt} type="button" role="menuitem" onClick={() => download(fmt)}
              className="w-full text-left px-4 py-[9px] text-[13.5px] text-ink hover:bg-muted">{label}</button>
          ))}
        </div>
      )}
      {error && <p role="alert" className="absolute right-0 mt-1 text-[12px] text-red whitespace-nowrap">{error}</p>}
    </div>
  );
}

export default function ProfilePage() {
  const [persona, setPersona] = useState<Persona | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [section, setSection] = useState<SectionKey>("identity");
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [editing, setEditing] = useState<string | null>(null);
  const [removed, setRemoved] = useState<{ label: string; restore: () => void } | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const suggestions = useResource<ProfileSuggestions>(SUGGESTIONS_URL);
  const latest = useRef<Persona | null>(null);
  const dirty = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const queue = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    load<Persona>("/api/persona", { force: true })
      .then((p) => { latest.current = p; setPersona(p); })
      .catch((e) => setLoadError(e instanceof Error ? e.message : "Couldn't load your persona."));
  }, []);

  // The open section lives in the URL hash, so links like /profile#skills land on it.
  useEffect(() => {
    const read = () => {
      const h = window.location.hash.replace("#", "") as SectionKey;
      if (h) setSection(h);
    };
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);

  const save = useCallback(() => {
    queue.current = queue.current.then(async () => {
      if (!dirty.current || !latest.current) return;
      const body = latest.current;
      dirty.current = false;
      setSaveState("saving");
      try {
        await requestJson("/api/persona", {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        mutate<Persona>("/api/persona", body);
        setSaveState(dirty.current ? "pending" : "saved");
      } catch {
        dirty.current = true;
        setSaveState("error");
      }
    });
    return queue.current;
  }, []);

  // Unsaved edits go out when you leave (keepalive lets the request outlive the page).
  useEffect(() => {
    const flush = () => {
      if (!dirty.current || !latest.current) return;
      dirty.current = false;
      authFetch("/api/persona", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(latest.current), keepalive: true,
      }).catch(() => {});
    };
    window.addEventListener("pagehide", flush);
    return () => {
      window.removeEventListener("pagehide", flush);
      clearTimeout(timer.current);
      flush();
    };
  }, []);

  /** Save any edit still waiting, so a change made on the server (an accepted suggestion) isn't overwritten. */
  const flush = useCallback(async () => {
    clearTimeout(timer.current);
    await save();
  }, [save]);

  /** Take the persona as the server saved it. */
  const replace = useCallback((p: Persona) => {
    latest.current = p;
    setPersona(p);
  }, []);

  const update = (fn: (p: Persona) => Persona) => {
    if (!latest.current) return;
    const next = fn(latest.current);
    latest.current = next;
    setPersona(next);
    dirty.current = true;
    setSaveState("pending");
    clearTimeout(timer.current);
    timer.current = setTimeout(save, SAVE_DELAY);
  };

  const set = <K extends "core_info" | "preferences" | "diversity" | "screening">(key: K, field: keyof Persona[K], value: unknown) =>
    update((p) => ({ ...p, [key]: { ...(p[key] ?? {}), [field]: value } }));
  const setTop = <K extends keyof Persona>(key: K, value: Persona[K]) => update((p) => ({ ...p, [key]: value }));

  const go = (k: SectionKey) => {
    setSection(k);
    setEditing(null);
    history.replaceState(null, "", `#${k}`);
  };

  /** Edit, add and remove entries of a repeating section (with undo for a removal). */
  function listOps<K extends "history" | "education" | "projects" | "certifications" | "story_bank">(key: K, noun: string) {
    const list = (persona?.[key] ?? []) as Persona[K];
    type Item = Persona[K][number];
    return {
      list,
      edit: (i: number, patch: Partial<Item>) =>
        setTop(key, (list as Item[]).map((x, j) => (j === i ? { ...x, ...patch } : x)) as Persona[K]),
      add: (empty: Item) => {
        setTop(key, [...(list as Item[]), empty] as Persona[K]);
        setEditing(`${key}-${list.length}`);
      },
      remove: (i: number) => {
        const item = (list as Item[])[i];
        setTop(key, (list as Item[]).filter((_, j) => j !== i) as Persona[K]);
        setEditing(null);
        setRemoved({
          label: `Removed ${noun}.`,
          restore: () => update((p) => {
            const cur = [...((p[key] ?? []) as Item[])];
            cur.splice(i, 0, item);
            return { ...p, [key]: cur };
          }),
        });
      },
      toggle: (i: number) => setEditing((e) => (e === `${key}-${i}` ? null : `${key}-${i}`)),
      isEditing: (i: number) => editing === `${key}-${i}`,
    };
  }

  useEffect(() => {
    if (!removed) return;
    const t = setTimeout(() => setRemoved(null), 8000);
    return () => clearTimeout(t);
  }, [removed]);

  if (loadError) {
    return (
      <>
        <TopBar crumbs={[{ label: "Grow" }, { label: "Persona" }]} />
        <Page><Callout title="Couldn't load your persona">{loadError}</Callout></Page>
      </>
    );
  }

  if (!persona) {
    return (
      <>
        <TopBar crumbs={[{ label: "Grow" }, { label: "Persona" }]} />
        <Page className="gap-4">
          <Skeleton className="h-24 rounded-card" />
          <div className="flex gap-4"><Skeleton className="h-[480px] w-[220px] rounded-card" /><Skeleton className="h-[480px] flex-1 rounded-card" /></div>
        </Page>
      </>
    );
  }

  const checks = personaChecks(persona);
  const strength = personaStrength(persona);
  const c = persona.core_info;
  const prefs = persona.preferences;
  const scr = persona.screening ?? {};
  const div = persona.diversity ?? {};

  const roles = listOps("history", "a role");
  const edu = listOps("education", "an education entry");
  const projects = listOps("projects", "a project");
  const certs = listOps("certifications", "a certification");
  const stories = listOps("story_bank", "a story");

  const setSkills = (skills: SkillCategory[]) => setTop("skills", skills);

  const status = {
    saved: <><Icon name="check" size={14} strokeWidth={2.4} className="text-teal" />All changes saved</>,
    pending: <>Unsaved changes</>,
    saving: <><Spinner className="w-3 h-3" />Saving…</>,
    error: <span className="text-red flex items-center gap-2">Couldn&apos;t save.
      <button type="button" onClick={() => { dirty.current = true; save(); }} className="underline underline-offset-2">Try again</button></span>,
  }[saveState];

  const body = (() => {
    switch (section) {
      case "identity":
        return (
          <SectionCard title="Identity & contact" intro="Used to fill application forms. Contact details go only to the agent that fills them in, never into writing your CVs or letters.">
            <div className={grid2}>
              <TextField label="First name" value={c.first_name} onChange={(v) => set("core_info", "first_name", v)} autoComplete="given-name" />
              <TextField label="Preferred name" value={c.preferred_name} onChange={(v) => set("core_info", "preferred_name", v)} />
              <TextField label="Last name" value={c.last_name} onChange={(v) => set("core_info", "last_name", v)} autoComplete="family-name" />
              <TextField label="Date of birth" type="date" value={c.dob} onChange={(v) => set("core_info", "dob", v)} />
              <TextField label="Email" type="email" value={c.email} onChange={(v) => set("core_info", "email", v)} autoComplete="email" />
              <TextField label="Phone" type="tel" value={c.phone} onChange={(v) => set("core_info", "phone", v)} autoComplete="tel" />
              <TextField label="Address" value={c.address_line_1} onChange={(v) => set("core_info", "address_line_1", v)} autoComplete="address-line1" />
              <TextField label="City" value={c.city} onChange={(v) => set("core_info", "city", v)} autoComplete="address-level2" />
              <TextField label="Postcode" value={c.postcode} onChange={(v) => set("core_info", "postcode", v)} autoComplete="postal-code" />
              <TextField label="Country" value={c.country} onChange={(v) => set("core_info", "country", v)} autoComplete="country-name" />
            </div>
            <AreaField label="Professional summary" rows={4} value={persona.summary} onChange={(v) => setTop("summary", v)}
              hint="The starting point for every tailored CV." />
            <h3 className="m-0 mt-2 text-[14px] font-semibold">Right to work</h3>
            <div className="flex flex-col gap-2">
              <YesNoField label="Right to work in the UK" value={c.right_to_work_uk} onChange={(v) => set("core_info", "right_to_work_uk", v)} />
              <YesNoField label="Need visa sponsorship" value={c.require_sponsorship} onChange={(v) => set("core_info", "require_sponsorship", v)} />
              <YesNoField label="Ties to a foreign government" value={c.has_government_ties} onChange={(v) => set("core_info", "has_government_ties", v)} />
              <YesNoField label="Hold another nationality now" value={c.holds_other_nationality} onChange={(v) => set("core_info", "holds_other_nationality", v)} />
              <YesNoField label="Held another nationality before" value={c.held_other_nationality} onChange={(v) => set("core_info", "held_other_nationality", v)} />
            </div>
            <div className={grid2}>
              <TextField label="Visa type" value={c.visa_type} placeholder="e.g. Graduate visa, Skilled Worker" onChange={(v) => set("core_info", "visa_type", v)} />
              <TextField label="Nationality" value={c.nationality} onChange={(v) => set("core_info", "nationality", v)} />
              {c.holds_other_nationality === true && (
                <TextField label="Other nationalities" value={c.other_nationalities} onChange={(v) => set("core_info", "other_nationalities", v)} />
              )}
              {c.held_other_nationality === true && (
                <TextField label="Previous nationalities" value={c.previous_nationalities} onChange={(v) => set("core_info", "previous_nationalities", v)} />
              )}
              <TextField label="Security clearance" value={c.security_clearance} placeholder="None, SC, DV…" onChange={(v) => set("core_info", "security_clearance", v)} />
            </div>
          </SectionCard>
        );
      case "login":
        return (
          <SectionCard title="Job-board login" intro="Many application sites ask you to create an account. The agent uses this email and password for them.">
            <div className={grid2}>
              <TextField label="Email for job sites" type="email" value={c.job_email} onChange={(v) => set("core_info", "job_email", v)} placeholder="you@example.com" />
              <div className="flex flex-col gap-[6px]">
                <TextField label="Password for job sites" type={showPassword ? "text" : "password"} value={c.job_password}
                  onChange={(v) => set("core_info", "job_password", v)} autoComplete="new-password" />
                <button type="button" onClick={() => setShowPassword((s) => !s)} aria-pressed={showPassword}
                  className="self-start text-[12.5px] text-teal hover:underline underline-offset-2">{showPassword ? "Hide password" : "Show password"}</button>
              </div>
            </div>
            <Callout tone="info">Encrypted at rest. The AI only sees a placeholder; the real password is typed only into the job site&apos;s own login field.</Callout>
          </SectionCard>
        );
      case "links":
        return (
          <SectionCard title="Links" intro="Added to your CV and to the link fields on application forms.">
            <div className={grid2}>
              <TextField label="LinkedIn" type="url" value={c.linkedin} placeholder="linkedin.com/in/…" onChange={(v) => set("core_info", "linkedin", v)} />
              <TextField label="GitHub" type="url" value={c.github} placeholder="github.com/…" onChange={(v) => set("core_info", "github", v)} />
              <TextField label="Portfolio" type="url" value={c.portfolio} onChange={(v) => set("core_info", "portfolio", v)} />
              <TextField label="Website" type="url" value={c.website} onChange={(v) => set("core_info", "website", v)} />
              <TextField label="X (Twitter)" value={c.twitter} onChange={(v) => set("core_info", "twitter", v)} />
            </div>
          </SectionCard>
        );
      case "skills":
        return (
          <SectionCard title="Skills" intro="Grouped so the agent can answer technical form questions precisely."
            action={<AddButton onClick={() => setSkills([...persona.skills, { category: "", skills: [] }])}>Add group</AddButton>}>
            {persona.skills.length === 0 && <p className="m-0 text-[13.5px] text-ink-2">No skills yet. Add a group, then the skills in it.</p>}
            {persona.skills.map((g, i) => (
              <div key={i} className="flex flex-wrap gap-3 p-[14px] border border-track rounded-inner items-start">
                <div className="w-full sm:w-[170px] flex flex-col gap-2">
                  <label htmlFor={`group-${i}`} className="sr-only">Group name</label>
                  <input id={`group-${i}`} value={g.category} placeholder="Group, e.g. Backend"
                    onChange={(e) => setSkills(persona.skills.map((x, j) => (j === i ? { ...x, category: e.target.value } : x)))}
                    className="h-9 px-[10px] border border-transparent hover:border-border rounded-[9px] bg-transparent text-[13.5px] font-semibold text-ink focus:outline-none focus:border-teal" />
                  <button type="button" onClick={() => {
                    const item = g;
                    setSkills(persona.skills.filter((_, j) => j !== i));
                    setRemoved({ label: `Removed the ${g.category || "skill"} group.`,
                      restore: () => update((p) => { const s = [...p.skills]; s.splice(i, 0, item); return { ...p, skills: s }; }) });
                  }} className="self-start px-[10px] text-[12px] text-red hover:underline underline-offset-2">Remove group</button>
                </div>
                <div className="flex-[1_1_300px] min-w-0">
                  <ChipInput label={`Skills in ${g.category || "this group"}`} hideLabel value={g.skills}
                    placeholder="Type a skill, then a comma" addLabel="Add skill"
                    onChange={(items) => setSkills(persona.skills.map((x, j) => (j === i ? { ...x, skills: items } : x)))} />
                </div>
              </div>
            ))}
          </SectionCard>
        );
      case "work":
        return (
          <SectionCard title="Work history" action={<AddButton onClick={() => roles.add({ ...EMPTY_ROLE })}>Add role</AddButton>}>
            {roles.list.length === 0 && <p className="m-0 text-[13.5px] text-ink-2">No roles yet. Part-time and volunteer work count too.</p>}
            {roles.list.map((r, i) => (
              <EntryCard key={i} title={r.title} subtitle={r.employer} meta={dateRange(r.start_date, r.end_date, r.is_current)}
                editing={roles.isEditing(i)} onEdit={() => roles.toggle(i)} onRemove={() => roles.remove(i)}
                form={
                  <div className="flex flex-col gap-[14px]">
                    <div className={grid2}>
                      <TextField label="Job title" value={r.title} onChange={(v) => roles.edit(i, { title: v })} />
                      <TextField label="Employer" value={r.employer} onChange={(v) => roles.edit(i, { employer: v })} />
                      <TextField label="Start" value={r.start_date} placeholder="e.g. 2024-09 or Sep 2024" onChange={(v) => roles.edit(i, { start_date: v })} />
                      <TextField label="End" value={r.is_current ? "" : r.end_date} placeholder={r.is_current ? "Present" : "e.g. 2025-06"} onChange={(v) => roles.edit(i, { end_date: v })} />
                    </div>
                    <label className="flex items-center gap-2 text-[13.5px]">
                      <input type="checkbox" checked={r.is_current} onChange={(e) => roles.edit(i, { is_current: e.target.checked, end_date: e.target.checked ? "" : r.end_date })}
                        className="w-4 h-4" style={{ accentColor: "var(--teal)" }} />I work here now
                    </label>
                    <AreaField label="Achievements, one per line" rows={4} value={r.achievements.join("\n")}
                      onChange={(v) => roles.edit(i, { achievements: v.split("\n") })} hint="Lead with results: what changed because of you." />
                    <ChipInput label="Technologies used" value={r.tech_stack} onChange={(v) => roles.edit(i, { tech_stack: v })} placeholder="e.g. Python, FastAPI" />
                    <TextField label="Headline metric" value={r.metrics} placeholder="e.g. Cut report time by 40%" onChange={(v) => roles.edit(i, { metrics: v })} />
                    <AreaField label="Summary" rows={2} value={r.summary} onChange={(v) => roles.edit(i, { summary: v })} />
                  </div>
                }>
                {r.achievements.filter((a) => a.trim()).length > 0 && (
                  <ul className="m-0 pl-[18px] flex flex-col gap-1 text-[13.5px] leading-[1.5] list-disc">
                    {r.achievements.filter((a) => a.trim()).map((a, j) => <li key={j}>{a}</li>)}
                  </ul>
                )}
              </EntryCard>
            ))}
          </SectionCard>
        );
      case "education":
        return (
          <SectionCard title="Education" action={<AddButton onClick={() => edu.add({ ...EMPTY_EDU })}>Add education</AddButton>}>
            {edu.list.length === 0 && <p className="m-0 text-[13.5px] text-ink-2">No education yet.</p>}
            {edu.list.map((e, i) => (
              <EntryCard key={i} title={e.degree} subtitle={[e.institution, e.grade && `Grade: ${e.grade}`].filter(Boolean).join(" · ")}
                meta={dateRange(e.start_date, e.end_date, e.is_currently_enrolled)}
                editing={edu.isEditing(i)} onEdit={() => edu.toggle(i)} onRemove={() => edu.remove(i)}
                form={
                  <div className="flex flex-col gap-[14px]">
                    <div className={grid2}>
                      <TextField label="Degree" value={e.degree} onChange={(v) => edu.edit(i, { degree: v })} />
                      <TextField label="Institution" value={e.institution} onChange={(v) => edu.edit(i, { institution: v })} />
                      <TextField label="Start" value={e.start_date} placeholder="e.g. 2022-09" onChange={(v) => edu.edit(i, { start_date: v })} />
                      <TextField label="End" value={e.end_date} placeholder="e.g. 2025-06" onChange={(v) => edu.edit(i, { end_date: v })} />
                      <TextField label="Grade" value={e.grade} placeholder="e.g. 2:1 (Honours)" onChange={(v) => edu.edit(i, { grade: v })} />
                    </div>
                    <label className="flex items-center gap-2 text-[13.5px]">
                      <input type="checkbox" checked={e.is_currently_enrolled} onChange={(ev) => edu.edit(i, { is_currently_enrolled: ev.target.checked })}
                        className="w-4 h-4" style={{ accentColor: "var(--teal)" }} />Still studying here
                    </label>
                  </div>
                } />
            ))}
          </SectionCard>
        );
      case "projects":
        return (
          <SectionCard title="Projects" action={<AddButton onClick={() => projects.add({ ...EMPTY_PROJECT })}>Add project</AddButton>}>
            {projects.list.length === 0 && <p className="m-0 text-[13.5px] text-ink-2">No projects yet. Side projects and coursework count.</p>}
            {projects.list.map((p, i) => (
              <EntryCard key={i} title={p.name} subtitle={p.technologies.join(", ")} meta={p.is_ongoing ? "Ongoing" : undefined}
                editing={projects.isEditing(i)} onEdit={() => projects.toggle(i)} onRemove={() => projects.remove(i)}
                form={
                  <div className="flex flex-col gap-[14px]">
                    <div className={grid2}>
                      <TextField label="Name" value={p.name} onChange={(v) => projects.edit(i, { name: v })} />
                      <TextField label="Link" type="url" value={p.url ?? ""} onChange={(v) => projects.edit(i, { url: v })} />
                    </div>
                    <AreaField label="What problem it solves" rows={2} value={p.problem_solved} onChange={(v) => projects.edit(i, { problem_solved: v })} />
                    <AreaField label="Outcomes" rows={2} value={p.outcomes} onChange={(v) => projects.edit(i, { outcomes: v })} />
                    <AreaField label="Summary" rows={2} value={p.summary} onChange={(v) => projects.edit(i, { summary: v })} />
                    <ChipInput label="Technologies" value={p.technologies} onChange={(v) => projects.edit(i, { technologies: v })} placeholder="e.g. Next.js, SQLite" />
                    <label className="flex items-center gap-2 text-[13.5px]">
                      <input type="checkbox" checked={p.is_ongoing} onChange={(e) => projects.edit(i, { is_ongoing: e.target.checked })}
                        className="w-4 h-4" style={{ accentColor: "var(--teal)" }} />Still working on it
                    </label>
                  </div>
                }>
                {(p.summary || p.problem_solved) && <p className="m-0 text-[13.5px] leading-[1.5] text-ink-2">{p.summary || p.problem_solved}</p>}
              </EntryCard>
            ))}
          </SectionCard>
        );
      case "certs":
        return (
          <SectionCard title="Certifications" intro="Optional. Listed with your education on tailored CVs."
            action={<AddButton onClick={() => certs.add({ ...EMPTY_CERT })}>Add certification</AddButton>}>
            {certs.list.length === 0 && <p className="m-0 text-[13.5px] text-ink-2">No certifications yet.</p>}
            {certs.list.map((ct, i) => (
              <EntryCard key={i} title={ct.name} subtitle={ct.issuing_organization} meta={monthLabel(ct.issue_date)}
                editing={certs.isEditing(i)} onEdit={() => certs.toggle(i)} onRemove={() => certs.remove(i)}
                form={
                  <div className={grid2}>
                    <TextField label="Name" value={ct.name} onChange={(v) => certs.edit(i, { name: v })} />
                    <TextField label="Issued by" value={ct.issuing_organization} onChange={(v) => certs.edit(i, { issuing_organization: v })} />
                    <TextField label="Issued" value={ct.issue_date} placeholder="e.g. 2025-07" onChange={(v) => certs.edit(i, { issue_date: v })} />
                    <TextField label="Expires" value={ct.expiration_date} onChange={(v) => certs.edit(i, { expiration_date: v })} />
                    <TextField label="Credential ID" value={ct.credential_id} onChange={(v) => certs.edit(i, { credential_id: v })} />
                    <TextField label="Credential link" type="url" value={ct.credential_url} onChange={(v) => certs.edit(i, { credential_url: v })} />
                  </div>
                } />
            ))}
          </SectionCard>
        );
      case "stories":
        return (
          <SectionCard title="STAR stories"
            intro={`Situation, task, action, result. The agent adapts these for behavioural questions. ${MIN_STORIES} or more covers most forms.`}>
            {stories.list.map((s, i) => (
              <EntryCard key={i} title={s.title} editing={stories.isEditing(i)} onEdit={() => stories.toggle(i)} onRemove={() => stories.remove(i)}
                form={
                  <div className="flex flex-col gap-[14px]">
                    <TextField label="Title" value={s.title} placeholder="e.g. Rescuing a failing release" onChange={(v) => stories.edit(i, { title: v })} />
                    <AreaField label="Situation and task" rows={3} value={s.scenario} onChange={(v) => stories.edit(i, { scenario: v })} />
                    <AreaField label="What you did" rows={3} value={s.action} onChange={(v) => stories.edit(i, { action: v })} />
                    <AreaField label="The result" rows={2} value={s.result} hint="Measurable if you can." onChange={(v) => stories.edit(i, { result: v })} />
                    <ChipInput label="Tags" value={s.tags} onChange={(v) => stories.edit(i, { tags: v })} placeholder="e.g. teamwork, deadline" />
                  </div>
                }>
                <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(200px, 100%), 1fr))" }}>
                  {[["Situation & task", s.scenario], ["Action", s.action], ["Result", s.result]].map(([k, v]) => (
                    <span key={k} className="flex flex-col gap-1">
                      <span className="micro">{k}</span>
                      <span className="text-[13.5px] leading-[1.5]">{v || <span className="text-ink-3">Not written yet</span>}</span>
                    </span>
                  ))}
                </div>
              </EntryCard>
            ))}
            <AddButton dashed onClick={() => stories.add({ ...EMPTY_STORY })}>Add a story</AddButton>
          </SectionCard>
        );
      case "screening":
        return (
          <SectionCard title="Screening answers" intro="Your standard answers. The agent adapts them to each role rather than pasting them as they are.">
            <AreaField label="Why this role?" value={scr.why_this_role} onChange={(v) => set("screening", "why_this_role", v)} />
            <AreaField label="Why this company?" value={scr.why_this_company} onChange={(v) => set("screening", "why_this_company", v)} />
            <AreaField label="Greatest strength" rows={3} value={scr.greatest_strength} onChange={(v) => set("screening", "greatest_strength", v)} />
            <AreaField label="Biggest weakness" rows={3} value={scr.biggest_weakness} onChange={(v) => set("screening", "biggest_weakness", v)} />
            <AreaField label="A time you led something" rows={3} value={scr.leadership_example} onChange={(v) => set("screening", "leadership_example", v)} />
            <AreaField label="A conflict you resolved" rows={3} value={scr.conflict_resolution} onChange={(v) => set("screening", "conflict_resolution", v)} />
            <div className={grid2}>
              <TextField label="Salary expectation" value={scr.salary_canonical} placeholder="e.g. £35,000" onChange={(v) => set("screening", "salary_canonical", v)}
                hint="Given only to the agent filling in a salary question, never used for writing." />
              <TextField label="Notice period" value={scr.notice_period_canonical} placeholder="e.g. 2 weeks" onChange={(v) => set("screening", "notice_period_canonical", v)} />
            </div>
          </SectionCard>
        );
      case "answers":
        return <AnswerBank />;
      case "suggestions":
        return <Suggestions beforeChange={flush} onPersona={replace} />;
      case "prefs":
        return (
          <SectionCard title="Job preferences" intro="This shapes your feed. Discovery searches each title in each location.">
            <ChipInput label="Target job titles" value={prefs.target_titles ?? []} onChange={(v) => set("preferences", "target_titles", v)}
              placeholder="e.g. Graduate Software Engineer, Junior ML Engineer" />
            <ChipInput label="Preferred locations" value={prefs.preferred_locations ?? []} onChange={(v) => set("preferences", "preferred_locations", v)}
              placeholder="e.g. London, Manchester, New York" />
            <div className={grid2}>
              <SelectField label="Work setting" value={prefs.remote_preference} onChange={(v) => set("preferences", "remote_preference", v)}
                options={[{ value: "", label: "No preference" }, { value: "remote", label: "Remote only" }, { value: "hybrid", label: "Hybrid" }, { value: "onsite", label: "On-site" }]} />
              <SelectField label="Employment type" value={prefs.employment_type} onChange={(v) => set("preferences", "employment_type", v)}
                options={[{ value: "full-time", label: "Full-time" }, { value: "contract", label: "Contract" }, { value: "internship", label: "Internship" }]} />
              <TextField label="Minimum salary (per year, £)" type="number" value={prefs.min_salary ?? ""}
                onChange={(v) => set("preferences", "min_salary", v === "" ? null : parseInt(v, 10))} />
              <TextField label="Expected hourly rate (£)" type="number" value={prefs.expected_hourly_rate ?? ""}
                onChange={(v) => set("preferences", "expected_hourly_rate", v === "" ? null : parseFloat(v))} />
              <TextField label="Company size" value={prefs.company_size_preference} placeholder="e.g. Startup, Scale-up" onChange={(v) => set("preferences", "company_size_preference", v)} />
            </div>
            <ChipInput label="Industries" value={prefs.industries ?? []} onChange={(v) => set("preferences", "industries", v)} placeholder="e.g. Fintech, Health" />
            <ChipInput label="Companies to avoid" value={prefs.companies_to_avoid ?? []} onChange={(v) => set("preferences", "companies_to_avoid", v)} />
            <div className="flex flex-col gap-2">
              <YesNoField label="Willing to relocate" value={prefs.relocation_willingness} onChange={(v) => set("preferences", "relocation_willingness", v)} />
              <YesNoField label="Can work in person" value={prefs.can_work_in_person} onChange={(v) => set("preferences", "can_work_in_person", v)} />
              <YesNoField label="Can start immediately" value={prefs.can_start_immediately} onChange={(v) => set("preferences", "can_start_immediately", v)} />
              <YesNoField label="Reliable transport" value={prefs.has_reliable_transportation} onChange={(v) => set("preferences", "has_reliable_transportation", v)} />
              <YesNoField label="Need adjustments or accommodations" value={prefs.needs_accommodations} onChange={(v) => set("preferences", "needs_accommodations", v)} />
            </div>
          </SectionCard>
        );
      case "equality":
        return (
          <SectionCard title="Equality monitoring" intro="Optional. Given only to the agent filling in the equality questions some forms ask, never used for writing.">
            <div className={grid2}>
              <TextField label="Gender" value={div.gender} onChange={(v) => set("diversity", "gender", v)} />
              <TextField label="Ethnicity" value={div.ethnicity} onChange={(v) => set("diversity", "ethnicity", v)} />
              <SelectField label="Disability" value={div.disability_status} onChange={(v) => set("diversity", "disability_status", v)}
                options={[{ value: "", label: "Not answered" }, { value: "yes", label: "Yes, I have a disability" }, { value: "no", label: "No" }, { value: "prefer_not_to_say", label: "Prefer not to say" }]} />
              <TextField label="Veteran status" value={div.veteran_status} onChange={(v) => set("diversity", "veteran_status", v)} />
              <TextField label="Sexual orientation" value={div.sexual_orientation} onChange={(v) => set("diversity", "sexual_orientation", v)} />
            </div>
          </SectionCard>
        );
      case "directives":
        return (
          <SectionCard title="Custom AI directives" intro="Optional. Instructions the AI follows when it writes your CVs, letters and answers.">
            <AreaField label="Directives" rows={10} value={persona.custom_directives} onChange={(v) => setTop("custom_directives", v)}
              placeholder="e.g. Keep a plain, confident tone. Never invent experience." />
          </SectionCard>
        );
    }
  })();

  return (
    <>
      <TopBar crumbs={[{ label: "Grow" }, { label: "Persona" }]}>
        <span role="status" className="flex items-center gap-[6px] text-[13px] text-ink-2">{status}</span>
        <ExportMenu />
      </TopBar>
      <Page className="gap-[18px] pt-[26px] sm:pt-[26px]">
        <div className="flex flex-wrap gap-4 items-stretch">
          <div className="flex-[2_1_420px] flex flex-col gap-[6px] justify-center">
            <h1 className="m-0 text-[26px] font-semibold tracking-[-0.025em]">Your persona</h1>
            <p className="m-0 text-[14px] leading-[1.55] text-ink-2 max-w-[62ch]">
              Everything the agent knows about you. It fills forms, tailors CVs and answers screening questions from here, so the
              more complete it is, the less you fix by hand.
            </p>
          </div>
          <Card className="flex-[1_1_320px] px-[18px] py-4 flex flex-col gap-[10px]">
            <span className="flex justify-between items-baseline">
              <span className="text-[14px] font-semibold">Persona strength</span>
              <span className="font-mono text-[15px] font-semibold text-teal">{strength.pct}%</span>
            </span>
            <span className="block h-2 rounded-full bg-track overflow-hidden" aria-hidden="true">
              <span className="block h-full rounded-full bg-teal" style={{ width: `${strength.pct}%` }} />
            </span>
            {strength.todos.length ? (
              <ul className="m-0 p-0 list-none flex flex-col gap-[6px] text-[13px]">
                {strength.todos.slice(0, 2).map((t) => (
                  <li key={t} className="flex gap-2 items-center"><span aria-hidden="true" className="w-[7px] h-[7px] rounded-full bg-amber shrink-0" />{t}</li>
                ))}
              </ul>
            ) : <span className="text-[13px] text-ink-2">Complete. The agent has what it needs.</span>}
          </Card>
        </div>

        <div className="flex flex-wrap gap-4 items-start">
          <nav aria-label="Persona sections" className="flex-[1_1_220px] max-w-full md:max-w-[260px] bg-surface border border-border rounded-card p-2 flex flex-col gap-[2px]">
            <button type="button" onClick={() => go("suggestions")} aria-current={section === "suggestions" ? "true" : undefined}
              className={cx("flex items-center gap-[10px] h-[38px] px-[10px] rounded-[9px] text-[13.5px] text-left mb-1",
                section === "suggestions" ? "bg-muted text-ink font-semibold" : "text-ink-2 font-medium hover:bg-subtle hover:text-ink")}>
              <Icon name="sparkle" size={15} className="text-teal" />
              <span className="flex-1 truncate">Suggestions</span>
              {!!suggestions.data?.suggestions.length && (
                <span className="min-w-5 h-5 px-[6px] rounded-full font-mono text-[11px] font-semibold flex items-center justify-center bg-teal-logo text-teal">
                  {suggestions.data.suggestions.length}<span className="sr-only"> waiting</span>
                </span>
              )}
            </button>
            {checks.map((s) => {
              const on = s.key === section;
              return (
                <button key={s.key} type="button" onClick={() => go(s.key)} aria-current={on ? "true" : undefined}
                  className={cx("flex items-center gap-[10px] h-[38px] px-[10px] rounded-[9px] text-[13.5px] text-left",
                    on ? "bg-muted text-ink font-semibold" : "text-ink-2 font-medium hover:bg-subtle hover:text-ink")}>
                  <span className="flex-1 truncate">{s.label}</span>
                  {s.state === "complete" ? (
                    <span className="text-teal" title="Complete"><Icon name="check" size={13} strokeWidth={2.6} /><span className="sr-only"> complete</span></span>
                  ) : s.state === "attention" ? (
                    <span className="text-[11.5px] font-semibold text-amber-text" title={s.todo}>!<span className="sr-only"> needs attention: {s.todo}</span></span>
                  ) : (
                    <span className="text-[11.5px] font-semibold text-ink-3">Optional</span>
                  )}
                </button>
              );
            })}
          </nav>

          <div className="flex-[999_1_520px] min-w-0 flex flex-col gap-[14px]">
            {removed && (
              <div role="status" className="flex items-center justify-between gap-3 px-4 py-[10px] rounded-inner bg-ink text-on-ink text-[13.5px]">
                {removed.label}
                <button type="button" onClick={() => { removed.restore(); setRemoved(null); }} className="font-semibold underline underline-offset-2">Undo</button>
              </div>
            )}
            {body}
            <section aria-labelledby="priv" className="flex flex-wrap gap-[14px] items-start px-[18px] py-4 rounded-card bg-surface border border-border">
              <span className="w-9 h-9 rounded-control bg-teal-soft text-teal flex items-center justify-center shrink-0">
                <Icon name="shield" size={18} />
              </span>
              <span className="flex-[1_1_300px] flex flex-col gap-1">
                <h2 id="priv" className="m-0 text-[14px] font-semibold">Where your private details go</h2>
                <span className="text-[13px] leading-[1.55] text-ink-2">
                  The AI that writes your CVs, cover letters and answers never sees your contact details, date of birth, salary or
                  equality data. The agent that fills in forms is an AI too: it&apos;s given your name, contact details and date of
                  birth to type in, and your salary or equality answers when a form asks for them. Your job-board password reaches
                  no AI: it&apos;s encrypted, and only ever typed into the job site itself.
                </span>
              </span>
            </section>
          </div>
        </div>
      </Page>
    </>
  );
}
