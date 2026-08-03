import { Icon } from "@/components/Icon";
import { getTrustStatus } from "@/lib/dataSource";
import { fmtDateTime, fmtNzd, fmtPct } from "@/lib/format";

export const dynamic = "force-dynamic";

const SCORECARD_COLUMNS: [string, string][] = [
  ["recall_material", "Recall (material)"],
  ["precision_material", "Precision"],
  ["grounded_pct", "Grounded %"],
  ["confidently_wrong", "Confidently wrong"],
  ["abstention_ambiguous", "Abstention (ambiguous)"],
  ["cost_per_item_nzd", "Cost/item NZD"],
];

export default async function TrustPage() {
  const { summary, liveFingerprint, stale } = await getTrustStatus();

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Trust</p>
          <h1>Eval scorecard</h1>
          <p>The committed evals/eval_summary.json snapshot, compared against the live config&rsquo;s fingerprint.</p>
        </div>
      </div>

      {stale && (
        <div className="banner banner-warning" role="status">
          <Icon code="f071" />
          <div>
            <strong>Trust numbers are stale.</strong> The live runtime_config eval-fingerprint (
            <span className="mono">{liveFingerprint}</span>) does not match the fingerprint the last eval was run
            against (<span className="mono">{summary?.eval_config_fingerprint ?? "none recorded"}</span>). The prompt,
            override, provider, model or pricing changed since the last eval &mdash; re-run the eval (&ldquo;Run eval
            now&rdquo; above) before trusting these numbers for the current configuration.
          </div>
        </div>
      )}
      {!stale && summary && (
        <div className="banner banner-info" role="status">
          <Icon code="f058" />
          <div>
            Fingerprint matches the live config (<span className="mono">{liveFingerprint}</span>). These numbers
            describe the currently configured system.
          </div>
        </div>
      )}

      {!summary ? (
        <div className="card card-pad empty">
          <p>No evals/eval_summary.json found in this checkout.</p>
        </div>
      ) : (
        <>
          <div className="grid metrics">
            <article className="card card-pad metric">
              <span>Generated</span>
              <strong style={{ fontSize: "1.2rem" }}>{fmtDateTime(summary.generated_at)}</strong>
              <small className="muted">{summary.n_items} items &times; {summary.runs} run(s)</small>
            </article>
            <article className="card card-pad metric">
              <span>Ranking precision@5</span>
              <strong>{fmtPct(summary.ranking.precision_at_5)}</strong>
            </article>
            <article className="card card-pad metric">
              <span>Ranking precision@10</span>
              <strong>{fmtPct(summary.ranking.precision_at_10)}</strong>
            </article>
            <article className="card card-pad metric">
              <span>Eval fingerprint</span>
              <strong className="mono" style={{ fontSize: "1rem" }}>
                {summary.eval_config_fingerprint}
              </strong>
            </article>
          </div>

          <article className="card card-pad" style={{ marginBottom: 16 }}>
            <div className="card-head">
              <div>
                <h3>Scorecard by prompt / baseline</h3>
                <p>reuses report.py:SCORECARD_COLUMNS (CONTRACTS.md §2)</p>
              </div>
            </div>
            <div className="table-wrap scorecard-table">
              <table>
                <thead>
                  <tr>
                    <th>Prompt</th>
                    {SCORECARD_COLUMNS.map(([, title]) => (
                      <th key={title} className="align-right">
                        {title}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(summary.scorecard).map(([label, row]) => (
                    <tr key={label}>
                      <td>
                        <strong>{label}</strong>
                      </td>
                      {SCORECARD_COLUMNS.map(([key]) => {
                        const v = (row as unknown as Record<string, number | null>)[key];
                        const isCost = key === "cost_per_item_nzd";
                        return (
                          <td key={key} className="align-right tabular">
                            {isCost ? fmtNzd(v) : fmtPct(v)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>

          <article className="card card-pad" style={{ marginBottom: 16 }}>
            <div className="card-head">
              <div>
                <h3>Providers evaluated</h3>
                <p>Same gold set, same prompt &mdash; provider comparison</p>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th className="align-right">Recall</th>
                    <th className="align-right">Precision</th>
                    <th className="align-right">Grounded</th>
                    <th className="align-right">Confidently wrong</th>
                    <th className="align-right">Abstention</th>
                    <th className="align-right">Cost/item NZD</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.providers.map((p) => (
                    <tr key={p.model}>
                      <td className="mono">{p.model}</td>
                      <td className="align-right tabular">{fmtPct(p.recall)}</td>
                      <td className="align-right tabular">{fmtPct(p.precision)}</td>
                      <td className="align-right tabular">{fmtPct(p.grounded)}</td>
                      <td className="align-right tabular">{fmtPct(p.confidently_wrong)}</td>
                      <td className="align-right tabular">{fmtPct(p.abstention)}</td>
                      <td className="align-right tabular">{fmtNzd(p.cost_per_item_nzd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>

          {summary.caveats?.length > 0 && (
            <article className="card card-pad">
              <div className="card-head">
                <div>
                  <h3>Caveats</h3>
                </div>
              </div>
              <ul style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 8, fontSize: ".82rem" }}>
                {summary.caveats.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </article>
          )}
        </>
      )}
    </section>
  );
}
