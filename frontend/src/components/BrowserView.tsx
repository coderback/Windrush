"use client";

import { useRef, useState, useEffect } from "react";

interface Props {
  action: string;
  screenshot: string | null;
  blocked: boolean;
  reason: string | null;
  sessionId: string;
  interactive?: boolean;
  onInstructionSent?: () => void;
}

const BROWSER_W = 1280;
const BROWSER_H = 800;

export default function BrowserView({
  action,
  screenshot,
  blocked,
  reason,
  sessionId,
  interactive,
  onInstructionSent,
}: Props) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [liveFrame, setLiveFrame] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  // Open a separate SSE connection for live CDP screencast frames
  useEffect(() => {
    if (!sessionId) return;
    const es = new EventSource(`/api/browser-stream/${sessionId}`);
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.frame) setLiveFrame(data.frame);
        if (data.type === "close") es.close();
      } catch {}
    };
    return () => es.close();
  }, [sessionId]);

  const send = async (payload: object | string) => {
    const instruction = typeof payload === "string" ? payload : JSON.stringify(payload);
    setSending(true);
    try {
      await fetch(`/api/browser-input/${sessionId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction }),
      });
      onInstructionSent?.();
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

  const handleImageScroll = (e: React.WheelEvent<HTMLImageElement>) => {
    if (!interactive) return;
    e.preventDefault();
    send({ type: "scroll", delta: e.deltaY });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (text.trim()) {
        send(text.trim());
        setText("");
      }
    }
  };

  return (
    <div className="fixed inset-0 bg-black/92 backdrop-blur-sm z-50 flex flex-col items-center justify-center p-4 gap-3">
      {/* Header */}
      <div className="w-full max-w-5xl flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          {!blocked ? (
            <span className="w-2 h-2 rounded-full bg-teal-400 animate-pulse" />
          ) : (
            <span className="w-2 h-2 rounded-full bg-amber-400" />
          )}
          <span className="text-xs uppercase tracking-widest font-semibold text-zinc-400">
            {interactive ? "You have control" : blocked ? "Waiting for input" : "Browser automation"}
          </span>
        </div>
        <span className="text-xs text-zinc-500 max-w-[60%] truncate">{action}</span>
      </div>

      {/* Screenshot */}
      <div className="w-full max-w-5xl border border-zinc-700 rounded-lg overflow-hidden bg-zinc-900 shrink-0">
        {(liveFrame || screenshot) ? (
          <img
            ref={imgRef}
            src={liveFrame ? `data:image/jpeg;base64,${liveFrame}` : `data:image/png;base64,${screenshot}`}
            alt="Browser view"
            className={`w-full h-auto block ${interactive ? "cursor-crosshair select-none" : ""}`}
            onClick={handleImageClick}
            onWheel={handleImageScroll}
            draggable={false}
          />
        ) : (
          <div className="h-52 flex items-center justify-center text-zinc-600 text-sm">
            {blocked ? "Waiting…" : "Loading page…"}
          </div>
        )}
      </div>

      {/* Controls */}
      {blocked && (
        <div className="w-full max-w-5xl space-y-2 shrink-0">
          {reason && !interactive && (
            <div className="text-sm text-amber-300 border border-amber-500/30 rounded-lg px-4 py-2.5 bg-amber-500/5">
              {reason}
            </div>
          )}

          <div className="flex gap-2">
            <input
              type="text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                interactive
                  ? 'Type text to send to browser, or "submit" / "skip"…'
                  : 'Type an instruction, "submit" to confirm, or "skip" to cancel…'
              }
              autoFocus
              className="flex-1 bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-teal-500 transition-colors"
            />
            <button
              onClick={() => send({ type: "key", key: "Tab" })}
              disabled={!interactive || sending}
              title="Send Tab key"
              className="px-3 py-2 text-xs text-zinc-400 border border-zinc-700 rounded-lg hover:border-zinc-500 disabled:opacity-30 transition-colors"
            >
              Tab
            </button>
            <button
              onClick={() => send({ type: "key", key: "Enter" })}
              disabled={!interactive || sending}
              title="Send Enter key"
              className="px-3 py-2 text-xs text-zinc-400 border border-zinc-700 rounded-lg hover:border-zinc-500 disabled:opacity-30 transition-colors"
            >
              ↵
            </button>
            <button
              onClick={() => { if (text.trim()) { send(text.trim()); setText(""); } }}
              disabled={sending || !text.trim()}
              className="px-4 py-2 text-sm font-semibold text-white bg-teal-600 hover:bg-teal-500 rounded-lg transition-colors disabled:opacity-40"
            >
              {sending ? "…" : "Send"}
            </button>
            <button
              onClick={() => send("skip")}
              disabled={sending}
              className="px-4 py-2 text-sm text-zinc-400 border border-zinc-700 hover:border-zinc-500 rounded-lg transition-colors disabled:opacity-40"
            >
              Skip
            </button>
          </div>

          {interactive && (
            <p className="text-xs text-zinc-600">
              Click the screenshot to click · scroll to scroll · type in the box to type · Tab / ↵ to send keys
            </p>
          )}
        </div>
      )}

      {!blocked && (
        <p className="text-xs text-zinc-600 shrink-0">
          Automating — screenshots update as the agent works
        </p>
      )}
    </div>
  );
}
