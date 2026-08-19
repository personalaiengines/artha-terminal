import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ARTHA Terminal — AI Equities Intelligence",
  description: "Premium AI-powered institutional research terminal for Indian equities.",
};

/**
 * Root layout carries the document only. The chrome lives one level down:
 * `(portal)/layout.tsx` wraps the signed-in app in AppShell, `(public)/` renders
 * bare. Route groups do not appear in URLs, so every existing path is unchanged.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Inter + Geist Mono. Falls back to system stack if offline. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
      </head>
      <body className="antialiased">{children}</body>
    </html>
  );
}
