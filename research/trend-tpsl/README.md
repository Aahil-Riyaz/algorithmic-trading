# Do TP/SL trades in the trend's direction make money?

**Barely, and not reliably.** Long trades were taken only when the trend signal was fully on. Each took half off at +1R and trailed a stop on the rest. Across the 278 untouched coins this produced 11,493 trades from 2018 to October 2026.
- **Trades:** they won **46%** of the time and averaged only **+0.05R** after costs. The median trade lost 0.20R.
- **Basket:** it earned **+1.3% a year**, with a Sharpe of 0.48 and a 95% interval of **−0.23 to +1.24**. Since 2024 it lost 0.7% a year.
- **Verdict:** both pass conditions failed. The plain trend rule did much better on the same coins and dates.

This is a historical simulation. [Rules and the pre-scoring amendment](../trend-tpsl-plan.md) · [Code](../../trend_tpsl.py) · [Tests](../../test_trend_tpsl.py) · [Every trade](trades.csv) · [Totals](results.json)

| Apr 2018–Oct 2026, equal-weight basket | Sharpe | CAGR | Volatility | Max drawdown | CAGR since 2024 |
| --- | ---: | ---: | ---: | ---: | ---: |
| TP/SL with trailing stop | 0.48 | +1.3% | 2.8% | −6.0% | −0.7% |
| Plain trend rule | 0.89 | +14.1% | 16.4% | −29.3% | +1.8% |
| Hold | 0.29 | −11.8% | 84.4% | −95.4% | −36.1% |

| Trade statistics | Value |
| --- | ---: |
| Trades | 11,493 |
| Win rate after costs | 46.0% |
| Mean / median R per trade | +0.048 / −0.197 |
| Reached the first target (+1R) | 43.9% |
| Reached the second target (+3R) | 12.9% |
| Share of days in a trade | 21% |
| Days a held coin opened more than 50% below the prior close | 0 |

## Why it does worse than the plain trend rule

- **Exits come too early.** The plain rule makes its money from a few long trends. Taking half off at +1R, and trailing the rest two ATRs below the high, exits most trends early. Only 13% of trades reached +3R.
- **Most trades never reach the first target.** 6,452 trades missed it:
  - 3,453 hit the full stop;
  - 2,600 left when the trend signal turned off;
  - 399 timed out.
- **Fixed risk keeps the basket small.** With 2% risk per trade and a stop that is often 10–20% wide on altcoins, positions were usually well under the 2x cap. The basket's volatility was only 2.8%. Leverage up to 2x never came into play for most trades.

## Leverage and margin

- **Cross margin:** it was assumed throughout. No held coin ever opened more than 50% below the prior close, so the 2x cap never came near liquidation.
- **Why 20x was not tested:** a 20x position on these coins would be liquidated by a move of about 5%. That is smaller than a typical 2 × ATR stop here, so most trades would be liquidated before reaching their stop.

```
python -m unittest test_trend_tpsl
python trend_tpsl.py
```
