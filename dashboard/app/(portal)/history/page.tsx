import { getRunLog } from "@/lib/dataSource";
import { fmtDateTime, fmtNzd } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function HistoryPage() {
  const rows = await getRunLog();

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Operations</p>
          <h1>Run history</h1>
          <p>Every digest and intraday pass recorded in out/run_log.jsonl, newest first.</p>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="card card-pad empty">
          <p>No rows in out/run_log.jsonl yet in this checkout.</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date / time (UTC)</th>
                <th>Kind</th>
                <th>Processed</th>
                <th>New</th>
                <th>Deduped</th>
                <th>Material</th>
                <th>Needs look</th>
                <th>Escalations</th>
                <th>Guardrail flags</th>
                <th className="align-right">Cost (NZD)</th>
                <th className="align-right">Runtime (s)</th>
                <th>Prompt</th>
                <th>Model</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.ts}-${i}`}>
                  <td className="mono small">{fmtDateTime(r.ts)}</td>
                  <td>
                    <span className={`badge ${r.kind === "intraday" ? "orange" : ""}`}>{r.kind}</span>
                  </td>
                  <td>{r.processed}</td>
                  <td>{r.new}</td>
                  <td>{r.deduped}</td>
                  <td>{r.material}</td>
                  <td>{r.needs_look}</td>
                  <td>
                    <span className={r.escalations > 0 ? "badge orange" : "badge"}>{r.escalations}</span>
                  </td>
                  <td className="small">
                    {Object.keys(r.guardrail_flag_counts || {}).length === 0
                      ? "—"
                      : Object.entries(r.guardrail_flag_counts)
                          .map(([k, v]) => `${k}: ${v}`)
                          .join(", ")}
                  </td>
                  <td className="align-right tabular">{fmtNzd(r.total_cost_nzd)}</td>
                  <td className="align-right tabular">{r.runtime_seconds.toFixed(1)}</td>
                  <td>{r.prompt_version}</td>
                  <td className="mono small">{r.model_primary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
