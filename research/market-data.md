# The live layout and its data

[Open the original CryExc layout](https://cryexc.josedonato.com/app?layout=Pq4IMXG9) to restore the shared configuration. I checked its public settings on November 9, 2026. It is named **My Layout**, was created on August 19, and enables 15 windows. Its Live Heatmap requests a 500 ms sampling interval and a 300-second display history, with order-book profile, trade circles and liquidation overlays enabled. The original link preserves the docking and tabs. [Saved layout settings](https://cryexc.josedonato.com/api/layouts/Pq4IMXG9)

| Enabled CryExc windows | What enters the experiment |
| --- | --- |
| Live Heatmap, OB Stats | Binance perpetual bid and ask notional within 1% and 2% of the market. Use the latest complete archived snapshot in the last three minutes of each hour. Screenshots, individual walls and cancellations between snapshots are outside this input. |
| Footprint Chart, Trades, CVD | Executed taker-buy and taker-sell quote volume over 1, 6 and 24 completed hours. These supply normalized volume delta. The visual terminal also has per-price and trade-size detail. |
| Options | Actual Deribit BTC and ETH single-leg call and put trades in fixed 20-minute sampling windows. The model uses observed premium flow. The full chain, dealer gamma and open interest are separate measurements. |
| Historical Chart | Five-minute Binance perpetual candles for execution, aggregated to completed hourly bars for signals. |
| Market Correlation, Premium Index, ETF Flows, Market Times, Economic Calendar | Available for reading the layout. No inputs from these five panels were used in this run. Each would require its own publication clock and historical series. |
| Liquidations, HL Liquidation, HL Cohorts | Available in the layout. Forced orders, estimated liquidation levels and wallet cohorts describe different events. This run has no verified historical series for those panels in its inputs. |

The tested venue is Binance USD-M. CryExc can aggregate several exchanges, so its displayed flow can differ. A resting bid can be cancelled. A taker buy is an executed trade initiated by a buyer accepting the ask. The buy share measures taker-buy quote volume divided by total quote volume. It does not count unique traders or reveal their positions. [CryExc venue and aggregation guide](https://cryexc.josedonato.com/docs/primary-aggregation)

## Free tools worth opening

| Tool | Best use in this project | Access and training use |
| --- | --- | --- |
| CryExc | View the saved footprint, heatmap, CVD, options and liquidation panels together in a browser. | Free terminal. The experiment uses exchange event data corresponding to selected panels. [Exact layout](https://cryexc.josedonato.com/app?layout=Pq4IMXG9) |
| Flowsurface | Inspect how visible liquidity shifts on the depth heatmap, then check whether trades actually execute there on the footprint. | Free, open-source desktop workstation. It connects directly to public exchange feeds. [Flowsurface](https://flowsurface.com/) |
| aggr | Cross-check aggressive trades and volume delta across venues during a fast move. | Open-source aggregated trade tape. This answers who crossed the spread. [aggr.trade](https://aggr.trade/) · [Project](https://github.com/Tucsky/aggr) |
| CoinGlass | Inspect possible liquidation concentrations as a separate hypothesis. | Public chart with tier-dependent access. Its zones are estimates from a liquidation model. No premium API, scraped tiles or inferred liquidation labels enter training. [Liquidation heatmap](https://www.coinglass.com/pro/futures/LiquidationHeatMap) · [Method](https://www.coinglass.com/learn/coinglass-intro-en) |

## Reproducible feeds

- **Prices and executed volume.** Monthly five-minute USD-M perpetual archives contain OHLC, quote volume and taker-buy quote volume. Taker-sell quote volume is the difference. All six instruments are USDT perpetuals. [Binance public-data schema](https://github.com/binance/binance-public-data)
- **Resting depth.** Daily bookDepth archives contain cumulative bid and ask notional by percentage band. The 1% and 2% bands span the research period. The earlier files lack the newer 0.2% band. Missing or stale observations exclude that hour for every model being compared. [Binance depth archive](https://data.binance.vision/?prefix=data/futures/um/daily/bookDepth/)
- **Funding.** Historical settlement time, signed rate and the mark price come from Binance. A positive rate transfers money from longs to shorts. The simulator charges adverse funding and omits favorable funding on an ambiguous entry or exit candle. [Binance funding history](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History)
- **Options.** Query the 20 minutes preceding 00:00, 06:00, 12:00 and 18:00 UTC on Deribit's history host. Split truncated responses by event time and check trade IDs for duplicates. Exclude flagged block and combo trades. Use underlying amount × option price × index price to estimate USD premium for inverse BTC and ETH options. Keep call buys, call sells, put buys and put sells separately. A bought call may hedge a short. These samples do not reveal whether the trader opened or closed a position. [Deribit trade API](https://docs.deribit.com/api-reference/market-data/public-get_last_trades_by_currency_and_time)

The two options underlyings provide market context for all six perpetuals. For example, a SOL trade uses SOL's own order flow and market-wide BTC and ETH options context. Every holdout decision uses a snapshot with an earlier event time. Historical archives were downloaded after the events and can incorporate vendor corrections. Exact historical delivery latency cannot be recovered. The five-minute activation delay and saved input fingerprints make that assumption auditable.

## Capture what is happening now

Run `python flow_live.py` for a fresh six-coin sample, or `python flow_live.py --count 60 --interval 60` for a bounded session. These commands need no credentials. They save the exchange timestamps, local receipt times, raw top-1,000 bid and ask levels, visible USDT depth bands, rolling 15- and 60-minute aggressive buy/sell volumes, and rolling and six-hour-anchored Deribit option samples. The terminal shows the taker-buy share over the last 15 completed minutes. [Binance market data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)

The original CryExc layout remains the live visual companion. The local recorder stores numerical observations under `data/forward-flow/`. A band is complete only when the returned ladder reaches both edges. A truncated band keeps its observed quantities and a missing imbalance value. Use `python flow_live.py --export-hourly` to write comparable 1%/2% observations from the final three minutes of each hour. `perp_market.load_market(..., depth_folder=...)` can read those daily exports for a later period with completed candles and funding outcomes. Capture files are timestamped and kept outside the historical scorecard. No live or paper account returns have been measured by the recorder.
