import { FilingsTable } from "@/components/FilingsTable";
import { getLatestFilings } from "@/lib/dataSource";
import { fmtDateTime } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function FilingsPage() {
  const run = await getLatestFilings();

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Today</p>
          <h1>This run</h1>
          <p>
            Every filing classified in the latest run, from out/filings/&lt;date&gt;.json &mdash; materiality call,
            confidence, guardrail flags, and a link back to the source filing.
          </p>
        </div>
      </div>

      {!run && (
        <div className="card card-pad empty">
          <p>
            <strong>No filings recorded yet.</strong> out/filings/ has no runs in this checkout. Once a digest or
            intraday pass completes, its classified filings will appear here.
          </p>
        </div>
      )}

      {run && (
        <>
          <div className="grid metrics">
            <article className="card card-pad metric">
              <span>Kind / date</span>
              <strong style={{ fontSize: "1.3rem" }}>{run.kind}</strong>
              <small className="muted">{fmtDateTime(run.generated_at)}</small>
            </article>
            <article className="card card-pad metric">
              <span>Received</span>
              <strong>{run.counts.total_received}</strong>
              <small className="muted">total items</small>
            </article>
            <article className="card card-pad metric">
              <span>Material / needs info</span>
              <strong>
                {run.counts.material} / {run.counts.needs_more_info}
              </strong>
              <small className="muted">{run.counts.immaterial} immaterial</small>
            </article>
            <article className="card card-pad metric">
              <span>Dropped / dead-lettered</span>
              <strong>
                {run.counts.dropped_offwatchlist} / {run.counts.dead_lettered}
              </strong>
              <small className="muted">off-watchlist / errored</small>
            </article>
          </div>

          <FilingsTable filings={run.filings} />
        </>
      )}
    </section>
  );
}
