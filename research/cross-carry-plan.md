# Cross-sectional funding carry: rules fixed before scoring

The earlier perpetual carry study hedged only BTC, ETH, SOL and AVAX. This study asks whether a broad, rules-only selection of the highest-funding perpetuals earns more than cash after realistic costs. Every parameter below is fixed before any return is computed. Nothing is tuned on these results.

## Universe

- Binance USDT-margined perpetuals whose identical symbol also trades as a Binance USDT spot pair. Multiplied contracts such as `1000PEPEUSDT` are excluded.
- Symbols come from the public archive listing, which keeps delisted contracts. A contract that delists while held is closed at its last available daily close on both legs.
- At each monthly decision a coin is eligible if both legs have complete daily bars for the prior 30 days and at least 30 settled funding prints. Then the 40 largest by prior-30-day quote volume (the smaller of spot and perpetual volume) form that month's universe.

## Rule

- Decision at 00:00 UTC on the first day of each month, using only data before that instant.
- Score: mean funding rate per settlement over the prior 30 days, annualised by each print's own interval.
- **Top-10 carry:** hold the 10 highest-scoring eligible coins whose annualised score exceeds the cost hurdle below. Fewer qualifiers leave the remaining capital in cash.
- **Equal-weight control:** hold all 40 eligible coins regardless of score.
- **Cash control:** zero return. A 4% simple annual rate is reported separately as a comparison.
- Each position buys spot and shorts the same quantity of perpetual. Capital per slot is 10% of portfolio equity (2.5% in the 40-coin control). Half funds spot and half is perpetual margin, so the perpetual runs at about 2x.
- Entry and exit use the next daily open after the decision. Positions held into the next month are resized only when a coin leaves or enters.

## Costs and risk

- Spot: 10 bp fee per side. Perpetual: 5 bp taker fee per side. Slippage: 5 bp per leg on every trade, doubled for coins outside the top 20 by volume.
- Hurdle to enter: projected 30-day funding must exceed round-trip costs plus 4% annualised on the slot capital.
- Funding uses each settlement's rate times the perpetual daily close of that day. Mark prices are unavailable in the archive, so this is an approximation.
- Liquidation stress: if the perpetual daily high moves the short's margin ratio below 5%, the pair is force-closed. The perpetual is bought back at that high plus 20 bp, the spot is sold at that day's close, and the slot sits in cash until the next decision.

## Periods and reporting

- One pass from 2021-01 through 2026-10. Results are also shown by calendar year, with 2024-01 onward labelled as the most recent regime.
- Report net USDT and return on 10,000, CAGR, annualised volatility, Sharpe (zero risk-free), max drawdown, funding/basis/fees/slippage split, liquidations and months positive.
- Also report a 30-day block-bootstrap 95% interval for annual return, and the result with positive funding halved.
- A pass needs a positive bootstrap lower bound **and** beating 4% cash in the most recent regime. Anything less is reported as no established edge.
