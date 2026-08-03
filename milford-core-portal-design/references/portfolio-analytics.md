# Portfolio analytics and role requirements

Use this reference when building portfolio-manager, quant, performance, risk, attribution, security-network, or required-commentary workflows. The supplied dashboard is an illustrative design template; connect it to governed sources before using any result for an investment decision.

## Decision hierarchy

Lead with the decision, then portfolio outcome, then drivers, then risk, then evidence and required action. Do not create a wall of metrics with no accountable decision.

Every view must expose:

- portfolio and parent product;
- benchmark and benchmark version;
- reporting period and data timestamp;
- return basis, currency, fee and tax basis;
- source/reconciliation state;
- risk or attribution model and model date;
- owner, reviewer, commentary status and next action.

## Portfolio manager view

The PM must be able to answer: what happened, why, which decisions mattered, whether the result fits the stated process, what risks changed, and what action follows.

Show:

1. Cumulative growth of a fixed investment versus benchmark.
2. Annualised return, active return, tracking error, information ratio, maximum drawdown and recovery.
3. Active-return attribution aligned to actual decisions: allocation, selection, currency, interaction and implementation costs.
4. Top contributors and detractors with position action and thesis status.
5. Weight versus contribution to active risk.
6. Current active weights, concentration, liquidity and mandate headroom.
7. Required commentary and sign-off.

Require five commentary fields: outcome versus objective; decisions and evidence; risk changes and intentionally retained exposures; what did not work and what was learned; next actions, owners, dates and proof points. Do not allow submission when required fields are empty.

## Quant and portfolio-construction view

The quant user must distinguish exposure from risk contribution and forecast risk from realised risk.

Show:

- active factor exposures and factor contribution to risk;
- factor versus specific-risk decomposition;
- security weight versus marginal or component risk contribution;
- covariance/correlation diagnostics and model freshness;
- pre-trade what-if impact on active return, tracking error, factor, sector, currency, liquidity and mandate limits;
- historical, factor, macro and full-revaluation stress cases where supported;
- turnover, transaction-cost and capacity estimates;
- data-quality flags, stale prices, missing classifications and unexplained residuals.

## Performance and risk view

The performance analyst must reconcile returns and attribution; the risk analyst must connect exposures to downside, limits and action.

Show:

- official and ad-hoc return status;
- portfolio and benchmark returns on the same basis;
- attribution effects that reconcile to active return within a visible tolerance;
- rolling active return, tracking error and information ratio;
- volatility, maximum drawdown, VaR/expected shortfall where governed, and scenario loss;
- risk decomposition, concentration, liquidity and limit utilisation;
- reconciliation, pricing, benchmark, corporate-action, FX and residual checks;
- open risk exceptions with owner, threshold, due date and evidence required to close.

Use multiple risk measures. Tracking error answers benchmark-relative dispersion; drawdown and stress answer loss severity; liquidity answers exit feasibility. Do not present one as a complete definition of risk.

## Company relationship view

Use a node-link map only for a bounded company ecosystem. Put the covered company at the centre; suppliers upstream; customers downstream; partners and competitors as secondary relationship types.

Every relationship needs direction, category, direct or reverse disclosure, source date, confidence/relevance, known revenue dependency, geography and research owner where available. Pair the graphic with a sortable detail table and investment questions. Do not infer a commercial dependency from visual proximity alone.

## Visualisation map

| Decision question | Visual | Required treatment |
|---|---|---|
| How did wealth grow? | Cumulative line/area | Portfolio and benchmark; fixed base value; period and return basis |
| How severe were losses? | Drawdown area | Zero baseline; portfolio and benchmark; maximum and recovery |
| What drove active return? | Horizontal attribution bars or waterfall | Positive/negative effects; effects reconcile to active return |
| What drives forecast risk? | Risk decomposition doughnut plus table | Factor/specific split; total active risk; model date |
| Which factor tilts are intentional? | Diverging horizontal bars | Zero line; portfolio exposure and risk contribution as separate series |
| Is risk disproportionate to weight? | Grouped bars or scatter | Capital weight versus contribution/marginal risk |
| What happens under stress? | Scenario matrix | Portfolio, benchmark and active impact; scenario owner and version |
| Who are the economic dependencies? | Bounded node-link graph plus detail table | Relationship direction, type, dependency, source and confidence |
| What action is required? | Commentary/action form | Required fields, owner, approver, due date and workflow state |

## Milford chart grammar

- Use a white plotting field, fine cool-grey grid lines and compact Montserrat labels.
- Use slate for the benchmark or neutral comparison and orange for the internal portfolio/action series.
- Use a restrained translucent fill under the main cumulative or drawdown line.
- Use no gradients, 3D effects, decorative animation or rainbow categorical palettes.
- Use blue or green only to identify a KiwiSaver or Investment Funds context; keep internal analytical series slate/orange.
- Put definitions and source state directly below the chart.
- Provide an accessible tabular fallback for material quantitative results.

## Primary research basis

- Bloomberg PORT describes a unified positions, risk and performance workflow with performance attribution, multi-dimensional risk, optimization, data validation and factor/full-valuation/macro/climate scenario analysis: https://professional.bloomberg.com/products/bloomberg-terminal/portfolio-analytics/
- Bloomberg MAC3 emphasizes risk decomposition and unintended style, industry and country exposures: https://professional.bloomberg.com/products/risk/mac3/
- MSCI BarraOne combines factor risk, VaR, full-revaluation stress testing, attribution, what-if analysis and reporting in a holdings-based framework: https://www.msci.com/data-and-analytics/portfolio-management/barra-one
- FactSet Performance supports transaction-based measurement and allocation, selection and currency attribution: https://www.factset.com/lp/performance-solutions
- CFA Institute states that effective attribution should reconcile to portfolio return/risk, reflect the decision process and quantify active decisions: https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/portfolio-performance-evaluation
- Bloomberg Supply Chain and FactSet Supply Chain Relationships describe dynamic supplier/customer networks, reverse disclosures, relationship categories and revenue dependencies: https://professional.bloomberg.com/institutions/corporations/supply-chain/ and https://www.factset.com/marketplace/catalog/product/factset-supply-chain-relationships
- New Zealand FMA guidance requires managed-fund updates, gives annual-return graph conventions and defines the 1–7 risk indicator from annualised weekly-return volatility over five years: https://www.fma.govt.nz/business/services/mis-manager/ and https://www.fma.govt.nz/library/research/increased-risk-profile-of-kiwisaver-funds-2021-2024/

