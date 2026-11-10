# Do newer limit quotes improve the trade?

On October's six-coin replay, replacing a working quote lost 328.22 USDT on 262 submissions. Keeping the first quote lost 256.94 USDT. The result supports leaving the strategy in paper trading. [Rules fixed before scoring](../quote-plan.md) · [All signals, including cancellations and blocked submissions](signals.csv) · [Results by coin](results.json) · [Portfolio metrics](totals.json)

| October 2026 historical simulation | Submissions | Wins / fills | Win rate | Net USDT | Return on 60,000 USDT | Five-minute max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Replace pending quote | 262 | 13 / 33 | 39.39% | −328.22 | −0.55% | 0.88% |
| Keep first quote | 216 | 14 / 34 | 41.18% | −256.94 | −0.43% | 0.88% |
| Replace, require 2 bp penetration | 270 | 12 / 28 | 42.86% | −181.09 | −0.30% | 0.56% |
| Earlier classifier, original one-bar entry | 77 | 4 / 9 | 44.44% | +82.63 | +0.14% | 0.30% |
| Stay in cash | 0 | 0 / 0 | — | 0 | 0% | 0% |

Only the first two rows isolate replacement. The earlier classifier also changes the training period, score, TTL and marketability assumptions. Five-minute drawdown uses marked positions and funding across six 10,000 USDT accounts. It can miss a worse intrabar drawdown. The deeper-fill stress removes some losing trades in this sample. It also changes which later signals find a free account.

## What happened to the orders?

Of 348 eligible, positive-score signals, 86 arrived while the coin was busy. Of 262 submissions, 186 expired, 38 were replaced, 5 were rejected as marketable and 33 filled. Fill rate was 12.60%. Net expectancy was −1.25 USDT per submission and −9.95 per fill. The positive fills averaged +51.44, and the losing fills averaged −49.84 USDT. At that realized payoff ratio the break-even win rate was about 49.2%. A 1.5R target does not guarantee that each win realizes 1.5R.

| Replacement policy by coin | Submitted | Wins / fills | Net USDT |
| --- | ---: | ---: | ---: |
| BTC | 0 | 0 / 0 | 0.00 |
| ETH | 1 | 1 / 1 | +74.90 |
| SOL | 10 | 1 / 3 | −49.69 |
| HYPE | 50 | 1 / 9 | −374.21 |
| AAVE | 173 | 7 / 15 | −21.69 |
| XRP | 28 | 3 / 5 | +42.48 |

Twenty fills stopped out, seven reached target and six timed out. Trading fees totaled 142.50 USDT and funding cost 3.16 USDT. Even adding both amounts back leaves a loss. HYPE alone lost more than the combined net loss. Dropping it after observing October would create a new strategy requiring a new test.

For 13/33 the illustrative 95% Wilson interval is 24.7%–56.3% under independent fills. Cross-coin trades during shared market shocks can reduce the effective sample. Even under independence, roughly 385 fills give about ±5 percentage points near a 50% win rate. That measures rate precision. Evidence for profitability requires net returns across independent time blocks and several regimes. The former 14/24 estimate from August–September belongs to a different model and evaluation window. [Earlier audit and statistical assumptions](../regime-audit.md)

## Training and execution

Each XGBoost regressor saw 23,733 labeled five-minute proposals from its own coin, 142,398 total, of which 122,053 had zero payoff. Rows use all feature-complete regimes for fitting. The strategy applies the fixed long gates at decision time. The target is net P&L divided by the proposal's stop risk, including zero for an expiry or post-only rejection. Labels price standalone proposals. Actual trading then introduces inventory limits and competition between overlapping quotes. These 142,398 rows share candles and outcomes. They are far fewer independent bets.

The training data begin July 1. Every included training sample's worst-case outcome ends at least 24 hours before October 1. October supplies the later test, with the end of the month reserved for the full exit horizon. The exchange monthly files had a 288-candle gap on October 28 for every coin. The loader filled the absent prices from the same contract's exchange REST klines, checked the complete sequence and kept the original archive intact. Missing depth or spot blocks a decision. Each coin had 591 missing-feature boundaries inside the evaluation window. The result file includes market, spot and fitted model hashes.

The active inputs are closed-candle VWAP deviation, hourly ATR relative to its prior week, cross-venue perp/spot basis, relative turnover, displayed bid/ask notional within 1%, aggressive buy/sell volume, funding and ATR as a fraction of price. Binance perpetual and KuCoin spot closes can differ because of venue timing. Model scores estimate net R per standalone submission and are not win probabilities.

Five minutes after a signal, a long quote at or above the activation open is rejected. An accepted quote stays eligible for 15 minutes. A newer qualifying signal for the same coin cancels the old unfilled quote on activation, even if the replacement is then rejected. A fill keeps its stop and target until exit. Each coin has one open position, a 0.5% modeled risk budget and a 1× notional cap. The replay supports either order side. This study trains the existing long discount setup. The earlier two-sided model remains available. Stops include gap-through pricing. Both legs cost 10 bp in the simulation, stop and timeout exits incur 2 bp slippage, and funding uses observed settlement records.

Five-minute OHLC cannot reveal the queue ahead, partial quantities, cancel/fill races, exact best ask at activation or the order of all intrabar events. We assume atomic cancellation and full size on trade-through. Entry-bar stops take precedence and entry-bar targets are ignored. The ledger includes each fill's next-bar-close signed price change in basis points, a coarse markout whose clock is roughly 5–10 minutes after the fill.

## What published strategies actually achieved

- Albers and colleagues posted live BTC perpetual quotes on Bybit and canceled when cross-venue flow predicted an unfavorable move. About 1.54 million USD filled. Their price execution lost 4.47 bp per round trip. Maker rebates of 5 bp turned that into a gain of about 0.53 bp. Their benchmark traded smaller sizes on different dates. The fee tier and subsecond data are essential to interpreting that result. This project charges fees on both sides. [Live experiment, section 6.3](https://arxiv.org/pdf/2108.09750)
- Menkveld studied an operating high-frequency equity market maker. Spread capture after exchange and clearing fees covered inventory losses. The reported gross trading profit does not include every cost of running the firm. Our long pullback strategy holds directional inventory and lacks that spread-capture business. [Author's working paper](https://research.vu.nl/files/2910592/11076.pdf)
- A live Bybit/Binance experiment found that marketable orders with favorable subsequent returns often received worse execution than the snapshot suggested. That experiment concerns taker orders. Here it motivates measuring marketable rejections and subsequent price movement separately. [Oxford research record](https://ora.ox.ac.uk/objects/uuid%3Acdab1de2-7576-42e2-abae-ab12371eba76)
- The queue-reactive and order-flow forecasting papers motivated the liquidity features and matched replacement test. The theoretical dealer model motivates checking inventory and time exposure. None supplies audited returns for these six coins or Jane Street's private strategy. [Methods and primary sources](../quote-plan.md)

## Live depth and paper orders

At the November 10, 13:25 UTC boundary we scored the recorded exchange data before 13:30 activation. The top 1,000 levels failed to cover both sides of the 1% band for BTC and ETH. SOL, HYPE, AAVE and XRP had complete bands. Their cross-venue basis ranged from −8.53 to −6.21 bp, above the −10 bp entry threshold. Six timely coin decisions produced zero paper orders.

| Coin | Bid/ask imbalance within 1% | Taker buy share, preceding 15 min |
| --- | ---: | ---: |
| BTC | Unavailable | 41.8% |
| ETH | Unavailable | 53.5% |
| SOL | +0.8% | 47.1% |
| HYPE | +2.1% | 47.3% |
| AAVE | +15.2% | 47.7% |
| XRP | +10.4% | 54.1% |

The heatmap shows signed displayed depth at 5, 10, 20, 100 and 200 bp from the midpoint. Taker share measures executed flow. The recorder also saves BTC/ETH options flow for research. Liquidation estimates, screenshot pixels and options features do not enter these six regressors. [CryExc layout, public feed mappings and free terminals](../market-data.md)

From the repository root with the research dependencies installed:

```sh
python -m pip install -r requirements-flow.txt
python train_quotes.py
python live_quotes.py --count 3
python paper_quotes.py
python -m unittest discover
```

The live command waits for a fresh pre-boundary book, reads the just-closed candles, scores the frozen models and updates the local depth heatmap at `data/forward-flow/depth-heatmap.html`. It writes immutable decision snapshots including the scoring time. The paper ledger at `data/forward-flow/paper-orders.json` uses the earliest timely decision per coin and boundary, then replays subsequent closed exchange bars. Re-running reconstructs the same order history with newly observed bars. Late scores are excluded. When capture is stopped, missing boundaries generate no signals. Paper fills remain simulated.

The next test worth the collection cost is to record sequenced trades and depth updates, then measure volume ahead of each prospective quote, partial executions, cancellation timing and 1/5/30-second post-fill markouts. Compare keep and replace on the same event stream. Use new dates for any rule learned from October. [Prioritized file-by-file roadmap](../regime-audit.md)
