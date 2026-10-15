"use client";

import { useEffect, useRef } from "react";
import Icon from "./Icon";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** A 440px panel from the right with a scrim. Esc and the close button dismiss it, focus is
    trapped inside while it is open, and focus goes back to what opened it on close. */
export default function SlideOver({ open, onClose, label, header, footer, children }: {
  open: boolean;
  onClose: () => void;
  label: string;
  header: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement as HTMLElement | null;
    const first = panel.current?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab" || !panel.current) return;
      const items = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) return;
      const firstEl = items[0], lastEl = items[items.length - 1];
      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      opener.current?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0" style={{ background: "var(--scrim)" }} onClick={onClose} aria-hidden="true" />
      <div ref={panel} role="dialog" aria-modal="true" aria-label={label}
        className="absolute top-0 right-0 bottom-0 w-full max-w-[440px] bg-surface border-l border-border shadow-slideover flex flex-col overflow-y-auto">
        <div className="flex gap-3 items-start px-5 pt-5 pb-4 border-b border-track">
          <div className="flex-1 min-w-0">{header}</div>
          <button type="button" aria-label="Close" onClick={onClose}
            className="w-[34px] h-[34px] border border-border rounded-[9px] bg-surface text-ink-2 hover:text-ink flex items-center justify-center shrink-0">
            <Icon name="close" size={15} strokeWidth={2} />
          </button>
        </div>
        <div className="px-5 py-[18px] flex flex-col gap-[18px]">{children}</div>
        {footer && <div className="mt-auto flex gap-2 px-5 py-[14px] border-t border-track bg-subtle">{footer}</div>}
      </div>
    </div>
  );
}
