---
name: milford-core-portal-design
description: Build, extend, or review an authenticated Milford corporate internal portal in standalone HTML or production frontend code. Use for Milford dashboards, research libraries, funds, holdings, investment-team directories, documents, approvals, internal tools, administration, login screens, navigation shells, tables, filters, and internal workflow UI that must follow Milford's exact logo, typography, colors, product accents, spacing, and component language.
---

# Milford Core Portal Design

Build from the supplied Milford system. Do not invent a new palette, logo treatment, navigation model, radius system, or type hierarchy.

## Workflow

1. Read `references/brand-language.md` before changing visible UI.
2. Read `references/portal-architecture.md` when adding routes, navigation, tables, workflows, or responsive behavior.
3. Read `references/portfolio-analytics.md` for portfolio-manager, quant, attribution, risk, commentary, and company-relationship work.
4. Read `references/template-map.md` to choose a starting file.
5. Copy the closest template with `scripts/scaffold.py`; preserve all asset-relative paths.
6. Replace illustrative content with the user's real content. Keep the hierarchy and component rules unless the request explicitly changes them.
7. Make primary navigation, search, filters, tabs, forms, menus, approvals, and visible states work. Do not leave the core workflow as static chrome.
8. Check desktop at 1440 px, tablet at 1024 px, and mobile at 390 px. Check keyboard focus, contrast, overflow, empty states, and print behavior.
9. Keep browser-only templates free of external dependencies so `file://` preview works.

## Required Assets

- Use `assets/brand/milfordasset.svg` for the Milford mark. Never redraw it.
- Use the supplied Glypha and Montserrat font files through `assets/styles/milford-system.css`.
- Use the bundled Font Awesome font for standard UI icons. Do not substitute emoji or handmade SVG icons.
- Use only Milford-sourced imagery in `assets/brand/` unless the user explicitly supplies another approved source.

## Product Accents

- Use blue `#1c99d6` for KiwiSaver classification and data cues.
- Use green `#4bc864` for Investment Funds classification and data cues.
- Use purple `#915fb4` for wealth or private-client classification.
- Use orange `#e1690e` for the master-brand action, active focus, or high-attention workflow cue.
- Keep the shell slate-first. Product colors classify content; they do not recolor the entire portal.

## Output Contract

- Keep deliverables self-contained and runnable from disk.
- Reuse CSS variables and existing components before adding new values.
- Mark mock data as illustrative.
- Never imply that authentication, authorisation, data persistence, audit logging, or regulatory controls are production-ready unless those systems are actually implemented.
- Preserve the source provenance recorded in `references/asset-provenance.md`.
