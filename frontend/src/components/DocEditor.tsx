"use client";

import { useEffect, useId, useRef, useState } from "react";
import { authFetch } from "@/app/api";
import CommaListInput from "./CommaListInput";
import Icon from "./ui/Icon";
import { buttonClass, cx } from "./ui/kit";

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
  company_location?: string;
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
  "w-full min-w-0 h-9 px-[10px] border border-border-strong rounded-[9px] bg-surface text-[13px] text-ink " +
  "placeholder:text-ink-3 focus:outline-none focus:border-teal";
const areaCls =
  "w-full min-w-0 px-[10px] py-2 border border-border-strong rounded-[9px] bg-surface text-[13px] leading-[1.55] text-ink " +
  "placeholder:text-ink-3 focus:outline-none focus:border-teal resize-y";
const labelCls = "block text-[12px] font-semibold text-ink-2 mb-1";
const addBtn = buttonClass("secondary", "xs", "gap-[6px]");
const removeBtn = "text-[12px] text-red hover:underline underline-offset-2";

function Field({ label, value, onChange, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  const id = useId();
  return (
    <div className="min-w-0">
      <label htmlFor={id} className={labelCls}>{label}</label>
      <input id={id} className={inputCls} value={value} placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function AddButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" className={cx(addBtn, "self-start")} onClick={onClick}>
      <Icon name="plus" size={13} strokeWidth={2} />{children}
    </button>
  );
}

/** A collapsible section card: the header button names the section and summarises what's inside. */
function SectionCard({ title, meta, open, onToggle, children }: {
  title: string; meta?: string; open: boolean; onToggle: () => void; children: React.ReactNode;
}) {
  const id = useId();
  return (
    <div className="border border-border rounded-inner overflow-hidden bg-surface">
      <button type="button" aria-expanded={open} aria-controls={id} onClick={onToggle}
        className={cx("w-full flex justify-between items-center gap-[10px] px-[14px] py-3 text-left text-ink",
          open ? "bg-subtle border-b border-track" : "hover:bg-subtle")}>
        <span className="flex flex-col gap-[2px] min-w-0">
          <span className="text-[13.5px] font-semibold">{title}</span>
          {meta && <span className="text-[12px] text-ink-3 truncate">{meta}</span>}
        </span>
        <Icon name={open ? "chevronUp" : "chevronDown"} size={14} strokeWidth={2} className="text-ink-3" />
      </button>
      {open && <div id={id} className="p-[14px] flex flex-col gap-3">{children}</div>}
    </div>
  );
}

function useSections(initial: string) {
  const [open, setOpen] = useState<Set<string>>(() => new Set([initial]));
  return {
    isOpen: (k: string) => open.has(k),
    toggle: (k: string) => setOpen((s) => {
      const n = new Set(s);
      if (n.has(k)) n.delete(k); else n.add(k);
      return n;
    }),
  };
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/* ── Live preview pane (same HTML the PDF is built from) ────────────────── */

export function PreviewPane({ kind, doc, templateId }: {
  kind: "cv" | "cover_letter"; doc: CVDoc | LetterDoc; templateId: string;
}) {
  const [html, setHtml] = useState("");
  const [failed, setFailed] = useState(false);
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
        if (res.ok) {
          setHtml(((await res.json()) as { html: string }).html);
          setFailed(false);
        } else {
          setFailed(true);
        }
      } catch {
        setFailed(true);
      }
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
    <div className="w-full max-w-[520px] mx-auto">
      {failed && <p role="status" className="m-0 mb-2 text-[12.5px] text-ink-3">The preview couldn&apos;t update. Your edits are kept.</p>}
      <div ref={wrapRef} className="w-full">
        <div style={{ height: contentH * scale }} className="relative">
          {/* The paper keeps its own colours in dark mode: it is the real document. */}
          <iframe
            title={kind === "cv" ? "CV preview" : "Cover letter preview"}
            srcDoc={html}
            onLoad={(e) => {
              try {
                const d = e.currentTarget.contentDocument;
                if (d?.body) setContentH(d.body.scrollHeight + 24);
              } catch {}
            }}
            className="absolute top-0 left-0 border-0 bg-white rounded-[4px] shadow-paper"
            style={{ width: 794, height: contentH, transform: `scale(${scale})`, transformOrigin: "top left" }}
          />
        </div>
      </div>
    </div>
  );
}

/* ── CV form ─────────────────────────────────────────────────────────────── */

function CvForm({ cv, onChange }: { cv: CVDoc; onChange: (c: CVDoc) => void }) {
  const s = useSections("summary");
  const set = (patch: Partial<CVDoc>) => onChange({ ...cv, ...patch });
  const setContact = (patch: Partial<CVContact>) => set({ contact: { ...cv.contact, ...patch } });
  const setExp = (i: number, patch: Partial<CVExperience>) =>
    set({ experience: cv.experience.map((e, idx) => (idx === i ? { ...e, ...patch } : e)) });
  const skillCount = cv.skills.reduce((n, g) => n + g.items.length, 0);

  return (
    <div className="flex flex-col gap-[10px]">
      <SectionCard title="Summary" meta={cv.summary ? `${cv.summary.split(/\s+/).filter(Boolean).length} words` : "Empty"}
        open={s.isOpen("summary")} onToggle={() => s.toggle("summary")}>
        <label className="sr-only" htmlFor="cv-summary">Summary</label>
        <textarea id="cv-summary" className={areaCls} rows={5} value={cv.summary ?? ""}
          onChange={(e) => set({ summary: e.target.value })} />
      </SectionCard>

      <SectionCard title="Name & contact" meta={[cv.name, cv.contact.location].filter(Boolean).join(" · ")}
        open={s.isOpen("contact")} onToggle={() => s.toggle("contact")}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-[10px]">
          <Field label="Name" value={cv.name} onChange={(v) => set({ name: v })} />
          <Field label="Headline" value={cv.headline ?? ""} onChange={(v) => set({ headline: v })} />
          <Field label="Email" value={cv.contact.email ?? ""} onChange={(v) => setContact({ email: v })} />
          <Field label="Phone" value={cv.contact.phone ?? ""} onChange={(v) => setContact({ phone: v })} />
          <Field label="Location" value={cv.contact.location ?? ""} onChange={(v) => setContact({ location: v })} />
          <Field label="LinkedIn" value={cv.contact.linkedin ?? ""} onChange={(v) => setContact({ linkedin: v })} />
          <Field label="GitHub" value={cv.contact.github ?? ""} onChange={(v) => setContact({ github: v })} />
          <Field label="Website" value={cv.contact.website ?? ""} onChange={(v) => setContact({ website: v })} />
        </div>
      </SectionCard>

      <SectionCard title="Skills" meta={`${plural(cv.skills.length, "group")} · ${plural(skillCount, "skill")}`}
        open={s.isOpen("skills")} onToggle={() => s.toggle("skills")}>
        {cv.skills.map((g, i) => (
          <div key={i} className="grid grid-cols-1 sm:grid-cols-[1fr_2fr] gap-[10px] items-end">
            <Field label="Group" value={g.category}
              onChange={(v) => set({ skills: cv.skills.map((x, idx) => idx === i ? { ...x, category: v } : x) })} />
            <div className="min-w-0">
              <span className="flex justify-between items-baseline">
                <label htmlFor={`cv-skill-${i}`} className={labelCls}>Skills, separated by commas</label>
                <button type="button" className={removeBtn} onClick={() => set({ skills: cv.skills.filter((_, idx) => idx !== i) })}>Remove</button>
              </span>
              <CommaListInput id={`cv-skill-${i}`} className={inputCls} value={g.items}
                onChange={(items) => set({ skills: cv.skills.map((x, idx) => idx === i ? { ...x, items } : x) })} />
            </div>
          </div>
        ))}
        <AddButton onClick={() => set({ skills: [...cv.skills, { category: "", items: [] }] })}>Add group</AddButton>
      </SectionCard>

      <SectionCard title="Projects" meta={cv.projects.map((p) => p.name).filter(Boolean).join(", ") || "None"}
        open={s.isOpen("projects")} onToggle={() => s.toggle("projects")}>
        {cv.projects.map((p, i) => (
          <div key={i} className="border border-track rounded-[10px] p-3 flex flex-col gap-[10px]">
            <Field label="Name" value={p.name} onChange={(v) => set({ projects: cv.projects.map((x, idx) => idx === i ? { ...x, name: v } : x) })} />
            <div>
              <label htmlFor={`cv-proj-${i}`} className={labelCls}>Description</label>
              <textarea id={`cv-proj-${i}`} className={areaCls} rows={3} value={p.description ?? ""}
                onChange={(e) => set({ projects: cv.projects.map((x, idx) => idx === i ? { ...x, description: e.target.value } : x) })} />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-[10px]">
              <div className="min-w-0">
                <label htmlFor={`cv-tech-${i}`} className={labelCls}>Technologies</label>
                <CommaListInput id={`cv-tech-${i}`} className={inputCls} value={p.tech ?? []}
                  onChange={(tech) => set({ projects: cv.projects.map((x, idx) => idx === i ? { ...x, tech } : x) })} />
              </div>
              <Field label="Link" value={p.link ?? ""}
                onChange={(v) => set({ projects: cv.projects.map((x, idx) => idx === i ? { ...x, link: v } : x) })} />
            </div>
            <button type="button" className={cx(removeBtn, "self-start")} onClick={() => set({ projects: cv.projects.filter((_, idx) => idx !== i) })}>Remove project</button>
          </div>
        ))}
        <AddButton onClick={() => set({ projects: [...cv.projects, { name: "" }] })}>Add project</AddButton>
      </SectionCard>

      <SectionCard title="Experience" meta={cv.experience.map((e) => e.employer).filter(Boolean).join(", ") || "None"}
        open={s.isOpen("experience")} onToggle={() => s.toggle("experience")}>
        {cv.experience.map((exp, i) => (
          <div key={i} className="border border-track rounded-[10px] p-3 flex flex-col gap-[10px]">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-[10px]">
              <Field label="Title" value={exp.title} onChange={(v) => setExp(i, { title: v })} />
              <Field label="Employer" value={exp.employer} onChange={(v) => setExp(i, { employer: v })} />
              <Field label="Start" value={exp.start_date ?? ""} onChange={(v) => setExp(i, { start_date: v })} />
              <Field label="End" value={exp.end_date ?? ""} onChange={(v) => setExp(i, { end_date: v })} />
            </div>
            <span className={labelCls}>Bullets</span>
            {exp.bullets.map((b, bi) => (
              <div key={bi} className="flex gap-2 items-center">
                <label className="sr-only" htmlFor={`cv-b-${i}-${bi}`}>Bullet {bi + 1}</label>
                <input id={`cv-b-${i}-${bi}`} className={inputCls} value={b}
                  onChange={(e) => setExp(i, { bullets: exp.bullets.map((x, idx) => idx === bi ? e.target.value : x) })} />
                <button type="button" aria-label={`Remove bullet ${bi + 1}`}
                  className="w-8 h-8 shrink-0 rounded-[8px] text-ink-3 hover:text-red hover:bg-red-soft flex items-center justify-center"
                  onClick={() => setExp(i, { bullets: exp.bullets.filter((_, idx) => idx !== bi) })}>
                  <Icon name="close" size={14} strokeWidth={2} />
                </button>
              </div>
            ))}
            <div className="flex justify-between items-center">
              <AddButton onClick={() => setExp(i, { bullets: [...exp.bullets, ""] })}>Add bullet</AddButton>
              <button type="button" className={removeBtn} onClick={() => set({ experience: cv.experience.filter((_, idx) => idx !== i) })}>Remove role</button>
            </div>
          </div>
        ))}
        <AddButton onClick={() => set({ experience: [...cv.experience, { title: "", employer: "", bullets: [] }] })}>Add role</AddButton>
      </SectionCard>

      <SectionCard title="Education" meta={cv.education.map((e) => [e.degree, e.institution].filter(Boolean).join(", ")).join("; ") || "None"}
        open={s.isOpen("education")} onToggle={() => s.toggle("education")}>
        {cv.education.map((ed, i) => (
          <div key={i} className="border border-track rounded-[10px] p-3 flex flex-col gap-[10px]">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-[10px]">
              <Field label="Degree" value={ed.degree} onChange={(v) => set({ education: cv.education.map((x, idx) => idx === i ? { ...x, degree: v } : x) })} />
              <Field label="Institution" value={ed.institution} onChange={(v) => set({ education: cv.education.map((x, idx) => idx === i ? { ...x, institution: v } : x) })} />
              <Field label="Year" value={ed.year ?? ""} onChange={(v) => set({ education: cv.education.map((x, idx) => idx === i ? { ...x, year: v } : x) })} />
              <Field label="Grade" value={ed.grade ?? ""} onChange={(v) => set({ education: cv.education.map((x, idx) => idx === i ? { ...x, grade: v } : x) })} />
            </div>
            <button type="button" className={cx(removeBtn, "self-start")} onClick={() => set({ education: cv.education.filter((_, idx) => idx !== i) })}>Remove</button>
          </div>
        ))}
        <AddButton onClick={() => set({ education: [...cv.education, { degree: "", institution: "" }] })}>Add education</AddButton>
      </SectionCard>

      <SectionCard title="Certifications" meta={cv.certifications.map((c) => c.name).filter(Boolean).join(", ") || "None"}
        open={s.isOpen("certs")} onToggle={() => s.toggle("certs")}>
        {cv.certifications.map((c, i) => (
          <div key={i} className="grid grid-cols-1 sm:grid-cols-[2fr_2fr_1fr] gap-[10px] items-end">
            <Field label="Name" value={c.name} onChange={(v) => set({ certifications: cv.certifications.map((x, idx) => idx === i ? { ...x, name: v } : x) })} />
            <Field label="Issuer" value={c.issuer ?? ""} onChange={(v) => set({ certifications: cv.certifications.map((x, idx) => idx === i ? { ...x, issuer: v } : x) })} />
            <Field label="Year" value={c.year ?? ""} onChange={(v) => set({ certifications: cv.certifications.map((x, idx) => idx === i ? { ...x, year: v } : x) })} />
            <button type="button" className={cx(removeBtn, "justify-self-start")} onClick={() => set({ certifications: cv.certifications.filter((_, idx) => idx !== i) })}>Remove</button>
          </div>
        ))}
        <AddButton onClick={() => set({ certifications: [...cv.certifications, { name: "" }] })}>Add certification</AddButton>
      </SectionCard>
    </div>
  );
}

/* ── Cover letter form ──────────────────────────────────────────────────── */

function LetterForm({ letter, onChange }: { letter: LetterDoc; onChange: (l: LetterDoc) => void }) {
  const s = useSections("body");
  const set = (patch: Partial<LetterDoc>) => onChange({ ...letter, ...patch });
  return (
    <div className="flex flex-col gap-[10px]">
      <SectionCard title="Letter" meta={plural(letter.paragraphs.length, "paragraph")}
        open={s.isOpen("body")} onToggle={() => s.toggle("body")}>
        <Field label="Greeting" value={letter.salutation} onChange={(v) => set({ salutation: v })} />
        {letter.paragraphs.map((p, i) => (
          <div key={i} className="flex flex-col gap-1">
            <span className="flex justify-between items-baseline">
              <label htmlFor={`letter-p-${i}`} className={labelCls}>Paragraph {i + 1}</label>
              <button type="button" className={removeBtn} onClick={() => set({ paragraphs: letter.paragraphs.filter((_, idx) => idx !== i) })}>Remove</button>
            </span>
            <textarea id={`letter-p-${i}`} className={areaCls} rows={4} value={p}
              onChange={(e) => set({ paragraphs: letter.paragraphs.map((x, idx) => idx === i ? e.target.value : x) })} />
          </div>
        ))}
        <AddButton onClick={() => set({ paragraphs: [...letter.paragraphs, ""] })}>Add paragraph</AddButton>
        <Field label="Sign-off" value={letter.signoff} onChange={(v) => set({ signoff: v })} />
      </SectionCard>
      {/* The dated recipient block above the greeting. */}
      <SectionCard title="Date & recipient" meta={[letter.date, letter.company].filter(Boolean).join(" · ")}
        open={s.isOpen("head")} onToggle={() => s.toggle("head")}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-[10px]">
          <Field label="Date" value={letter.date ?? ""} onChange={(v) => set({ date: v })} />
          <Field label="Role (Re: line)" value={letter.job_title ?? ""} onChange={(v) => set({ job_title: v })} />
          <Field label="Company" value={letter.company ?? ""} onChange={(v) => set({ company: v })} />
          <Field label="Company location" value={letter.company_location ?? ""} onChange={(v) => set({ company_location: v })} />
        </div>
      </SectionCard>
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
    <div className="flex flex-wrap">
      <div className="flex-[1_1_300px] min-w-0 px-4 sm:px-5 py-4 flex flex-col gap-[10px] border-b md:border-b-0 md:border-r border-track">
        {kind === "cv" && cv
          ? <CvForm cv={cv} onChange={(c) => onCvChange?.(c)} />
          : letter ? <LetterForm letter={letter} onChange={(l) => onLetterChange?.(l)} /> : null}
      </div>
      <div className="flex-[1.1_1_340px] min-w-0 p-5 bg-track">
        <PreviewPane kind={kind} doc={doc} templateId={templateId} />
      </div>
    </div>
  );
}
