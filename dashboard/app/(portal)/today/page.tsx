import { Icon } from "@/components/Icon";
import { getRunLog, listBriefVersions } from "@/lib/dataSource";
import { fmtDateTime, fmtNzd } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function TodayPage() {
  const [runLog, briefs] = await Promise.all([getRunLog(), listBriefVersions(1)]);
  const latest = runLog[0] ?? null;
  const latestBrief = briefs[0] ?? null;

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Today</p>
          <h1>Latest run</h1>
          <p>The most recent digest or intraday pass, and the brief it produced.</p>
        </div>
      </div>

      {!latest && (
        <div className="card card-pad empty">
          <p>
            <strong>No runs yet.</strong> out/run_log.jsonl has no rows in this checkout. Once{" "}
            <code>daily-brief.yml</code> runs (on schedule, or via &ldquo;Run now&rdquo; above), the latest
            digest or intraday result will appear here.
          </p>
        </div>
      )}

      {latest && (
        <>
          <div className="grid metrics">
            <article className="card card-pad metric">
              <span>Kind / date</span>
              <strong style={{ fontSize: "1.3rem" }}>{latest.kind}</strong>
              <small className="muted">{fmtDateTime(latest.ts)}</small>
            </article>
            <article className="card card-pad metric">
              <span>Processed / new</span>
              <strong>
                {latest.processed} / {latest.new}
              </strong>
              <small className="muted">{latest.deduped} deduped</small>
            </article>
            <article className="card card-pad metric">
              <span>Material / needs a look</span>
              <strong>
                {latest.material} / {latest.needs_look}
              </strong>
              <small className={latest.escalations > 0 ? "delta down" : "delta up"}>{latest.escalations} escalations</small>
            </article>
            <article className="card card-pad metric">
              <span>Cost / runtime</span>
              <strong>{fmtNzd(latest.total_cost_nzd)}</strong>
              <small className="muted">{latest.runtime_seconds.toFixed(1)}s</small>
            </article>
          </div>

          <div className="grid split" style={{ marginBottom: 16 }}>
            <article className="card card-pad">
              <div className="card-head">
                <div>
                  <h3>Run detail</h3>
                  <p>Provider and guardrails for this run</p>
                </div>
              </div>
              <dl className="kv-list">
                <dt>Prompt version</dt>
                <dd>{latest.prompt_version}</dd>
                <dt>Model (primary)</dt>
                <dd className="mono">{latest.model_primary}</dd>
                <dt>Guardrail flags</dt>
                <dd>
                  {Object.keys(latest.guardrail_flag_counts || {}).length === 0 ? (
                    <span className="muted">none</span>
                  ) : (
                    <span className="pill-row">
                      {Object.entries(latest.guardrail_flag_counts).map(([k, v]) => (
                        <span key={k} className="badge red">
                          {k}: {v}
                        </span>
                      ))}
                    </span>
                  )}
                </dd>
                <dt>Dashboard URL</dt>
                <dd>{latest.dashboard_url ?? <span className="muted">n/a</span>}</dd>
              </dl>
            </article>
            <article className="card card-pad">
              <div className="card-head">
                <div>
                  <h3>Latest brief</h3>
                  <p>{latestBrief ? `${latestBrief.name} (${latestBrief.kind})` : "No archived brief found"}</p>
                </div>
                {latestBrief && (
                  <a className="btn secondary" href={latestBrief.url} target="_blank" rel="noreferrer">
                    <Icon code="f08e" /> Open
                  </a>
                )}
              </div>
              {!latestBrief && <div className="empty">No out/briefs/*.email.html found in this checkout yet.</div>}
            </article>
          </div>
        </>
      )}

      {latestBrief && (
        <article className="card card-pad">
          <div className="card-head">
            <div>
              <h3>Material list &mdash; {latestBrief.name}</h3>
              <p>Ranked material items with filing/news links, rendered from the archived brief HTML.</p>
            </div>
          </div>
          <div className="brief-frame-wrap">
            <iframe className="brief-frame" src={latestBrief.url} title={`Brief ${latestBrief.name}`} />
          </div>
        </article>
      )}
    </section>
  );
}
