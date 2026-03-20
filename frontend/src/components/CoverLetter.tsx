"use client";

interface Props {
  coverLetter: string;
  jobTitle: string;
  company: string;
  onApprove: () => void;
  onSkip: () => void;
  applying: boolean;
}

export default function CoverLetter({
  coverLetter,
  jobTitle,
  company,
  onApprove,
  onSkip,
  applying,
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
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          <pre className="text-xs text-zinc-300 whitespace-pre-wrap leading-relaxed">
            {coverLetter}
          </pre>
        </div>

        <div className="p-4 border-t border-zinc-800 flex gap-3 justify-end">
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
  );
}
