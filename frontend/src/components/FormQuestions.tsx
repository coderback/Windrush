"use client";

import { useEffect, useId, useState } from "react";
import Icon from "./ui/Icon";
import { buttonClass, Callout, Card, Chip, inputClass, Spinner, textareaClass, type ChipTone } from "./ui/kit";
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

/** An answer you gave in the review, for the agent to put on the form. */
export interface ReviewAnswer { question: string; answer: string; kind: FormAnswer["kind"]; options: string[] }

function Row({ q, company, savedNote, onSaved }: {
  q: FormAnswer; company: string; savedNote: string;
  /** Called once the answer is saved, when it differs from what the agent put on the form. */
  onSaved: (a: ReviewAnswer) => void;
}) {
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
      const answer = value.trim();
      await saveAnswer(q.question, answer, q.kind, company);
      setState("saved");
      setEditing(false);
      if (q.source === "needs_you" || answer !== q.answer.trim()) {
        onSaved({ question: q.question, answer, kind: q.kind, options: q.options });
      }
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
export default function FormQuestions({ questions, company, savedNote, onFill }: {
  questions: FormAnswer[];
  company: string;
  /** Shown once you've answered a question the agent left blank. */
  savedNote: string;
  /** While the agent's browser is paused on the form: have it put your answers on the form. */
  onFill?: (answers: ReviewAnswer[]) => Promise<void>;
}) {
  // Answers saved in this review that aren't on the form yet, by question.
  const [pending, setPending] = useState<Record<string, ReviewAnswer>>({});
  const [filling, setFilling] = useState(false);
  const [fillError, setFillError] = useState<string | null>(null);

  // The agent sends the questions again once it has put your answers on the form: those are done.
  // (Callers may pass a new array on every render, so nothing changes unless an answer really went in.)
  useEffect(() => {
    setFilling(false);
    setPending((prev) => {
      const left = Object.entries(prev).filter(([question, a]) =>
        !questions.some((q) => q.question === question && q.source === "saved" && q.answer === a.answer));
      return left.length === Object.keys(prev).length ? prev : Object.fromEntries(left);
    });
  }, [questions]);

  if (questions.length === 0) return null;
  const waiting = Object.values(pending);

  const fill = async () => {
    if (!onFill || waiting.length === 0) return;
    setFilling(true);
    setFillError(null);
    try {
      await onFill(waiting);
    } catch (e) {
      setFilling(false);
      setFillError(e instanceof Error ? e.message : "Couldn't reach the agent.");
    }
  };
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
      {onFill && waiting.length > 0 && (
        <div role="status" className="flex flex-wrap items-center justify-between gap-3 px-[14px] py-3 rounded-inner bg-teal-soft text-teal-deep text-[13px]">
          <span>
            {filling
              ? `The agent is putting your ${waiting.length === 1 ? "answer" : `${waiting.length} answers`} on the form…`
              : `${waiting.length} saved ${waiting.length === 1 ? "answer isn't" : "answers aren't"} on the form yet.`}
          </span>
          <button type="button" onClick={fill} disabled={filling} className={buttonClass("commit", "sm")}>
            {filling ? <Spinner /> : null}Fill {waiting.length === 1 ? "it" : "them"} in on the form
          </button>
        </div>
      )}
      {fillError && <Callout>{fillError}</Callout>}
      <ul className="m-0 p-0 list-none flex flex-col">
        {sorted.map((q) => (
          <Row key={`${q.question}|${q.source}`} q={q} company={company} savedNote={savedNote}
            onSaved={(a) => setPending((prev) => ({ ...prev, [a.question]: a }))} />
        ))}
      </ul>
    </Card>
  );
}
