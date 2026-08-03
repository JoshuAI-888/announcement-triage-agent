import { Icon } from "@/components/Icon";

const ITEMS: { title: string; detail: string; icon: string }[] = [
  {
    title: "Eval concurrency: ~50 min -> ~4 min",
    detail:
      "The eval harness classifies gold items I/O-bound and in parallel (config.yaml eval.concurrency, default 12 workers, dashboard-editable 1-32). A full gold-set pass drops from roughly 50 minutes serial to roughly 4 minutes at concurrency 12. Lower it if a provider starts rate-limiting.",
    icon: "f0e7",
  },
  {
    title: "Batch API: ~50% cost discount",
    detail:
      "evals/batch.py submits every gold item as one provider batch job (Anthropic Message Batches API, or the OpenAI-compatible batch endpoint for OpenAI/GLM) instead of live calls, at roughly half the per-token price. Escalation is adaptive and can't be batched, so batch runs stay single-model.",
    icon: "f02d",
  },
  {
    title: "--runs 1, temperature 0: determinism over repetition",
    detail:
      "Classification calls run at temperature 0 (config.yaml models.temperature). With a deterministic model, one run (--runs 1) is usually enough to read the stability metric — repeat runs mainly matter for a provider whose SDK forces a non-zero default temperature (see the gpt-5.6-terra caveat on the Trust panel).",
    icon: "f2f1",
  },
  {
    title: "GLM: reasoning disabled",
    detail:
      "glm-5.x is a reasoning model by default; without extra_body.thinking.type = \"disabled\" (config.yaml providers.glm) it spends its whole token budget thinking and returns empty content. Disabling it forces direct JSON classification, which is what this harness needs.",
    icon: "f0eb",
  },
  {
    title: "Escalation: adaptive cost control",
    detail:
      "Only low-confidence classifications (below thresholds.escalate_below_confidence) or very long documents (over thresholds.escalate_above_chars) escalate to the stronger/more expensive model (models.escalation). Both thresholds are dashboard-editable, so operators can trade cost against recall directly.",
    icon: "f062",
  },
  {
    title: "Round-robin sampling for gold coverage",
    detail:
      "The 120-candidate gold draw is round-robin across native form types, grouped into a \"substantive\" pool (8-K, 10-Q, DEF 14A, SC 13D, etc.) and a \"routine\" pool (S-8, 11-K, SD...), each sized separately (config.yaml normalise.topup_groups) — a single flat round-robin under-sampled 8-Ks by a large margin on the first attempt.",
    icon: "f074",
  },
  {
    title: "Raw-document caching",
    detail:
      "Fetched raw filings are cached under data/raw/ (idempotent fetch, watermarked in state.db) and restored from the data-state branch at the start of every workflow run, so a digest, an intraday pass and an eval over overlapping announcements never re-fetch or re-pay for the same document.",
    icon: "f1c0",
  },
];

export default function OptimisationsPage() {
  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Cost & performance</p>
          <h1>Optimisations</h1>
          <p>Static reference — how the pipeline keeps eval and run costs down. Illustrative figures from PROGRESS.md / config.yaml comments, not live-measured here.</p>
        </div>
      </div>
      <div className="grid split">
        {ITEMS.map((item) => (
          <article className="card card-pad" key={item.title}>
            <div className="module-icon">
              <Icon code={item.icon} />
            </div>
            <h3 style={{ marginTop: 18 }}>{item.title}</h3>
            <p className="small muted">{item.detail}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
