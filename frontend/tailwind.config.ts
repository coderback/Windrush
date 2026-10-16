import type { Config } from "tailwindcss";

// Every colour is a CSS variable from globals.css, so one class works in both themes:
// light is the default and `.dark` on <html> swaps the values.
const v = (name: string) => `var(--${name})`;

const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: v("canvas"),
        surface: v("surface"),
        subtle: v("subtle"),
        muted: v("muted"),
        track: v("track"),
        divider: v("divider"),
        border: v("border"),
        "border-strong": v("border-strong"),
        "bar-idle": v("bar-idle"),
        stone: v("stone"),
        ink: { DEFAULT: v("ink"), 2: v("ink-2"), 3: v("ink-3") },
        "on-ink": v("on-ink"),
        teal: {
          DEFAULT: v("teal"), deep: v("teal-deep"), soft: v("teal-soft"), chip: v("teal-chip"),
          logo: v("teal-logo"), line: v("teal-line"), ok: v("teal-ok"), "ok-line": v("teal-ok-line"),
        },
        amber: {
          DEFAULT: v("amber"), text: v("amber-text"), soft: v("amber-soft"), chip: v("amber-chip"),
          wash: v("amber-wash"), "wash-2": v("amber-wash-2"), line: v("amber-line"), "line-2": v("amber-line-2"),
          "line-3": v("amber-line-3"), ink: v("amber-ink"), "ink-2": v("amber-ink-2"), dash: v("amber-dash"),
        },
        orange: { DEFAULT: v("orange"), text: v("orange-text") },
        red: { DEFAULT: v("red"), soft: v("red-soft") },
        blue: { DEFAULT: v("blue"), soft: v("blue-soft"), text: v("blue-text") },
        violet: { DEFAULT: v("violet"), soft: v("violet-soft"), text: v("violet-text") },
        green: { DEFAULT: v("green"), soft: v("green-soft"), text: v("green-text") },
        tint: { mint: v("tint-mint"), sky: v("tint-sky"), peach: v("tint-peach"), lilac: v("tint-lilac"), sand: v("tint-sand") },
        band: v("band"),
        scale: { low: v("scale-low"), mid: v("scale-mid"), high: v("scale-high") },
      },
      fontFamily: {
        sans: ["var(--font-geist)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: { card: "16px", inner: "12px", control: "10px" },
      boxShadow: {
        selected: "0 0 0 3px var(--ring-teal)",
        slideover: "-12px 0 32px rgba(20,20,15,0.08)",
        paper: "0 1px 3px rgba(20,20,15,0.08), 0 8px 24px rgba(20,20,15,0.06)",
        lift: "0 1px 2px rgba(20,20,15,0.05)",
      },
    },
  },
  plugins: [],
};
export default config;
