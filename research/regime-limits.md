# Five-minute regime and liquidity gates

From the repo root install `requirements-flow.txt` in the project environment and run `python train_limits.py`. The trainer downloads July–September 2026 inputs and saves twelve XGBoost classifiers (one per coin per fold), coverage counts, validation results and submitted orders in `data/regime-limits/`. Use `python train_limits.py --legacy` for the earlier pooled baseline.

## Entry clock

Evaluate every five minutes on finished candles. Divide 30-minute cumulative quote turnover by base volume for traded VWAP and measure the latest perp close's deviation in basis points. On the same five-minute phase, form hourly high/low bars and compute the mean of 14 hourly true ranges. Block a long when that ATR exceeds 1.5 times the average of the preceding 168 hourly ATR observations. The reference excludes the current observation.

Use simultaneous KuCoin USDT spot and Binance USDT perpetual closes for each asset, including HYPE. Basis is 10,000 × (perp / spot − 1). This measures cross-venue basis, which includes exchange-specific price differences. The mean-reversion setup requires a discount of at least 10 basis points and a perp close below its rolling VWAP. A premium of 10 basis points or more explicitly vetoes the long. Neutral basis also sits out this strategy. A discount qualifies a setup for scoring and does not guarantee convergence.

Require the last 30 minutes' turnover to reach half the preceding 24-hour average for a 30-minute interval. Displayed bid notional inside 1% must reach half the equivalent ask notional. Sample the latest complete archived book before the five-minute boundary, at most three minutes old. For a recorder snapshot, pass `live_record=record` to `regime_filters.observation`. It checks coverage and receipt time. Missing spot, warmup, stale funding and missing books suppress entries. Actual aggressor flow uses buyer-initiated quote volume divided by seller-initiated quote volume over 30 minutes.

Both replay arms use a half-ATR pullback limit, the existing wide stop and target, one five-minute activation delay, and one five-minute entry lifetime. Stops and time exits use the existing slippage and funding model. Filters are sampled at decision time. An intra-candle cascade can still fill and stop the order.

## Training and validation

Each coin fits its own XGBoost binary classifier with 100 depth-three trees and a fixed 0.50 probability cutoff. It learns wins after trading costs and funding conditional on a fill, across all observed regimes for that coin. It uses no shared weights, pooled prior or random split. Funding features include the sum and count of completed settlements over four hours and the last known rate. Zero settlements is meaningful on an eight-hour schedule. The realized-settlement sum differs from an indicative live funding quote.

August and September are successive validation windows. The August model learns from July after warmup. September can use completed July and August labels. The split takes half-open intervals from decision time through the end of the exit candle or expiry. It requires each training label to finish at least 24 hours before validation starts. A 24-hour post-validation embargo also excludes intersecting examples from subsequent training. Validation only admits decisions whose full possible horizon fits in the fold, regardless of the actual outcome. [Splitter](../purged_cv.py) · [Entry features](../regime_filters.py)

## Historical result

| Variant | August wins / fills | August net USDT | September wins / fills | September net USDT |
| --- | ---: | ---: | ---: | ---: |
| Per-coin model alone | 69 / 142 | +176.46 | 57 / 142 | −832.57 |
| Same scores with all gates | 12 / 20 | +197.79 | 2 / 4 | +49.98 |

Each month starts with 60,000 simulated USDT across six accounts. The filters produced 14 wins from 24 fills and +247.77 USDT summed across monthly resets. SOL accounted for +214.83 USDT on four fills. BTC and ETH had zero filtered fills. This comparison tests the filters together. It does not isolate ATR's contribution, prove that past losses were liquidations, or measure live performance. The 10 bp basis threshold and liquidity floors are fixed research assumptions.

[Per-asset fold results](regime/results.json) · [Order ledger](regime/orders.csv)
