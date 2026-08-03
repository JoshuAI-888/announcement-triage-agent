// POST /api/run-eval — workflow_dispatch run-eval.yml (CONTRACTS.md §7).
// Accepts the same optional inputs the workflow exposes (prompt_version,
// provider, runs, limit, no_baselines); blank prompt_version/provider fall
// back to runtime_config.json's run.prompt_version / eval.provider, same as
// the workflow itself does (DEPLOY.md §5). Mocked in local dev mode.
import { NextResponse } from "next/server";
import { dispatchRunEval, mode, type RunEvalInputs } from "@/lib/dataSource";

export async function POST(req: Request) {
  let body: RunEvalInputs = {};
  try {
    body = (await req.json()) ?? {};
  } catch {
    // no body is fine — every input is optional
  }
  try {
    const { mocked } = await dispatchRunEval(body);
    return NextResponse.json({
      ok: true,
      mocked,
      mode,
      message: mocked
        ? "Local dev mode: logged the dispatch instead of calling GitHub. See server console."
        : "Dispatched run-eval.yml on main.",
    });
  } catch (err) {
    return NextResponse.json({ error: "dispatch_failed", message: (err as Error).message }, { status: 502 });
  }
}
