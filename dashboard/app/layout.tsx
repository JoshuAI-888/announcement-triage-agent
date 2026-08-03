import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Milford Workspace — Announcement Triage",
  description: "Operator dashboard for the announcement-triage-agent (illustrative internal tool).",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="stylesheet" href="/styles/milford-system.css" />
        <link rel="stylesheet" href="/styles/portal.css" />
        <link rel="stylesheet" href="/styles/dashboard.css" />
      </head>
      <body>{children}</body>
    </html>
  );
}
