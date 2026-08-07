"use client";

// Interactive reference-architecture diagram for the "On Databricks" page.
// Hover (or keyboard-focus) any component to see what it is, its function, and a
// cited Databricks reference. A continuous data-flow animation shows a filing
// travelling ingest -> classify -> eval -> serve -> app; it honours
// prefers-reduced-motion (falls back to static edges). Pure SVG/CSS — no libs.
// Content + every citation URL come from the research brief; keep them accurate.

import { useEffect, useState } from "react";

type Kind = "ingest" | "store" | "ai" | "eval" | "serve" | "app" | "govern" | "orchestrate";

interface Node {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  sub?: string;
  kind: Kind;
  what: string;
  fn: string;
  href: string;
  refLabel: string;
}

interface Edge {
  id: string;
  d: string;
  flow?: boolean; // animated data-flow spine
}

const KIND_LABEL: Record<Kind, string> = {
  ingest: "Ingestion",
  store: "Lakehouse & storage",
  ai: "AI / classification",
  eval: "Eval & observability",
  serve: "Serving & state",
  app: "Serving & UX",
  govern: "Governance",
  orchestrate: "Orchestration",
};

const NODES: Node[] = [
  {
    id: "jobs",
    x: 40, y: 24, w: 880, h: 40,
    title: "Lakeflow Jobs · Workflows",
    kind: "orchestrate",
    what: "Native, serverless orchestrator for multi-task pipelines.",
    fn: "Schedules the whole ingest → classify → eval → deliver run with default auto-retry, cluster reuse, SLA/timeout alerting, and scale-to-zero between runs — replacing hand-rolled cron and retry logic.",
    href: "https://docs.databricks.com/aws/en/jobs/run-serverless-jobs",
    refLabel: "Serverless jobs docs",
  },
  {
    id: "src",
    x: 24, y: 110, w: 150, h: 72,
    title: "EDGAR + Market APIs",
    sub: "external sources",
    kind: "ingest",
    what: "The external feeds the agent watches: SEC EDGAR filings and market price data.",
    fn: "The raw source of every filing and price the pipeline pulls in each run — the same inputs the current app fetches directly.",
    href: "https://www.sec.gov/edgar/about",
    refLabel: "About SEC EDGAR",
  },
  {
    id: "pipe",
    x: 210, y: 110, w: 160, h: 72,
    title: "Lakeflow Pipelines",
    sub: "declarative ingest",
    kind: "ingest",
    what: "Declarative bronze/silver/gold ETL framework (formerly Delta Live Tables).",
    fn: "Ingests EDGAR/market data with in-catalog data-quality expectations, dedup/watermarking via Delta MERGE, and cluster-reuse retries — reliable ingestion without bespoke fetch/dedup code.",
    href: "https://docs.databricks.com/aws/en/ldp/concepts/",
    refLabel: "Lakeflow Declarative Pipelines",
  },
  {
    id: "vol",
    x: 210, y: 214, w: 160, h: 54,
    title: "Unity Catalog Volumes",
    sub: "raw object store",
    kind: "store",
    what: "Governed object storage for non-tabular files inside Unity Catalog.",
    fn: "The catalogued, access-controlled home for raw filing PDFs/HTML and rendered briefs — same ACL/audit/lineage model as tables, replacing loose files on disk or unmanaged S3.",
    href: "https://docs.databricks.com/aws/en/volumes/",
    refLabel: "Unity Catalog Volumes",
  },
  {
    id: "lake",
    x: 406, y: 110, w: 170, h: 72,
    title: "Delta Lake + Unity Catalog",
    sub: "governed lakehouse",
    kind: "store",
    what: "Open transactional storage (Delta) under a unified governance layer (Unity Catalog).",
    fn: "Stores bronze/silver/gold filing data; Unity Catalog enforces access, tracks automatic column-level lineage, and logs every action to audit system tables.",
    href: "https://www.databricks.com/product/unity-catalog",
    refLabel: "Unity Catalog product",
  },
  {
    id: "cls",
    x: 612, y: 110, w: 170, h: 72,
    title: "Agent Bricks / AI Functions",
    sub: "materiality classifier",
    kind: "ai",
    what: "No-/low-code classification: ai_parse_document → ai_classify → ai_extract, or an Agent Bricks agent.",
    fn: "Parses each filing, classifies materiality against a taxonomy, and extracts structured rationale fields. Databricks ships a public template that runs this exact pipeline over SEC-filed documents — the closest one-to-one match for this use case.",
    href: "https://docs.databricks.com/aws/en/generative-ai/agent-bricks/idp-pipeline-tutorial",
    refLabel: "SEC document-intelligence tutorial",
  },
  {
    id: "gold",
    x: 818, y: 110, w: 118, h: 72,
    title: "Gold tables",
    sub: "verdicts + rationale",
    kind: "store",
    what: "Curated Delta tables of the final materiality verdicts and extracted fields.",
    fn: "The query-ready output the portal, Genie, and downstream models read — governed and lineage-tracked back to the source filing.",
    href: "https://docs.databricks.com/aws/en/lakehouse/medallion",
    refLabel: "Medallion architecture",
  },
  {
    id: "gate",
    x: 612, y: 214, w: 170, h: 54,
    title: "Unity AI Gateway",
    sub: "model control-plane",
    kind: "ai",
    what: "A governed control-plane in front of every model call, internal or external.",
    fn: "Routes across providers (Claude/OpenAI/…), configures fallback chains for escalation on low confidence, enforces hard spend caps and per-user rate limits, and applies PII/jailbreak guardrails — all centrally logged.",
    href: "https://www.databricks.com/product/artificial-intelligence/unity-ai-gateway",
    refLabel: "Unity AI Gateway",
  },
  {
    id: "serve",
    x: 612, y: 290, w: 170, h: 54,
    title: "Mosaic AI Model Serving",
    sub: "serverless endpoints",
    kind: "ai",
    what: "Serverless endpoint for foundation, custom, and agent models.",
    fn: "Serves whichever model is configured behind one schema, autoscales to zero, and supports champion/challenger rollout via Unity Catalog Model Registry aliases.",
    href: "https://www.databricks.com/product/artificial-intelligence",
    refLabel: "Mosaic AI",
  },
  {
    id: "mlf",
    x: 406, y: 290, w: 170, h: 54,
    title: "MLflow 3 (GenAI)",
    sub: "trace · eval · prompts",
    kind: "eval",
    what: "GenAI-native lifecycle platform: tracing, evaluation, and a prompt registry.",
    fn: "OpenTelemetry-native traces of every call (the append-only run log), built-in and custom LLM judges via make_judge() for precision/recall/grounding, and versioned prompts evaluated across models.",
    href: "https://www.databricks.com/blog/mlflow-30-unified-ai-experimentation-observability-and-governance",
    refLabel: "MLflow 3 announcement",
  },
  {
    id: "mon",
    x: 818, y: 290, w: 118, h: 54,
    title: "Lakehouse Monitoring",
    sub: "+ inference tables",
    kind: "eval",
    what: "Auto-captured request/response logging plus drift/quality monitoring.",
    fn: "Every serving call is logged to a Delta inference table; monitoring generates drift and quality metrics with dashboards and alerts — production drift detection the offline eval harness never covered.",
    href: "https://www.databricks.com/br/blog/lakehouse-monitoring-ga-profiling-diagnosing-and-enforcing-data-quality-intelligence",
    refLabel: "Lakehouse Monitoring GA",
  },
  {
    id: "lbase",
    x: 210, y: 400, w: 160, h: 72,
    title: "Lakebase",
    sub: "serverless Postgres",
    kind: "serve",
    what: "Fully managed, serverless Postgres-compatible OLTP database inside the lakehouse (built on Neon).",
    fn: "Low-latency store for runtime config, the per-run cost ledger, portal state, and the draft-email queue — governed by Unity Catalog, no bolt-on RDS/Cloud SQL.",
    href: "https://www.databricks.com/blog/announcing-databricks-lakebase-launch-partners",
    refLabel: "Lakebase launch",
  },
  {
    id: "apps",
    x: 406, y: 400, w: 170, h: 72,
    title: "Databricks Apps",
    sub: "operator portal",
    kind: "app",
    what: "Managed, serverless app-hosting runtime with built-in OAuth and governed data access.",
    fn: "Hosts the operator portal in-workspace, attaching Genie, Model Serving, and Lakebase as governed resources — no separate infra. (React/Node official; Next.js runs via the Node runtime but is an unofficial path.)",
    href: "https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/",
    refLabel: "Databricks Apps docs",
  },
  {
    id: "genie",
    x: 612, y: 400, w: 170, h: 72,
    title: "Genie",
    sub: "no-code NL queries",
    kind: "app",
    what: "Natural-language BI — governed text-to-SQL over Unity Catalog tables.",
    fn: "Lets a business user or examiner ask “show high-materiality filings with confidence < 0.7” and get governed SQL + a table/chart, with no custom UI. Drivable via API and embeddable in the App as a resource.",
    href: "https://docs.databricks.com/aws/en/dev-tools/databricks-apps/genie",
    refLabel: "Genie in Databricks Apps",
  },
  {
    id: "uc",
    x: 40, y: 520, w: 880, h: 44,
    title: "Unity Catalog — governance, lineage, audit, Model Registry",
    kind: "govern",
    what: "The unified governance layer across every data and AI asset (tables, volumes, models, prompts, functions).",
    fn: "ABAC access control, automatic lineage (filing → extracted field → classification → email draft), audit-log system tables, and the Model Registry — the examiner-ready audit trail the 2026 interagency model-risk guidance expects.",
    href: "https://docs.databricks.com/aws/en/data-governance/unity-catalog/",
    refLabel: "Unity Catalog governance",
  },
];

const EDGES: Edge[] = [
  // orchestration control (dashed, static)
  { id: "e-jobs-pipe", d: "M290,64 L290,110" },
  { id: "e-jobs-cls", d: "M697,64 L697,110" },
  // data-flow spine (animated)
  { id: "e-src-pipe", d: "M174,146 L210,146", flow: true },
  { id: "e-pipe-lake", d: "M370,146 L406,146", flow: true },
  { id: "e-lake-cls", d: "M576,146 L612,146", flow: true },
  { id: "e-cls-gold", d: "M782,146 L818,146", flow: true },
  { id: "e-pipe-vol", d: "M290,182 L290,214", flow: true },
  { id: "e-cls-gate", d: "M697,182 L697,214", flow: true },
  { id: "e-gate-serve", d: "M697,268 L697,290", flow: true },
  { id: "e-cls-mlf", d: "M655,182 C610,250 555,268 505,290", flow: true },
  { id: "e-serve-mon", d: "M782,317 L818,317", flow: true },
  { id: "e-gold-apps", d: "M877,182 C880,350 560,372 500,400", flow: true },
  // serve/app wiring
  { id: "e-apps-lbase", d: "M406,436 L370,436", flow: true },
  { id: "e-apps-genie", d: "M576,436 L612,436", flow: true },
  { id: "e-genie-lake", d: "M697,400 C700,300 560,212 498,182" },
  // governance rail (dashed, static)
  { id: "e-uc-lbase", d: "M290,520 L290,472" },
  { id: "e-uc-apps", d: "M491,520 L491,472" },
  { id: "e-uc-genie", d: "M697,520 L697,472" },
];

export function DatabricksArchitecture() {
  const [active, setActive] = useState<string | null>(null);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  const node = active ? NODES.find((n) => n.id === active) ?? null : null;

  return (
    <div className="arch-grid">
      <div className="arch-wrap">
        <svg className="arch-svg" viewBox="0 0 960 588" role="group" aria-label="Databricks reference architecture diagram">
          <defs>
            <marker id="arch-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="#9aa6ac" />
            </marker>
          </defs>

          {/* edges first so nodes sit on top */}
          {EDGES.map((e) => (
            <path
              key={e.id}
              id={e.id}
              className={`arch-edge ${e.flow ? "flow" : "control"}`}
              d={e.d}
              markerEnd="url(#arch-arrow)"
            />
          ))}

          {/* travelling data dots on the flow spine (skipped when reduced-motion) */}
          {!reduced &&
            EDGES.filter((e) => e.flow).map((e, i) => (
              <circle key={`dot-${e.id}`} className="flow-dot" r="3.4">
                <animateMotion dur={`${2 + (i % 4) * 0.5}s`} begin={`${(i % 5) * 0.3}s`} repeatCount="indefinite">
                  <mpath href={`#${e.id}`} />
                </animateMotion>
              </circle>
            ))}

          {/* nodes */}
          {NODES.map((n) => {
            const rail = n.kind === "orchestrate" || n.kind === "govern";
            return (
              <g
                key={n.id}
                className={`arch-node k-${n.kind} ${rail ? "rail" : ""} ${n.kind === "govern" ? "gov" : ""} ${active === n.id ? "active" : ""}`}
                tabIndex={0}
                role="button"
                aria-label={`${n.title}. ${KIND_LABEL[n.kind]}. ${n.what}`}
                onMouseEnter={() => setActive(n.id)}
                onFocus={() => setActive(n.id)}
              >
                <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={rail ? 6 : 9} />
                <text x={n.x + n.w / 2} y={n.y + (n.sub ? n.h / 2 - 4 : n.h / 2 + 4)} textAnchor="middle">
                  {n.title.length > 30 ? n.title : n.title}
                </text>
                {n.sub && (
                  <text className="node-sub" x={n.x + n.w / 2} y={n.y + n.h / 2 + 13} textAnchor="middle">
                    {n.sub}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
        <div className="arch-legend">
          <span><i className="dot-blue" /> Data flow (a filing moving through the pipeline)</span>
          <span><i className="dash-grey" /> Orchestration &amp; governance control</span>
        </div>
      </div>

      <aside className="arch-panel" aria-live="polite">
        {node ? (
          <>
            <span className={`arch-chip k-${node.kind}`}>{KIND_LABEL[node.kind]}</span>
            <h4>{node.title}</h4>
            <p className="arch-lbl">What it is</p>
            <p className="arch-txt">{node.what}</p>
            <p className="arch-lbl">Its function here</p>
            <p className="arch-txt">{node.fn}</p>
            <a className="arch-ref" href={node.href} target="_blank" rel="noreferrer">
              {node.refLabel} &#8599;
            </a>
          </>
        ) : (
          <>
            <h4>Interactive architecture</h4>
            <p className="arch-txt">
              Hover — or tab to and focus — any component to see what it is, what it does in this design, and a cited
              Databricks reference. The orange dots trace a single filing as it flows <strong>ingest → classify → eval →
              serve → app</strong>.
            </p>
            <p className="arch-txt muted-note">
              Every box maps to a concern the current agent already handles (cost, config, eval, observability, model
              choice, governance) — see the sections below.
            </p>
          </>
        )}
      </aside>
    </div>
  );
}
