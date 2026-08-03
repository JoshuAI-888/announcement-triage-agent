// GET /api/versions/[name] — raw HTML of one archived brief
// (out/briefs/<name>.email.html), used as the "view" for a draft version and
// as the iframe src for the Today panel's latest-brief preview. The name is
// validated against the exact brief-filename pattern in lib/dataSource.ts
// before any file access, so this can't be used for path traversal.
import { NextResponse } from "next/server";
import { getBriefHtml } from "@/lib/dataSource";

export async function GET(_req: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  const html = await getBriefHtml(decodeURIComponent(name));
  if (html === null) {
    return NextResponse.json({ error: "not_found", message: `no brief named ${name}` }, { status: 404 });
  }
  return new NextResponse(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}
