"use client";

import { useId, useState } from "react";
import Icon from "./ui/Icon";
import { buttonClass, Card, Chip, inputClass, Spinner, textareaClass, type ChipTone } from "./ui/kit";
import { saveAnswer, SOURCE_LABEL } from "@/lib/answers";
import type { AnswerSource, FormAnswer } from "@/lib/types";

const TONE: Record<AnswerSource, ChipTone> = { needs_you: "warn", drafted: "info", saved: "positive", profile: "neutral" };
const ORDER: AnswerSource[] = ["needs_you", "drafted", "saved", "profile"];

function count(source: AnswerSource, n: number): string {
  switch (source) {
    case "needs_you": return `${n} only you can answer`;
    case "drafted": return `${n} drafted, check ${n === 1 ? "it" : "them"}`;
    case "saved": return `${n} saved`;
    case "profile": return `${n} from your persona`;
  }
}

function Row({ q, company, savedNote }: { q: FormAnswer; company: string; savedNote: string }) {
  const [value, setValue] = useState(q.answer);
  const [editing, setEditing] = useState(q.source === "needs_you");
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);
  const labelId = useId();

  const source: AnswerSource = state === "saved" ? "saved" : q.source;
  const canSave = value.trim().length > 0 && state !== "saving";

  const save = async () => {
    setState("saving");
    setError(null);
    try {
      await saveAnswer(q.question, value.trim(), q.kind, company);
      setState("saved");
      setEditing(false);
    } catch (e) {
      setState("idle");
      setError(e instanceof Error ? e.message : "Couldn't save the answer.");
    }
  };

  return (
    <li className="flex flex-col gap-2 py-[14px] border-t border-track first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span id={labelId} className="flex-1 min-w-[200px] text-[13.5px] font-medium text-ink">{q.question}</span>
        <Chip tone={TONE[source]} size="sm" className="font-semibold">{SOURCE_LABEL[source]}</Chip>
      </div>

      {editing ? (
        <div className="flex flex-col gap-2">
          {q.options.length > 0 ? (
            <select aria-labelledby={labelId} className={inputClass} value={value} onChange={(e) => setValue(e.target.value)}>
              <option value="">Choose an answer…</option>
              {q.options.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : q.kind === "written" ? (
            <textarea aria-labelledby={labelId} rows={6} className={textareaClass} value={value} onChange={(e) => setValue(e.target.value)} />
          ) : (
            <input aria-labelledby={labelId} className={inputClass} value={value} onChange={(e) => setValue(e.target.value)} />
          )}
          <span className="flex flex-wrap gap-2">
            <button type="button" onClick={save} disabled={!canSave} className={buttonClass("primary", "sm")}>
              {state === "saving" ? <Spinner /> : null}Save answer
            </button>
            {q.source !== "needs_you" && (
              <button type="button" onClick={() => { setEditing(false); setValue(q.answer); }} className={buttonClass("quiet", "sm")}>
                Cancel
              </button>
            )}
          </span>
        </div>
      ) : value ? (
        <p className="m-0 text-[13.5px] leading-[1.55] text-ink-2 whitespace-pre-wrap break-words">{value}</p>
      ) : null}

      {state !== "saved" && q.flags.length > 0 && (
        <ul className="m-0 p-0 list-none flex flex-col gap-1">
          {q.flags.map((f) => (
            <li key={f} className="flex gap-2 text-[12.5px] leading-[1.45] text-amber-text">
              <Icon name="alert" size={13} className="mt-[2px] shrink-0" /><span>{f}</span>
            </li>
          ))}
        </ul>
      )}
      {state === "saved" ? (
        <span role="status" className="flex items-center gap-[6px] text-[12.5px] text-teal-deep">
          <Icon name="check" size={13} strokeWidth={2.4} />{q.source === "needs_you" ? savedNote : "Saved for your next form."}
        </span>
      ) : q.because ? (
        <span className="text-[12px] leading-[1.45] text-ink-3">{q.because}</span>
      ) : null}

      {q.source === "drafted" && !editing && state !== "saved" && (
        <span className="flex flex-wrap gap-2">
          <button type="button" onClick={() => setEditing(true)} className={buttonClass("secondary", "xs")}>
            <Icon name="edit" size={13} />Edit
          </button>
          <button type="button" onClick={save} disabled={!canSave} className={buttonClass("secondary", "xs")}>
            {state === "saving" ? <Spinner /> : null}Save for next time
          </button>
        </span>
      )}
      {error && <p role="alert" className="m-0 text-[12.5px] text-red">{error}</p>}
    </li>
  );
}

/**
 * The questions the agent met on an application form: each answer with where it came from (your
 * answer bank, your persona, or drafted for this job), and a box for those only you can answer.
 * What you answer here goes into your answer bank, so the next form gets it.
 */
export default function FormQuestions({ questions, company, savedNote }: {
  questions: FormAnswer[];
  company: string;
  /** Shown once you've answered a question the agent left blank. */
  savedNote: string;
}) {
  if (questions.length === 0) return null;
  const sorted = [...questions].sort((a, b) => ORDER.indexOf(a.source) - ORDER.indexOf(b.source));
  const counts = ORDER.map((s) => [s, questions.filter((q) => q.source === s).length] as const).filter(([, n]) => n > 0);

  return (
    <Card className="p-5 flex flex-col gap-4" aria-labelledby="form-questions">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-[3px] min-w-0 max-w-[70ch]">
          <h2 id="form-questions" className="m-0 text-[16px] font-semibold">Questions on this form</h2>
          <span className="text-[13px] text-ink-3">
            Facts come only from your persona and the answers you&apos;ve saved; nothing is guessed. Anything you answer here is
            saved for your next form.
          </span>
        </div>
        <span className="flex flex-wrap gap-[6px]">
          {counts.map(([s, n]) => <Chip key={s} tone={TONE[s]} size="sm">{count(s, n)}</Chip>)}
        </span>
      </div>
      <ul className="m-0 p-0 list-none flex flex-col">
        {sorted.map((q) => <Row key={q.question} q={q} company={company} savedNote={savedNote} />)}
      </ul>
    </Card>
  );
}
