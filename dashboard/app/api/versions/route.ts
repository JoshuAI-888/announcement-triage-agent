// GET /api/versions — last N out/briefs/*.email.html, newest first
// (CONTRACTS.md §4/§7).
import { NextResponse } from "next/server";
import { listBriefVersions } from "@/lib/dataSource";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const limitParam = searchParams.get("limit");
  const limit = limitParam ? Math.max(1, Math.min(100, parseInt(limitParam, 10) || 20)) : 20;
  const versions = await listBriefVersions(limit);
  return NextResponse.json({ versions });
}
