import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import AppShell from "@/components/AppShell";
import { THEME_SCRIPT } from "@/lib/theme";
import { DEMO_MODE } from "@/lib/demo";

const geist = localFont({
  src: "./fonts/GeistVF.woff",
  variable: "--font-geist",
  weight: "100 900",
  display: "swap",
});
const geistMono = localFont({
  src: "./fonts/GeistMonoVF.woff",
  variable: "--font-geist-mono",
  weight: "100 900",
  display: "swap",
});

export const metadata: Metadata = {
  title: DEMO_MODE ? "Windrush: read-only demo with sample data" : "Windrush — Career navigator",
  description: DEMO_MODE
    ? "Read-only demo of an AI career navigator, with a fictional CV and fictional jobs."
    : "Find roles that fit you, tailor every application, and never submit without you",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // The theme script sets `dark` on <html> before React hydrates, so the class can differ.
    <html lang="en" suppressHydrationWarning className={`${geist.variable} ${geistMono.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="font-sans bg-canvas text-ink antialiased">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
