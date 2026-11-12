# Sudden-move reversal study

## Question and fixed rules

Test whether a pooled, cost-aware model can improve on simply fading or continuing confirmed large moves in Binance USDT perpetuals. This is a directional strategy, not arbitrage. A signal is a conditional paper order; no exchange order is sent.

- Universe: BTC, ETH, SOL and AVAX, the four contracts in the current Aahil Wave research mandate. Do not choose membership from returns.
- Data: checked five-minute perpetual candles and funding from December 2023 through September 2026. The first seven days are warmup. A label needs the full six-hour entry window and up to 24 hours after a fill.
- Event: the absolute three-bar log return first reaches 3.0 times the standard deviation of the prior 672 non-overlapping 15-minute returns. The volatility estimate ends before the event return. Keep at most one event per coin in each 36-hour interval so event labels do not overlap.
- Confirmation: wait three completed five-minute bars. A candidate exists only when price has moved at least 0.25 of the event-time 14-bar five-minute ATR in the direction opposite the shock. This is an observed bounce/rejection, not a claim that the move was caused by liquidations.
- Regime gate: reject the candidate if the current partial-hour 14-hour ATR exceeds 1.5 times the mean of the prior 168 completed hourly ATR observations. Compute the partial hour only from bars already closed.
- Order: post a limit 0.5 five-minute ATR away from the signal close, with a stop beyond the recent 12-bar swing, at least two ATRs and at least 1.5% of price away. Put the target at 1.5 planned net risk using the assumed maker-entry/maker-target fees. Activate only after the signal bar closes; require strict trade-through; expire after 72 five-minute bars (six hours). Exit on stop/target or after 24 hours from fill. If stop and target are both touched in a bar, count the stop first.
- Costs: use the repo's 2 bp stop slippage, 2 bp assumed maker fee, 10 bp assumed taker fee, and observed funding settlements. These are explicit stress assumptions, not the user's actual fee tier. Report maker/maker, maker/taker-on-stop-and-timeout, and taker/taker P&L on identical fills and size.
- Model: fixed pooled XGBoost fill and TP-before-stop classifiers, calibrated on a later chronological slice of prior data. Include coin indicators, shock size, confirmation, preceding returns, volatility regime, volume/taker-buy share, lagged BTC return and latest settled funding. Expected R is the calibrated fill probability times expected net R conditional on fill. Trade only above +0.05 expected R. Do not tune features or thresholds on test P&L.
- Controls: fade every eligible confirmed event and continue every eligible confirmed event using the same decision time, geometry, expiry, and costs. All orders are replayed even when the model declines them for audit.
- Validation: expanding quarterly tests from 2025 Q1 through 2026 Q3. Within each training window, reserve the latest 20% of candidates for calibration; purge training outcomes ending within 24 hours of calibration. Do not use observations whose full execution horizon reaches beyond the test window. Report the 2025 walk-forward separately from Jan–Sep 2026, which is a historical holdout that becomes consumed when reported.
- Sizing: start with 10,000 USDT split into four 2,500 USDT coin sleeves. Risk 0.25% of each sleeve per filled trade, use at most 1x sleeve notional, and show the implied quantity and notional. This caps simultaneous planned risk at 0.25% of total starting equity when all four sleeves are used. Report portfolio outcomes with a joint UTC-day block bootstrap, including zero-return days.

## Reporting and known limits

Report event/candidate/rejected counts, fills, expiration, TP/SL/timeout, net R and USDT by model, control, coin, side and quarter. Include block-bootstrap intervals for daily net R and net USDT, drawdown, score calibration, and every eligible event in the ledger. Never describe a 3-sigma move as a liquidation without a liquidation feed.

The archive has no historical queue position, order latency or partial-fill evidence. A strict OHLC trade-through is still an optimistic fill proxy and can overstate maker fill probability. Candle bars cannot establish intrabar path except for the conservative stop-first rule. Results are research simulations, not live or paper fills. An observed conditional setup is not an instruction to trade.

The event threshold, confirmation, regime cutoff, geometry, exit rules, cost scenarios and EV hurdle above are fixed before this study's outcomes are scored. Any later change requires a new dated protocol and genuinely later validation data.
