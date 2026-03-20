import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Windrush — AI Career Navigator",
  description: "Navigate the impact of AI on your career with personalised guidance",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Playfair+Display:wght@400;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="antialiased bg-[#0a0a0a] text-zinc-100 font-mono">
        {children}
      </body>
    </html>
  );
}
