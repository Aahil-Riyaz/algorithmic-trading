# Win rate and profit history

**Latest historical validation.** Five-minute long filters won 14 of 24 fills (58.33%) across two monthly resets. Live P&L is unmeasured. [Matched control and coverage](regime-limits.md)

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
