import Link from "next/link";
import { fitColor, riskLevel, RISK, statusMeta } from "@/lib/status";
import { initials } from "@/lib/format";
import Icon, { type IconName } from "./Icon";

export const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");

/* ── Buttons ─────────────────────────────────────────────────────────── */

export type ButtonVariant = "primary" | "commit" | "secondary" | "quiet" | "destructive";
export type ButtonSize = "xs" | "sm" | "md" | "top" | "lg" | "xl";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-ink text-on-ink hover:opacity-90",
  commit: "bg-teal text-on-ink font-semibold hover:opacity-90",
  secondary: "border border-border bg-surface text-ink hover:bg-subtle",
  quiet: "bg-transparent text-ink-2 hover:bg-muted hover:text-ink",
  destructive: "bg-transparent text-red hover:bg-red-soft",
};

const SIZE: Record<ButtonSize, string> = {
  xs: "h-[30px] px-[10px] text-[12.5px] rounded-[8px]",
  sm: "h-[34px] px-3 text-[13px] rounded-[9px]",
  md: "h-10 px-4 text-[13.5px] rounded-control",
  top: "h-[38px] px-[14px] text-[13.5px] rounded-control",
  lg: "h-[42px] px-[18px] text-[14px] rounded-control",
  xl: "h-[44px] px-5 text-[14px] rounded-control",
};

export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md", extra?: string) {
  return cx(
    "inline-flex items-center justify-center gap-2 font-medium whitespace-nowrap transition-[background-color,opacity,color] select-none",
    "disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:opacity-50",
    VARIANT[variant], SIZE[size], extra,
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span aria-hidden="true"
      className={cx("inline-block w-[14px] h-[14px] rounded-full border-2 border-current border-t-transparent animate-spin", className)} />
  );
}

/* ── Surfaces ────────────────────────────────────────────────────────── */

export function Card({ as: Tag = "section", className, children, ...rest }: {
  as?: "section" | "div" | "article" | "aside" | "li";
  className?: string;
  children: React.ReactNode;
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <Tag className={cx("bg-surface border border-border rounded-card", className)} {...rest}>
      {children}
    </Tag>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden="true" className={cx("skeleton block", className)} />;
}

export function Callout({ tone = "error", title, children, className, action }: {
  tone?: "error" | "info" | "warn";
  title?: string;
  children?: React.ReactNode;
  className?: string;
  action?: React.ReactNode;
}) {
  const tones = {
    error: "bg-red-soft text-red",
    info: "bg-teal-soft text-teal-deep",
    warn: "bg-amber-wash-2 border border-amber-line-3 text-amber-ink",
  };
  return (
    <div role={tone === "error" ? "alert" : "status"}
      className={cx("flex gap-[10px] items-start rounded-[10px] px-[14px] py-3 text-[13px] leading-[1.5]", tones[tone], className)}>
      <Icon name={tone === "info" ? "shield" : "alert"} size={16} className="mt-[2px]" />
      <div className="flex-1 min-w-0 flex flex-col gap-1">
        {title && <span className={cx("font-semibold", tone === "warn" && "text-amber-ink-2")}>{title}</span>}
        {children && <span>{children}</span>}
        {action}
      </div>
    </div>
  );
}

export function EmptyState({ children, action, className }: {
  children: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("flex flex-col items-center justify-center gap-3 text-center px-4 py-8 border border-dashed border-border-strong rounded-inner text-[13.5px] text-ink-2", className)}>
      <p className="m-0 max-w-[48ch]">{children}</p>
      {action}
    </div>
  );
}

/* ── Chips ───────────────────────────────────────────────────────────── */

export type ChipTone = "neutral" | "positive" | "matched" | "gap" | "warn" | "danger" | "info" | "violet" | "outline";

const CHIP_TONE: Record<ChipTone, string> = {
  neutral: "bg-muted text-ink-2",
  positive: "bg-teal-chip text-teal-deep",
  matched: "bg-teal-soft text-teal-deep",
  gap: "border border-dashed border-amber-dash text-amber-text",
  warn: "bg-amber-soft text-amber-text",
  danger: "bg-red-soft text-red",
  info: "bg-blue-soft text-blue-text",
  violet: "bg-violet-soft text-violet-text",
  outline: "border border-border bg-surface text-ink-2",
};

const CHIP_SIZE = {
  sm: "h-[22px] px-2 text-[11.5px]",
  md: "h-6 px-[9px] text-[12px]",
  lg: "h-[26px] px-[10px] text-[12.5px]",
};

export function Chip({ tone = "neutral", size = "md", title, className, children }: {
  tone?: ChipTone;
  size?: keyof typeof CHIP_SIZE;
  title?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span title={title}
      className={cx("inline-flex items-center gap-[6px] rounded-full font-medium whitespace-nowrap", CHIP_TONE[tone], CHIP_SIZE[size], className)}>
      {children}
    </span>
  );
}

export function Dot({ className }: { className: string }) {
  return <span aria-hidden="true" className={cx("inline-block w-[7px] h-[7px] rounded-full shrink-0", className)} />;
}

export function StatusChip({ status, size = "md" }: { status: string; size?: keyof typeof CHIP_SIZE }) {
  const m = statusMeta(status);
  return (
    <span className={cx("inline-flex items-center gap-[6px] rounded-full font-medium whitespace-nowrap", m.chip, CHIP_SIZE[size])}>
      <Dot className={m.dot} />
      {m.label}
    </span>
  );
}

/* ── Figures ─────────────────────────────────────────────────────────── */

/** Fit / match ring. The number is an HTML span over the SVG so it takes the font and theme. */
export function FitRing({ value, size = 42, label = "Fit" }: { value: number; size?: number; label?: "Fit" | "Match" }) {
  const v = Math.max(0, Math.min(100, Math.round(value)));
  const stroke = size >= 60 ? 6 : 4;
  const r = size / 2 - stroke;
  const font = size >= 72 ? 19 : size >= 64 ? 17 : size >= 42 ? 12 : 11;
  return (
    <span role="img" aria-label={`${label} ${v} of 100`} className="relative inline-flex shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--track)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={fitColor(v)} strokeWidth={stroke}
          strokeLinecap="round" pathLength={100} strokeDasharray={`${v} 100`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      </svg>
      <span aria-hidden="true" className="absolute inset-0 flex items-center justify-center font-mono font-semibold text-ink"
        style={{ fontSize: font }}>{v}</span>
    </span>
  );
}

export function RiskBar({ label, score, className }: { label: React.ReactNode; score: number; className?: string }) {
  const level = riskLevel(score);
  return (
    <div className={cx("flex flex-col gap-[6px]", className)}>
      <span className="flex justify-between gap-3 text-[13px]">
        <span className="min-w-0 truncate">{label}</span>
        <span className={cx("font-mono text-[12px] font-semibold shrink-0", RISK[level].text)}>{score} · {level}</span>
      </span>
      <Bar value={score} className={RISK[level].bar} />
    </div>
  );
}

export function Bar({ value, className, height = 6, track = "bg-track" }: {
  value: number; className: string; height?: number; track?: string;
}) {
  return (
    <span aria-hidden="true" className={cx("block rounded-full overflow-hidden", track)} style={{ height }}>
      <span className={cx("block h-full rounded-full", className)} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </span>
  );
}

const MARK_TINTS = [
  "bg-teal-logo text-teal",
  "bg-blue-soft text-blue-text",
  "bg-violet-soft text-violet-text",
  "bg-amber-soft text-amber-text",
];

function hash(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

const MARK_SIZE: Record<number, { r: number; f: number }> = {
  22: { r: 6, f: 9.5 }, 24: { r: 7, f: 10.5 }, 34: { r: 9, f: 11.5 }, 36: { r: 9, f: 12.5 },
  40: { r: 10, f: 13 }, 44: { r: 11, f: 14 }, 48: { r: 12, f: 15 }, 56: { r: 14, f: 17 },
};

/** Company initials in a rounded square, tinted by a hash of the name. */
export function CompanyMark({ name, size = 40 }: { name: string; size?: keyof typeof MARK_SIZE | number }) {
  const s = MARK_SIZE[size] ?? { r: Math.round(size / 4), f: Math.round(size / 3) };
  return (
    <span aria-hidden="true"
      className={cx("inline-flex items-center justify-center font-semibold shrink-0", MARK_TINTS[hash(name || "") % MARK_TINTS.length])}
      style={{ width: size, height: size, borderRadius: s.r, fontSize: s.f }}>
      {initials(name)}
    </span>
  );
}

export type Tint = "mint" | "sky" | "peach" | "lilac" | "sand";
const TINT: Record<Tint, string> = {
  mint: "bg-tint-mint", sky: "bg-tint-sky", peach: "bg-tint-peach", lilac: "bg-tint-lilac", sand: "bg-tint-sand",
};

export function FactTile({ label, value, note, tint, large }: {
  label: string; value: React.ReactNode; note?: React.ReactNode; tint: Tint; large?: boolean;
}) {
  return (
    <div className={cx("flex flex-col min-w-0", TINT[tint], large ? "px-4 py-[14px] rounded-[14px] gap-[6px]" : "px-[14px] py-3 rounded-inner gap-1")}>
      <span className={cx("text-ink-2", large ? "text-[12px]" : "text-[11.5px]")}>{label}</span>
      <span className={cx("font-semibold text-ink break-words", large ? "text-[17px] tracking-[-0.01em]" : "text-[15px]")}>{value}</span>
      {note && <span className="text-[12px] text-ink-2">{note}</span>}
    </div>
  );
}

export function DateTile({ date, tint = "sky", size = 46, onTeal }: { date: Date; tint?: Tint; size?: 46 | 52; onTeal?: boolean }) {
  return (
    <span aria-hidden="true"
      className={cx("flex flex-col items-center justify-center gap-px shrink-0 rounded-inner", onTeal ? "bg-surface text-ink" : TINT[tint])}
      style={{ width: size, height: size }}>
      <span className={cx("font-mono font-semibold leading-none", size === 52 ? "text-[18px]" : "text-[16px]")}>{date.getDate()}</span>
      <span className={cx("text-ink-2", size === 52 ? "text-[11px]" : "text-[10.5px]")}>
        {date.toLocaleDateString("en-GB", { weekday: "short" })}
      </span>
    </span>
  );
}

/* ── Form bits ───────────────────────────────────────────────────────── */

export const inputClass =
  "h-10 px-3 border border-border-strong rounded-control bg-surface text-[14px] text-ink placeholder:text-ink-3 " +
  "focus:outline-none focus:border-teal focus-visible:outline-none w-full min-w-0";

export const textareaClass =
  "px-3 py-[10px] border border-border-strong rounded-control bg-surface text-[13.5px] leading-[1.5] text-ink " +
  "placeholder:text-ink-3 focus:outline-none focus:border-teal focus-visible:outline-none w-full min-w-0 resize-y";

export const labelClass = "text-[12.5px] font-semibold text-ink-2";

export function Switch({ checked, onChange, label, disabled }: {
  checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean;
}) {
  return (
    <button type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
      className={cx(buttonClass("secondary", "sm"), "gap-2 px-[10px] text-[12.5px] font-normal")}>
      <span aria-hidden="true" className={cx("relative block w-7 h-4 rounded-full transition-colors", checked ? "bg-teal" : "bg-border-strong")}>
        <span className="absolute top-[2px] w-3 h-3 rounded-full bg-surface transition-[left]" style={{ left: checked ? 14 : 2 }} />
      </span>
      {label}
    </button>
  );
}

/* ── Links ───────────────────────────────────────────────────────────── */

export function TextLink({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) {
  return (
    <Link href={href} className={cx("whitespace-nowrap text-teal text-[13.5px] font-medium hover:text-teal-deep hover:underline underline-offset-2", className)}>
      {children}
    </Link>
  );
}

export function IconButton({ icon, label, onClick, className, size = 38, disabled }: {
  icon: IconName; label: string; onClick?: () => void; className?: string; size?: number; disabled?: boolean;
}) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} disabled={disabled}
      className={cx("inline-flex items-center justify-center rounded-control border border-border bg-surface text-ink-2 hover:bg-subtle hover:text-ink disabled:opacity-50 shrink-0", className)}
      style={{ width: size, height: size }}>
      <Icon name={icon} size={17} />
    </button>
  );
}

export function SectionTitle({ id, children, className }: { id?: string; children: React.ReactNode; className?: string }) {
  return <h2 id={id} className={cx("m-0 text-[15.5px] font-semibold", className)}>{children}</h2>;
}
