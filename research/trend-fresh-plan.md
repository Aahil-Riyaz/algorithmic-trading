# Trend rule on coins never examined: rules fixed before scoring

The trend rule beat holding on BTC, ETH and seven other coins, but every 95% interval crossed zero and those nine coins were all seen before this test. This study runs the unchanged rule on a mechanically chosen set of coins that no earlier study in this repo has touched. Nothing below is changed after results are seen.

## Universe

- Every Binance spot pair quoted in USDT whose first monthly daily-candle archive is December 2021 or earlier, including pairs later delisted.
- Excluded before any return is computed:
  - the nine coins already studied (BTC, ETH, BNB, XRP, ADA, LTC, LINK, DOGE, SOL);
  - stablecoin and fiat bases;
  - leveraged tokens whose base ends in UP, DOWN, BULL or BEAR;
  - pairs with fewer than 365 days of history after warm-up.
- A coin is used from its first possible trade through 2026-10-31 or its last archived day, whichever is earlier. A delisted coin's sleeves stop at its last close.

## Rule and costs

- Exactly the rule in [trend-plan.md](trend-plan.md):
  - 20/60/120-day signal;
  - 40% volatility target over 30 days, capped at 1;
  - 0.10 rebalance band;
  - next-open execution.
- Costs: 10 bp fee plus **10 bp** slippage per side, five times the BTC/ETH slippage, because these books are thinner.
- Each coin has a trend sleeve and a buy-and-hold sleeve. A daily gap or invalid candle ends that coin's sample at the last valid close before it.

## Tests

- **Primary:** an equal-weight basket that averages each day's returns across all coins whose sleeves are live that day.
  - Statistic: the Sharpe difference, trend basket minus hold basket.
  - Interval: 95% 60-day moving-block bootstrap, 5,000 resamples, seed 20261119.
  - **Pass if the lower bound is above zero.**
- **Secondary:** the share of coins where trend Sharpe exceeds hold Sharpe, with an exact one-sided sign test. Coins are correlated, so this is descriptive.
- **Reported:** basket CAGR, volatility, maximum drawdown, and the 2024-01 onward subperiod.
