# Six-hour limit expiry

Pending entries have 72 five-minute bars from activation to fill. An order activated at 09:00 UTC can fill through the 14:55 bar and expires at 15:00. A newer qualifying signal for the same coin can replace a pending entry sooner. The holding period for a filled position runs from its fill.

All six per-coin models were retrained with six-hour entry labels. The training embargo and end-of-test cutoff allow the full entry and exit horizons. Run `python train_quotes.py` to reproduce the comparison and create the six-hour models for `python live_quotes.py`. Paper replay uses each recorded quote's original expiry.

| October 2026 historical replay, same signals | Submissions | Wins / fills | Net USDT |
| --- | ---: | ---: | ---: |
| Six-hour expiry | 104 | 22 / 56 | −337.85 |
| 15-minute expiry | 155 | 12 / 31 | −223.71 |

Of 104 six-hour submissions, 56 filled, 35 were replaced and 13 expired. Of the fills, 36 occurred at least 15 minutes after activation. Longer-lived entries changed which later signals found the account available. October had already been examined before this change, so this comparison is retrospective. Both rows include fees and funding. The [original 15-minute study](../october-quotes/README.md) used a separately trained model.

[Execution configuration](../../quote_replay.py) · [Signals and fills](signals.csv) · [All controls and drawdown](totals.json) · [Per-coin results](results.json)
