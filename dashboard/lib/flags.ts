// flags.ts — TS mirror of src/flags.py. Plain-English guardrail flag
// vocabulary: every code the classifier can attach to an item maps to a
// short label plus a longer "why it matters" explanation. Keep this in
// lockstep with src/flags.py — do not invent new codes here.
//
// Note: out/filings/<date>.json already ships flags pre-rendered as
// {code, label, why} (CONTRACTS.md), so most call sites don't need this
// module at all. It exists for older/plainer surfaces (out/run_log.jsonl's
// guardrail_flag_counts, out/pdf_log.jsonl-adjacent views) that still carry
// raw codes and need to render them as plain English.

export interface FlagInfo {
  label: string;
  meaning: string;
  why: string;
}

export const FLAG_VOCAB: Record<string, FlagInfo> = {
  G2_ungrounded_quote: {
    label: "Unverified quote",
    meaning: "The supporting quote couldn't be found word-for-word in the filing.",
    why: "Possible paraphrase or model error — confirm the quote against the source before relying on it.",
  },
  G3_unverified_amount: {
    label: "Unverified figure",
    meaning: "One or more dollar/number figures the model cited couldn't be matched in the filing and were removed.",
    why: "Treat amounts as unconfirmed — check the filing for the actual numbers.",
  },
  G5_low_confidence: {
    label: "Low confidence",
    meaning: "The model's confidence was below the threshold, so the call was downgraded to 'Needs more info'.",
    why: "The signal was weak or ambiguous — a person should read the filing to decide.",
  },
  G6_directional_language: {
    label: "Advice wording removed",
    meaning: "The draft contained buy/sell-style wording, which this system may not publish.",
    why: "Wording was withheld for compliance — the underlying facts still stand; read them directly.",
  },
  G1_parse_error: {
    label: "Unreadable model output",
    meaning: "The model returned malformed output that couldn't be parsed.",
    why: "The item was retried and set aside — no classification was produced.",
  },
  G4_off_watchlist: {
    label: "Off-watchlist",
    meaning: "The filer isn't on your watchlist.",
    why: "Dropped from the brief by design.",
  },
  insufficient_info: {
    label: "Needs more info",
    meaning: "There wasn't enough in the filing to judge materiality confidently.",
    why: "Flagged for a person to review.",
  },
};

export function explainFlag(code: string): FlagInfo {
  return FLAG_VOCAB[code] ?? { label: code, meaning: code, why: "" };
}

// KIND_LABEL — display mapping for run kinds. Keep in lockstep with the
// Python-side KIND_LABEL in src/flags.py. The internal slug ("digest",
// "intraday", "backfill") stays lowercase everywhere in logic/comparisons;
// only the rendered text changes.
export const KIND_LABEL: Record<string, string> = {
  digest: "Daily digest",
  intraday: "Intraday",
  backfill: "Backfill",
};
