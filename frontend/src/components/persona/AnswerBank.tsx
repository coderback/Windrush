"use client";

import { useId, useState } from "react";
import Icon from "@/components/ui/Icon";
import { buttonClass, Callout, Card, Chip, EmptyState, inputClass, labelClass, Skeleton, Spinner, textareaClass } from "@/components/ui/kit";
import { ANSWERS_URL, deleteAnswer, saveAnswer, updateAnswer } from "@/lib/answers";
import { useResource } from "@/lib/store";
import type { SavedAnswer } from "@/lib/types";

function Entry({ a }: { a: SavedAnswer }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(a.answer);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState<"save" | "delete" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const id = useId();

  const run = async (kind: "save" | "delete", fn: () => Promise<unknown>) => {
    setBusy(kind);
    setError(null);
    try {
      await fn();
      if (kind === "save") setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work. Try again.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <li className="flex flex-col gap-2 py-[14px] border-t border-track first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span id={id} className="flex-1 min-w-[200px] text-[13.5px] font-medium">{a.question}</span>
        <span className="flex flex-wrap gap-[6px]">
          <Chip size="sm">{a.kind === "written" ? "Written" : "Fact"}</Chip>
          {a.company && <Chip size="sm" tone="info">Only for {a.company}</Chip>}
        </span>
      </div>
      {editing ? (
        a.kind === "written" ? (
          <textarea aria-labelledby={id} rows={5} className={textareaClass} value={value} onChange={(e) => setValue(e.target.value)} />
        ) : (
          <input aria-labelledby={id} className={inputClass} value={value} onChange={(e) => setValue(e.target.value)} />
        )
      ) : (
        <p className="m-0 text-[13.5px] leading-[1.55] text-ink-2 whitespace-pre-wrap break-words">{a.answer}</p>
      )}
      <span className="flex flex-wrap gap-2">
        {editing ? (
          <>
            <button type="button" disabled={!value.trim() || busy !== null} onClick={() => run("save", () => updateAnswer(a.id, value.trim()))}
              className={buttonClass("primary", "xs")}>{busy === "save" ? <Spinner /> : null}Save</button>
            <button type="button" onClick={() => { setEditing(false); setValue(a.answer); }} className={buttonClass("quiet", "xs")}>Cancel</button>
          </>
        ) : confirming ? (
          <>
            <button type="button" disabled={busy !== null} onClick={() => run("delete", () => deleteAnswer(a.id))}
              className={buttonClass("destructive", "xs", "border border-red-soft")}>{busy === "delete" ? <Spinner /> : null}Delete it</button>
            <button type="button" onClick={() => setConfirming(false)} className={buttonClass("quiet", "xs")}>Keep it</button>
          </>
        ) : (
          <>
            <button type="button" onClick={() => setEditing(true)} className={buttonClass("secondary", "xs")}>
              <Icon name="edit" size={13} />Edit
            </button>
            <button type="button" onClick={() => setConfirming(true)} className={buttonClass("quiet", "xs")}>Delete</button>
          </>
        )}
      </span>
      {error && <p role="alert" className="m-0 text-[12.5px] text-red">{error}</p>}
    </li>
  );
}

function AddAnswer({ onDone }: { onDone: () => void }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [kind, setKind] = useState<"fact" | "written">("fact");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const qId = useId();
  const aId = useId();
  const kId = useId();

  const add = async () => {
    setBusy(true);
    setError(null);
    try {
      await saveAnswer(question.trim(), answer.trim(), kind);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the answer.");
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3 p-4 rounded-inner border border-dashed border-stone bg-subtle">
      <div className="flex flex-col gap-[6px]">
        <label htmlFor={qId} className={labelClass}>Question, as forms ask it</label>
        <input id={qId} className={inputClass} value={question} onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Do you have any unspent criminal convictions?" />
      </div>
      <div className="flex flex-col gap-[6px]">
        <label htmlFor={kId} className={labelClass}>Kind</label>
        <select id={kId} className={inputClass} value={kind} onChange={(e) => setKind(e.target.value as "fact" | "written")}>
          <option value="fact">A fact (yes / no, a date, a choice)</option>
          <option value="written">A written answer</option>
        </select>
      </div>
      <div className="flex flex-col gap-[6px]">
        <label htmlFor={aId} className={labelClass}>Your answer</label>
        {kind === "written" ? (
          <textarea id={aId} rows={5} className={textareaClass} value={answer} onChange={(e) => setAnswer(e.target.value)} />
        ) : (
          <input id={aId} className={inputClass} value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="e.g. No" />
        )}
      </div>
      {error && <p role="alert" className="m-0 text-[12.5px] text-red">{error}</p>}
      <span className="flex gap-2">
        <button type="button" onClick={add} disabled={busy || !question.trim() || !answer.trim()} className={buttonClass("primary", "sm")}>
          {busy ? <Spinner /> : null}Save answer
        </button>
        <button type="button" onClick={onDone} className={buttonClass("quiet", "sm")}>Cancel</button>
      </span>
    </div>
  );
}

/** Your answer bank: what you've answered on application forms, reused on later ones (api/app/answers.py). */
export default function AnswerBank() {
  const saved = useResource<SavedAnswer[]>(ANSWERS_URL);
  const [adding, setAdding] = useState(false);

  return (
    <Card className="p-5 flex flex-col gap-4">
      <div className="flex flex-wrap justify-between items-start gap-[10px]">
        <div className="flex flex-col gap-[3px] min-w-0">
          <h2 className="m-0 text-[16px] font-semibold">Saved answers</h2>
          <span className="text-[13px] text-ink-3 max-w-[70ch]">
            Your answers to application-form questions. The agent reuses them on later forms, and a fact that neither these nor
            your persona state is left blank for you rather than guessed. An answer that names an employer is only used on
            that employer&apos;s forms.
          </span>
        </div>
        {!adding && (
          <button type="button" onClick={() => setAdding(true)} className={buttonClass("secondary", "sm")}>
            <Icon name="plus" size={14} strokeWidth={2} />Add an answer
          </button>
        )}
      </div>
      {adding && <AddAnswer onDone={() => setAdding(false)} />}
      {saved.loading ? (
        <Skeleton className="h-24 rounded-inner" />
      ) : saved.error ? (
        <Callout title="Couldn't load your saved answers">{saved.error}</Callout>
      ) : (saved.data ?? []).length === 0 ? (
        <EmptyState>
          Nothing saved yet. When the agent meets a question only you can answer, you answer it once in the review and it&apos;s
          kept here for the next form.
        </EmptyState>
      ) : (
        <ul className="m-0 p-0 list-none flex flex-col">
          {(saved.data ?? []).map((a) => <Entry key={`${a.id}-${a.updated_at}`} a={a} />)}
        </ul>
      )}
    </Card>
  );
}
