import { FLAG_VOCAB } from "@/lib/flags";
import { MODEL_TIERS } from "@/lib/models";

export const dynamic = "force-static";

const GLOSSARY: { term: string; def: string }[] = [
  { term: "EDGAR", def: "The SEC's public filing system. Every 8-K, 10-K, Form 4, etc. lands here first — it's the source the agent watches." },
  { term: "Watchlist", def: "The set of tickers you care about (S&P 500 + your original names). Filings from companies not on it are dropped from the brief (see 'Off-watchlist')." },
  { term: "Filing / announcement", def: "A single document a company submitted to the SEC. The agent fetches the new ones, reads them, and classifies each." },
  { term: "Digest", def: "The Daily digest: the once-a-day batch that fetches everything new on the watchlist since yesterday, classifies it all, and produces one consolidated brief. This is the main morning deliverable." },
  { term: "Intraday", def: "A lighter mid-day pass that only surfaces newly-arrived material items as an alert. It never rewrites the Daily digest." },
  { term: "Backfill", def: "A manually-triggered run over a chosen past window (an as-of date and a lookback in days). It fetches and classifies that window in isolation and never moves the live watermark used by the Daily digest." },
  { term: "Material", def: "The agent judged this filing likely to matter to an investor in that name (e.g. an M&A completion, earnings, a major agreement or executive change). Material items are ranked at the top of the brief." },
  { term: "Immaterial", def: "Routine or administrative — judged unlikely to move the investment view (e.g. a boilerplate ownership form). Kept in the all-filings table for completeness, not surfaced as a headline." },
  { term: "Needs a look / Needs more info", def: "The agent wasn't confident enough to call it either way — weak signal, a guardrail fired, or only metadata was available. Routed to a human rather than trusted automatically." },
  { term: "Confidence", def: "A 0–1 score the model assigns to its own materiality call — how sure it is, given the text it was shown. It is NOT the probability the event matters to markets; it's the model's certainty about its classification." },
  { term: "Escalation", def: "When the first-pass model is unsure (confidence below a threshold) or the document is very long, the filing can be re-read by a stronger model (Opus). Escalation is currently OFF for the daily run to control cost." },
  { term: "Guardrail", def: "An automatic safety check applied after classification — e.g. verifying that a quoted sentence actually appears in the filing. When one fires, the item is flagged in plain English and usually routed to 'Needs a look'." },
  { term: "8-K item codes", def: "8-K filings carry numbered item codes for what happened — 2.02 results, 1.01 a material agreement, 5.02 executive departures, 8.01 other events. The agent uses these as signal even when the document body is a PDF it can't fully read." },
  { term: "XBRL", def: "Structured financial data tagged inside filings (the numbers). Distinct from the narrative text the agent reads for materiality." },
  { term: "SIC", def: "The SEC's Standard Industrial Classification — the authoritative industry label for a company, shown next to each name in the brief." },
  { term: "OCR", def: "Optical Character Recognition — reading text out of a scanned/image PDF. When a filing is a no-text-layer PDF, the agent can hand it to Claude to transcribe. See the PDF / OCR log page." },
  { term: "Brief", def: "The rendered email/HTML the agent produces each run: ranked material items with company context and prices, the 'needs a look' list, and the all-filings table. The portal embeds this exact HTML." },
  { term: "Trust / staleness", def: "The evaluation summary measures the agent against a fixed gold set. If the live config's fingerprint no longer matches what was last evaluated, the Trust page flags the numbers as stale." },
];

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <div className="card card-pad" id={id} style={{ marginBottom: 18 }}>
      <h2 style={{ marginTop: 0, fontSize: 18 }}>{title}</h2>
      {children}
    </div>
  );
}

export default function FaqPage() {
  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Reference</p>
          <h1>How it works — FAQ &amp; glossary</h1>
          <p>What this agent does, how a filing becomes a brief, how confidence and the AI models work, and what every key term means.</p>
        </div>
      </div>

      <div className="card card-pad" style={{ marginBottom: 18 }}>
        <strong className="small">On this page</strong>
        <p className="small" style={{ margin: "6px 0 0" }}>
          <a href="#intent">What it is</a> · <a href="#flow">The flow</a> · <a href="#architecture">Architecture</a> ·{" "}
          <a href="#digest">Daily digest vs intraday</a> · <a href="#confidence">Confidence</a> · <a href="#models">The AI models</a> ·{" "}
          <a href="#guardrails">Guardrails</a> · <a href="#glossary">Glossary</a>
        </p>
      </div>

      <Section id="intent" title="What this is, and why">
        <p>
          This is an <strong>SEC announcement-triage agent</strong> for an investment team. Hundreds of filings hit SEC EDGAR
          every day across the watchlist; almost all are routine. The agent&#39;s job is to read them all, surface the few that
          are <strong>material</strong>, explain <em>why</em> in plain language with the company context and current price, and
          route anything ambiguous to a human — so an analyst starts the morning with a short, self-explaining brief instead of
          a firehose. It is a triage and drafting tool, not an advice engine: it never issues buy/sell calls, and every material
          call is meant to be checked against the linked source.
        </p>
      </Section>

      <Section id="flow" title="The flow — how a filing becomes a brief">
        <ol style={{ margin: 0, paddingLeft: 20, lineHeight: 1.7 }}>
          <li><strong>Fetch.</strong> Pull everything new on EDGAR for the watchlist since the last run (past a saved watermark, so nothing is read twice).</li>
          <li><strong>Normalise.</strong> Extract the readable text. If the primary document is a PDF, try a text-layer read, then Claude OCR, else fall back to the filing&#39;s metadata (form + 8-K item codes) so it&#39;s never silently dropped.</li>
          <li><strong>Classify.</strong> The first-pass model reads each filing and returns material / immaterial / needs-more-info, a confidence score, a rationale, and a supporting quote.</li>
          <li><strong>Guardrails.</strong> Automatic checks verify the quote and figures against the source and strip advice-style wording. Anything that fails is flagged in plain English.</li>
          <li><strong>Rank.</strong> Material items are scored and ordered; off-watchlist filers are dropped.</li>
          <li><strong>Enrich.</strong> Material items get an AI company profile (business + competitive edge), the latest price with a 7-day trend, and clickable source links.</li>
          <li><strong>Publish.</strong> Render the brief (email HTML + a per-run all-filings JSON), commit it, and the portal displays it. Delivery drafts it into Gmail for review.</li>
        </ol>
      </Section>

      <Section id="architecture" title="Architecture — what runs where">
        <p>Two schedulers, kept deliberately separate:</p>
        <ul style={{ lineHeight: 1.7 }}>
          <li>
            <strong>Generation — GitHub Actions (always-on, server-side).</strong> A workflow runs on a cron, decides Daily digest / intraday / skip,
            does the whole pipeline above, and commits the brief + logs to the <span className="mono">main</span> branch. This needs no device of yours to be on.
          </li>
          <li>
            <strong>This portal — Vercel.</strong> A read-only Next.js app that reads those committed artifacts (briefs, run log, filings JSON, eval summary)
            live from GitHub via the API. It doesn&#39;t run the pipeline; it shows what the pipeline produced, and lets you trigger a run or change config (which commit back to <span className="mono">main</span>).
          </li>
          <li>
            <strong>Delivery — a routine.</strong> A daily routine reads the latest committed brief and drafts it into Gmail <em>for review</em> (never auto-sends).
          </li>
        </ul>
        <p className="small muted">Because the portal only ever <em>reads</em> committed files, what you see here is exactly what the server produced — there&#39;s no separate live database to drift out of sync.</p>
      </Section>

      <Section id="digest" title="What “Daily digest” means (vs intraday)">
        <p>
          A <strong>Daily digest</strong> is the once-daily consolidated brief: it fetches the last N days of filings (the configured lookback
          window), classifies all of it, and produces one ranked brief — the main morning deliverable. An <strong>intraday</strong> run is a
          lighter mid-day pass that only alerts on newly-arrived <em>material</em> items and never rewrites the Daily digest. A{" "}
          <strong>Backfill</strong> is a manually-triggered run over a past window that never disturbs the live schedule. On the{" "}
          <a href="/history">Run history</a> page each workflow run is labelled with which it did (or <em>skip</em>, when the schedule gate
          decided it wasn&#39;t time yet), and you can open the exact brief HTML a run produced.
        </p>
      </Section>

      <Section id="confidence" title="How confidence is rated">
        <p>
          Every classification carries a <strong>confidence score from 0 to 1</strong> — the model&#39;s own estimate of how sure it is that its
          materiality call is right, <em>given the filing text it was shown</em>. Two things to keep in mind:
        </p>
        <ul style={{ lineHeight: 1.7 }}>
          <li>It is <strong>not</strong> a probability that the event will move the market — it&#39;s the model&#39;s certainty about its own label.</li>
          <li>Low confidence (below a configurable floor) downgrades the item to <strong>Needs a look</strong> rather than trusting it, and — when escalation is on — can trigger a re-read by a stronger model.</li>
        </ul>
        <p className="small muted">The confidence floor and escalation triggers are on the <a href="/config">Config</a> page. The <a href="/trust">Trust</a> page shows how the current settings scored against the fixed gold evaluation set.</p>
      </Section>

      <Section id="models" title="The AI models — what each actually does">
        <p>The daily run uses a two-tier setup so the bulk work is cheap and the careful re-reads are reserved for hard cases:</p>
        <div className="table-wrap" style={{ marginTop: 10 }}>
          <table>
            <thead>
              <tr><th>Model</th><th>What it does here</th></tr>
            </thead>
            <tbody>
              {MODEL_TIERS.map((m) => (
                <tr key={m.label}>
                  <td className="small"><strong>{m.label}</strong></td>
                  <td className="small">{m.role}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted" style={{ marginTop: 10 }}>
          Two more models sit outside the classifier: <strong>Claude Haiku</strong> also handles PDF OCR and the one-off company-profile lines (pinned to Claude regardless of the chosen provider).
          On <a href="/history">Run history</a>, hover the model name in any row to see its role.
        </p>
      </Section>

      <Section id="guardrails" title="Guardrails — the plain-English flags">
        <p>After classification, automatic checks can flag an item. You never see a raw code (like “G2”) — each maps to a plain-English label:</p>
        <div className="table-wrap" style={{ marginTop: 10 }}>
          <table>
            <thead>
              <tr><th>Flag</th><th>What it means</th><th>Why it matters</th></tr>
            </thead>
            <tbody>
              {Object.values(FLAG_VOCAB).map((f) => (
                <tr key={f.label}>
                  <td className="small"><span className="badge orange">{f.label}</span></td>
                  <td className="small">{f.meaning}</td>
                  <td className="small muted">{f.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section id="glossary" title="Glossary — key terms">
        <dl style={{ margin: 0 }}>
          {GLOSSARY.map((g) => (
            <div key={g.term} style={{ marginBottom: 12 }}>
              <dt style={{ fontWeight: 700, color: "var(--milford-slate)" }}>{g.term}</dt>
              <dd style={{ margin: "2px 0 0", color: "var(--milford-muted, #46545b)", fontSize: 14, lineHeight: 1.6 }}>{g.def}</dd>
            </div>
          ))}
        </dl>
      </Section>
    </section>
  );
}
