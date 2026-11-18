# Volatility-targeted BTC and ETH trend: rules fixed before scoring

Every directional test so far used intraday entries with tight stops, and fees dominated. This study tests a slow, stop-free spot rule. The question is whether trend and volatility scaling add risk-adjusted return over simply holding. All parameters are fixed here before any return is computed.

## Rule

- Binance spot BTCUSDT and ETHUSDT daily candles, 2018-01 through 2026-10. Each coin is a separate 10,000 USDT account.
- Signal at each daily close: the share of the 20-, 60- and 120-day returns that are positive, so 0, 1/3, 2/3 or 1.
- Volatility scale: 40% annual target divided by the annualised standard deviation of the last 30 daily log returns, capped at 1. Spot only, with no leverage and no shorting.
- Target weight = signal × scale. Trade at the next daily open, and only when target and current weight differ by more than 0.10.
- Costs: 10 bp fee plus 2 bp slippage per side on traded notional. Idle cash earns zero.

## Controls on the same dates

- **Buy and hold:** fully invested from the first trade date.
- **Volatility-targeted hold:** the same scale with the signal fixed at 1. This isolates what the trend signal adds beyond volatility scaling.

## Reporting

- Report CAGR, annualised volatility, Sharpe (zero risk-free), max drawdown, time invested, turnover, fees and net USDT for each rule and coin, plus a calendar-year table.
- Report a 60-day block-bootstrap 95% interval for the Sharpe difference between trend and buy-and-hold.
- Win rate of completed position episodes is reported for reference only.
- The trend rule passes if its Sharpe difference interval sits above zero for at least one coin, and its 2024-01 onward Sharpe is not below buy-and-hold for either coin.
