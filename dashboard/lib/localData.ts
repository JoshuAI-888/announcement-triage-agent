// localData.ts — LOCAL DEV MODE filesystem access.
//
// Reads: straight off the real repo checkout one level up from dashboard/,
// read-only, exactly the files CONTRACTS.md §10 says the app reads from `main`.
//
// Writes: NEVER touch the real repo files. "Committing" a config edit in local
// dev writes to dashboard/.local-data/ (gitignored) instead and logs what the
// GitHub commit would have been — the same mock contract as lib/github.ts's
// production calls, just without a token. This keeps the dashboard build/dev
// loop fully offline and keeps this agent's own footprint inside dashboard/.

import fs from "node:fs/promises";
import path from "node:path";
import { LOCAL_DATA_DIR, REPO_ROOT_LOCAL } from "./env";

async function readIfExists(p: string): Promise<string | null> {
  try {
    return await fs.readFile(p, "utf-8");
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    if (code === "ENOENT") return null;
    throw err;
  }
}

export async function ensureLocalDataDir(): Promise<void> {
  await fs.mkdir(LOCAL_DATA_DIR, { recursive: true });
}

// --- repo baseline reads (read-only) ---

export async function readRepoFile(relPath: string): Promise<string | null> {
  return readIfExists(path.join(REPO_ROOT_LOCAL, relPath));
}

export async function listRepoDir(relPath: string): Promise<string[]> {
  try {
    return await fs.readdir(path.join(REPO_ROOT_LOCAL, relPath));
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    if (code === "ENOENT") return [];
    throw err;
  }
}

// --- local override store (mocked "commits") ---

function overridePath(name: string): string {
  return path.join(LOCAL_DATA_DIR, name);
}

export async function readOverride(name: string): Promise<string | null> {
  return readIfExists(overridePath(name));
}

export async function writeOverride(name: string, content: string): Promise<void> {
  await ensureLocalDataDir();
  await fs.writeFile(overridePath(name), content, "utf-8");
}

export async function deleteOverride(name: string): Promise<void> {
  try {
    await fs.unlink(overridePath(name));
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    if (code !== "ENOENT") throw err;
  }
}

export async function overrideExists(name: string): Promise<boolean> {
  try {
    await fs.access(overridePath(name));
    return true;
  } catch {
    return false;
  }
}

// dashboard/portal_auth.json lives inside dashboard/ itself, so local dev
// reads/writes it for real (no mock needed). The path is intentionally a
// static literal (not built from a dynamic argument) so bundlers don't treat
// this as "reads anywhere under cwd" and trace the whole project into the
// serverless output.
const PORTAL_AUTH_LOCAL_PATH = path.join(process.cwd(), "portal_auth.json");

export async function writePortalAuthLocal(content: string): Promise<void> {
  await fs.writeFile(PORTAL_AUTH_LOCAL_PATH, content, "utf-8");
}

export async function readPortalAuthLocal(): Promise<string | null> {
  return readIfExists(PORTAL_AUTH_LOCAL_PATH);
}

export function mockCommitLog(filePath: string, message: string): void {
  // eslint-disable-next-line no-console
  console.log(
    `[LOCAL DEV MODE] Would commit to GitHub (${filePath}): "${message}". ` +
      `No GITHUB_TOKEN/GITHUB_REPO set — mocked locally under dashboard/.local-data/. ` +
      `The real repo checkout was NOT modified.`
  );
}

export function mockDispatchLog(workflowFile: string, inputs: Record<string, unknown>): void {
  // eslint-disable-next-line no-console
  console.log(
    `[LOCAL DEV MODE] Would dispatch workflow "${workflowFile}" with inputs ${JSON.stringify(inputs)}. ` +
      `No GITHUB_TOKEN/GITHUB_REPO set — mocked, nothing was called.`
  );
}
