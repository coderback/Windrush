import Link from "next/link";
import { DEMO_MODE, GITHUB_URL, SAMPLE_CV_TEXT } from "@/lib/demo";

export function DemoBanner() {
  if (!DEMO_MODE) return null;
  return (
    <div role="note" className="bg-amber-chip text-amber-text border-b border-border px-4 py-2 text-[13px] leading-[1.5]">
      <strong className="font-semibold">Read-only demo with fictional sample data.</strong>{" "}
      No backend, LLM calls or browser agent. It cannot submit applications or store credentials.{" "}
      <a href={GITHUB_URL} className="underline underline-offset-2">Source on GitHub</a>
    </div>
  );
}

function Box({ children }: { children: React.ReactNode }) {
  return <div className="rounded-card border border-border bg-subtle px-4 py-3 text-[13px] leading-[1.55] text-ink-2">{children}</div>;
}

/** What the project is and the order to look at it in, on the demo's home page. */
export function DemoIntro() {
  if (!DEMO_MODE) return null;
  const steps = [
    { href: "/profile", label: "1. CV parsing result", body: "A fictional CV turned into a structured persona." },
    { href: "/careers", label: "2. Skill-by-skill AI exposure", body: "Scores from the project's real lookup against the Economic Index and O*NET tasks." },
    { href: "/jobs", label: "3. Ranked jobs", body: "Fictional listings ranked against the persona." },
    { href: "/jobs", label: "4. Fit, tailored CV and cover letter", body: "Open the top job and step through the workspace." },
  ];
  return (
    <section aria-label="About this demo" className="rounded-card border border-border bg-surface p-[18px] flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h2 className="m-0 text-[15px] font-semibold">Windrush is an AI career navigator</h2>
        <p className="m-0 text-[13.5px] leading-[1.55] text-ink-2 max-w-[80ch]">
          The real app parses a CV, scores how exposed each skill is to AI, ranks jobs, drafts tailored documents and can fill in
          application forms with a browser agent. This public demo shows the flow with an invented person and invented jobs. The
          parsed CV, fit results, tailored CV and letter are hand-written samples, not model output. The agent, autopilot, inbox
          and credential features are removed.
        </p>
      </div>
      <ul className="m-0 p-0 list-none grid gap-[10px]" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(220px, 100%), 1fr))" }}>
        {steps.map((s) => (
          <li key={s.label}>
            <Link href={s.href} className="block h-full rounded-inner border border-border p-3 no-underline text-ink hover:bg-subtle">
              <span className="block text-[13.5px] font-semibold">{s.label}</span>
              <span className="block mt-1 text-[12.5px] leading-[1.5] text-ink-2">{s.body}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function DemoPersonaNote() {
  if (!DEMO_MODE) return null;
  return (
    <Box>
      <strong className="font-semibold text-ink">Sample parse result.</strong> This persona belongs to a fictional person and was
      written by hand to show what a parsed CV looks like; no model ran. Edits stay in this tab and reset on refresh.
      <details className="mt-2">
        <summary className="cursor-pointer text-teal">Show the fictional CV it represents</summary>
        <pre className="mt-2 mb-0 whitespace-pre-wrap font-mono text-[12px] leading-[1.5]">{SAMPLE_CV_TEXT}</pre>
      </details>
    </Box>
  );
}

export function DemoExposureNote() {
  if (!DEMO_MODE) return null;
  return (
    <Box>
      <strong className="font-semibold text-ink">Saved scores for fictional skills.</strong> These numbers are real output of the
      project&apos;s scoring code (Anthropic Economic Index and O*NET task data, plus its built-in table), run once on these skills.
      They are rough lookups, not forecasts. The real app also has a model write a one-line explanation of each score; those are
      left out because this demo makes no LLM calls, and the roadmap is off for the same reason.
    </Box>
  );
}

export function DemoJobsNote() {
  if (!DEMO_MODE) return null;
  return (
    <Box>
      <strong className="font-semibold text-ink">Fictional listings.</strong> The employers, jobs and match scores are invented to show
      how the feed ranks roles. The real app collects live listings and matches them with embeddings.
    </Box>
  );
}

export function DemoApplicationsNote() {
  if (!DEMO_MODE) return null;
  return (
    <Box>
      <strong className="font-semibold text-ink">Fictional history.</strong> These entries show how the tracker looks. No application
      was ever submitted, and these figures say nothing about real results.
    </Box>
  );
}

export function DemoAgentDisabled() {
  return (
    <div className="rounded-card border border-border bg-amber-chip px-4 py-3 text-[13.5px] leading-[1.55] text-amber-text">
      <strong className="font-semibold">Disabled in this demo.</strong> The browser agent is not part of this site: there is no backend,
      no job-site login and no way to submit an application from here. In the real app the agent stops before the final submit and
      waits for you.
    </div>
  );
}
