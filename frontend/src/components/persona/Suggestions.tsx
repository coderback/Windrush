"use client";

import { useEffect, useState } from "react";
import Icon from "@/components/ui/Icon";
import { buttonClass, Callout, Card, Chip, EmptyState, Skeleton, Spinner } from "@/components/ui/kit";
import { acceptSuggestions, dismissSuggestions, readSource, refreshSuggestions, SUGGESTIONS_URL, uploadLinkedIn } from "@/lib/suggestions";
import { useResource } from "@/lib/store";
import type { Persona, ProfileSuggestion, ProfileSuggestions, SourceRead, SuggestionSection, SuggestionSource } from "@/lib/types";

const SOURCE_LABEL: Record<SuggestionSource, string> = { github: "GitHub", website: "Website", linkedin: "LinkedIn" };

const GROUPS: { section: SuggestionSection[]; title: string }[] = [
  { section: ["projects"], title: "Projects" },
  { section: ["history"], title: "Work history" },
  { section: ["education"], title: "Education" },
  { section: ["certifications"], title: "Certifications" },
  { section: ["skills"], title: "Skills" },
  { section: ["core_info", "summary"], title: "Contact details and summary" },
];

const FIELD_LABEL: Record<string, string> = {
  url: "Link", problem_solved: "Description", technologies: "Technologies", outcomes: "Outcomes", summary: "Summary",
  achievements: "Achievements", tech_stack: "Technologies", start_date: "Started", end_date: "Ended", degree: "Degree",
  grade: "Grade", is_current: "Current role", is_currently_enrolled: "Still studying", first_name: "First name",
  last_name: "Last name", email: "Email", phone: "Phone", address_line_1: "Address", city: "City", linkedin: "LinkedIn",
  github: "GitHub", website: "Website", issuer: "Issued by", issued: "Issued",
};

function ago(iso?: string) {
  if (!iso) return "";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  return hours < 24 ? `${hours} h ago` : new Date(iso).toLocaleDateString();
}

function show(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value ?? "");
}

/** The fields a suggestion fills, one line each (a list of achievements as a list). */
function Fields({ value }: { value: Record<string, unknown> }) {
  const rows = Object.entries(value).filter(([k, v]) => k !== "is_current" && k !== "is_currently_enrolled" && show(v));
  return (
    <dl className="m-0 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-[13px]">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-ink-3">{FIELD_LABEL[k] ?? k}</dt>
          <dd className="m-0 text-ink-2 break-words min-w-0">
            {k === "achievements" && Array.isArray(v) ? (
              <ul className="m-0 pl-4 flex flex-col gap-[2px]">{v.map((a, i) => <li key={i}>{String(a)}</li>)}</ul>
            ) : k === "url" ? (
              <a href={String(v)} target="_blank" rel="noreferrer" className="text-teal underline underline-offset-2 break-all">{String(v)}</a>
            ) : show(v)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function describe(s: ProfileSuggestion): { title: string; fields: Record<string, unknown> | null } {
  const v = (typeof s.value === "object" ? s.value : {}) as Record<string, unknown>;
  if (s.action === "fill") {
    if (s.section === "core_info" || s.section === "summary") return { title: FIELD_LABEL[s.key] ?? s.key, fields: v };
    return { title: `Add to “${s.key}”`, fields: v };
  }
  switch (s.section) {
    case "projects":
      return { title: `New project: ${v.name}`, fields: { url: v.url, problem_solved: v.problem_solved, technologies: v.technologies, outcomes: v.outcomes } };
    case "history":
      return { title: `New role: ${s.key}`, fields: { start_date: v.start_date, end_date: v.end_date || (v.is_current ? "Present" : ""), summary: v.summary, achievements: v.achievements } };
    case "education":
      return { title: `New education: ${v.institution}`, fields: { degree: v.degree, start_date: v.start_date, end_date: v.end_date, grade: v.grade } };
    case "certifications":
      return { title: `New certification: ${v.name}`, fields: { issuer: v.issuing_organization, issued: v.issue_date, url: v.credential_url } };
    default:
      return { title: s.key, fields: null };
  }
}

function Evidence({ s }: { s: ProfileSuggestion }) {
  const { text, url, detail } = s.evidence ?? {};
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-ink-3">
      <Chip size="sm">{SOURCE_LABEL[s.source]}</Chip>
      {url ? (
        <a href={url} target="_blank" rel="noreferrer" className="underline underline-offset-2 hover:text-ink break-all">{text || url}</a>
      ) : text}
      {detail && <span>· {detail}</span>}
    </span>
  );
}

function Actions({ label, busy, onAdd, onDismiss, size = "xs" }: {
  label: string; busy: boolean; onAdd: () => void; onDismiss: () => void; size?: "xs" | "sm";
}) {
  return (
    <span className="flex gap-2 shrink-0">
      <button type="button" disabled={busy} onClick={onAdd} aria-label={`Add ${label}`} className={buttonClass("primary", size)}>
        <Icon name="check" size={13} strokeWidth={2.4} />Add
      </button>
      <button type="button" disabled={busy} onClick={onDismiss} aria-label={`Dismiss ${label}`} className={buttonClass("quiet", size)}>
        Dismiss
      </button>
    </span>
  );
}

function Source({ source, read, reading, busy, onRead, onUpload }: {
  source: SuggestionSource; read: SourceRead; reading: boolean; busy: boolean;
  onRead: () => void; onUpload: (f: File) => void;
}) {
  const result = reading ? "Reading…"
    : read.error ? read.error
    : read.at ? `${read.added ? `${read.added} new` : "Nothing new"} · ${ago(read.at)}` : "";
  return (
    <li className="flex flex-wrap items-center gap-3 py-3 border-t border-track first:border-t-0 first:pt-0">
      <span className="flex-1 min-w-[220px] flex flex-col gap-[2px]">
        <span className="text-[14px] font-semibold">{source === "linkedin" ? "LinkedIn data export" : SOURCE_LABEL[source]}</span>
        <span className="text-[12.5px] text-ink-3 break-all">
          {source === "linkedin"
            ? "LinkedIn > Settings > Data privacy > Get a copy of your data. Upload the zip they email you."
            : read.address || (source === "github" ? "Add your GitHub link under Links first." : "Add your website under Links first.")}
        </span>
        {result && (
          <span role={read.error ? "alert" : "status"} className={read.error && !reading ? "text-[12.5px] text-red" : "text-[12.5px] text-ink-2"}>
            {result}
          </span>
        )}
      </span>
      {source === "linkedin" ? (
        <label className={buttonClass("secondary", "sm", busy ? "opacity-60 pointer-events-none" : "cursor-pointer")}>
          {busy ? <Spinner /> : <Icon name="upload" size={14} />}Upload export
          <input type="file" accept=".zip,application/zip" className="sr-only-input" disabled={busy}
            onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onUpload(f); }} />
        </label>
      ) : (
        <button type="button" disabled={busy || !read.address} onClick={onRead} className={buttonClass("secondary", "sm")}>
          {reading ? <Spinner /> : <Icon name="refresh" size={14} />}{reading ? "Reading" : `Read ${SOURCE_LABEL[source].toLowerCase()}`}
        </button>
      )}
    </li>
  );
}

/**
 * What GitHub, the user's website and a LinkedIn export say that the persona doesn't. Each suggestion only adds an
 * entry or fills an empty field; nothing changes until the user adds it.
 * `beforeChange` saves any edit still waiting on the page; `onPersona` takes the persona as the server saved it.
 */
export default function Suggestions({ beforeChange, onPersona }: {
  beforeChange: () => Promise<void>; onPersona: (p: Persona) => void;
}) {
  const res = useResource<ProfileSuggestions>(SUGGESTIONS_URL, { staleMs: 0 });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const data = res.data;
  const reading = data?.reading ?? "";

  // While a source is being read, check back until it's done.
  useEffect(() => {
    if (!reading) return;
    const t = setInterval(() => { refreshSuggestions().catch(() => {}); }, 2500);
    return () => clearInterval(t);
  }, [reading]);

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    setNote(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work. Try again.");
    } finally {
      setBusy(null);
    }
  };

  const accept = (key: string, ids: string[]) => run(key, async () => {
    await beforeChange();
    const result = await acceptSuggestions(ids);
    onPersona(result.persona);
    const added = result.accepted === 1 ? "Added 1 change" : `Added ${result.accepted} changes`;
    setNote(result.outdated ? `${added}. ${result.outdated} you already had, so ${result.outdated === 1 ? "it was" : "they were"} skipped.` : `${added} to your persona.`);
  });
  const dismiss = (key: string, ids: string[]) => run(key, () => dismissSuggestions(ids));

  if (res.loading) return <Skeleton className="h-[320px] rounded-card" />;
  if (!data) return <Callout title="Couldn't load suggestions">{res.error ?? "Try again in a moment."}</Callout>;

  const items = data.suggestions;
  return (
    <div className="flex flex-col gap-[14px]">
      <Card className="p-5 flex flex-col gap-3">
        <div className="flex flex-col gap-[3px]">
          <h2 className="m-0 text-[16px] font-semibold">Suggestions from your profiles</h2>
          <span className="text-[13px] text-ink-3 max-w-[70ch]">
            Windrush reads your GitHub, your website and your LinkedIn export, and suggests what your persona is missing.
            A suggestion only adds something new or fills an empty field. Nothing you wrote is changed, and nothing is
            added until you say so.
          </span>
        </div>
        <ul className="m-0 p-0 list-none">
          {(["github", "website", "linkedin"] as const).map((source) => (
            <Source key={source} source={source} read={data.sources[source] ?? { address: "" }}
              reading={reading === source} busy={!!reading || busy === `read-${source}`}
              onRead={() => run(`read-${source}`, () => readSource(source as "github" | "website"))}
              onUpload={(f) => run("read-linkedin", async () => {
                const added = await uploadLinkedIn(f);
                setNote(added ? `${added} new suggestion${added === 1 ? "" : "s"} from your LinkedIn export.` : "Your LinkedIn export has nothing your persona is missing.");
              })} />
          ))}
        </ul>
      </Card>

      {error && <Callout title="That didn't work">{error}</Callout>}
      {note && <p role="status" className="m-0 px-4 py-[10px] rounded-inner bg-teal-soft text-[13.5px] text-ink">{note}</p>}

      {items.length === 0 ? (
        <EmptyState>Nothing to add right now. Read a source above to look for more.</EmptyState>
      ) : GROUPS.map(({ section, title }) => {
        const group = items.filter((s) => section.includes(s.section));
        if (!group.length) return null;
        const ids = group.map((s) => s.id);
        const groupKey = `group-${title}`;
        return (
          <Card key={title} className="p-5 flex flex-col gap-3">
            <div className="flex flex-wrap justify-between items-center gap-2">
              <h3 className="m-0 text-[15px] font-semibold">{title} <span className="font-mono text-[13px] text-ink-3">{group.length}</span></h3>
              {group.length > 1 && (
                <span className="flex gap-2">
                  <button type="button" disabled={!!busy} onClick={() => accept(groupKey, ids)} className={buttonClass("secondary", "xs")}>
                    {busy === groupKey ? <Spinner /> : null}Add all {group.length}
                  </button>
                  <button type="button" disabled={!!busy} onClick={() => dismiss(`${groupKey}-d`, ids)} className={buttonClass("quiet", "xs")}>
                    Dismiss all
                  </button>
                </span>
              )}
            </div>
            {section[0] === "skills" ? (
              <ul className="m-0 p-0 list-none flex flex-col">
                {group.map((s) => (
                  <li key={s.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2 border-t border-track first:border-t-0">
                    <span className="flex-1 min-w-[200px] flex flex-col gap-[3px]">
                      <span className="text-[13.5px]"><span className="font-semibold">{String(s.value)}</span>
                        <span className="text-ink-3"> in {s.category || "Other"}</span></span>
                      <Evidence s={s} />
                    </span>
                    <Actions label={String(s.value)} busy={!!busy} onAdd={() => accept(s.id, [s.id])} onDismiss={() => dismiss(s.id, [s.id])} />
                  </li>
                ))}
              </ul>
            ) : (
              <ul className="m-0 p-0 list-none flex flex-col">
                {group.map((s) => {
                  const { title: line, fields } = describe(s);
                  return (
                    <li key={s.id} className="flex flex-col gap-2 py-[14px] border-t border-track first:border-t-0 first:pt-0">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <span className="flex-1 min-w-[220px] text-[14px] font-semibold break-words">{line}</span>
                        <Actions label={line} busy={!!busy} onAdd={() => accept(s.id, [s.id])} onDismiss={() => dismiss(s.id, [s.id])} />
                      </div>
                      {fields && <Fields value={fields} />}
                      <Evidence s={s} />
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        );
      })}
    </div>
  );
}
