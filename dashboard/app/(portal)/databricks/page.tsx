import { DatabricksArchitecture } from "@/components/DatabricksArchitecture";

export const dynamic = "force-static";

function Section({ id, title, kicker, children }: { id: string; title: string; kicker?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="card card-pad" id={id} style={{ marginBottom: 18 }}>
      {kicker}
      <h2 style={{ marginTop: kicker ? 8 : 0, fontSize: 18 }}>{title}</h2>
      {children}
    </div>
  );
}

function A({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" style={{ color: "var(--milford-orange)", fontWeight: 600 }}>
      {children}
    </a>
  );
}

function LayerKey({ color, label }: { color: string; label: string }) {
  return (
    <span className="db-layer-key">
      <i style={{ background: color }} /> {label}
    </span>
  );
}

const SOURCES: { label: string; href: string }[] = [
  { label: "Unity AI Gateway", href: "https://www.databricks.com/product/artificial-intelligence/unity-ai-gateway" },
  { label: "Introducing Agent Bricks", href: "https://www.databricks.com/blog/introducing-agent-bricks" },
  { label: "Agent Bricks — Supervisor Agent (GA)", href: "https://www.databricks.com/blog/agent-bricks-supervisor-agent-now-ga-orchestrate-enterprise-agents" },
  { label: "SEC document-intelligence tutorial", href: "https://docs.databricks.com/aws/en/generative-ai/agent-bricks/idp-pipeline-tutorial" },
  { label: "ai_extract function", href: "https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_extract" },
  { label: "MLflow 3 — unified GenAI observability", href: "https://www.databricks.com/blog/mlflow-30-unified-ai-experimentation-observability-and-governance" },
  { label: "MLflow — custom LLM judges", href: "https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/custom-judge/" },
  { label: "Unity Catalog governance", href: "https://docs.databricks.com/aws/en/data-governance/unity-catalog/" },
  { label: "Lakeflow Declarative Pipelines", href: "https://docs.databricks.com/aws/en/ldp/concepts/" },
  { label: "Lakehouse Monitoring (GA)", href: "https://www.databricks.com/br/blog/lakehouse-monitoring-ga-profiling-diagnosing-and-enforcing-data-quality-intelligence" },
  { label: "Lakebase launch", href: "https://www.databricks.com/blog/announcing-databricks-lakebase-launch-partners" },
  { label: "Model risk management — 2026 banker's guide", href: "https://www.databricks.com/blog/model-risk-management-2026-bankers-guide-revised-interagency-guidance" },
  { label: "Databricks Apps", href: "https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/" },
  { label: "Genie in Databricks Apps", href: "https://docs.databricks.com/aws/en/dev-tools/databricks-apps/genie" },
  { label: "Serverless Jobs / Workflows", href: "https://docs.databricks.com/aws/en/jobs/run-serverless-jobs" },
  { label: "CI/CD best practices (Asset Bundles + OIDC)", href: "https://docs.databricks.com/aws/en/dev-tools/ci-cd/best-practices" },
];

const MAPPING: { concern: string; product: string; how: string }[] = [
  { concern: "Materiality classification", product: "Agent Bricks · AI Functions · Model Serving", how: "Databricks' own SEC-filing template: parse → classify against a taxonomy → extract typed fields, served behind a governed endpoint." },
  { concern: "Multi-provider + escalation", product: "Unity AI Gateway", how: "One gateway routes to any provider; fallback chains escalate to a stronger model on low confidence." },
  { concern: "Cost tracking per run", product: "AI Gateway logs · UC system tables · Budget Policies", how: "Per-call cost/tokens logged centrally; hard spend caps and per-team tagging independent of app code." },
  { concern: "Config + schema validation", product: "Unity Catalog · Asset Bundles", how: "Config-as-versioned-table or bundle YAML validated in CI via databricks bundle validate." },
  { concern: "Observability", product: "MLflow 3 Tracing · Lakehouse Monitoring · Inference Tables", how: "OpenTelemetry traces of every call; auto-captured inference logs; drift/quality dashboards + alerts." },
  { concern: "Evaluation (precision/recall/grounding)", product: "MLflow judges · Agent Bricks auto-eval", how: "Custom make_judge() scorers + auto-generated eval sets replace much of the hand-rolled harness." },
  { concern: "Append-only logging", product: "MLflow Tracing · UC audit tables", how: "Every trace and action is immutably logged and governed." },
  { concern: "Guardrails", product: "Unity AI Gateway", how: "PII, prompt-injection, jailbreak, and toxicity checks enforced centrally, not per-app." },
  { concern: "Ingestion reliability + retries", product: "Lakeflow Declarative Pipelines · Jobs", how: "Declarative pipeline with data-quality expectations, cluster-reuse retries, and SLA alerting." },
  { concern: "Dedup / watermarks", product: "Delta Lake MERGE · Structured Streaming", how: "Native upsert and watermark semantics instead of bespoke dedup logic." },
  { concern: "Operator portal (UX/UI)", product: "Databricks Apps · Genie", how: "Host in-workspace with built-in OAuth and governed resources; or replace read views with a no-code Genie space." },
  { concern: "Draft-only email + state", product: "Lakebase · Jobs", how: "Serverless Postgres holds config, cost ledger, and the draft queue; a job composes and holds for human send." },
  { concern: "Governance, trust, audit", product: "Unity Catalog · Model Registry", how: "ABAC, automatic lineage, audit system tables, and versioned models — one governed control plane." },
];

export default function DatabricksPage() {
  return (
    <section className="db-page">
      <div className="page-head">
        <div>
          <p className="eyebrow db-eyebrow">Reference architecture · vision</p>
          <h1>On Databricks — a lakehouse reference architecture</h1>
          <p>
            How this class of use case — LLM materiality triage of SEC filings, with its cost, config, evaluation,
            observability, model-choice, and governance concerns — would run on the Databricks Data + AI platform. This is
            a forward-looking reference design, not a committed migration of the current stack.
          </p>
          <div className="db-theme-tags">
            <span className="db-swatch"><i style={{ background: "#e1690e" }} /> Milford portal theme</span>
            <span className="db-swatch"><i style={{ background: "#ff3621" }} /> Databricks accents</span>
          </div>
        </div>
      </div>

      <div className="card card-pad" style={{ marginBottom: 18 }}>
        <strong className="small">On this page</strong>
        <p className="small" style={{ margin: "6px 0 0" }}>
          <a href="#summary">Executive summary</a> · <a href="#architecture">Interactive architecture</a> ·{" "}
          <a href="#flow">How a filing flows</a> · <a href="#velocity">Low/no-code velocity</a> ·{" "}
          <a href="#observability">Cost, observability &amp; eval</a> · <a href="#reliability">Reliable data</a> ·{" "}
          <a href="#governance">Governance &amp; FSI compliance</a> · <a href="#mapping">Concern → product map</a> ·{" "}
          <a href="#gaps">What we&rsquo;d gain</a> · <a href="#caveats">Caveats</a> · <a href="#sources">Sources</a>
        </p>
      </div>

      {/* ---------- Executive summary (business layer) ---------- */}
      <Section id="summary" title="Executive summary" kicker={<p className="eyebrow">For the whole room</p>}>
        <p>
          Databricks has consolidated, through 2025&ndash;2026, into a coherent &ldquo;agentic lakehouse&rdquo; that maps
          almost one-to-one onto every concern this agent already handles. The classification pipeline becomes governed,
          managed services instead of bespoke code; evaluation, cost, and logging become platform features; and the whole
          thing sits inside a single governance and audit layer built for regulated industries.
        </p>
        <p>
          The strongest signal that this is the right platform: Databricks publishes a public tutorial that{" "}
          <A href="https://docs.databricks.com/aws/en/generative-ai/agent-bricks/idp-pipeline-tutorial">parses, classifies,
          and extracts structured fields from SEC-filed documents</A> using its Document Intelligence functions &mdash;
          effectively a template for materiality triage of EDGAR filings. And Databricks has published a{" "}
          <A href="https://www.databricks.com/blog/model-risk-management-2026-bankers-guide-revised-interagency-guidance">2026
          banker&rsquo;s guide</A> mapping the latest interagency model-risk guidance (the successor to SR 11-7) directly
          onto this same stack &mdash; so an LLM materiality classifier can be run as a governed, examinable model, not
          &ldquo;just software.&rdquo;
        </p>
      </Section>

      {/* ---------- Interactive architecture ---------- */}
      <Section
        id="architecture"
        title="Interactive reference architecture"
        kicker={<p className="eyebrow">Hover any component</p>}
      >
        <p className="small" style={{ marginTop: 0, color: "var(--milford-muted)" }}>
          Hover &mdash; or keyboard-focus &mdash; any box to see what it is, its function in this design, and a cited
          Databricks reference. The orange dots trace one filing as it flows ingest → classify → eval → serve → app.
          Colour marks the layer:{" "}
          <LayerKey color="#1c99d6" label="Ingest" /> <LayerKey color="#8fa3ab" label="Lakehouse" />{" "}
          <LayerKey color="#ff3621" label="AI" /> <LayerKey color="#198754" label="Eval" />{" "}
          <LayerKey color="#915fb4" label="Serve" /> <LayerKey color="#e1690e" label="App" />{" "}
          <LayerKey color="#1b3139" label="Governance" />
        </p>
        <div className="arch-card card card-pad" style={{ marginTop: 12 }}>
          <DatabricksArchitecture />
        </div>
      </Section>

      {/* ---------- How a filing flows ---------- */}
      <Section id="flow" title="How a filing flows, end to end">
        <ol className="db-flow-steps">
          <li>
            <strong>Ingest.</strong> A <A href="https://docs.databricks.com/aws/en/ldp/concepts/">Lakeflow Declarative
            Pipeline</A> pulls EDGAR + market data into bronze tables and{" "}
            <A href="https://docs.databricks.com/aws/en/volumes/">Unity Catalog Volumes</A>, with data-quality
            expectations gating malformed filings and Delta MERGE handling dedup/watermarks. Scheduled by{" "}
            <A href="https://docs.databricks.com/aws/en/jobs/run-serverless-jobs">Lakeflow Jobs</A> with auto-retry.
          </li>
          <li>
            <strong>Classify.</strong> Silver/gold steps run <code>ai_parse_document → ai_classify → ai_extract</code>{" "}
            (or an <A href="https://www.databricks.com/blog/introducing-agent-bricks">Agent Bricks</A> agent), calling out
            through the <A href="https://www.databricks.com/product/artificial-intelligence/unity-ai-gateway">Unity AI
            Gateway</A> with fallback to a stronger model on low confidence.
          </li>
          <li>
            <strong>Evaluate.</strong> Every call is traced in{" "}
            <A href="https://www.databricks.com/blog/mlflow-30-unified-ai-experimentation-observability-and-governance">MLflow
            3</A>; scheduled runs score precision/recall/grounding with built-in and custom LLM judges, versioned against
            the prompts that produced them.
          </li>
          <li>
            <strong>Serve.</strong> Verdicts land in governed gold Delta tables; runtime config, the cost ledger, and the
            draft-email queue live in <A href="https://www.databricks.com/blog/announcing-databricks-lakebase-launch-partners">Lakebase</A>{" "}
            (serverless Postgres).
          </li>
          <li>
            <strong>App.</strong> The operator portal runs on{" "}
            <A href="https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/">Databricks Apps</A>{" "}
            with built-in OAuth, and a no-code <A href="https://docs.databricks.com/aws/en/dev-tools/databricks-apps/genie">Genie
            space</A> answers ad-hoc questions over run history.
          </li>
          <li>
            <strong>Govern (cross-cutting).</strong>{" "}
            <A href="https://docs.databricks.com/aws/en/data-governance/unity-catalog/">Unity Catalog</A> tracks lineage
            from raw filing → classification → email draft, with tiering tags driving proportionate approval workflows and
            Lakehouse Monitoring watching for drift.
          </li>
        </ol>
      </Section>

      {/* ---------- Theme 1: velocity ---------- */}
      <Section id="velocity" title="Low / no-code development velocity" kicker={<span className="arch-chip k-ai">AI &amp; App layer</span>}>
        <p>
          Much of what is hand-written today becomes configuration.{" "}
          <A href="https://www.databricks.com/blog/introducing-agent-bricks">Agent Bricks</A> lets you describe the
          classification task in natural language, point it at your data, and have it auto-build, auto-evaluate, and
          auto-optimise the agent &mdash; including prompt, retrieval, and model choice &mdash; without writing the harness
          by hand. The <A href="https://www.databricks.com/blog/agent-bricks-supervisor-agent-now-ga-orchestrate-enterprise-agents">Supervisor
          Agent</A> handles routing/escalation, and its human-feedback loop can turn an operator&rsquo;s corrections on a
          draft email into a continuous improvement signal.
        </p>
        <p>
          On the UI side, <A href="https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/">Databricks
          Apps</A> hosts the portal in-workspace with built-in OAuth and governed data access, while{" "}
          <A href="https://docs.databricks.com/aws/en/dev-tools/databricks-apps/genie">Genie</A> covers a large slice of the
          read-only views with zero custom UI &mdash; a business user just asks &ldquo;show this week&rsquo;s high-materiality
          filings with confidence &lt; 0.7.&rdquo;
        </p>
      </Section>

      {/* ---------- Theme 2: cost / observability / eval ---------- */}
      <Section id="observability" title="Cost, observability &amp; evaluation" kicker={<span className="arch-chip k-eval">Eval &amp; observability layer</span>}>
        <p>
          The <A href="https://www.databricks.com/product/artificial-intelligence/unity-ai-gateway">Unity AI Gateway</A>{" "}
          logs cost and tokens on every call and enforces hard spend caps and per-user rate limits &mdash; a governance
          backstop finance can trust independent of the app&rsquo;s own tracker &mdash; complemented by serverless budget
          policies for per-team attribution.
        </p>
        <p>
          <A href="https://www.databricks.com/blog/mlflow-30-unified-ai-experimentation-observability-and-governance">MLflow
          3</A> makes tracing OpenTelemetry-native (effectively the append-only run log), scores groundedness/correctness
          with built-in and <A href="https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/custom-judge/">custom
          LLM judges</A>, and versions prompts in a registry. Where the current app stops at offline scorecards,{" "}
          <A href="https://www.databricks.com/br/blog/lakehouse-monitoring-ga-profiling-diagnosing-and-enforcing-data-quality-intelligence">Lakehouse
          Monitoring</A> + inference tables add live drift detection on production classifications.
        </p>
      </Section>

      {/* ---------- Theme 3: reliability ---------- */}
      <Section id="reliability" title="Reliable data engineering &amp; failure recovery" kicker={<span className="arch-chip k-ingest">Ingestion layer</span>}>
        <p>
          <A href="https://docs.databricks.com/aws/en/ldp/concepts/">Lakeflow Declarative Pipelines</A> replace bespoke
          fetch/dedup/retry code with a declarative bronze/silver/gold flow: data-quality expectations (warn/drop/fail) gate
          malformed EDGAR feeds, retries reuse existing clusters for faster/cheaper recovery, and a queued execution mode
          serialises concurrent updates instead of erroring.
        </p>
        <p>
          <A href="https://docs.databricks.com/aws/en/jobs/run-serverless-jobs">Lakeflow Jobs</A> orchestrate the whole run
          with default auto-retry, SLA/timeout alerting, and scale-to-zero between the daily passes &mdash; a workload
          profile that suits serverless economics exactly. Dedup and watermarking use native Delta MERGE and Structured
          Streaming semantics rather than hand-rolled logic.
        </p>
      </Section>

      {/* ---------- Theme 4: governance / FSI ---------- */}
      <Section id="governance" title="Governance, trust &amp; FSI compliance" kicker={<span className="arch-chip k-govern">Governance layer</span>}>
        <p>
          <A href="https://docs.databricks.com/aws/en/data-governance/unity-catalog/">Unity Catalog</A> is the single
          control plane over every data and AI asset: ABAC access control, automatic column-level lineage (filing →
          extracted field → classification → email draft), audit-log system tables, and a Model Registry for versioned,
          aliased models. That lineage is a stronger, harder-to-fake audit trail than log files &mdash; and it is exactly
          what examiners want to see.
        </p>
        <p>
          Databricks&rsquo; <A href="https://www.databricks.com/blog/model-risk-management-2026-bankers-guide-revised-interagency-guidance">2026
          model-risk-management guide</A> maps the latest interagency guidance (the SR 11-7 successor) onto a four-layer
          architecture &mdash; governance, data/features, model, and assurance &mdash; and treats materiality tiering as
          metadata: Tier-1 (high-impact) models require dual approval, all enforced via ABAC and auditable in access logs.
          A supervisory question like &ldquo;show validation, performance, and drift for this model over 12 months&rdquo;
          resolves by querying the inventory + monitoring catalogs, with Genie letting an examiner ask it in natural
          language under row-level access filters. Guardrails (PII, jailbreak) are enforced at the gateway, centrally.
        </p>
      </Section>

      {/* ---------- Mapping table ---------- */}
      <Section id="mapping" title="Concern → Databricks product mapping">
        <div className="table-wrap" style={{ marginTop: 4 }}>
          <table className="db-map-table">
            <thead>
              <tr>
                <th>This agent&rsquo;s concern</th>
                <th>Databricks product(s)</th>
                <th>How</th>
              </tr>
            </thead>
            <tbody>
              {MAPPING.map((m) => (
                <tr key={m.concern}>
                  <td>{m.concern}</td>
                  <td className="small">{m.product}</td>
                  <td className="small" style={{ color: "var(--milford-slate)" }}>{m.how}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      {/* ---------- Gaps ---------- */}
      <Section id="gaps" title="What we&rsquo;d gain that isn&rsquo;t in the app today">
        <ul className="gap-list">
          <li><b>Vector Search / RAG grounding.</b> Retrieve prior filings and peer disclosures so a materiality call is grounded in precedent, cutting hallucinated judgments &mdash; and score groundedness directly.</li>
          <li><b>Production drift detection.</b> Lakehouse Monitoring + inference tables catch shifts in filing mix or classifier confidence over time, which offline eval never sees.</li>
          <li><b>Lineage as the audit trail.</b> Unity Catalog&rsquo;s automatic lineage is a stronger audit primitive than append-only logs &mdash; and is exactly the examiner-ready evidence the 2026 MRM guidance expects.</li>
          <li><b>Platform-level cost governance.</b> Gateway hard spend caps and per-user limits give risk/finance a backstop independent of the app&rsquo;s own code.</li>
          <li><b>A real feedback loop.</b> The Supervisor Agent&rsquo;s human-feedback learning turns operator corrections into continuous improvement, instead of a static confidence threshold.</li>
        </ul>
      </Section>

      {/* ---------- Caveats ---------- */}
      <Section id="caveats" title="Caveats &amp; honest edges">
        <ul className="list">
          <li>
            <strong>This is a vision, not a committed migration.</strong> It shows how the use case maps onto Databricks;
            it does not change how the current pipeline or portal run.
          </li>
          <li>
            <strong>Next.js on Databricks Apps is an unofficial path.</strong> Databricks officially documents React /
            Angular / Svelte / Express on the Node runtime; Next.js can run via Node standalone mode but isn&rsquo;t a
            first-class framework, so a fully-supported deployment may mean re-platforming the portal&rsquo;s UI layer.
          </li>
          <li>
            <strong>Verify dated claims against the sources.</strong> Product names, GA status, and the 2026 regulatory
            references below move quickly &mdash; each is linked so it can be checked before anyone relies on it.
          </li>
        </ul>
      </Section>

      {/* ---------- Sources ---------- */}
      <Section id="sources" title="Sources">
        <ul className="db-source-list list">
          {SOURCES.map((s) => (
            <li key={s.href}>
              <A href={s.href}>{s.label}</A>
            </li>
          ))}
        </ul>
      </Section>
    </section>
  );
}
