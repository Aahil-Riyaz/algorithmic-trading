# Wave pullback experiment

Test May and June 2026 separately with a fresh 60,000 simulated USDT each month. Refit before each month on the preceding six calendar months, excluding labels that could cross the boundary. Use the previous options model's 15 leaves, 120 boosting rounds and 0.05 R threshold throughout. Compare identical monthly refits with and without a wave entry restriction. Also replay the original frozen options model.

For each hourly decision, read the last 72 completed hourly closes. A local high or low must exceed or undercut both closes on either side. This confirms a pivot two hours later. Keep alternating pivots, retaining the more extreme of consecutive highs or lows. For a long, require a low, high and higher low, with the correction retracing 30–75% of an impulse of at least two current hourly ATRs. The latest close must be between the higher low and the impulse high, and the low must have occurred within eight hours. Mirror for shorts. This is a mechanical candidate for a third-wave entry. It cannot identify an entire Elliott count. Keep the existing limit, stop, target, funding and execution model. Report every month and every variant even if a filter barely trades.

For example, an impulse from 100 to 110 and a correction to 105 gives a 50% retracement. The bot still needs two later closes to confirm the low, a qualifying model score and an actual simulated limit fill. The retracement band, lookbacks and ATR multiple are our research choices. [Elliott Wave International on impulse rules](https://www.elliottwave.com/articles/elevate-your-elliott-wave-analysis/)

## Reproduce

| Simulated model | May wins/fills | May net USDT | June wins/fills | June net USDT |
| --- | ---: | ---: | ---: | ---: |
| Original frozen | 58/131 | −366.57 | 61/124 | +338.59 |
| Monthly refit | 35/87 | −555.38 | 64/142 | −308.76 |
| Monthly refit with wave rule | 1/7 | −240.45 | 3/12 | −243.26 |

The wave rule submitted 41 orders. Nineteen filled. Its mean loss was 25.46 USDT per fill compared with 3.77 for the monthly refit alone. Repeated training did not improve the original model in either month. These observations are specific to this pattern and period. [Full results](wave/results.json) · [Order ledger](wave/orders.csv)

First reproduce the original options study using its fit and evaluation commands to populate the October–April cache and frozen control. Then run `python wave_study.py` in the same environment. The study checks the original control model hash, downloads May and June, refits twice, and saves each model's submitted orders and monthly results in `data/wave-run/`. [Original environment and commands](flow-v1/README.md)
