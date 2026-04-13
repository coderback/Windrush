"use client";

interface Props {
  coverLetter: string;
  jobTitle: string;
  company: string;
  archetype?: string;
  onApprove: () => void;
  onSkip: () => void;
  applying: boolean;
  jobEmail: string;
  jobPassword: string;
  onJobEmailChange: (v: string) => void;
  onJobPasswordChange: (v: string) => void;
}

const archetypePill: Record<string, string> = {
  SoftwareEngineer: "bg-teal-500/20 text-teal-400",
  DataML: "bg-purple-500/20 text-purple-400",
  FinanceAnalyst: "bg-amber-500/20 text-amber-400",
};

const archetypeLabel: Record<string, string> = {
  SoftwareEngineer: "Software Engineer",
  DataML: "Data / ML",
  FinanceAnalyst: "Finance",
};

export default function CoverLetter({
  coverLetter,
  jobTitle,
  company,
  archetype,
  onApprove,
  onSkip,
  applying,
  jobEmail,
  jobPassword,
  onJobEmailChange,
  onJobPasswordChange,
}: Props) {
  if (!coverLetter) return null;

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-zinc-900 border border-zinc-700 rounded-lg max-w-2xl w-full max-h-[80vh] flex flex-col">
        <div className="p-4 border-b border-zinc-800">
          <div className="text-xs text-amber-400 font-semibold uppercase tracking-widest mb-1">
            Approval Required
          </div>
          <h2 className="text-lg font-bold text-zinc-100" style={{ fontFamily: "Playfair Display, serif" }}>
            Apply to {jobTitle} at {company}?
          </h2>
          {archetype && (
            <span
              className={`inline-block mt-1 text-xs font-semibold px-2 py-0.5 rounded ${
                archetypePill[archetype] ?? "bg-zinc-700 text-zinc-400"
              }`}
            >
              {archetypeLabel[archetype] ?? archetype}
            </span>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          <pre className="text-xs text-zinc-300 whitespace-pre-wrap leading-relaxed">
            {coverLetter}
          </pre>
        </div>

        <div className="p-4 border-t border-zinc-800 space-y-3">
          <div>
            <p className="text-xs text-zinc-500 mb-2">
              Job site credentials — agent will log in automatically if required
            </p>
            <div className="flex gap-2">
              <input
                type="email"
                placeholder="Email"
                value={jobEmail}
                onChange={(e) => onJobEmailChange(e.target.value)}
                disabled={applying}
                className="flex-1 px-3 py-1.5 text-xs bg-zinc-800 border border-zinc-700 rounded text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-teal-600 disabled:opacity-50"
              />
              <input
                type="password"
                placeholder="Password"
                value={jobPassword}
                onChange={(e) => onJobPasswordChange(e.target.value)}
                disabled={applying}
                className="flex-1 px-3 py-1.5 text-xs bg-zinc-800 border border-zinc-700 rounded text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-teal-600 disabled:opacity-50"
              />
            </div>
          </div>
          <div className="flex gap-3 justify-end">
            <button
              onClick={onSkip}
              disabled={applying}
              className="px-4 py-2 text-sm text-zinc-400 bg-zinc-800 hover:bg-zinc-700 rounded transition-colors disabled:opacity-50"
            >
              Skip
            </button>
            <button
              onClick={onApprove}
              disabled={applying}
              className="px-6 py-2 text-sm font-semibold text-white bg-teal-600 hover:bg-teal-500 rounded shadow-lg shadow-teal-500/20 transition-all animate-pulse disabled:animate-none disabled:opacity-50"
            >
              {applying ? "Applying…" : "Approve & Apply"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
