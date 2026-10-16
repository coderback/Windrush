import Icon from "./ui/Icon";

export function Wordmark({ size = 32 }: { size?: 30 | 32 }) {
  return (
    <span className="flex items-center gap-[10px]">
      <span className="rounded-[9px] bg-teal text-on-ink flex items-center justify-center shrink-0" style={{ width: size, height: size }}>
        <Icon name="wind" size={size === 32 ? 18 : 17} strokeWidth={2} />
      </span>
      <span className="text-[17px] font-[650] tracking-[-0.02em]">windrush</span>
    </span>
  );
}

/** Sign in and sign up: the form on the left, what Windrush does on the right. The right panel
    is an illustration, so it keeps its own colours in both themes. */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-wrap bg-surface text-ink">
      <section className="flex-[1_1_480px] min-w-0 box-border px-6 sm:px-[clamp(24px,6vw,96px)] py-10 flex flex-col gap-10">
        <Wordmark />
        <div className="flex-1 w-full max-w-[400px] self-center flex flex-col justify-center">{children}</div>
        <span className="text-[12.5px] text-ink-3">Your job-board password is encrypted at rest and never shown to the AI.</span>
      </section>
      <section aria-label="What Windrush does"
        className="hidden min-[900px]:flex flex-[1_1_480px] min-w-0 box-border m-[14px] rounded-[22px] bg-[#15171C] text-[#F5F5F2] p-[clamp(28px,5vw,64px)] flex-col justify-center gap-9 dark:border dark:border-border">
        <h2 className="m-0 text-[clamp(28px,3.2vw,42px)] font-semibold tracking-[-0.035em] leading-[1.1] max-w-[16ch] text-balance">
          Apply to more of the right jobs, with less of the busywork.
        </h2>
        <div className="flex flex-col gap-[10px] max-w-[460px]" aria-hidden="true">
          <div className="bg-white text-[#15171C] rounded-[14px] px-4 py-[14px] flex items-center gap-3 shadow-[0_12px_32px_rgba(0,0,0,0.25)]">
            <span className="relative inline-flex w-10 h-10 shrink-0">
              <svg width="40" height="40" viewBox="0 0 40 40"><circle cx="20" cy="20" r="16" fill="none" stroke="#EFEEEA" strokeWidth="4" />
                <circle cx="20" cy="20" r="16" fill="none" stroke="#0D6E66" strokeWidth="4" strokeLinecap="round" pathLength={100}
                  strokeDasharray="88 100" transform="rotate(-90 20 20)" /></svg>
              <span className="absolute inset-0 flex items-center justify-center font-mono text-[11px] font-semibold">88</span>
            </span>
            <span className="flex-1 flex flex-col gap-[2px]">
              <span className="text-[13.5px] font-semibold">Backend Engineer, Graduate</span>
              <span className="text-[12px] text-[#6B6E76]">Strong fit · licensed sponsor</span>
            </span>
          </div>
          <div className="bg-white text-[#15171C] rounded-[14px] px-4 py-[14px] flex items-center gap-3 ml-7 shadow-[0_12px_32px_rgba(0,0,0,0.25)]">
            <span className="w-2 h-2 rounded-full bg-[#D98E04] shrink-0" />
            <span className="flex-1 text-[13.5px] font-semibold">Form filled, paused before submit</span>
            <span className="h-[30px] px-3 rounded-[8px] bg-[#0D6E66] text-white text-[12.5px] font-medium flex items-center">Review</span>
          </div>
        </div>
        <ul className="m-0 p-0 list-none flex flex-col gap-[14px] text-[15px]">
          {["Finds roles that fit you, including visa sponsorship", "Tailors your CV and cover letter for each one",
            "Fills the form, and never submits without you"].map((t, i) => (
            <li key={t} className="flex gap-3 items-center">
              <span className="font-mono text-[12px] text-[#8CC7BD]">{String(i + 1).padStart(2, "0")}</span>{t}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
