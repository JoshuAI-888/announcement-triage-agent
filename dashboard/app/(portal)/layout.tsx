import { PortalShell } from "@/components/PortalShell";
import { getTrustStatus, mode } from "@/lib/dataSource";

export default async function PortalLayout({ children }: { children: React.ReactNode }) {
  let stale = false;
  try {
    const trust = await getTrustStatus();
    stale = trust.stale;
  } catch {
    // If trust status can't be computed (e.g. no config yet), don't block the shell.
    stale = false;
  }

  return (
    <PortalShell stale={stale} mode={mode}>
      {children}
    </PortalShell>
  );
}
