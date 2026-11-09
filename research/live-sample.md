# Example of a live capture

**2026-11-09 07:27 UTC** is the end of the 15-minute trade window. These are executed Binance USD-M perpetual trades. Net aggressive flow is taker-buy minus taker-sell quote volume. The depth snapshots were requested separately just after the trade window.

| Coin | Taker buy share | Net aggressive flow (USDT) | Bid share of resting depth within 0.10% | Full 2% band visible |
| --- | ---: | ---: | ---: | --- |
| BTC | 46.1% | -21,795,665 | 45.4% | Partial |
| ETH | 43.8% | -66,135,038 | 47.4% | Partial |
| SOL | 47.8% | -1,930,968 | 51.0% | Yes |
| HYPE | 48.2% | -440,872 | 49.2% | Partial |
| AAVE | 46.3% | -161,116 | 45.4% | Yes |
| XRP | 54.3% | +1,524,172 | 43.2% | Yes |

## Options traded in the preceding 20 minutes

Each premium figure is in USD and comes from qualifying Deribit trades. Buy and sell refer to the aggressor. The command separately records the 20-minute sample at the most recent six-hour boundary for use with the model's feature definition.

| Underlying | Call buys | Call sells | Put buys | Put sells | Trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC | 21,169 | 37,304 | 15,777 | 124,855 | 155 |
| ETH | 21,787 | 329,215 | 50,091 | 8,000 | 215 |

Run `python flow_live.py` from the repo root for current values. This saved snapshot illustrates the feed and has no trading outcome. [Data and live layout](market-data.md)
