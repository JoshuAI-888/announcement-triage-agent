// docTypes.ts — plain-English, one-sentence descriptions of common SEC form
// codes, so a reader never sees a bare "8-K" or "SC 13G" without knowing what
// it actually is. Used by the FilingsTable "Type" column tooltip and the FAQ
// glossary (single source of truth — keep both in sync by importing this).
//
// Keys are the canonical SEC form code, uppercased, with any "/A" (amended)
// suffix stripped — docTypeBlurb() normalises lookups the same way, so
// callers can pass a raw code in whatever case/shape it arrives in
// (e.g. pulled out of doc_type_label's trailing "(...)" via
// /\(([^)]+)\)$/, which may read "8-K", "Form 4", or "SC 13D").

export interface DocTypeEntry {
  code: string; // canonical display code, e.g. "8-K"
  blurb: string; // one plain-English sentence
}

// Canonical lookup keys (normalised: uppercase, no "/A", no "FORM "/"SC " prefix).
const DOC_TYPE_BLURBS: Record<string, DocTypeEntry> = {
  "8-K": {
    code: "8-K",
    blurb:
      "A same-day report a public company must file when a major event happens — a big deal, an executive change, a bankruptcy — so investors hear about it quickly instead of waiting for the next quarterly report.",
  },
  "10-K": {
    code: "10-K",
    blurb: "The company's audited annual report — a full fiscal year of financial results, risk factors, and business detail.",
  },
  "10-Q": {
    code: "10-Q",
    blurb: "A quarterly report with unaudited financial statements and an update on the business since the last 10-K or 10-Q.",
  },
  "6-K": {
    code: "6-K",
    blurb:
      "A report a foreign private issuer files to share information it's already required to disclose at home — roughly the foreign-issuer equivalent of an 8-K.",
  },
  "20-F": {
    code: "20-F",
    blurb: "The annual report foreign private issuers file instead of a 10-K, covering a full fiscal year of financials and business detail.",
  },
  "3": {
    code: "Form 3",
    blurb: "An insider's first filing after becoming an officer, director, or 10%+ owner, disclosing their initial stake in the company.",
  },
  "4": {
    code: "Form 4",
    blurb: "A filing an insider (officer, director, or large owner) submits within two business days of buying or selling company stock.",
  },
  "5": {
    code: "Form 5",
    blurb: "An annual catch-all filing for insider stock transactions that weren't already reported during the year on a Form 4.",
  },
  "144": {
    code: "Form 144",
    blurb: "A notice an insider files before selling a significant amount of restricted or control stock, ahead of the actual sale.",
  },
  "S-1": {
    code: "S-1",
    blurb:
      "The registration statement a company files before its initial public offering (IPO), describing the business, risks, and how the shares will be sold.",
  },
  "S-3": {
    code: "S-3",
    blurb:
      "A simplified 'shelf' registration statement that lets an already-public, SEC-seasoned company register securities to sell over time without a full S-1 each time.",
  },
  "S-4": {
    code: "S-4",
    blurb:
      "A registration statement for securities issued in a merger, acquisition, or exchange offer, describing the deal terms for the holders being asked to vote or exchange.",
  },
  "424B": {
    code: "424B",
    blurb: "A prospectus supplement filed once a registration statement is effective, giving the final price and terms of a securities offering.",
  },
  "DEF 14A": {
    code: "DEF 14A",
    blurb:
      "The definitive proxy statement sent to shareholders ahead of a shareholder meeting — what's up for a vote: board elections, executive pay, mergers, and more.",
  },
  "13D": {
    code: "SC 13D",
    blurb: "A filing disclosing that an investor has acquired more than 5% of a company's stock with an intent to influence or control it.",
  },
  "13G": {
    code: "SC 13G",
    blurb: "A shorter filing disclosing a 5%+ ownership stake by a passive investor who isn't seeking to influence or control the company.",
  },
  "13F-HR": {
    code: "13F-HR",
    blurb: "A quarterly report institutional investment managers file listing the U.S. equity holdings they manage.",
  },
  SD: {
    code: "SD",
    blurb: "A 'Specialized Disclosure' report — most commonly used for the conflict-minerals disclosures required of certain manufacturers.",
  },
  ARS: {
    code: "ARS",
    blurb: "The annual report to shareholders — the financial-highlights document sent to shareholders, often filed alongside the DEF 14A proxy.",
  },
  FWP: {
    code: "FWP",
    blurb: "A 'free writing prospectus' — supplemental marketing material about a securities offering that isn't part of the formal prospectus itself.",
  },
};

/** Ordered list for display (e.g. the FAQ glossary table). */
export const DOC_TYPE_LIST: DocTypeEntry[] = [
  "8-K",
  "10-K",
  "10-Q",
  "6-K",
  "20-F",
  "3",
  "4",
  "5",
  "144",
  "S-1",
  "S-3",
  "S-4",
  "424B",
  "DEF 14A",
  "13D",
  "13G",
  "13F-HR",
  "SD",
  "ARS",
  "FWP",
].map((k) => DOC_TYPE_BLURBS[k]);

function normalise(raw: string): string {
  return raw.trim().toUpperCase().replace(/\/A$/, "");
}

/**
 * Plain-English one-sentence blurb for an SEC form code. Accepts common
 * variants — "8-K", "8-K/A", "Form 4", "SC 13D", "424B3" — and normalises
 * case and amendment suffixes before matching. Returns null if unrecognised.
 */
export function docTypeBlurb(code: string | null | undefined): string | null {
  if (!code) return null;
  const c = normalise(code);

  if (DOC_TYPE_BLURBS[c]) return DOC_TYPE_BLURBS[c].blurb;

  const noForm = c.replace(/^FORM\s+/, "");
  if (DOC_TYPE_BLURBS[noForm]) return DOC_TYPE_BLURBS[noForm].blurb;

  const noSc = c.replace(/^SC\s+/, "");
  if (DOC_TYPE_BLURBS[noSc]) return DOC_TYPE_BLURBS[noSc].blurb;

  if (c.startsWith("424B")) return DOC_TYPE_BLURBS["424B"].blurb;

  return null;
}

/** Extracts the trailing "(CODE)" out of a friendly label like "Material event report (8-K)". */
export function extractFormCode(label: string | null | undefined): string | null {
  if (!label) return null;
  const m = label.match(/\(([^)]+)\)$/);
  return m ? m[1] : null;
}
