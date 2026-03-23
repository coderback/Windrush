"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  onStart: (file?: File) => void;
  uploading?: boolean;
  error?: string | null;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function useInView(threshold = 0.15) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { setVisible(true); obs.disconnect(); } },
      { threshold }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [threshold]);
  return { ref, visible };
}

const mono: React.CSSProperties = { fontFamily: "'IBM Plex Mono', monospace" };
const serif: React.CSSProperties = { fontFamily: "'Playfair Display', serif" };

// ── Sub-components ────────────────────────────────────────────────────────────

function FadeSection({ children, className, style }: {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}) {
  const { ref, visible } = useInView();
  return (
    <div
      ref={ref}
      className={className}
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? "translateY(0)" : "translateY(18px)",
        transition: "opacity 0.7s ease, transform 0.7s ease",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function UploadButton({ onStart, uploading }: { onStart: (f?: File) => void; uploading?: boolean }) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf"
        className="hidden"
        disabled={uploading}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onStart(f); }}
      />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={uploading}
        style={{
          ...mono,
          fontSize: "0.8rem",
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          background: uploading ? "#115e59" : "#2dd4bf",
          color: uploading ? "#5eead4" : "#0a0a0a",
          border: "none",
          padding: "0.75rem 1.75rem",
          cursor: uploading ? "default" : "pointer",
          fontWeight: 600,
          transition: "background 0.2s",
          opacity: uploading ? 0.7 : 1,
        }}
        onMouseEnter={(e) => { if (!uploading) e.currentTarget.style.background = "#5eead4"; }}
        onMouseLeave={(e) => { if (!uploading) e.currentTarget.style.background = "#2dd4bf"; }}
      >
        {uploading ? "Uploading…" : "Upload your CV →"}
      </button>
    </>
  );
}

function DropZoneLarge({ onStart }: { onStart: (f?: File) => void }) {
  const [over, setOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault(); setOver(false);
        const f = e.dataTransfer.files[0];
        if (f?.type === "application/pdf") onStart(f);
      }}
      onClick={() => inputRef.current?.click()}
      style={{
        border: `1px solid ${over ? "#2dd4bf" : "rgba(45,212,191,0.25)"}`,
        background: over ? "rgba(45,212,191,0.05)" : "transparent",
        padding: "2.5rem 5rem",
        cursor: "pointer",
        transition: "border-color 0.2s, background 0.2s",
        display: "inline-block",
        textAlign: "center",
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf"
        className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onStart(f); }}
      />
      <p style={{ ...mono, fontSize: "0.85rem", color: "#a1a1aa", marginBottom: "0.3rem" }}>
        Drop your CV PDF here
      </p>
      <p style={{ ...mono, fontSize: "0.7rem", color: "#52525b", letterSpacing: "0.06em" }}>
        or click to browse · PDF only
      </p>
    </div>
  );
}

const SKILLS = [
  { name: "Machine Learning", pct: 82, high: true },
  { name: "Data Analysis",    pct: 80, high: true },
  { name: "Python",           pct: 78, high: true },
  { name: "Systems Design",   pct: 38, high: false },
  { name: "Technical Leadership", pct: 28, high: false },
];

function RiskBars() {
  const { ref, visible } = useInView(0.2);
  const [counts, setCounts] = useState(SKILLS.map(() => 0));

  useEffect(() => {
    if (!visible) return;
    const timers = SKILLS.map((s, i) =>
      setTimeout(() => {
        let frame = 0;
        const total = 36;
        const tick = setInterval(() => {
          frame++;
          setCounts((prev) => {
            const next = [...prev];
            next[i] = Math.round((s.pct * frame) / total);
            return next;
          });
          if (frame >= total) clearInterval(tick);
        }, 22);
      }, i * 100)
    );
    return () => timers.forEach(clearTimeout);
  }, [visible]);

  return (
    <div ref={ref} style={{ display: "flex", flexDirection: "column", gap: "1.4rem" }}>
      {SKILLS.map((s, i) => (
        <div key={s.name}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.45rem" }}>
            <span style={{ ...mono, fontSize: "0.75rem", color: "#71717a" }}>{s.name}</span>
            <span style={{ ...mono, fontSize: "0.75rem", color: s.high ? "#f59e0b" : "#2dd4bf", minWidth: "3ch", textAlign: "right" }}>
              {visible ? counts[i] : 0}%
            </span>
          </div>
          <div style={{ height: "2px", background: "#18181b", overflow: "hidden" }}>
            <div style={{
              height: "100%",
              width: visible ? `${s.pct}%` : "0%",
              background: s.high ? "linear-gradient(90deg,#92400e,#f59e0b)" : "linear-gradient(90deg,#0f766e,#2dd4bf)",
              transition: `width 0.75s cubic-bezier(0.16,1,0.3,1) ${i * 100}ms`,
            }} />
          </div>
        </div>
      ))}
    </div>
  );
}

const FEATURES = [
  {
    title: "AI Risk Scoring",
    desc: "Every skill on your CV is scored against O*NET labour data and AI task-penetration research. You see exactly which parts of your career are most at risk.",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      </svg>
    ),
  },
  {
    title: "Safer Job Matching",
    desc: "Live job listings ranked so the roles where your skills are least replaceable appear first. You're not just finding any job — you're finding a better one.",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/>
        <line x1="6" y1="20" x2="6" y2="14"/>
      </svg>
    ),
  },
  {
    title: "Autonomous Application",
    desc: "A browser agent opens the application page, fills every field, uploads your CV, and pastes the cover letter. You review it, then decide whether to submit.",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="3" width="20" height="14" rx="0"/><line x1="8" y1="21" x2="16" y2="21"/>
        <line x1="12" y1="17" x2="12" y2="21"/>
      </svg>
    ),
  },
];

const STEPS = [
  {
    n: "01", title: "Upload your CV",
    desc: "Drop a PDF. Nothing to fill out, no account to create. Windrush reads your skills, experience, and background automatically.",
    visual: [`┌─────────────────┐`, `│  CV.pdf         │`, `│                 │`, `│  ↑ uploading    │`, `└─────────────────┘`],
  },
  {
    n: "02", title: "See your exposure",
    desc: "Every skill is scored against real O*NET data and AI research. The teal bars are safer. The amber ones need your attention.",
    visual: [`Python       ████████ 78%`, `SQL          ███████  72%`, `Leadership   ██       28%`, `Sys Design   ████     38%`],
  },
  {
    n: "03", title: "Find safer jobs",
    desc: "Live job listings scored by two factors: how automatable the role is, and how well your skills match. The ones at the top are safer bets.",
    visual: [`◆ 0.82  ML Engineer`, `◆ 0.74  Platform Eng`, `◆ 0.68  Backend Dev`, `◆ 0.61  Data Engineer`],
  },
  {
    n: "04", title: "Get a roadmap",
    desc: "Six concrete skill recommendations — specific courses, projects, certifications — tailored to your background and target role.",
    visual: [`→ 01  MLOps (3 months)`, `→ 02  Rust systems (6mo)`, `→ 03  Distributed DB`, `→ 04  LLM evaluation`],
  },
  {
    n: "05", title: "Apply automatically",
    desc: "The agent opens the application, fills every field, uploads your CV, and pastes the cover letter. You review the completed form and submit.",
    visual: [`[Full name  ___________]`, `[Email     ___________]`, `[Cover letter  ↓ ...]  `, `[ Submit application ] `],
  },
];

// ── Main component ────────────────────────────────────────────────────────────

export default function Landing({ onStart, uploading, error }: Props) {
  const [heroOver, setHeroOver] = useState(false);

  return (
    <>
      <style>{`
        @keyframes fu { from { opacity:0; transform:translateY(16px); } to { opacity:1; transform:translateY(0); } }
        .fu  { animation: fu 0.8s cubic-bezier(0.16,1,0.3,1) both; }
        .d1  { animation-delay:0.05s; } .d2 { animation-delay:0.18s; }
        .d3  { animation-delay:0.3s;  } .d4 { animation-delay:0.44s; }
        .d5  { animation-delay:0.58s; }
      `}</style>

      <div
        style={{ background: "#0a0a0a", color: "#e4e4e7", minHeight: "100vh", overflowX: "hidden" }}
        onDragOver={(e) => { e.preventDefault(); setHeroOver(true); }}
        onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setHeroOver(false); }}
        onDrop={(e) => {
          e.preventDefault(); setHeroOver(false);
          if (uploading) return;
          const f = e.dataTransfer.files[0];
          if (f?.type === "application/pdf") onStart(f);
        }}
      >
        {heroOver && (
          <div style={{
            position: "fixed", inset: 0, zIndex: 100,
            border: "1px solid #2dd4bf", background: "rgba(45,212,191,0.03)",
            display: "flex", alignItems: "center", justifyContent: "center",
            pointerEvents: "none",
          }}>
            <p style={{ ...serif, fontSize: "1.6rem", color: "#2dd4bf" }}>Drop to begin</p>
          </div>
        )}

        {/* ── NAV ── */}
        <nav style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          padding: "1.25rem 2.5rem", borderBottom: "1px solid #18181b",
          position: "sticky", top: 0, zIndex: 50,
          background: "rgba(10,10,10,0.9)", backdropFilter: "blur(8px)",
        }}>
          <span style={{ ...serif, fontSize: "1.1rem", fontWeight: 700, color: "#e4e4e7" }}>Windrush</span>
          <button
            onClick={() => onStart()}
            style={{
              ...mono, fontSize: "0.7rem", letterSpacing: "0.12em", textTransform: "uppercase",
              color: "#2dd4bf", background: "none", border: "none", cursor: "pointer",
              padding: 0,
            }}
          >
            Open App →
          </button>
        </nav>

        {/* ── HERO ── */}
        <section style={{
          maxWidth: "1100px", margin: "0 auto",
          padding: "7rem 2.5rem 6rem",
          position: "relative",
        }}>
          {/* soft glow */}
          <div aria-hidden style={{
            position: "absolute", top: "20%", left: "50%", transform: "translateX(-50%)",
            width: "600px", height: "400px", pointerEvents: "none",
            background: "radial-gradient(ellipse at center, rgba(45,212,191,0.07) 0%, transparent 70%)",
          }} />

          <p className="fu d1" style={{ ...mono, fontSize: "0.65rem", color: "#52525b", letterSpacing: "0.2em", textTransform: "uppercase", marginBottom: "2rem" }}>
            AI-Powered Career Intelligence
          </p>

          <h1 className="fu d2" style={{ ...serif, fontSize: "clamp(2.4rem, 5vw, 4.2rem)", fontWeight: 700, lineHeight: 1.15, color: "#f4f4f5", marginBottom: "1.75rem", maxWidth: "18ch" }}>
            Know your risk.<br />
            Find safer work.<br />
            <span style={{ color: "#2dd4bf" }}>Apply automatically.</span>
          </h1>

          <p className="fu d3" style={{ ...mono, fontSize: "0.85rem", color: "#71717a", lineHeight: 1.8, maxWidth: "52ch", marginBottom: "2.5rem" }}>
            Windrush analyses your CV against AI displacement research, finds jobs
            ranked by how hard they are to automate, and applies for them on your behalf.
          </p>

          <div className="fu d4" style={{ display: "flex", gap: "1.25rem", alignItems: "center", flexWrap: "wrap" }}>
            <UploadButton onStart={onStart} uploading={uploading} />
            <a href="#how-it-works" style={{ ...mono, fontSize: "0.7rem", color: "#52525b", letterSpacing: "0.1em", textDecoration: "none", textTransform: "uppercase" }}>
              How it works ↓
            </a>
          </div>
          {error && (
            <p className="fu d5" style={{ ...mono, fontSize: "0.72rem", color: "#ef4444", marginTop: "1rem" }}>
              {error}
            </p>
          )}
        </section>

        {/* ── FEATURES ── */}
        <section style={{ borderTop: "1px solid #18181b", borderBottom: "1px solid #18181b" }}>
          <div style={{ maxWidth: "1100px", margin: "0 auto", display: "grid", gridTemplateColumns: "repeat(3,1fr)" }}>
            {FEATURES.map((f, i) => (
              <FadeSection
                key={f.title}
                style={{
                  padding: "2.75rem 2.5rem",
                  borderRight: i < 2 ? "1px solid #18181b" : "none",
                }}
              >
                <div style={{ color: "#3f3f46", marginBottom: "1.1rem" }}>{f.icon}</div>
                <h3 style={{ ...serif, fontSize: "1.05rem", fontWeight: 700, color: "#e4e4e7", marginBottom: "0.75rem" }}>{f.title}</h3>
                <p style={{ ...mono, fontSize: "0.75rem", color: "#71717a", lineHeight: 1.75 }}>{f.desc}</p>
              </FadeSection>
            ))}
          </div>
        </section>

        {/* ── RISK BARS ── */}
        <section style={{ maxWidth: "1100px", margin: "0 auto", padding: "6rem 2.5rem" }}>
          <FadeSection style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "5rem", alignItems: "center" }}>
            <div>
              <p style={{ ...mono, fontSize: "0.65rem", color: "#52525b", letterSpacing: "0.15em", textTransform: "uppercase", marginBottom: "1.25rem" }}>
                Example · Software Engineer
              </p>
              <RiskBars />
              <div style={{ marginTop: "1.5rem", display: "flex", gap: "1.5rem" }}>
                <span style={{ ...mono, fontSize: "0.65rem", color: "#2dd4bf", display: "flex", alignItems: "center", gap: "0.4rem" }}>
                  <span style={{ display: "inline-block", width: 8, height: 8, background: "#2dd4bf" }} /> Lower risk
                </span>
                <span style={{ ...mono, fontSize: "0.65rem", color: "#f59e0b", display: "flex", alignItems: "center", gap: "0.4rem" }}>
                  <span style={{ display: "inline-block", width: 8, height: 8, background: "#f59e0b" }} /> Higher risk
                </span>
              </div>
            </div>
            <div>
              <h2 style={{ ...serif, fontSize: "clamp(1.5rem, 2.5vw, 2rem)", fontWeight: 700, color: "#f4f4f5", lineHeight: 1.3, marginBottom: "1rem" }}>
                Your skills, honestly scored.
              </h2>
              <p style={{ ...mono, fontSize: "0.78rem", color: "#71717a", lineHeight: 1.8, marginBottom: "1rem" }}>
                Four-tier scoring cascade: keyword search across O*NET task descriptions → TF-IDF semantic matching → occupation word-overlap → research baseline.
              </p>
              <p style={{ ...mono, fontSize: "0.78rem", color: "#71717a", lineHeight: 1.8 }}>
                Your actual CV will produce its own scores. The teal bars are safer. The amber ones need a plan.
              </p>
            </div>
          </FadeSection>
        </section>

        {/* ── HOW IT WORKS ── */}
        <section id="how-it-works" style={{ borderTop: "1px solid #18181b" }}>
          <div style={{ maxWidth: "1100px", margin: "0 auto", padding: "6rem 2.5rem" }}>
            <FadeSection style={{ marginBottom: "4rem" }}>
              <p style={{ ...mono, fontSize: "0.65rem", color: "#52525b", letterSpacing: "0.15em", textTransform: "uppercase", marginBottom: "0.75rem" }}>
                How it works
              </p>
              <h2 style={{ ...serif, fontSize: "clamp(1.5rem, 3vw, 2.2rem)", fontWeight: 700, color: "#f4f4f5" }}>
                From CV to application in five steps.
              </h2>
            </FadeSection>

            <div style={{ display: "flex", flexDirection: "column" }}>
              {STEPS.map((step, i) => {
                const odd = i % 2 === 1;
                return (
                  <FadeSection
                    key={step.n}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: "4rem",
                      alignItems: "center",
                      padding: "3.5rem 0",
                      borderTop: i > 0 ? "1px solid #18181b" : "none",
                      direction: odd ? "rtl" : "ltr",
                    }}
                  >
                    <div style={{ direction: "ltr" }}>
                      <p style={{ ...mono, fontSize: "0.65rem", color: "#52525b", letterSpacing: "0.12em", marginBottom: "0.75rem" }}>
                        {step.n}
                      </p>
                      <h3 style={{ ...serif, fontSize: "1.25rem", fontWeight: 700, color: "#f4f4f5", marginBottom: "0.75rem" }}>
                        {step.title}
                      </h3>
                      <p style={{ ...mono, fontSize: "0.78rem", color: "#71717a", lineHeight: 1.8 }}>
                        {step.desc}
                      </p>
                    </div>
                    <div style={{ direction: "ltr" }}>
                      <pre style={{
                        ...mono,
                        fontSize: "0.75rem",
                        color: "#3f3f46",
                        lineHeight: 1.9,
                        margin: 0,
                        padding: "1.5rem",
                        border: "1px solid #18181b",
                        background: "#0d0d0d",
                        overflowX: "auto",
                      }}>
                        {step.visual.join("\n")}
                      </pre>
                    </div>
                  </FadeSection>
                );
              })}
            </div>
          </div>
        </section>

        {/* ── INSIGHT ── */}
        <section style={{ borderTop: "1px solid #18181b", borderBottom: "1px solid #18181b" }}>
          <FadeSection style={{ maxWidth: "700px", margin: "0 auto", padding: "6rem 2.5rem", textAlign: "center" }}>
            <p style={{ ...serif, fontSize: "clamp(1.3rem, 2.5vw, 1.9rem)", fontWeight: 400, fontStyle: "italic", color: "#a1a1aa", lineHeight: 1.5, marginBottom: "1.5rem" }}>
              "Most tools find you more work.<br />Windrush finds you safer work."
            </p>
            <p style={{ ...mono, fontSize: "0.72rem", color: "#52525b", lineHeight: 1.7 }}>
              Composite score = (1 − AI exposure) × 0.5 + skill-match fit × 0.5.<br />
              Jobs that resist automation and match your background rank highest.
            </p>
          </FadeSection>
        </section>

        {/* ── THE NAME ── */}
        <section style={{ maxWidth: "680px", margin: "0 auto", padding: "7rem 2.5rem" }}>
          <FadeSection>
            <p style={{ ...mono, fontSize: "0.65rem", color: "#52525b", letterSpacing: "0.15em", textTransform: "uppercase", marginBottom: "1.5rem" }}>
              The name
            </p>
            <p style={{ ...serif, fontSize: "1.1rem", fontWeight: 400, fontStyle: "italic", color: "#71717a", lineHeight: 1.85 }}>
              The Windrush Generation came to Britain in an era of upheaval — navigating uncertainty, building new lives, adapting to a world that was shifting under their feet. The AI transition is this generation&apos;s version of that moment. The tools look different. The stakes feel the same. Windrush helps you move.
            </p>
          </FadeSection>
        </section>

        {/* ── CLOSING CTA ── */}
        <section style={{ borderTop: "1px solid #18181b", padding: "7rem 2.5rem", textAlign: "center" }}>
          <FadeSection>
            <h2 style={{ ...serif, fontSize: "clamp(1.8rem, 4vw, 2.8rem)", fontWeight: 700, color: "#f4f4f5", marginBottom: "0.75rem", lineHeight: 1.2 }}>
              From CV to application<br />in two minutes.
            </h2>
            <p style={{ ...mono, fontSize: "0.75rem", color: "#52525b", letterSpacing: "0.08em", marginBottom: "3rem", textTransform: "uppercase" }}>
              No account · No credit card
            </p>
            <DropZoneLarge onStart={onStart} />
          </FadeSection>
        </section>

        {/* ── FOOTER ── */}
        <footer style={{
          borderTop: "1px solid #18181b", padding: "1.5rem 2.5rem",
          display: "flex", justifyContent: "space-between", alignItems: "center",
          maxWidth: "1100px", margin: "0 auto",
        }}>
          <span style={{ ...serif, fontSize: "0.85rem", color: "#3f3f46" }}>Windrush</span>
          <span style={{ ...mono, fontSize: "0.65rem", color: "#27272a", letterSpacing: "0.05em" }}>
            Claude · Anthropic SDK · browser-use · Civic Guardrails
          </span>
        </footer>
      </div>
    </>
  );
}
