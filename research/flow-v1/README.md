# Training the two-sided model

The research question is whether options activity and order flow can identify a pullback worth trading, including which side to take. At each eligible hour the model scores two hypothetical orders on the same coin. A positive score is an estimate in risk units. It is not a probability of winning.

## Reproduce the run

Python 3.11 or newer is required for this experiment. The recorded environment used Python 3.14.3, scikit-learn 1.9.1, NumPy 2.5.4 and SciPy 1.18.1. From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-flow.txt
.\.venv\Scripts\python -m unittest -v
.\.venv\Scripts\python train_flow.py fit
.\.venv\Scripts\python train_flow.py evaluate
```

On macOS or Linux, use `.venv/bin/python` for the commands inside the environment. The first run downloads public data without exchange keys. It verifies Binance archive checksums, checks the five-minute candle clock, caches completed files and fingerprints the inputs. Training and evaluation produce separate files under `data/perp-flow-v1/run/`. Re-running the commands replays the same dates. Results from these dates have already been seen.

## What was trained

- **Examples.** Use the same six Binance USDT perpetuals and two possible directions. Five months supplied 21,378 eligible coin-hours and **42,756 hypothetical orders**. Many proposals share candles, so the independent sample size is smaller. Historical training inputs included **143,246 qualifying BTC and ETH option prints** across 1,208 fixed sampling windows. Another 43,060 qualifying prints fell in the held-out windows.
- **Features.** Start with past price changes over 1, 6 and 24 hours in units of ATR, the close's location in its prior 12-hour range, volatility, relative volume, side and stop geometry. Add signed taker-flow imbalances, visible bid/ask imbalance at 1% and 2%, and last settled funding. The final model also gets call share of premium, call-buyer imbalance, put-buyer imbalance and log trade count for BTC and ETH. Directional features are oriented to the proposed side. The regressor learns whether each input helps or hurts. [Market-data definitions](../market-data.md)
- **Labels.** Resolve each proposed order on later five-minute candles. A fill earns realized P&L after fees, slippage and funding divided by planned stop risk. An expired order earns zero. The execution replay allows one pending order or open position per coin. Buying and selling the same coin simultaneously would overstate capacity.
- **Validation.** Fit first on October–November 2025. Validate on December, expand training and validate on January, then repeat for February. Purge any setup whose maximum possible exit crosses a split. Score three tree sizes and three thresholds per feature set. Across the three feature sets this made **27 fold-specific model fits, 81 validation replays and three final fits**, with 120 boosting iterations per fit. Each threshold comparison uses the same trained trees. [All fold results](validation.json)
- **Selection.** Maximize total validation P&L with at least 20 fills in every fold. All chosen candidates met the activity requirement. The full model selected 15 leaf nodes and a 0.05 R threshold. It lost 1,346.47 USDT in December and 981.47 in January, then made 1,673.66 in February. Total validation P&L was **−654.28 USDT**. Its settings and input fingerprints were committed before scoring March and April. [Frozen settings](freeze.json)
- **Execution.** Signals use finished hourly inputs and the orders activate five minutes later. A long quotes half an ATR below the close and a short quotes half an ATR above. Orders expire after two hours. The stop is beyond the trailing 12-hour low or high by 0.25 ATR, with minimum distances of two ATRs and 1.5% of entry. The quantity is reduced to keep ordinary stop risk within 0.5% of that coin's cash. The take-profit targets 1.5 times that risk after fees and modeled stop slippage, before funding.
- **Fills and clocks.** Require price to trade through an entry or take-profit. Count an adverse stop first when both exits are possible inside the same five-minute candle, except when the bar already opens through the target. On the fill bar, only an adverse stop is eligible. Close remaining positions after 24 hours. An exact tie in estimated long and short returns skips the setup. The 26-hour maximum order lifecycle fits completely inside each evaluation period. [Execution code](../../perp_orders.py)
- **Costs and exposure.** Six independent 10,000 USDT accounts, at most one-times account notional per coin, fees of 0.10% per side and 0.02% adverse slippage on market exits. These are fixed research assumptions. The equity curve marks concurrent positions to five-minute closes with estimated exit costs and accrued funding. The price path inside each candle, exchange queue position, partial fills, outages and liquidation mechanics remain uncertain. [Replay code](../../flow_replay.py)

## Read the result

The full model won 118 of 284 fills in the final two months. Net return was −1.76% and five-minute-close portfolio drawdown reached 2.96%. Both months lost money. The model estimated positive returns for setups whose realized average was **−0.076 R per fill**. With the current evidence, this strategy belongs in research.

[Win-rate history, matched controls and stop comparison](../scorecard.md) · [Detailed test results](holdout.json) · [Every submitted test order, including expirations](orders.csv)

The CSV uses UTC Unix seconds. `feature_cutoff` is the hourly data boundary and `active` is the next five-minute candle. `fill` and `end` identify the start of the simulated execution candle. An empty fill or exit price means the entry expired. Net P&L includes funding. The published results aggregate actual simulated fills for the selected orders.

Run `python research/flow-v1/audit.py` to independently check the published CSV against the results and model freeze. It checks order overlap, position sizing, win counts, P&L, fees, and an illustrative maker/taker fee sensitivity. The audit needs no downloads or third-party packages.
