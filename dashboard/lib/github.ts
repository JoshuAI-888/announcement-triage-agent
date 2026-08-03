// github.ts — thin wrapper around the GitHub REST API for the pieces
// CONTRACTS.md §7/§10 needs: read a file from `main`, commit a file to `main`,
// list a directory, list commits touching a path (for "revert to previous"),
// and workflow_dispatch. Only used when NOT in LOCAL_DEV_MODE (lib/env.ts).

import { GITHUB_BRANCH, GITHUB_REPO, GITHUB_TOKEN } from "./env";

const API = "https://api.github.com";

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  return {
    Authorization: `Bearer ${GITHUB_TOKEN}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    ...extra,
  };
}

async function ghFetch(pathAndQuery: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`${API}/repos/${GITHUB_REPO}${pathAndQuery}`, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers as Record<string, string> | undefined) },
    cache: "no-store",
  });
  return res;
}

export interface GhFile {
  content: string; // decoded (utf-8)
  sha: string;
}

/** Fetch a text file's decoded content + blob sha at a given ref (default the configured branch). */
export async function getFile(filePath: string, ref: string = GITHUB_BRANCH): Promise<GhFile | null> {
  const res = await ghFetch(`/contents/${encodeURIComponentPath(filePath)}?ref=${encodeURIComponent(ref)}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`GitHub getFile(${filePath}) failed: ${res.status} ${await res.text()}`);
  const json = (await res.json()) as { content: string; encoding: string; sha: string };
  const content = Buffer.from(json.content, (json.encoding as BufferEncoding) || "base64").toString("utf-8");
  return { content, sha: json.sha };
}

export interface GhDirEntry {
  name: string;
  path: string;
  sha: string;
  type: "file" | "dir";
}

/** List a directory's entries at a given ref. Returns [] if the directory doesn't exist. */
export async function listDir(dirPath: string, ref: string = GITHUB_BRANCH): Promise<GhDirEntry[]> {
  const res = await ghFetch(`/contents/${encodeURIComponentPath(dirPath)}?ref=${encodeURIComponent(ref)}`);
  if (res.status === 404) return [];
  if (!res.ok) throw new Error(`GitHub listDir(${dirPath}) failed: ${res.status} ${await res.text()}`);
  const json = (await res.json()) as GhDirEntry[] | Record<string, unknown>;
  if (!Array.isArray(json)) return [];
  return json;
}

/** Direct-commit a text file to the branch (create or update). */
export async function commitFile(filePath: string, content: string, message: string, sha?: string): Promise<{ sha: string; commitSha: string }> {
  const body: Record<string, unknown> = {
    message,
    content: Buffer.from(content, "utf-8").toString("base64"),
    branch: GITHUB_BRANCH,
  };
  if (sha) body.sha = sha;
  const res = await ghFetch(`/contents/${encodeURIComponentPath(filePath)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`GitHub commitFile(${filePath}) failed: ${res.status} ${await res.text()}`);
  const json = (await res.json()) as { content: { sha: string }; commit: { sha: string } };
  return { sha: json.content.sha, commitSha: json.commit.sha };
}

/** List commit SHAs touching a path, newest first (for "revert to previous"). */
export async function listCommitsForPath(filePath: string, perPage = 5): Promise<string[]> {
  const res = await ghFetch(`/commits?path=${encodeURIComponent(filePath)}&sha=${encodeURIComponent(GITHUB_BRANCH)}&per_page=${perPage}`);
  if (!res.ok) throw new Error(`GitHub listCommitsForPath(${filePath}) failed: ${res.status} ${await res.text()}`);
  const json = (await res.json()) as { sha: string }[];
  return json.map((c) => c.sha);
}

/** Dispatch a workflow_dispatch event for a workflow file under .github/workflows/. */
export async function dispatchWorkflow(workflowFile: string, inputs: Record<string, string | boolean> = {}): Promise<void> {
  const res = await ghFetch(`/actions/workflows/${encodeURIComponent(workflowFile)}/dispatches`, {
    method: "POST",
    body: JSON.stringify({ ref: GITHUB_BRANCH, inputs }),
  });
  if (!res.ok && res.status !== 204) {
    throw new Error(`GitHub dispatchWorkflow(${workflowFile}) failed: ${res.status} ${await res.text()}`);
  }
}

function encodeURIComponentPath(p: string): string {
  // Encode each path segment but keep the slashes.
  return p.split("/").map(encodeURIComponent).join("/");
}
