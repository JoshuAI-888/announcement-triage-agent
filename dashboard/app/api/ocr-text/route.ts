// GET /api/ocr-text?path=out/ocr/<id>.txt — one persisted PDF/OCR transcript,
// lazy-loaded by the audit page when a row is expanded (so the initial page
// payload never carries every transcript). Reads via lib/dataSource.ts's
// getOcrText(), which hard-validates the path against out/ocr/*.txt — a
// crafted path can never escape the artifact directory. A missing/invalid
// path returns 404 (not 500); the caller shows "transcript unavailable".
//
// Auth: gated by dashboard/proxy.ts like every non-/login route.
import { NextRequest, NextResponse } from "next/server";
import { getOcrText } from "@/lib/dataSource";

export async function GET(req: NextRequest) {
  const path = req.nextUrl.searchParams.get("path");
  if (!path) {
    return NextResponse.json({ error: "missing_path" }, { status: 400 });
  }
  try {
    const text = await getOcrText(path);
    if (text === null) {
      return NextResponse.json({ error: "not_found" }, { status: 404 });
    }
    return NextResponse.json({ text });
  } catch (err) {
    return NextResponse.json({ error: "read_failed", message: (err as Error).message }, { status: 500 });
  }
}
