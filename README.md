# Algorithmic Trading

Can price, visible liquidity and options flow predict a profitable limit entry on **BTC, ETH, SOL, HYPE, AAVE and XRP**? This project tests ideas with public exchange data and keeps a record of each result.

**Latest held-out run (March–April 2026)** — 118 wins from 284 filled long and short orders, **41.55% win rate, −1.76% net return**, and 2.96% maximum drawdown. Live P&L is unmeasured. The earlier spot experiments are preserved below.

| Start here | What to open |
| --- | --- |
| Compare the starting and current win rates | [Scorecard, same-period controls and stop-out study](research/scorecard.md) |
| Reproduce the two-sided model | [Data, training, frozen model selection and execution](research/flow-v1/README.md) |
| Check individual trades | [All 518 submitted orders](research/flow-v1/orders.csv) and [results by coin and side](research/flow-v1/holdout.json) |
| Read a live heatmap | [Original shared CryExc layout](https://cryexc.josedonato.com/app?layout=Pq4IMXG9) and [free tools and panel guide](research/market-data.md) |
| Capture current market flow | Run `python flow_live.py` to record displayed bids/asks, aggressive buy/sell volume and BTC/ETH call/put premium flow. [Example snapshot](research/live-sample.md) |

<a id="run-the-experiment"></a>

## Earlier spot experiments

### Train the limit-entry model

Run `python train_limits.py` for the six-coin research run. At each hourly close the strategy posts a simulated buy half an ATR below the close. ATR here is the mean true range of the last 14 completed hours. The entry expires after two hours. Each coin allows one pending order or open position at a time.

The stop sits one ATR below the limit with a minimum distance of 0.5%. Position size risks 0.5% of that coin's cash on an ordinary stop. The target pays 1.5 times this risk after the assumed 0.10% fee per side and 0.02% slippage on market exits. The simulator requires a trade through the limit, assumes a full fill at the limit and ignores favorable entry gaps. It checks the stop immediately and allows target fills starting the following hour. A gap through the stop can increase the loss. Positions time out after 24 candles. Hourly data cannot verify queue priority or partial fills.

The model learns how often filled trades made money at different levels of volatility and six-hour momentum. It pools the six coins and smooths sparse groups toward the training win rate. Three expanding validation folds in October–December 2025 compare three bin counts and four entry thresholds. Selection maximizes total validation profit with at least 20 fills per fold. Each split excludes new orders in the last 24 hours so every possible outcome resolves inside its own window. Training considers overlapping hypothetical setups, while the trading replay enforces one active order per coin.

January 2026 was held out for the first evaluation. Six independent accounts started with 10,000 simulated USDT each.

| January replay | Orders | Fills | Winners | Win rate | Net P&L | Return |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Every eligible limit setup | 967 | 524 | 161 | 30.73% | −5,761.11 USDT | −9.60% |
| Trained filter | 288 | 144 | 45 | 31.25% | −1,522.84 USDT | −2.54% |

The selected model used six bins per feature and a 0.35 score threshold. Its average winner was 1.49 times its average loser. Its three validation folds also lost money in aggregate. The frozen model, validation scores and both January order ledgers are written to `data/limit-run/`. Ledger times are UTC Unix seconds. Future revisions need a later evaluation period because the January results are now visible.

### Reproduce the breakout comparison

Run the six-coin comparison from the repository folder with Python 3.10 or newer.

```sh
python compare.py
```

The first run downloads 2,208 hourly candles per coin from KuCoin for October through December 2025. Later runs use the cached files. Use `python compare.py --refresh` to download again. The comparison checks timestamp continuity and candle prices, runs each coin with its own 10,000 USDT per period, and saves the fills in coin-trades.csv. All six use the same strategy, costs and chronological 60/20/20 split. [KuCoin candle data](https://www.kucoin.com/docs-new/rest/spot-trading/market-data/get-klines)

The held-out period starts December 13 at 14:00 UTC and ends December 31 at 23:59 UTC.

| Coin | Trades | Win rate | Net return | Buy and hold |
| --- | ---: | ---: | ---: | ---: |
| BTC | 10 | 10.0% | -3.71% | -3.13% |
| ETH | 9 | 11.1% | -3.23% | -4.67% |
| SOL | 10 | 20.0% | -2.52% | -6.60% |
| HYPE | 8 | 12.5% | -2.74% | -12.67% |
| AAVE | 6 | 16.7% | -1.76% | -26.45% |
| XRP | 8 | 12.5% | -2.74% | -9.64% |

### Reproduce the original Bitcoin experiment

```sh
python prices.py
python -m unittest -v
python backtest.py
```

The downloader checks each monthly archive against its SHA-256 checksum and checks the full year for missing hours. The backtest runs offline once market.csv exists. It prints the score for each period and writes each simulated trade to trades.csv. The time and exit_bar columns are UTC Unix seconds marking the start of the hourly candle. Intrabar exit times are unknown. [Binance archive documentation](https://github.com/binance/binance-public-data)

## How a trade works

1. At the end of each hour, compare its closing price with the highest price of the previous 20 completed hours. A close strictly above that level triggers a buy at the following open if the account is flat.
2. Buy spot with available cash. Set a stop 1% below the simulated entry and a target 2% above it. Size each trade so an ordinary stop costs 0.5% of account equity including costs. A gap can cause a larger loss.
3. Assume a fee of 0.10% and adverse slippage of 0.02% per side. These are experiment settings. A stop gapped through fills at the opening price less slippage. A target gapped through fills at the target less slippage. If the bar opens between the levels and touches both, count the stop first.
4. Hold one position at a time. Close any remaining position at the last close of the period. Track drawdown from peak equity at hourly closes. Intrahour drawdowns can be larger.

## First run

Each period starts with 10,000 simulated USDT. Split the 8,784 hourly candles of 2024 chronologically into 60% development, 20% validation and 20% test. Earlier completed candles can supply signal history at a boundary. Positions and balances reset. The breakout has fixed rules and requires no training.

| Period | Trades | Win rate | Average win / average loss | Net return | Max drawdown | Buy and hold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Development | 149 | 32.89% | 1.46 | -13.52% | 15.86% | +34.09% |
| Validation | 44 | 31.82% | 1.49 | -4.31% | 5.97% | +19.68% |
| Test | 59 | 32.20% | 1.46 | -6.05% | 7.69% | +36.92% |

The last period runs from October 19 at 19:00 UTC through the end of December. Its average trade lost 10.26 USDT. Buy and hold invests the full starting balance and pays the same entry and exit costs. The breakout spends part of the time in cash. The comparison measures portfolio outcomes at different exposures.

A 2% target and 1% stop give a planned 2:1 reward-to-risk ratio before costs. The table uses actual average winning and losing trades in USDT after costs. At the observed 1.455 ratio, about 40.7% of trades would need to win to break even if average win and loss sizes stayed the same. Only 19 of 59 won.

The original spot baseline uses bar-level execution. The subsequent perpetuals study adds depth, funding, two-sided orders and finer execution candles. [Current study](research/flow-v1/README.md)
