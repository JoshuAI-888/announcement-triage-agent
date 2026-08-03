import { Icon } from "@/components/Icon";
import { getEvalSummary } from "@/lib/dataSource";
import { daysSince, fmtDateTime } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function CadencePage() {
  const summary = await getEvalSummary();
  const age = daysSince(summary?.generated_at);

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Trust maintenance</p>
          <h1>Eval cadence</h1>
          <p>The full gold-set eval is deliberately NOT run daily (DEPLOY.md §6). It runs on-change, monthly, and optionally as a cheap canary.</p>
        </div>
      </div>

      <div className="grid metrics" style={{ marginBottom: 20 }}>
        <article className={`card card-pad metric ${age !== null && age > 31 ? "attention-warn" : ""}`}>
          <span>Last verified</span>
          <strong style={{ fontSize: "1.15rem" }}>{summary ? fmtDateTime(summary.generated_at) : "never"}</strong>
          <small className={age !== null && age > 31 ? "delta down" : "muted"}>
            {age === null ? "no eval_summary.json" : `${age} day(s) ago`}
          </small>
        </article>
        <article className="card card-pad metric">
          <span>Cadence policy</span>
          <strong style={{ fontSize: "1.15rem" }}>Not daily</strong>
          <small className="muted">on-change + monthly + optional canary</small>
        </article>
      </div>

      <div className="grid split">
        <article className="card card-pad">
          <div className="module-icon">
            <Icon code="f021" />
          </div>
          <h3 style={{ marginTop: 18 }}>On change</h3>
          <p className="small muted">
            Any time an eval-affecting field in runtime_config.json moves &mdash; prompt version, prompt override,
            eval provider, model id, or pricing (exactly the fields folded into <span className="mono">eval_fingerprint()</span>).
            The Trust panel&rsquo;s stale banner is the signal this is due.
          </p>
        </article>
        <article className="card card-pad">
          <div className="module-icon">
            <Icon code="f133" />
          </div>
          <h3 style={{ marginTop: 18 }}>Monthly</h3>
          <p className="small muted">
            A baseline cadence even with no config change, to catch silent drift &mdash; a provider quietly updating
            a model, or a gold-set correction landing on main. Currently a manual monthly &ldquo;Run eval
            now&rdquo;; a scheduled trigger can be added to run-eval.yml later if the owner wants it automatic.
          </p>
        </article>
        <article className="card card-pad">
          <div className="module-icon">
            <Icon code="f0da" />
          </div>
          <h3 style={{ marginTop: 18 }}>Optional canary</h3>
          <p className="small muted">
            A small <span className="mono">--limit N</span> run (e.g. 20&ndash;30 items) after a prompt or provider
            tweak, before committing to a full 220-item &times; 3-run pass, to catch a broken prompt or parsing
            regression cheaply. Use the <span className="mono">limit</span> input on the manual run-eval dispatch.
          </p>
        </article>
        <article className="card card-pad">
          <div className="module-icon">
            <Icon code="f256" />
          </div>
          <h3 style={{ marginTop: 18 }}>Why not daily</h3>
          <p className="small muted">
            A full 220-item &times; 3-run pass costs roughly NZ$10&ndash;15+ per run (PROGRESS.md) and
            evals/eval_summary.json is meant to be a stable, occasionally-updated trust snapshot &mdash; running it
            on every commit would be both wasteful and noisy.
          </p>
        </article>
      </div>
    </section>
  );
}
