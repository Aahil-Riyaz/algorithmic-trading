# Where should the stop go?

**Wider at the start.** Five stop rules were compared on a random half of the untouched coins, and the best was checked on the other half.
- **The winner:** an initial stop at **3 × ATR** instead of 2 × ATR, with the runner trailing 3 × ATR below the highest close after the first target.
- **Confirmation:** on the second half it raised the basket Sharpe by **+0.21**, with a 95% interval of **+0.10 to +0.34**. That interval is entirely above zero, so the rule fixed beforehand adopts it.
- **The catch:** the improved TP/SL system still earns only about 1.5–1.8% a year, far below the plain trend rule.

This is a historical simulation. [Candidates fixed before scoring](../trend-tpsl-stops-plan.md) · [Code](../../trend_tpsl_stops.py) · [Totals](results.json)

| Stop rule | Development Sharpe, CAGR, win rate, mean R | Confirmation Sharpe, CAGR, win rate, mean R | Runners closed near entry (dev / conf) |
| --- | --- | --- | --- |
| base: 2 ATR, then entry or 2-ATR trail | 0.46, +1.35%, 45.6%, +0.043 | 0.50, +1.44%, 46.4%, +0.054 | 53% / 57% |
| no_breakeven: keep the initial stop, 2-ATR trail | 0.48, +1.39%, 45.4%, +0.046 | 0.50, +1.44%, 46.2%, +0.056 | 30% / 29% |
| wide_trail: entry or 3-ATR trail | 0.53, +1.54%, 45.2%, +0.045 | 0.54, +1.55%, 46.7%, +0.067 | 79% / 81% |
| wide_no_breakeven: initial stop or 4-ATR trail | 0.60, +1.73%, 40.9%, +0.068 | 0.64, +1.79%, 41.4%, +0.083 | 16% / 15% |
| **wide_initial: 3-ATR stop, then entry or 3-ATR trail** | **0.82**, +1.81%, 42.6%, +0.092 | **0.71**, +1.54%, 42.4%, +0.095 | 53% / 54% |

"Near entry" means a first-target trade whose total result landed within 0.1R of +0.5R. That is the outcome when the runner is stopped about where it started.

## What it shows

- **Removing breakeven helps less than expected.** Keeping the initial stop instead of moving to entry cut the runners closed near entry from about 55% to about 30%. It barely changed the Sharpe, because the runners that reversed now lost more.
- **The initial stop was the bigger problem.** A 2-ATR stop on daily altcoin candles is inside normal day-to-day noise. Widening it to 3 ATR lowered the win rate to about 42%, but roughly doubled the mean R per trade.
- **Returns stay small.** With 2% risk per trade, a wider stop means a smaller position. The adopted rule improves risk-adjusted return, but not the size of the return. The plain trend rule earned about +14% a year on the same coins.

```
python trend_tpsl_stops.py
```
