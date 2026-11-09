# Two-sided order-flow experiment

## Question and fixed evaluation

Can flow help choose between a passive long, a passive short and staying flat in BTC, ETH, SOL, HYPE, AAVE and XRP perpetual futures? Each coin has an independent 10,000 USDT account. Use Binance USD-M perpetual prices, taker volume, depth and actual funding events. Use Deribit BTC and ETH options as market context for all six. Options trades are explanatory inputs. All simulated positions are in the perpetuals.

| Stage | UTC dates | Purpose |
| --- | --- | --- |
| Initial training | October–November 2025 | Fit on earlier resolved outcomes |
| Walk-forward validation | December 2025, January and February 2026 | Expand training through the preceding month for each fold |
| Freeze | End of February 2026 | Select each model on validation only and refit on all five months |
| Final replay | March–April 2026 | Score the frozen models and report both months together |

Use one decision per coin per hour. Only fully observed inputs enter a decision. Allow five minutes from the hourly boundary before activating an order. Prevent entry and exit labels from crossing split boundaries. Purge the entire maximum holding and entry horizon at each boundary. Keep missing-data counts and source fingerprints. A missing required market input skips that coin-hour for all models.

## Models and comparisons

Train gradient-boosted regression trees to estimate after-cost profit per unit of planned risk for each proposed order. Expirations earn zero. Give both directions the same opportunity and choose the one with the higher score; skip if both are below the cutoff. Consider 7, 15 and 31 leaf nodes and minimum expected returns of 0, 0.05 and 0.10 R. Use 120 boosting rounds, learning rate 0.04 and a fixed seed. Compare three independently selected feature sets under the same search budget.

1. Price, range, trend and order geometry.
2. Price plus executed taker flow, near/wide resting depth and last known funding.
3. All of the above plus BTC and ETH call/put premium and aggressor flow.

Choose the settings with the highest sum of validation net profit among those with at least 20 fills per fold. If none qualify, report the shortfall and retain the most active candidate as exploratory. Losing validation and low activity count against deployment. Publish all candidates. Keep the March–April scores out of selection. Evaluate cash at zero return alongside all feature sets.

## Execution and risk

- Quote half an hourly ATR away from the last close, in the direction of a pullback. Use a two-hour expiry and a 24-hour time exit from fill. Model the execution on five-minute trade candles.
- Place the stop beyond the prior 12-hour swing with a quarter-ATR buffer. Enforce a minimum of two hourly ATRs and 1.5% of entry. Size down as the stop gets wider. Target 1.5 R after modeled trading costs before funding. Risk at most 0.5% of each account on an ordinary stop and cap entry notional at account equity.
- Charge 0.10% on each fill and two basis points of adverse slippage on market exits. Use the published funding rate and settlement mark. Apply funding against longs and to shorts when the rate is positive. Log the sign and amount per trade.
- Require penetration of the entry and target limits, resolve ambiguous candles conservatively, allow gap stops and expire unused orders. Five-minute replay cannot establish queue position or partial fills.
- For the same filled entries, compare the new stop with the previous one-ATR/0.5% floor. Count stop-outs and how often price gets back to entry in a later candle within 12 hours of the stop. This paired diagnostic measures the stop change independently of the model's ability to pick trades.
- Report trade counts, win rate, net P&L, realized payoff, portfolio drawdown and long/short results. Include cost sensitivity and results by coin. Keep the earlier spot baselines in a dated scorecard. Changes in markets and dates prevent a direct before/after attribution.
