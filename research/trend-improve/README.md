# Can a simple filter improve the trend basket?

**Not by enough to adopt.** Three pre-declared changes were tried on a random half of the 278 untouched coins, and the best one was checked on the other half.
- **The best candidate:** a BTC regime filter, which goes to cash in every coin while BTC's own trend signal is zero. It raised the confirmation-half Sharpe from 0.94 to 1.01.
- **Why it is not adopted:** the 95% interval for that gain was −0.013 to +0.17. It was positive in 95.5% of resamples, but its lower bound sits just below zero. The rule fixed beforehand requires a lower bound above zero, so the paper basket keeps the unchanged rule.
- **Liquidity filter:** dropping coins under 1 million USDT of daily volume made both halves worse.

This is a historical simulation. [Rules fixed before scoring](../trend-improve-plan.md) · [Code](../../trend_improve.py) · [Tests](../../test_trend_improve.py) · [Totals and coin lists](results.json)

| Basket Sharpe, CAGR, max drawdown | Development (139 coins) | Confirmation (139 coins) |
| --- | --- | --- |
| Base rule | 0.86, +14.2%, −28% | 0.94, +15.2%, −31% |
| BTC regime filter | **0.90**, +14.6%, −27% | 1.01, +16.4%, −29% |
| Liquidity filter | 0.73, +10.5%, −24% | 0.67, +8.7%, −26% |
| Both filters | 0.77, +11.0%, −22% | 0.73, +9.5%, −25% |

**Since January 2024.** Every version earned between −0.2% and +2.3% a year. The base rule made +2.2% on the development half and +1.2% on the confirmation half. The regime filter made +2.3% and +1.6%. None of the changes fixes the weak recent period.

## How it was run

- **Split:** coins came from [trend-fresh/coins.csv](../trend-fresh/coins.csv), shuffled with seed 20261120 and cut into two halves of 139.
- **Unchanged from the untouched-coin study:**
  - candles, ending at each coin's first gap or delisting;
  - the rule and its warm-up;
  - costs of 10 bp fee plus 10 bp slippage per side;
  - equal-weight daily baskets.
- **Filter timing:** filters use only data up to each decision close.
- **Liquidity proxy:** base volume times close, because the cached archives do not include quote volume here.
- **Selection:** the highest development-half Sharpe. The bootstrap uses 60-day moving blocks, 5,000 resamples and seed 20261120.

## What this means

- **The regime filter remains a candidate.** It is consistent with the main rule's behaviour of sitting out broad crypto downtrends, but the evidence is not strong enough to switch on.
- **Testing it again:** it should only be retested on data nobody has scored yet, such as the forward paper record. Re-tuning on these same coins would no longer be a fair test.

```
python -m unittest test_trend_improve
python trend_improve.py
```
