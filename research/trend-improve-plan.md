# Improving the trend basket without fitting the test: rules fixed before scoring

The trend rule passed on 278 untouched coins ([results](trend-fresh/README.md)). This study asks whether one of a few pre-declared changes improves it. A change is only adopted if it wins on one half of the coins **and** confirms on the other half.

## Split

- The 278 coins in [trend-fresh/coins.csv](trend-fresh/coins.csv) are shuffled with seed 20261120.
- The first 139 are the **development** half and the other 139 the **confirmation** half.
- Dates, costs (10 bp fee plus 10 bp slippage per side) and the equal-weight daily basket are as in the untouched-coin study.

## Candidates, all decided at the daily close and traded at the next open

1. **Base:** the unchanged rule.
2. **BTC regime filter:** a coin's target weight is set to zero on any day when BTC's own trend signal (the same 20/60/120-day count) is zero.
3. **Liquidity filter:** a coin's target weight is set to zero on any day when its average daily quote volume over the last 30 closes is below 1,000,000 USDT. Quote volume is approximated by base volume times the close.
4. **Both filters together.**

## Selection and confirmation

- **On the development half:** pick the candidate with the highest basket Sharpe. If it is the base rule, the study ends with no change.
- **On the confirmation half:** compare the chosen candidate with the base rule.
  - Statistic: the Sharpe difference.
  - Interval: 95% 60-day moving-block bootstrap, 5,000 resamples, seed 20261120.
  - **Adopt only if the lower bound is above zero.**
  - If it fails, the paper basket keeps the base rule.
- **Also reported, not used to decide:** each candidate's CAGR, maximum drawdown and time invested on both halves.
