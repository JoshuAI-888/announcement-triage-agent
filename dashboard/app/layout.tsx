import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Milford Workspace — Announcement Triage",
  description: "Operator dashboard for the announcement-triage-agent (illustrative internal tool).",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/* ?v=N cache-busts un-hashed public CSS; bump N when a stylesheet changes. */}
        <link rel="stylesheet" href="/styles/milford-system.css?v=2" />
        <link rel="stylesheet" href="/styles/portal.css?v=2" />
        <link rel="stylesheet" href="/styles/dashboard.css?v=2" />
      </head>
      <body>{children}</body>
    </html>
  );
}
