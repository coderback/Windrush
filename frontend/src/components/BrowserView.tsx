"use client";

import { useRef, useState, useEffect } from "react";
import { authFetch } from "@/app/api";
import Icon from "./ui/Icon";
import { buttonClass, cx, Spinner } from "./ui/kit";

interface Props {
  action: string;
  screenshot: string | null;
  blocked: boolean;
  reason: string | null;
  sessionId: string;
  interactive?: boolean;
  /** The page the agent opened, for the address bar. */
  url?: string;
  onInstructionSent?: () => void;
}

const BROWSER_W = 1280;
const BROWSER_H = 800;

/** Relay an instruction ("submit", "done", "skip", text, or a click/key/scroll payload) to the agent. */
export async function sendInstruction(sessionId: string, payload: object | string) {
  const instruction = typeof payload === "string" ? payload : JSON.stringify(payload);
  const res = await authFetch(`/api/browser-input/${sessionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction }),
  });
  if (!res.ok) throw new Error("The session has closed.");
}

/** Browser-style chrome: three dots, an address bar with a lock, and a live indicator. */
export function BrowserFrame({ url, live, children, footer }: {
  url?: string; live?: boolean; children: React.ReactNode; footer?: React.ReactNode;
}) {
  let host = url || "";
  try { if (url) host = new URL(url).host + new URL(url).pathname; } catch {}
  return (
    <section aria-label="Live application page" className="flex-1 min-w-0 bg-surface border border-border rounded-card overflow-hidden flex flex-col">
      <div className="flex items-center gap-[10px] px-[14px] py-[10px] border-b border-track bg-subtle">
        <span className="flex gap-[6px]" aria-hidden="true">
          {[0, 1, 2].map((i) => <span key={i} className="w-[10px] h-[10px] rounded-full bg-border-strong" />)}
        </span>
        <span className="flex-1 flex items-center gap-[6px] h-7 px-[10px] rounded-[7px] bg-surface border border-border font-mono text-[11.5px] text-ink-2 min-w-0 overflow-hidden whitespace-nowrap">
          <Icon name="lock" size={12} strokeWidth={2} />
          <span className="truncate">{host || "about:blank"}</span>
        </span>
        {live && (
          <span className="flex items-center gap-[6px] text-[12px] text-teal font-medium">
            <span className="w-[7px] h-[7px] rounded-full bg-teal animate-pulse" aria-hidden="true" />Live
          </span>
        )}
      </div>
      {children}
      {footer}
    </section>
  );
}

export default function BrowserView({
  action, screenshot, blocked, reason, sessionId, interactive, url, onInstructionSent,
}: Props) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  // Pending frame from SSE — written without triggering re-render
  const pendingFrame = useRef<string | null>(null);

  // Open a separate SSE connection for live CDP screencast frames.
  // Paint frames via requestAnimationFrame to avoid a React re-render per frame.
  useEffect(() => {
    if (!sessionId) return;
    const es = new EventSource(`/api/browser-stream/${sessionId}`);
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.frame) pendingFrame.current = data.frame;
        if (data.type === "close") es.close();
      } catch {}
    };

    let rafId: number;
    const paint = () => {
      const frame = pendingFrame.current;
      if (frame && imgRef.current) {
        imgRef.current.src = `data:image/jpeg;base64,${frame}`;
        pendingFrame.current = null;
      }
      rafId = requestAnimationFrame(paint);
    };
    rafId = requestAnimationFrame(paint);

    return () => {
      es.close();
      cancelAnimationFrame(rafId);
    };
  }, [sessionId]);

  const send = async (payload: object | string) => {
    setSending(true);
    setError(null);
    try {
      await sendInstruction(sessionId, payload);
      onInstructionSent?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't reach the agent.");
    } finally {
      setSending(false);
    }
  };

  const handleImageClick = (e: React.MouseEvent<HTMLImageElement>) => {
    if (!interactive || !imgRef.current) return;
    const rect = imgRef.current.getBoundingClientRect();
    const x = Math.round(((e.clientX - rect.left) / rect.width) * BROWSER_W);
    const y = Math.round(((e.clientY - rect.top) / rect.height) * BROWSER_H);
    send({ type: "click", x, y });
  };

  // The wheel over the screenshot scrolls the agent's page, not this one. React registers onWheel
  // as a passive listener, so its preventDefault() is ignored: use a native one.
  const sendRef = useRef(send);
  sendRef.current = send;
  const hasScreenshot = Boolean(screenshot);
  useEffect(() => {
    const img = imgRef.current;
    if (!interactive || !img) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      sendRef.current({ type: "scroll", delta: e.deltaY });
    };
    img.addEventListener("wheel", onWheel, { passive: false });
    return () => img.removeEventListener("wheel", onWheel);
  }, [interactive, hasScreenshot]);

  // Focus the input when the controls appear, without scrolling the page to it.
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (blocked) inputRef.current?.focus({ preventScroll: true });
  }, [blocked]);

  const sendText = () => {
    if (text.trim()) {
      send(text.trim());
      setText("");
    }
  };

  return (
    <BrowserFrame url={url} live={!!sessionId} footer={
      <div className="flex flex-col gap-[10px] px-[14px] py-[10px] border-t border-track">
        <div className="flex flex-wrap items-center gap-[14px] text-[12.5px] text-ink-2">
          <span className="flex items-center gap-[6px]">
            <span aria-hidden="true" className="w-3 h-3 rounded-[3px] border-[1.5px] border-teal-ok-line bg-teal-ok" />Filled by agent
          </span>
          <span className="flex items-center gap-[6px]">
            <span aria-hidden="true" className="w-3 h-3 rounded-[3px] border-[1.5px] border-amber bg-amber-wash-2" />Needs you
          </span>
          <span className="sm:ml-auto">{interactive ? "Click or type on the page to take over" : action}</span>
        </div>
        {blocked && (
          <div className="flex flex-col gap-2">
            {reason && !interactive && <p className="m-0 text-[13px] text-amber-ink">{reason}</p>}
            <div className="flex flex-wrap gap-2">
              <label htmlFor="browser-type" className="sr-only">
                {interactive ? "Type into the page" : "Instruction for the agent"}
              </label>
              <input id="browser-type" ref={inputRef} type="text" value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendText(); } }}
                placeholder={interactive ? "Type text into the focused field…" : "Tell the agent what to change…"}
                className="flex-[1_1_220px] min-w-0 h-[38px] px-3 border border-border-strong rounded-control bg-surface text-[13.5px] text-ink placeholder:text-ink-3 focus:outline-none focus:border-teal" />
              <button type="button" onClick={() => send({ type: "key", key: "Tab" })} disabled={!interactive || sending}
                className={buttonClass("secondary", "top", "px-3")} aria-label="Send the Tab key">Tab</button>
              <button type="button" onClick={() => send({ type: "key", key: "Enter" })} disabled={!interactive || sending}
                className={buttonClass("secondary", "top", "px-3")} aria-label="Send the Enter key">Enter</button>
              <button type="button" onClick={sendText} disabled={sending || !text.trim()} className={buttonClass("primary", "top")}>
                {sending ? <Spinner /> : "Send"}
              </button>
            </div>
            {error && <p role="alert" className="m-0 text-[12.5px] text-red">{error}</p>}
          </div>
        )}
      </div>
    }>
      {/* The live job site keeps its own colours in dark mode: it's a third-party page. */}
      <div className="flex-1 bg-[#F7F8FA] flex items-start justify-center">
        {screenshot ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            ref={imgRef}
            src={`data:image/jpeg;base64,${screenshot}`}
            alt={interactive ? "The application page. Click to click on it." : "The application page"}
            className={cx("w-full h-auto block", interactive && "cursor-crosshair select-none")}
            onClick={handleImageClick}
            draggable={false}
          />
        ) : (
          <div className="w-full min-h-[320px] flex flex-col items-center justify-center gap-2 text-[13px] text-[#4B5263]">
            <Spinner />
            {action || "Opening the application page…"}
          </div>
        )}
      </div>
    </BrowserFrame>
  );
}
