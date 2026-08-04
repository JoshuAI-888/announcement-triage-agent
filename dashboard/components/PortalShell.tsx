"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { Icon } from "./Icon";
import { TopbarActions } from "./TopbarActions";

const NAV_ITEMS = [
  { href: "/today", label: "Today", icon: "f015" },
  { href: "/filings", label: "This run", icon: "f0ce" },
  { href: "/config", label: "Config", icon: "f013" },
  { href: "/history", label: "Run history", icon: "f1da" },
  { href: "/pdf-log", label: "PDF / OCR log", icon: "f1c1" },
  { href: "/trust", label: "Trust", icon: "f3ed" },
  { href: "/optimisations", label: "Optimisations", icon: "f0e7" },
  { href: "/cadence", label: "Eval cadence", icon: "f017" },
  { href: "/versions", label: "Draft versions", icon: "f0f6" },
];

export function PortalShell({ stale, mode, children }: { stale: boolean; mode: "local-dev" | "github"; children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);

  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="portal">
      <aside className={`sidebar${menuOpen ? " open" : ""}`} id="sidebar">
        <a className="brand" href="/today">
          <img src="/brand/milfordasset.svg" alt="Milford" />
        </a>
        <div className="workspace-label">Announcement triage</div>
        <nav className="nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={pathname?.startsWith(item.href) ? "active" : ""}
              onClick={() => setMenuOpen(false)}
            >
              <Icon code={item.icon} />
              <span>{item.label}</span>
              {item.href === "/trust" && stale && (
                <span className="badge orange" style={{ marginLeft: "auto" }} title="Trust numbers are stale">
                  Stale
                </span>
              )}
            </Link>
          ))}
        </nav>
        <div className="sidebar-user">
          <div className="avatar initials">MW</div>
          <div style={{ flex: 1 }}>
            <strong>Milford Workspace</strong>
            <span>Operator dashboard</span>
          </div>
          <button className="icon-btn" aria-label="Sign out" onClick={signOut} type="button" style={{ marginLeft: 8 }}>
            <Icon code="f2f5" />
          </button>
        </div>
      </aside>
      <main className="app">
        <header className="topbar">
          <button className="menu-toggle" aria-label="Open navigation" type="button" onClick={() => setMenuOpen((v) => !v)}>
            <Icon code="f0c9" />
          </button>
          <div className="search" aria-hidden="true">
            <strong style={{ color: "var(--milford-slate)", fontFamily: "var(--font-display)", fontSize: "1.05rem" }}>
              Announcement Triage Agent
            </strong>
          </div>
          <TopbarActions mode={mode} />
        </header>
        <div className="content">{children}</div>
      </main>
    </div>
  );
}
