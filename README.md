# Algorithmic Trading

Can a Bitcoin breakout pay for its own trading costs? This is a Python research project for testing that question. The first experiment replays BTC/USDT spot trades on hourly candles. It uses public data and simulated USDT.

## Run the experiment

From the repository folder with Python 3.10 or newer:

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

## Next experiment

- Freeze this baseline. Reserve a fresh, later period for a final comparison since the 2024 results are now visible.
- Test a 1D convolutional neural network as a filter on the same breakout opportunities. Feed it trailing sequences of candle returns, ranges and volume. Label past examples by whether the simulated trade earned money after costs. Fit input scaling on training data alone and exclude training labels whose exits cross the split boundary.
- Pick a score threshold on chronological validation folds. Compare its trade count, average net profit per trade, drawdown and total return against the unfiltered rule under identical execution assumptions.
- Forward-test the frozen strategy with a paper account. Log each decision when it happens, including skipped entries. Compare observed spreads and simulated fills with the backtest assumptions before considering automation.

The project currently models bar-level execution. Order-book depth, partial fills, exchange lot sizes and service interruptions are outside the first simulation.
