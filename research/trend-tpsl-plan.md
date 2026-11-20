# Trend-filtered TP/SL trades: rules fixed before scoring

The earlier stop-and-target strategies all lost after costs. The slow trend rule passed out of sample ([results](trend-fresh/README.md)). This study asks whether stop-and-target trades taken only in the direction of that trend signal make money. Every value below is fixed before any return is computed, and none will be tuned on the result.

## Market and data

- **Coins:** the 278 coins of the untouched-coin study ([coins.csv](trend-fresh/coins.csv)), on the same cached Binance daily candles.
- **Period:** April 2018 to October 2026, ending each coin at its first gap or delisting.
- **Direction:** long only. Most of these coins had no perpetual for much of the period, so shorts are not tested.

## Trade rules, one position per coin at a time

- **Entry:** when a daily close has the trend signal at 1 (all of the 20-, 60- and 120-day returns positive) and the coin is flat, buy at the next open.
- **Stop:** the entry price minus 2 × ATR, where ATR is the average true range of the 14 completed days before entry.
- **First target:** at +1R, where R is the stop distance. Sell half there and move the stop on the rest to the entry price.
- **Second target:** sell the remaining half at +3R.
- **Trend exit:** if a daily close has the trend signal at 1/3 or 0, close everything left at the next open.
- **Timeout:** close any remainder at the close 30 days after entry.
- **Within a day:** the stop is checked first. A gap through the stop fills at the open. Targets fill at their level. On the entry day only the stop is checked, so no target can fill in the same daily candle as the entry.

### Amendment before scoring, 2026-11-20

The two changes below were requested and committed before any return was computed.
- **Trailing stop after the first target:** once +1R fills, the stop on the remaining half becomes the higher of the entry price and the highest close since entry minus 2 × the entry ATR. It moves only up, is checked from the next day, and replaces the fixed move to entry. The +3R target, trend exit and timeout are unchanged.
- **Cross margin:** all positions are assumed to share one cross-margin account. With at most 2x and stops at 2% risk, a position can only be liquidated if the price opens more than about 50% below the previous close while it is held. The number of such gap days is reported, and each is treated as the full stop-loss fill at that open.

## Sizing, leverage and costs

- **Accounts:** each coin is an independent sleeve.
- **Position size:** each trade risks 2% of sleeve equity at the stop, capped at a position worth 2 × sleeve equity. Above 1x the excess is treated as borrowed and charged 0.03% a day, about 11% a year.
- **Fees:** 10 bp fee plus 10 bp slippage on every entry and exit, matching the untouched-coin study.
- **No higher leverage:** 20x is not tested. A 2 × ATR stop on these coins is often more than 5%, which 20x would liquidate first.

## Tests

- **Basket:** an equal-weight daily basket of the sleeves, averaging the coins live each day.
- **Pass if both hold:**
  - the 95% 60-day moving-block bootstrap interval for the basket Sharpe (5,000 resamples, seed 20261121) has a lower bound above zero;
  - the basket's net CAGR since 2024-01 is positive.
- **Reported against the plain trend basket and holding:**
  - trade count, win rate, mean R per trade and target hit rates;
  - time invested, CAGR, maximum drawdown and costs.
