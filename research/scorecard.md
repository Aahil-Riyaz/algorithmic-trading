# Win rate and profit history

## Trend-filtered TP/SL trades, 278 untouched coins, historical

| Evaluation | Wins / trades | Win rate | Mean R | Basket CAGR | Sharpe, 95% interval | CAGR since 2024 |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| Half at +1R, trailing stop, +3R cap, 2% risk, max 2x | 5,285 / 11,493 | 46.0% | +0.048 | +1.3% | 0.48 (−0.23 to +1.24) | −0.7% |

**Fails.** It made less than the plain trend rule on every measure, because the early profit-taking cut off the long trends that pay for the losers. [Rules fixed before scoring](trend-tpsl-plan.md) · [Results and trade ledger](trend-tpsl/README.md)

## Trend basket filters, split-half check, historical

| Evaluation | Development Sharpe | Confirmation Sharpe | Confirmation gain over base, 95% |
| --- | ---: | ---: | --- |
| Base rule | 0.86 | 0.94 | — |
| BTC regime filter, chosen on development | 0.90 | 1.01 | +0.07 (−0.013 to +0.17) |
| Liquidity filter | 0.73 | 0.67 | not tested |
| Both filters | 0.77 | 0.73 | not tested |

**Not adopted.** The interval's lower bound fell just below zero, so the paper basket keeps the base rule. [Rules fixed before scoring](trend-improve-plan.md) · [Results](trend-improve/README.md)

## Trend rule on 278 untouched coins, Binance spot, historical

| Evaluation | Coins | Sharpe | CAGR | Max drawdown | Hold basket Sharpe, CAGR, max drawdown |
| --- | ---: | ---: | ---: | ---: | --- |
| Equal-weight trend basket, Apr 2018–Oct 2026 | 278 | 0.89 | +14.1% | −29.3% | 0.29, −12.0%, −95.4% |
| Same, Jan 2024–Oct 2026 | — | 0.19 | +1.8% | −29.3% | −0.30, −36.1%, −88.1% |

**Passes the pre-registered test.** The 95% interval for the Sharpe gain over holding was +0.14 to +1.02. Trend had the higher Sharpe on 198 of 278 coins. Since 2024 it beat holding but earned less than cash would have. Win rate is not a meaningful count for a daily-weighted basket. [Rules fixed before scoring](trend-fresh-plan.md) · [Results and per-coin ledger](trend-fresh/README.md)

## Volatility-targeted trend, BTC and ETH spot, historical

| Evaluation | Wins / episodes | Episode win rate | Net USDT on 10,000 | Sharpe | Max drawdown | Buy-and-hold Sharpe, max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| BTCUSDT, Jun 2018–Oct 2026 | 26 / 101 | 25.7% | +95,847.37 | 1.14 | −41.9% | 0.76, −76.6% |
| ETHUSDT, Jun 2018–Oct 2026 | 20 / 73 | 27.4% | +70,733.68 | 0.98 | −32.8% | 0.61, −86.5% |

**Fails the pre-registered test.** The 95% bootstrap interval for the Sharpe gain over holding was −0.08 to +0.80 for BTC and −0.07 to +0.79 for ETH. Post-hoc checks found the same direction across 27 nearby parameter sets and on seven coins the rule was not designed on. A nine-coin basket had a Sharpe of 1.02 against 0.76 and a −28% worst drawdown against −79%, but its interval also crossed zero (−0.13 to +0.78). The low win rate is expected: a few long trends pay for many small exits. [Rules fixed before scoring](trend-plan.md) · [Results, robustness and daily ledger](trend/README.md)

## Cross-sectional funding carry, Binance perpetuals against spot, historical

| Evaluation | Months positive | Net USDT on 10,000 | CAGR | Max drawdown | 95% bootstrap annual return |
| --- | ---: | ---: | ---: | ---: | --- |
| Top-10 by trailing funding, Jan 2021–Oct 2026 | 8 / 70 | −2,178.86 | −4.1% | −21.8% | −7.05% to −1.77% |
| Equal-weight 40 control, same months | 5 / 70 | −3,725.12 | −7.7% | −37.3% | −9.93% to −5.63% |
| Top-10, Jan 2024–Oct 2026 | 2 / 34 | −575.50 | −2.5% | −7.0% | −4.70% to −0.73% |

**Fails.** Funding received (+1,551.87 USDT) was outweighed by forced closes when shorted coins spiked. The plan text conflicted on leverage; the stricter reading was scored, and the looser 1x reading also failed (2024-on −90 USDT, interval crossing zero). [Rules fixed before scoring](cross-carry-plan.md) · [Results, leverage sensitivity and coin-month ledger](cross-carry/README.md)

## Sudden-move reversal, BTC/ETH/SOL/AVAX perpetuals

| Evaluation | Submitted | Fills | Profitable fills | Net win rate | Mean net R / fill | Net P&L on 10,000 USDT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pooled model, expanding quarterly walk-forward, Jan 2025–Sep 2026 | 77 | 74 | 29 | 39.19% | −0.122R | −56.71 USDT |
| Fade every qualifying event control, same test windows | 412 | 381 | 162 | 42.52% | −0.013R | −34.21 USDT |
| Continue every qualifying event control, same test windows | 412 | 377 | 154 | 40.85% | −0.026R | −60.52 USDT |

The model's seven-day joint-market block-bootstrap 95% interval was **−0.386R to +0.182R per fill** and **−190.18 to +69.24 USDT**. Cost sensitivity on the identical model submissions and sizes was **−40.30 USDT** for an unrealistic maker/maker best case, **−56.71 USDT** with maker entry and taker stop/time exits, and **−84.35 USDT** at 10 bp taker fees on both sides. The 74 fills comprised 19 targets, 42 stops and 13 time exits. Twenty-nine were net profitable after costs, including positive time exits. Three additional orders expired unfilled.

The final paper fit used 515 training candidates and 130 later calibration candidates. The research model lost in two of the three quarters where it placed orders; its one positive quarter was 2026 Q3, with 11 wins in 21 fills. A post-hoc random-time/random-side control matched the model's 77 submitted orders by coin and quarter. Across 2,000 assignments the maker-entry/taker-stop mean was **+0.011R per fill**; the 2.5th–97.5th randomization range was −0.218R to +0.262R. This is a diagnostic, not a confidence interval or an independent test. **No positive fee-adjusted edge is established.** [Protocol, order ledger, model freeze and live read-only setup](shock/README.md)

**Aahil Wave, historical walk-forward.** Across four independently funded 10,000 USDT coin accounts, the pooled model lost 382.16 USDT in 2025. [Model specification](aahil-wave-protocol.md) · [Order ledger](aahil-wave/wave-orders.csv) · [Full audit](aahil-wave-audit.md)

**Latest retrospective comparison.** Six-hour entries won 22 of 56 fills (39.29%) and lost 337.85 simulated USDT on the previously examined October data. [Expiry comparison and order ledger](october-quotes-6h/README.md)

| Experiment | Test market and dates (UTC) | Wins / fills | Net win rate | Net return |
| --- | --- | ---: | ---: | ---: |
| Starting Bitcoin breakout | Binance BTC spot, Oct 19–Dec 31, 2024 | 19 / 59 | 32.20% | −6.05% |
| First six-coin breakout | KuCoin spot, Dec 13–31, 2025 | 7 / 51 | 13.73% | −2.79% |
| First trained long-only limits | KuCoin spot, January 2026 | 45 / 144 | 31.25% | −2.54% |
| Two-sided limits with options and flow | Binance perpetuals, March–April 2026 | 118 / 284 | 41.55% | −1.76% |
| Monthly refit with wave filter | Binance perpetuals, May 2026 | 1 / 7 | 14.29% | −0.40% |
| Monthly refit with wave filter | Binance perpetuals, June 2026 | 3 / 12 | 25.00% | −0.41% |
| Per-coin regime filters | Binance perpetuals, August 2026 | 12 / 20 | 60.00% | +0.33% |
| Per-coin regime filters | Binance perpetuals, September 2026 | 2 / 4 | 50.00% | +0.08% |
| Earlier classifier replay | Binance perpetuals, October 2026 | 4 / 9 | 44.44% | +0.14% |
| Expiring limits, replace pending quote | Binance perpetuals, October 2026 | 13 / 33 | 39.39% | −0.55% |
| Six-hour limits, replace pending quote (retrospective) | Binance perpetuals, October 2026 | 22 / 56 | 39.29% | −0.56% |
| Aahil Wave pooled model, quarterly walk-forward | Binance USDT perpetuals, January–December 2025 | 12 / 34 | 35.29% | −0.96% |
| Aahil Wave plus RSI | Binance USDT perpetuals, same 2025 folds | 14 / 40 | 35.00% | −1.31% |
| Aahil Wave plus Bollinger Bands | Binance USDT perpetuals, same 2025 folds | 3 / 7 | 42.86% | −0.12% |
| Aahil Wave plus both indicators | Binance USDT perpetuals, same 2025 folds | 5 / 11 | 45.45% | −0.10% |

The three indicator rows use the same original model, four funded coin sleeves and order rules. [Configuration and ledgers](indicator-test/README.md)

May and June each start with fresh balances. [Matched controls and monthly results](wave-plan.md)

A win is a filled trade with positive P&L after costs, including funding on perpetuals. Expired orders are excluded from the win-rate denominator. Each six-coin run started with six separate 10,000 USDT accounts. Return is total P&L divided by 60,000 USDT. The starting Bitcoin run had a single 10,000 USDT account.

The rows span different periods, venues, entry rules and instruments. Use the three models below to compare inputs on the **same dates, coins, execution rules and risk budget**. Each received the same validation search budget and selected its own trading threshold.

| March–April 2026 | Orders | Fills | Wins | Win rate | Net USDT | Return | Max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Price and order geometry | 230 | 142 | 43 | 30.28% | −2,348.60 | −3.91% | 3.97% |
| Add executed flow, depth and funding | 85 | 52 | 20 | 38.46% | −484.17 | −0.81% | 1.16% |
| Add BTC and ETH options | 518 | 284 | 118 | 41.55% | −1,056.24 | −1.76% | 2.96% |
| Stay in cash | 0 | 0 | 0 | — | 0.00 | 0.00% | 0.00% |

The options model traded more often than the flow-only model. It had the highest win rate, while the flow-only model lost less money. The options model's average winning trade was 50.18 USDT and its average losing trade cost 42.04 USDT. With that observed payoff, break-even would have required about 45.6% wins. The approximate 95% seven-day block-bootstrap interval for win rate was **35.6%–47.3%**. It resamples all coins together by UTC exit day and covers a single two-month regime.

| Options model by market | Wins / fills | Net USDT |
| --- | ---: | ---: |
| BTC | 18 / 47 | −372.16 |
| ETH | 23 / 47 | +214.82 |
| SOL | 24 / 44 | +396.37 |
| HYPE | 15 / 49 | −738.27 |
| AAVE | 22 / 55 | −393.47 |
| XRP | 16 / 42 | −163.53 |
| **All longs** | **55 / 114** | **+280.49** |
| **All shorts** | **63 / 170** | **−1,336.73** |

At the simulated fill prices, price moves earned **133.08 USDT** before fees and funding. Trading fees cost **1,195.11 USDT**, and funding added **5.79 USDT**, leaving **−1,056.24 USDT**. The fill prices already include adverse slippage on market exits. March lost 630.92 USDT and April lost 425.32 USDT, grouped by exit month. Doubling assumed fees and adverse market-exit slippage on the same quantities and fills increased the loss to 2,344.81 USDT. Choosing only the profitable coins or side after seeing these rows would require a new test period.

I also repriced those identical fills using Binance's illustrative 0.02% maker and 0.05% taker rates. With maker fees for every entry and take-profit and taker fees for stops and time exits, the result was **−240.30 USDT**. Charging taker fees on all entries instead gave **−419.36 USDT**. This sensitivity keeps quantities, signals and prices fixed. An account's actual fee tier and maker eligibility depend on its fills. [Binance fee example](https://www.binance.com/en/support/faq/detail/360033544231) · [Independent ledger calculation](flow-v1/audit.py)

## Did the wider stop help?

The comparison replays **the same 284 filled entries and directions**. Each alternative puts its take-profit at 1.5 times its planned risk after modeled trading costs. We count a recovery when price gets back to the entry in a later five-minute candle within 12 hours of a stop. Both alternatives had complete follow-up on every stop.

| Stop geometry | Average entry-to-stop distance | Stop-outs | Stops followed by a recovery |
| --- | ---: | ---: | ---: |
| One hourly ATR, floor 0.5% | 1.03% | 175 | 122 |
| Beyond the 12-hour swing, floor of two ATRs and 1.5% | 2.45% | 131 | 46 |

Wider stops reduced both counts in this sample. Position sizing reduced the number of contracts as risk per contract increased. A recovery to entry alone would still owe trading costs. The full model closed 60 trades at target, 131 at stop and 93 on time. This explains why the realized winner/loser ratio can differ from the planned target.

## Audit trail

- [First BTC run](https://github.com/Aahil-Riyaz/algorithmic-trading/tree/f363d7d) · [Six-coin breakout](https://github.com/Aahil-Riyaz/algorithmic-trading/tree/2cef653) · [Long-only limit model](https://github.com/Aahil-Riyaz/algorithmic-trading/tree/f8fd98c)
- [Protocol committed before scoring](https://github.com/Aahil-Riyaz/algorithmic-trading/blob/98acc61/research/flow-protocol.md) · [Model freeze](https://github.com/Aahil-Riyaz/algorithmic-trading/tree/d553f28/research/flow-v1) · [All validation candidates](flow-v1/validation.json)
- [Held-out results](flow-v1/holdout.json) · [Full model order ledger](flow-v1/orders.csv) · [Training and replay instructions](flow-v1/README.md)

Append a dated row after each new frozen evaluation. Reserve genuinely later dates for changes made after viewing a holdout. Keep prospective paper and live fills in their own rows when they exist.

## Historical market-neutral carry

Each period starts with 10,000 USDT. Counts below use completed two-leg hedges or continuous funding episodes. An unchanged hedge across multiple funding payments is one episode. Percentages are cumulative period returns on the whole account.

| Strategy and market | 2024–25 wins / hedges, win rate | Net return | Jan–Sep 2026 wins / hedges, win rate | Net return |
| --- | ---: | ---: | ---: | ---: |
| Binance spot + dated future, seven-day premium gate | 0 / 0, — | 0.00% | 0 / 0, — | 0.00% |
| Same, enter all fillable seven-day pairs | 1 / 16, 6.25% | −1.17% | 0 / 6, 0% including two bounded losses | −0.40% to −0.38% |
| Binance spot + dated future, 84-day premium gate | 6 / 6, 100% across three expiries | +3.51% | 0 / 0, — | 0.00% |
| Same, enter all fillable 84-day pairs | 16 / 16, 100% across eight expiries | +5.80% | 3 / 5, 60% including one bounded loss | +0.13% to +0.14% |
| Binance spot + perpetual, trailing funding gate | 9 / 9, 100% | +1.87% | 0 / 0, — | 0.00% |
| Same, passive hedge with monthly rebalancing | 3 / 3, 100% | +5.20% | 2 / 3, 66.67% | +0.17% |

The dollar ranges reflect missing September 2026 published settlements. The exchange index windows determine the loss signs under the stated model. Both legs use simulated execution. The November spot-route and futures-premium observations are quote checks and have no realized win rate or P&L. [Study, controls and timestamped observations](carry/README.md) · [Dated hedge ledger](carry/dated-orders.csv) · [Funding episodes](carry/perp-episodes.csv)
