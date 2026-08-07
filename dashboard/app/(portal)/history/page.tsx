import { getRunLog } from "@/lib/dataSource";
import { WorkflowRuns } from "@/components/WorkflowRuns";
import { RunLogTable } from "@/components/RunLogTable";

export const dynamic = "force-dynamic";

export default async function HistoryPage() {
  const rows = await getRunLog();

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Operations</p>
          <h1>Run history</h1>
          <p>Live workflow runs (ongoing and finished) plus every completed Daily digest/intraday/backfill pass recorded in out/run_log.jsonl.</p>
        </div>
      </div>

      <WorkflowRuns />

      <h2 style={{ fontSize: 16, margin: "4px 0 12px" }}>Completed runs (run_log.jsonl)</h2>

      <RunLogTable rows={rows} />
    </section>
  );
}
