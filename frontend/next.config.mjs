/** @type {import('next').NextConfig} */
const demoMode = process.env.NEXT_PUBLIC_DEMO_MODE === "1";

// The public demo has no agent, autopilot, inbox or accounts: those routes go home.
const demoRedirects = ["/", "/login", "/signup", "/onboarding", "/autopilot", "/review", "/inbox"]
  .map((source) => ({ source, destination: "/dashboard", permanent: false }));

const nextConfig = {
  ...(demoMode ? { redirects: async () => demoRedirects } : {}),
  ...(process.env.VERCEL ? {} : { output: "standalone" }),
};

export default nextConfig;
