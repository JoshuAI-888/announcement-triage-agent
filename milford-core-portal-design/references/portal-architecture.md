# Portal architecture

## Authenticated shell

- Use a 244 px slate sidebar at desktop and a 72 px white top bar.
- Place the Milford logo first, the workspace label second, primary modules third, and signed-in identity last.
- Collapse to an icon rail at tablet and an off-canvas drawer on mobile.
- Put global search in the top bar. Search must lead to a useful result surface, not a decorative field.

## Navigation order

1. Dashboard
2. Research library
3. Funds
4. Holdings
5. Portfolio analytics
6. Investment teams
7. Documents
8. Approvals
9. Tools
10. Administration

Keep Tools and Administration below a divider. Show a count only for actionable work such as approvals.

## Components

- Page header: eyebrow, Glypha title, one-line context, then at most two page actions.
- Metric card: label, value, status/context. Never show an unlabeled number.
- Table: sticky or persistent header where useful, left-align names, right-align numbers, expose filter state.
- Badge: use only for compact state, product, risk, or approval labels.
- Approval row: show item, stage, requester, due date, and clear action.
- Empty state: explain why it is empty and offer the relevant next action.
- Research record: show title, type, team, author, status, and update date.
- Fund record: show product parent, strategy/risk, period, and data date.
- Portfolio analytics: show portfolio, benchmark, period, return basis, model date, source state, role view, and required action.

## Interaction states

Implement default, hover, focus-visible, selected, disabled, loading, empty, error, and success where the workflow exposes them. Keep focus orange and visible. Do not communicate status by color alone.

## Data density

Default to compact tables and 12–16 px row padding. Prefer a table when users must compare repeated fields. Prefer cards only for summaries, distinct objects, or entry points.

## Print

Hide navigation and filters. Print only the active view. Remove shadows and preserve product colors with `print-color-adjust: exact`.
