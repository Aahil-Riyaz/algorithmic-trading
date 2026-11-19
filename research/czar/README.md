# Do the pasted four-target alerts make money?

**No. Their entries did no better than random ones.** Three pasted runs of a Discord channel were replayed on Binance USD-M perpetual one-minute candles: 65 alerts on BTC and ten other coins, March 23 to November 19, 2026. The posted limit entry, stop and four targets were used as written.
- **Results:** 59 of the 61 fills resolved. They lost **0.23R per trade** after fees, with a 95% bootstrap interval of −0.47R to +0.03R.
- **Win rates:**
  - **Channel-style count (target 1 before the exit):** 36 trades, or 61%.
  - **Trades that made money:** 17, or 29%.
- **Unreported outcomes:**
  - 43 trades hit their full stop. No stop was ever posted.
  - 25 of those stopped trades had already been announced as a target hit.

**Random comparison.** Random-time entries on the same coins, with each alert's stop and target distances, reached target 1 just as often: 69%, the same as the alerts entered at market. Every exit rule tested was negative on the alerts. They also did slightly worse than the random entries, which mostly just paid fees.

This is a retrospective check of copied messages, not a record of anyone's account. [Replay code](../../czar_audit.py) · [Tests](../../test_czar_audit.py) · [Every alert](replay.csv) · [Totals](results.json)

## Exit rules compared

Mean R per resolved trade after fees, with the 95% bootstrap interval and the share of trades that made money:

| Exit rule | Alerts, limit entry (59–60) | Alerts, market entry (62–63) | Random entries, market (2,600) |
| --- | --- | --- | --- |
| Quarter at each target, posted stop | −0.23R [−0.47, +0.03], 29% | −0.17R [−0.43, +0.09], 34% | −0.16R [−0.20, −0.12], 31% |
| Stop to entry after target 1 | −0.23R [−0.43, −0.02], 56% | −0.22R [−0.40, −0.04], 33% | −0.11R [−0.14, −0.08], 59% |
| Trailing stop: entry, then target 1, then target 2 | −0.20R [−0.39, −0.00], 57% | −0.24R [−0.41, −0.07], 33% | −0.10R [−0.13, −0.08], 59% |
| Half at target 1, stop to entry | −0.22R [−0.40, −0.03], 59% | −0.20R [−0.37, −0.03], 52% | −0.10R [−0.13, −0.08], 66% |
| Half at target 1, trailing stop | −0.20R [−0.37, −0.01], 60% | −0.21R [−0.37, −0.05], 52% | −0.10R [−0.12, −0.07], 66% |

- **Taking profit early and tightening the stop roughly doubles the win rate:** from about 30% to about 60%.
- **It does not create an edge.** Average R stays negative because each extra small win is matched by trades that would have gone on to bigger targets.
- **The rules were not tuned.** These five were the ones proposed and were not adjusted to the results.

## Why a 61% hit rate still loses

- **Target 1 is close.** Its median distance from entry is **0.46R**, meaning 0.46 times the stop distance.
- **Payoffs per trade:** with a quarter at each target, a full run to target 4 earns about +1.5R. Target 1 followed by the stop costs about −0.65R. A straight stop is −1R.
- **Stop size:** the median stop was 1.5% from entry. At the posted 20x leverage that is about 30% of the margin per stopped trade. If every trade used the same margin, the 59 resolved trades together lost about **9 times** that margin.
- **By market:** BTC alerts averaged −0.17R over 49 trades. The ten other-coin alerts averaged −0.51R, with 2 of 10 profitable.

## Replay rules

- **Display time:** Discord times were read as UTC+4. That offset placed 78% of the 88 reported target hits within 30 minutes after the level traded, against at most 65% for any other offset.
- **Entry:** each alert starts at the next full minute. The entry is a limit that fills when price trades back to it, and it lapses after 24 hours.
- **Exits:**
  - The stop takes priority when stop and target trade in the same minute.
  - Targets count from the minute after the fill.
  - A position still open after seven days is closed.
- **Costs:** 2 bp maker on entries and targets, and 5 bp taker plus 1 bp slippage on stops. Funding is ignored.
- **Random baseline:** 40 random times per alert on the same coin's candles, entered at market, with stop and targets at the alert's percentage distances.

**Hits before entry.** 18 of the 88 reported hits came before the limit entry had traded, and three alerts never filled.

![BTC alerts on price, and cumulative R across all alerts](replay.png)

## Limits

- **Assumed exits:** the channel states no exit management, so every rule above is an assumption.
- **Ambiguous messages:**
  - One alert had no post time.
  - Two hit posts could belong to more than one open alert. They were assigned to the most recent matching alert, as noted in [alerts.csv](alerts.csv) and [hits.csv](hits.csv).
- **Sample:** these pastes may not be the channel's complete history.
- **Fills:** minute candles cannot show queue position or partial fills.

```
python czar_audit.py
```
