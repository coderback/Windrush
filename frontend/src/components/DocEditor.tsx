"use client";

import { useEffect, useRef, useState } from "react";
import { authFetch } from "@/app/api";

/* ── Document shapes (mirror the backend CVDoc / LetterDoc) ─────────────── */

export interface CVContact {
  email?: string; phone?: string; location?: string;
  linkedin?: string; github?: string; website?: string;
}
export interface CVSkill { category: string; items: string[]; }
export interface CVExperience {
  title: string; employer: string; location?: string;
  start_date?: string; end_date?: string; bullets: string[];
}
export interface CVEducation { degree: string; institution: string; year?: string; grade?: string; }
export interface CVProject { name: string; description?: string; tech?: string[]; link?: string; }
export interface CVCertification { name: string; issuer?: string; year?: string; }
export interface CVDoc {
  name: string;
  headline?: string;
  contact: CVContact;
  summary?: string;
  skills: CVSkill[];
  experience: CVExperience[];
  education: CVEducation[];
  projects: CVProject[];
  certifications: CVCertification[];
}
export interface LetterDoc {
  candidate_name: string;
  company?: string;
  job_title?: string;
  date?: string;
  contact?: { email?: string; phone?: string; location?: string };
  salutation: string;
  paragraphs: string[];
  signoff: string;
  archetype?: string;
}

/* Flatten a LetterDoc to plain text (used when the browser agent pastes it). */
export function letterToText(l: LetterDoc): string {
  return [l.salutation, ...(l.paragraphs || []), l.signoff, l.candidate_name]
    .filter(Boolean)
    .join("\n\n");
}

/* ── Shared styling ─────────────────────────────────────────────────────── */

const inputCls =
  "w-full bg-zinc-950 border border-zinc-800 rounded-md px-2.5 py-1.5 text-xs text-zinc-200 " +
  "focus:outline-none focus:border-teal-500 transition-colors";
const labelCls = "block text-[10px] text-zinc-500 uppercase tracking-widest mb-1";
const sectionCls = "border-t border-zinc-800 pt-3 mt-3";
const sectionTitleCls = "text-xs font-semibold text-zinc-300 uppercase tracking-widest mb-2";
const miniBtn =
  "text-[11px] px-2 py-0.5 rounded border border-zinc-700 text-zinc-400 hover:border-teal-600 hover:text-teal-400 transition-colors";
const removeBtn = "text-[11px] text-zinc-600 hover:text-red-400 transition-colors";

function Field({ label, value, onChange, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  return (
    <div>
      <label className={labelCls}>{label}</label>
      <input className={inputCls} value={value} placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

/* ── Live preview pane (same HTML the PDF is built from) ────────────────── */

function PreviewPane({ kind, doc, templateId }: {
  kind: "cv" | "cover_letter"; doc: CVDoc | LetterDoc; templateId: string;
}) {
  const [html, setHtml] = useState("");
  const [scale, setScale] = useState(0.5);
  const [contentH, setContentH] = useState(1123);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Debounced preview render
  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        const res = await authFetch("/api/documents/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: kind, doc, template_id: templateId }),
        });
        if (res.ok) setHtml(((await res.json()) as { html: string }).html);
      } catch {}
    }, 400);
    return () => clearTimeout(t);
  }, [kind, doc, templateId]);

  // Fit the A4 sheet (794px wide) to the available column width
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setScale(Math.min(1, el.clientWidth / 794)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={wrapRef} className="bg-zinc-800/40 rounded-lg p-3 overflow-auto" style={{ maxHeight: "70vh" }}>
      <div style={{ height: contentH * scale }}>
        <iframe
          title="preview"
          srcDoc={html}
          onLoad={(e) => {
            try {
              const d = e.currentTarget.contentDocument;
              if (d?.body) setContentH(d.body.scrollHeight + 24);
            } catch {}
          }}
          style={{
            width: 794, height: contentH, border: 0, background: "#fff",
            borderRadius: 4, transform: `scale(${scale})`, transformOrigin: "top left",
            boxShadow: "0 1px 8px rgba(0,0,0,0.4)",
          }}
        />
      </div>
    </div>
  );
}

/* ── CV form ─────────────────────────────────────────────────────────────── */

function CvForm({ cv, onChange }: { cv: CVDoc; onChange: (c: CVDoc) => void }) {
  const set = (patch: Partial<CVDoc>) => onChange({ ...cv, ...patch });
  const setContact = (patch: Partial<CVContact>) => set({ contact: { ...cv.contact, ...patch } });

  const setExp = (i: number, patch: Partial<CVExperience>) => {
    const experience = cv.experience.map((e, idx) => (idx === i ? { ...e, ...patch } : e));
    set({ experience });
  };

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <Field label="Name" value={cv.name} onChange={(v) => set({ name: v })} />
        <Field label="Headline" value={cv.headline ?? ""} onChange={(v) => set({ headline: v })} />
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Field label="Email" value={cv.contact.email ?? ""} onChange={(v) => setContact({ email: v })} />
        <Field label="Phone" value={cv.contact.phone ?? ""} onChange={(v) => setContact({ phone: v })} />
        <Field label="Location" value={cv.contact.location ?? ""} onChange={(v) => setContact({ location: v })} />
        <Field label="LinkedIn" value={cv.contact.linkedin ?? ""} onChange={(v) => setContact({ linkedin: v })} />
        <Field label="GitHub" value={cv.contact.github ?? ""} onChange={(v) => setContact({ github: v })} />
        <Field label="Website" value={cv.contact.website ?? ""} onChange={(v) => setContact({ website: v })} />
      </div>

      <div>
        <label className={labelCls}>Summary</label>
        <textarea className={`${inputCls} resize-y`} rows={3} value={cv.summary ?? ""}
          onChange={(e) => set({ summary: e.target.value })} />
      </div>

      {/* Skills */}
      <div className={sectionCls}>
        <div className="flex items-center justify-between mb-2">
          <span className={sectionTitleCls}>Skills</span>
          <button className={miniBtn}
            onClick={() => set({ skills: [...cv.skills, { category: "", items: [] }] })}>+ group</button>
        </div>
        <div className="space-y-2">
          {cv.skills.map((g, i) => (
            <div key={i} className="grid grid-cols-[1fr_2fr_auto] gap-2 items-end">
              <div>
                <label className={labelCls}>Category</label>
                <input className={inputCls} value={g.category}
                  onChange={(e) => set({ skills: cv.skills.map((x, idx) => idx === i ? { ...x, category: e.target.value } : x) })} />
              </div>
              <div>
                <label className={labelCls}>Items (comma-separated)</label>
                <input className={inputCls} value={g.items.join(", ")}
                  onChange={(e) => set({ skills: cv.skills.map((x, idx) => idx === i ? { ...x, items: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) } : x) })} />
              </div>
              <button className={removeBtn} onClick={() => set({ skills: cv.skills.filter((_, idx) => idx !== i) })}>remove</button>
            </div>
          ))}
        </div>
      </div>

      {/* Experience */}
      <div className={sectionCls}>
        <div className="flex items-center justify-between mb-2">
          <span className={sectionTitleCls}>Experience</span>
          <button className={miniBtn}
            onClick={() => set({ experience: [...cv.experience, { title: "", employer: "", bullets: [] }] })}>+ role</button>
        </div>
        <div className="space-y-3">
          {cv.experience.map((exp, i) => (
            <div key={i} className="bg-zinc-950/50 border border-zinc-800 rounded-lg p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-zinc-600 uppercase tracking-widest">Role {i + 1}</span>
                <button className={removeBtn} onClick={() => set({ experience: cv.experience.filter((_, idx) => idx !== i) })}>remove role</button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Title" value={exp.title} onChange={(v) => setExp(i, { title: v })} />
                <Field label="Employer" value={exp.employer} onChange={(v) => setExp(i, { employer: v })} />
                <Field label="Start" value={exp.start_date ?? ""} onChange={(v) => setExp(i, { start_date: v })} />
                <Field label="End" value={exp.end_date ?? ""} onChange={(v) => setExp(i, { end_date: v })} />
              </div>
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className={labelCls}>Bullets</label>
                  <button className={miniBtn} onClick={() => setExp(i, { bullets: [...exp.bullets, ""] })}>+ bullet</button>
                </div>
                <div className="space-y-1.5">
                  {exp.bullets.map((b, bi) => (
                    <div key={bi} className="flex gap-1.5 items-center">
                      <input className={inputCls} value={b}
                        onChange={(e) => setExp(i, { bullets: exp.bullets.map((x, idx) => idx === bi ? e.target.value : x) })} />
                      <button className={removeBtn} onClick={() => setExp(i, { bullets: exp.bullets.filter((_, idx) => idx !== bi) })}>×</button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Projects */}
      <div className={sectionCls}>
        <div className="flex items-center justify-between mb-2">
          <span className={sectionTitleCls}>Projects</span>
          <button className={miniBtn}
            onClick={() => set({ projects: [...cv.projects, { name: "" }] })}>+ project</button>
        </div>
        <div className="space-y-2">
          {cv.projects.map((p, i) => (
            <div key={i} className="bg-zinc-950/50 border border-zinc-800 rounded-lg p-3 space-y-2">
              <div className="flex items-center justify-between">
                <Field label="Name" value={p.name} onChange={(v) => set({ projects: cv.projects.map((x, idx) => idx === i ? { ...x, name: v } : x) })} />
                <button className={`${removeBtn} ml-2 mt-4`} onClick={() => set({ projects: cv.projects.filter((_, idx) => idx !== i) })}>remove</button>
              </div>
              <div>
                <label className={labelCls}>Description</label>
                <textarea className={`${inputCls} resize-y`} rows={2} value={p.description ?? ""}
                  onChange={(e) => set({ projects: cv.projects.map((x, idx) => idx === i ? { ...x, description: e.target.value } : x) })} />
              </div>
              <Field label="Tech (comma-separated)" value={(p.tech ?? []).join(", ")}
                onChange={(v) => set({ projects: cv.projects.map((x, idx) => idx === i ? { ...x, tech: v.split(",").map((s) => s.trim()).filter(Boolean) } : x) })} />
            </div>
          ))}
        </div>
      </div>

      {/* Education */}
      <div className={sectionCls}>
        <div className="flex items-center justify-between mb-2">
          <span className={sectionTitleCls}>Education</span>
          <button className={miniBtn}
            onClick={() => set({ education: [...cv.education, { degree: "", institution: "" }] })}>+ entry</button>
        </div>
        <div className="space-y-2">
          {cv.education.map((ed, i) => (
            <div key={i} className="grid grid-cols-[2fr_2fr_1fr_auto] gap-2 items-end">
              <Field label="Degree" value={ed.degree} onChange={(v) => set({ education: cv.education.map((x, idx) => idx === i ? { ...x, degree: v } : x) })} />
              <Field label="Institution" value={ed.institution} onChange={(v) => set({ education: cv.education.map((x, idx) => idx === i ? { ...x, institution: v } : x) })} />
              <Field label="Year" value={ed.year ?? ""} onChange={(v) => set({ education: cv.education.map((x, idx) => idx === i ? { ...x, year: v } : x) })} />
              <button className={removeBtn} onClick={() => set({ education: cv.education.filter((_, idx) => idx !== i) })}>remove</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── Cover letter form ──────────────────────────────────────────────────── */

function LetterForm({ letter, onChange }: { letter: LetterDoc; onChange: (l: LetterDoc) => void }) {
  const set = (patch: Partial<LetterDoc>) => onChange({ ...letter, ...patch });
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <Field label="Salutation" value={letter.salutation} onChange={(v) => set({ salutation: v })} />
        <Field label="Sign-off" value={letter.signoff} onChange={(v) => set({ signoff: v })} />
      </div>
      <div className={sectionCls}>
        <div className="flex items-center justify-between mb-2">
          <span className={sectionTitleCls}>Paragraphs</span>
          <button className={miniBtn} onClick={() => set({ paragraphs: [...letter.paragraphs, ""] })}>+ paragraph</button>
        </div>
        <div className="space-y-2">
          {letter.paragraphs.map((p, i) => (
            <div key={i} className="flex gap-1.5 items-start">
              <textarea className={`${inputCls} resize-y`} rows={3} value={p}
                onChange={(e) => set({ paragraphs: letter.paragraphs.map((x, idx) => idx === i ? e.target.value : x) })} />
              <button className={`${removeBtn} mt-1`} onClick={() => set({ paragraphs: letter.paragraphs.filter((_, idx) => idx !== i) })}>×</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── Public split-pane editor ───────────────────────────────────────────── */

interface DocEditorProps {
  kind: "cv" | "cover_letter";
  templateId?: string;
  cv?: CVDoc;
  letter?: LetterDoc;
  onCvChange?: (c: CVDoc) => void;
  onLetterChange?: (l: LetterDoc) => void;
}

export default function DocEditor({
  kind, templateId = "classic", cv, letter, onCvChange, onLetterChange,
}: DocEditorProps) {
  const doc = (kind === "cv" ? cv : letter) as CVDoc | LetterDoc;
  if (!doc) return null;
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div className="overflow-y-auto pr-1" style={{ maxHeight: "70vh" }}>
        {kind === "cv" && cv
          ? <CvForm cv={cv} onChange={(c) => onCvChange?.(c)} />
          : letter ? <LetterForm letter={letter} onChange={(l) => onLetterChange?.(l)} /> : null}
      </div>
      <PreviewPane kind={kind} doc={doc} templateId={templateId} />
    </div>
  );
}
