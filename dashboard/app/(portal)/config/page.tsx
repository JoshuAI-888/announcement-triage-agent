"use client";

// Config UI (CONTRACTS.md §7 build brief item 2). Loads the live
// runtime_config.json, lets the operator edit the full editable surface, and
// POSTs to /api/config on save — the server (lib/schema.ts, mirroring
// src/config_schema.py) is the authority on validity; this form does light
// client-side checks only for a fast fail before that round trip.

import { useCallback, useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import type { RuntimeConfig } from "@/lib/types";

type SaveState = { kind: "idle" } | { kind: "saving" } | { kind: "ok"; message: string } | { kind: "error"; errors: string[] };

export default function ConfigPage() {
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>({ kind: "idle" });
  const [watchlistInput, setWatchlistInput] = useState("");
  const [mode, setMode] = useState<string>("");

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const res = await fetch("/api/config");
      const body = await res.json();
      if (!res.ok) throw new Error(body.message || "failed to load config");
      setConfig(body.config);
      setMode(body.mode);
    } catch (e) {
      setLoadError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loadError) {
    return (
      <section>
        <div className="banner banner-danger">
          <Icon code="f071" />
          <span>Could not load config: {loadError}</span>
        </div>
      </section>
    );
  }
  if (!config) {
    return (
      <section>
        <p className="muted">Loading configuration…</p>
      </section>
    );
  }

  async function save() {
    if (!config) return;
    setSaveState({ kind: "saving" });
    try {
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      const body = await res.json();
      if (!res.ok) {
        setSaveState({ kind: "error", errors: body.errors || [body.message || "save failed"] });
        return;
      }
      setConfig(body.config);
      setSaveState({
        kind: "ok",
        message: body.mocked ? `Saved locally as version ${body.config.version} (mocked — see server console).` : `Committed version ${body.config.version} to main.`,
      });
    } catch (e) {
      setSaveState({ kind: "error", errors: [(e as Error).message] });
    }
  }

  async function revert() {
    setSaveState({ kind: "saving" });
    try {
      const res = await fetch("/api/config/revert", { method: "POST" });
      const body = await res.json();
      if (!res.ok) {
        setSaveState({ kind: "error", errors: [body.message || "revert failed"] });
        return;
      }
      setConfig(body.config);
      setSaveState({ kind: "ok", message: `Reverted to version ${body.config.version}.` });
    } catch (e) {
      setSaveState({ kind: "error", errors: [(e as Error).message] });
    }
  }

  function patchRun(partial: Partial<RuntimeConfig["run"]>) {
    setConfig((c) => (c ? { ...c, run: { ...c.run, ...partial } } : c));
  }
  function patchEval(partial: Partial<RuntimeConfig["eval"]>) {
    setConfig((c) => (c ? { ...c, eval: { ...c.eval, ...partial } } : c));
  }
  function patchSchedule(partial: Partial<RuntimeConfig["schedule"]>) {
    setConfig((c) => (c ? { ...c, schedule: { ...c.schedule, ...partial } } : c));
  }
  function patchDraft(partial: Partial<RuntimeConfig["draft"]>) {
    setConfig((c) => (c ? { ...c, draft: { ...c.draft, ...partial } } : c));
  }
  function patchThresholds(partial: Partial<RuntimeConfig["thresholds"]>) {
    setConfig((c) => (c ? { ...c, thresholds: { ...c.thresholds, ...partial } } : c));
  }
  function patchRanking(partial: Partial<RuntimeConfig["ranking"]>) {
    setConfig((c) => (c ? { ...c, ranking: { ...c.ranking, ...partial } } : c));
  }
  function patchMaterialityWeight(key: string, value: number) {
    setConfig((c) => (c ? { ...c, ranking: { ...c.ranking, materiality_weight: { ...c.ranking.materiality_weight, [key]: value } } } : c));
  }
  function patchTop(partial: Partial<RuntimeConfig>) {
    setConfig((c) => (c ? { ...c, ...partial } : c));
  }

  function addTicker() {
    const t = watchlistInput.trim().toUpperCase();
    if (!t || !config) return;
    if (!config.watchlist.includes(t)) {
      patchTop({ watchlist: [...config.watchlist, t] });
    }
    setWatchlistInput("");
  }
  function removeTicker(t: string) {
    if (!config) return;
    patchTop({ watchlist: config.watchlist.filter((x) => x !== t) });
  }

  const overrideActive = !!config.run.classification_prompt_override;

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Configuration</p>
          <h1>Runtime config</h1>
          <p>
            Editable overlay on config.yaml (version {config.version}, {mode === "local-dev" ? "local dev — saves mocked" : "live on main"}
            ).
          </p>
        </div>
        <div className="actions">
          <button className="btn secondary" type="button" onClick={revert} disabled={saveState.kind === "saving"}>
            <Icon code="f0e2" /> Revert to previous
          </button>
          <button className="btn" type="button" onClick={save} disabled={saveState.kind === "saving"}>
            <Icon code="f0c7" /> {saveState.kind === "saving" ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>

      {saveState.kind === "ok" && (
        <div className="banner banner-info">
          <Icon code="f058" />
          <span>{saveState.message}</span>
        </div>
      )}
      {saveState.kind === "error" && (
        <div className="banner banner-danger">
          <Icon code="f071" />
          <div>
            <strong>Save failed.</strong>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {saveState.errors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <article className="card card-pad config-section">
        <h2>Run</h2>
        <p className="section-intro">Which provider and prompt classify announcements in the daily/intraday run.</p>
        <div className="config-form-grid">
          <div className="field">
            <label>Provider</label>
            <select className="select" value={config.run.provider} onChange={(e) => patchRun({ provider: e.target.value as RuntimeConfig["run"]["provider"] })}>
              <option value="claude">claude</option>
              <option value="openai">openai</option>
              <option value="glm">glm</option>
            </select>
          </div>
          <div className="field">
            <label>Prompt version</label>
            <select
              className="select"
              value={config.run.prompt_version}
              onChange={(e) => patchRun({ prompt_version: e.target.value as RuntimeConfig["run"]["prompt_version"] })}
            >
              <option value="v1">v1</option>
              <option value="v2">v2</option>
              <option value="v3">v3</option>
              <option value="custom">custom</option>
            </select>
          </div>
          <div className="field span-2">
            <label>Classifier prompt override (optional, max 20,000 chars)</label>
            <div className="banner banner-warning" style={{ marginBottom: 10 }}>
              <Icon code="f071" />
              <span>Editing this invalidates the trust numbers until you re-run the eval &mdash; it changes the eval fingerprint (see Trust panel).</span>
            </div>
            <textarea
              className="input"
              rows={6}
              maxLength={20000}
              value={config.run.classification_prompt_override ?? ""}
              onChange={(e) => patchRun({ classification_prompt_override: e.target.value.length ? e.target.value : null })}
              placeholder="Leave blank to use the built-in prompt for the selected version."
            />
            <div className="char-count">
              {(config.run.classification_prompt_override ?? "").length} / 20000 {overrideActive ? "— override active" : ""}
            </div>
          </div>
        </div>
      </article>

      <article className="card card-pad config-section">
        <h2>Eval</h2>
        <p className="section-intro">Provider and concurrency for the gold-set eval harness (not the daily run).</p>
        <div className="config-form-grid">
          <div className="field">
            <label>Provider</label>
            <select className="select" value={config.eval.provider} onChange={(e) => patchEval({ provider: e.target.value as RuntimeConfig["eval"]["provider"] })}>
              <option value="claude">claude</option>
              <option value="openai">openai</option>
              <option value="glm">glm</option>
            </select>
          </div>
          <div className="field">
            <label>Concurrency (1&ndash;32)</label>
            <input
              className="input"
              type="number"
              min={1}
              max={32}
              value={config.eval.concurrency}
              onChange={(e) => patchEval({ concurrency: parseInt(e.target.value, 10) || 1 })}
            />
          </div>
        </div>
      </article>

      <article className="card card-pad config-section">
        <h2>Schedule</h2>
        <p className="section-intro">Read by scripts/ci_gate.py on every 15-minute cron tick to decide digest / intraday / skip.</p>
        <div className="config-form-grid">
          <div className="field">
            <label>Poll time (NZT, 24h)</label>
            <input className="input" type="time" value={config.schedule.poll_time_nzt} onChange={(e) => patchSchedule({ poll_time_nzt: e.target.value })} />
          </div>
          <div className="field">
            <label>Poll frequency</label>
            <select className="select" value={config.schedule.poll_frequency} onChange={(e) => patchSchedule({ poll_frequency: e.target.value as RuntimeConfig["schedule"]["poll_frequency"] })}>
              <option value="daily">daily</option>
              <option value="hourly">hourly</option>
            </select>
          </div>
          <div className="field checkbox-field span-2">
            <input
              id="intraday_alerts"
              type="checkbox"
              checked={config.schedule.intraday_alerts}
              onChange={(e) => patchSchedule({ intraday_alerts: e.target.checked })}
            />
            <label htmlFor="intraday_alerts" style={{ marginBottom: 0 }}>
              Intraday alerts (material-only alert pass between digests)
            </label>
          </div>
        </div>
      </article>

      <article className="card card-pad config-section">
        <h2>Draft email</h2>
        <p className="section-intro">Recipient and system prompt for the rendered brief.</p>
        <div className="config-form-grid">
          <div className="field span-2">
            <label>Recipient email</label>
            <input className="input" type="email" value={config.draft.email} onChange={(e) => patchDraft({ email: e.target.value })} />
          </div>
          <div className="field span-2">
            <label>Draft prompt (max 8,000 chars)</label>
            <textarea
              className="input"
              rows={6}
              maxLength={8000}
              value={config.draft.prompt}
              onChange={(e) => patchDraft({ prompt: e.target.value })}
            />
            <div className="char-count">{config.draft.prompt.length} / 8000</div>
          </div>
        </div>
      </article>

      <article className="card card-pad config-section">
        <h2>Thresholds</h2>
        <p className="section-intro">Confidence floor, escalation trigger, and document-length escalation trigger.</p>
        <div className="config-form-grid">
          <div className="field">
            <label>Confidence floor (0&ndash;1)</label>
            <input
              className="input"
              type="number"
              step={0.01}
              min={0}
              max={1}
              value={config.thresholds.confidence_floor}
              onChange={(e) => patchThresholds({ confidence_floor: parseFloat(e.target.value) })}
            />
          </div>
          <div className="field">
            <label>Escalate below confidence (0&ndash;1)</label>
            <input
              className="input"
              type="number"
              step={0.01}
              min={0}
              max={1}
              value={config.thresholds.escalate_below_confidence}
              onChange={(e) => patchThresholds({ escalate_below_confidence: parseFloat(e.target.value) })}
            />
          </div>
          <div className="field">
            <label>Escalate above chars</label>
            <input
              className="input"
              type="number"
              min={0}
              step={1000}
              value={config.thresholds.escalate_above_chars}
              onChange={(e) => patchThresholds({ escalate_above_chars: parseInt(e.target.value, 10) || 0 })}
            />
          </div>
        </div>
      </article>

      <article className="card card-pad config-section">
        <h2>Ranking</h2>
        <p className="section-intro">Recency decay, materiality weighting, and the default watchlist weight.</p>
        <div className="config-form-grid">
          <div className="field">
            <label>Recency half-life (hours, &gt; 0)</label>
            <input
              className="input"
              type="number"
              min={0.1}
              step={0.5}
              value={config.ranking.recency_half_life_hours}
              onChange={(e) => patchRanking({ recency_half_life_hours: parseFloat(e.target.value) })}
            />
          </div>
          <div className="field">
            <label>Watchlist weight default (&ge; 0)</label>
            <input
              className="input"
              type="number"
              min={0}
              step={0.1}
              value={config.ranking.watchlist_weight_default}
              onChange={(e) => patchRanking({ watchlist_weight_default: parseFloat(e.target.value) })}
            />
          </div>
          <div className="field span-2">
            <label>Materiality weight</label>
            <div className="kv-editor">
              {Object.entries(config.ranking.materiality_weight).map(([k, v]) => (
                <div className="kv-row" key={k}>
                  <label htmlFor={`mw-${k}`}>{k}</label>
                  <input
                    id={`mw-${k}`}
                    className="input"
                    type="number"
                    step={0.05}
                    value={v}
                    onChange={(e) => patchMaterialityWeight(k, parseFloat(e.target.value))}
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
      </article>

      <article className="card card-pad config-section">
        <h2>Watchlist ({config.watchlist.length} tickers)</h2>
        <p className="section-intro">Uppercase, unique tickers. Type a ticker and press Enter or click Add.</p>
        <div style={{ display: "flex", gap: 8, maxWidth: 360 }}>
          <input
            className="input"
            value={watchlistInput}
            onChange={(e) => setWatchlistInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addTicker();
              }
            }}
            placeholder="e.g. AAPL"
          />
          <button className="btn secondary" type="button" onClick={addTicker}>
            Add
          </button>
        </div>
        <div className="chip-list">
          {config.watchlist.map((t) => (
            <span className="chip" key={t}>
              {t}
              <button type="button" aria-label={`Remove ${t}`} onClick={() => removeTicker(t)}>
                &times;
              </button>
            </span>
          ))}
        </div>
      </article>

      <article className="card card-pad config-section">
        <h2>Other</h2>
        <div className="config-form-grid">
          <div className="field">
            <label>News mode</label>
            <select className="select" value={config.news_mode} onChange={(e) => patchTop({ news_mode: e.target.value as RuntimeConfig["news_mode"] })}>
              <option value="search">search</option>
              <option value="resolved">resolved</option>
              <option value="off">off</option>
            </select>
          </div>
          <div className="field">
            <label>Items shown (1&ndash;100)</label>
            <input
              className="input"
              type="number"
              min={1}
              max={100}
              value={config.items_shown}
              onChange={(e) => patchTop({ items_shown: parseInt(e.target.value, 10) || 1 })}
            />
          </div>
          <div className="field">
            <label>Theme</label>
            <input className="input" value={config.theme} onChange={(e) => patchTop({ theme: e.target.value })} />
            <span className="hint">Only &ldquo;milford&rdquo; is themed today.</span>
          </div>
        </div>
      </article>

      <div className="form-actions">
        <button className="btn secondary" type="button" onClick={revert} disabled={saveState.kind === "saving"}>
          <Icon code="f0e2" /> Revert to previous
        </button>
        <button className="btn" type="button" onClick={save} disabled={saveState.kind === "saving"}>
          <Icon code="f0c7" /> {saveState.kind === "saving" ? "Saving…" : "Save changes"}
        </button>
        {saveState.kind === "ok" && <span className="save-status ok">{saveState.message}</span>}
      </div>
    </section>
  );
}
