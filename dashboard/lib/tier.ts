// tier.ts — the single client-side source of truth for a filing's brief tier
// (material / needs_look / immaterial). Mirrors the Python side's
// src/rank.py::tier_of. Shared by FilingsTable (badging + sort), the column
// filters (lib/filingsFilters.ts), and the export module (lib/filingsExport.ts)
// so every surface agrees on the same three-way split as the summary tiles /
// email — see docs memory "brief-tiering-rule".

import type { FilingRow } from "@/lib/types";

export type Tier = "material" | "needs_look" | "immaterial";

export const TIER_LABEL: Record<Tier, string> = {
  material: "Material",
  needs_look: "Needs a look",
  immaterial: "Immaterial",
};

/** The authoritative brief tier for a row: the committed `tier` when present, else
 *  derived from materiality + flags exactly as the Python side does. Materiality wins:
 *  a material-classified filing stays material even when flagged (the flag rides along
 *  as a red "verify" chip in the Flags column). Needs-a-look is the NON-material items
 *  that still want a human eye (abstentions + flagged immaterial). Badging/sorting/
 *  filtering by this keeps the table's material count equal to the summary tile / email. */
export function tierOf(f: FilingRow): Tier {
  if (f.tier) return f.tier;
  const m = f.materiality.toLowerCase();
  if (m === "material") return "material";
  if (f.flags.length > 0 || m.includes("insufficient") || m.includes("more_info") || m.includes("needs")) {
    return "needs_look";
  }
  return "immaterial";
}

export function tierBadgeClass(tier: Tier): string {
  if (tier === "material") return "badge green";
  if (tier === "needs_look") return "badge orange";
  return "badge";
}

/** material > needs a look > immaterial, per the frozen color/priority contract. */
export function tierRank(tier: Tier): number {
  if (tier === "material") return 0;
  if (tier === "needs_look") return 1;
  return 2;
}
