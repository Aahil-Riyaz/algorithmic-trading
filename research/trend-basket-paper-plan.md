# Multi-coin trend basket, forward paper record: rules fixed before the first run

The trend rule passed out of sample on 278 untouched coins ([results](trend-fresh/README.md)). This paper record tests the same rule forward, from the first run onward, on a basket chosen mechanically at that moment. Nothing below changes after the record starts. A changed rule needs a new record with a new start date.

## Universe, chosen once at the first run

- **Candidates:** Binance spot pairs quoted in USDT, excluding stablecoin and fiat bases and leveraged tokens (bases ending in UP, DOWN, BULL or BEAR).
- **Liquidity screen:** the 80 candidates with the largest 24-hour quote volume at the first run are checked.
- **Selection:** of those, the 30 with the largest quote volume over the last 30 closed daily candles are chosen. A coin must have at least 151 consecutive valid daily candles so the rule can trade on day one.
- **Fixed list:** the list is stored with the record and is not refreshed. A delisted coin's sleeve is closed at its last available close and then holds cash.

### Amendment before the first trade, 2026-11-19

The first selection run included `U`, a dollar stablecoin missing from the stablecoin list, which the rule above already excludes. It also included tokenized stocks and gold: NVDAB, SNDKB, SPCXB, CRCLB, MUB and XAUT. The trend rule was validated only on crypto assets, so these are excluded too.
- **Stablecoins:** besides the name list, any candidate whose last 30 closes all lie within 1% of 1.00 is treated as a stablecoin.
- **Non-crypto assets:** the six tickers above, and PAXG, are excluded by name. Any later tokenized stock or commodity would need the same treatment in a new record.
- **What else changed:** nothing. The universe was re-selected on the same 2026-11-18 close before any paper trade, and the first trades are still at the 2026-11-19 open.

## Rule, sizing and costs

- **Rule:** exactly the rule in [trend-plan.md](trend-plan.md):
  - 20/60/120-day signal;
  - 40% volatility target over 30 days, capped at 1;
  - 0.10 rebalance band;
  - decide at the daily close, trade at the next open;
  - spot only, no leverage, no shorts.
- **Sizing:** 10,000 simulated USDT, split equally into 30 independent sleeves of 333.33. Sleeves are not rebalanced against each other.
- **Costs:** 10 bp fee plus 10 bp slippage per side, as in the untouched-coin test.
- **Comparison:** a buy-and-hold basket of the same 30 coins, with the same starting split.

## What counts

- This is a **prospective paper record**. It is labelled separately from historical and real-money results.
- **Reported each day:**
  - basket equity against the hold basket;
  - the number of coins with a position;
  - any trades for the next open.
- **First formal review after 180 days:**
  - Sharpe and maximum drawdown against the hold basket;
  - a 30-day block-bootstrap interval for the Sharpe difference.
  - Six months is too short to confirm an edge on its own. The review will say so.
