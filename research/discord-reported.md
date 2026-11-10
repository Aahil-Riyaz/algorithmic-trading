# What the copied Discord messages actually contain

The available 30,000-byte paste starts **October 29 at 16:17 UTC** and ends **November 10 at 19:24 UTC**, 2026. The first local timestamp is October 29 at 20:17 in Dubai. The parser anchors “Yesterday” to the supplied copy date of November 11. There are posts on October 30 after 07:31 local, November 1 and November 2. Gaps can conceal entire alerts and outcomes. All claims below about reported fills come from the copied status messages.

| Source | Closed | TP or wins | SL or losses | BE | Expired | Invalidated | Unresolved |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 54 visible setup cards | 14 | 6 | 4 | 4 | 2 | 36 | 2 |
| One cumulative post, November 1 at 17:39 UTC | 136 | 62 | 46 | 28 unclassified | 31 | 293 | Unknown |

All 52 visible terminal updates linked to exactly one setup using side, symbol, chronology, available rounded entry/exit levels and the pending-order expiry. Confirmed fills represent **25.9% of all 54 proposals** and 26.9% of the 52 resolved. If both unresolved setups filled, fill rate would be 29.6%. Thirty-six invalidations represent 66.7% of proposals. Their median delay was 32.5 minutes, with 15 of 36 between three and twenty minutes inclusive. ETH and AVAX each have one unresolved long at the end of the copy.

The cumulative card on source line 424 reports 45.6%, +31.80R total, +0.234R per close, +1.25R/−1.00R average win/loss, 1.25:1 realized R:R and +31.80% simulated return at 1% risk. Its win rate uses 62/136. The 28 residual closed trades are consistent with break-evens, though the card does not classify them. If all terminal categories are exclusive and exhaustive, 324/460 (70.4%) never filled. The earlier 124-closed card and October 21 alerts are absent. One observation cannot establish a trend, a starting balance or the full net ledger.

The six visible winning updates each report +1.50R. With four stops and four break-evens, the reported portion totals **+5.00R gross**. The reason the cumulative average winning trade paid +1.25R remains unidentified. Fees could not explain a reduced *before-fee* number, and zero-R trades outside the winners cannot change the average over winners. Earlier smaller wins, different exits or an accounting difference require the missing individual records.

## Fees at the original printed geometry

One R is the original absolute entry-to-stop distance per coin. Model fees on each executed leg's notional, assuming 2 bp maker, 5 bp taker and an adverse 1 bp of slippage per taker leg. The actual account tier, funding timestamps and queue fills are unknown. For reported exits use the full setup geometry and the posted outcome. Nonfills earn zero, unknown outcomes remain blank. Maker/maker is an optimistic sensitivity including passive stop execution. Mixed means maker entry, passive TP, market stop and break-even exits. [Binance fee schedule](https://www.binance.com/en-BH/fee/futureFee)

| Assumed execution | Net total, R | Net R/fill | Net R/resolved proposal | 95% bootstrap interval, R/fill |
| --- | ---: | ---: | ---: | --- |
| Maker/maker | +2.710 | +0.194 | +0.052 | −0.407 to +0.564 |
| Maker/taker-stop | +1.359 | +0.097 | +0.026 | −0.545 to +0.499 |
| Taker/taker | −1.849 | −0.132 | −0.036 | −0.722 to +0.257 |

The intervals resample the ten represented UTC signal days together across coins, 10,000 draws with a fixed seed. Only six days contain reported fills. They describe sampling variation conditional on these reports. Gaps, nonrandom copying, interday dependence, unknown fills and funding remain additional sources of uncertainty.

The median proposed stop is 0.2241% of entry. Risking 1% of equity at that stop implies approximately 4.46× account equity in initial notional before fees. Seven basis points of round-trip commission alone would consume 0.312R at the median geometry. Multiplying total R by a fixed 1% explains the printed return exactly. The post gives no portfolio-equity path or evidence about concurrent leverage, actual compounding or fills.

| Dots | Posted | Confirmed fills | TP | Mixed net R/fill |
| --- | ---: | ---: | ---: | ---: |
| 2 | 7 | 4 | 3 | +0.731 |
| 3 | 7 | 3 | 2 | +0.768 |
| 4 | 13 | 1 | 0 | −0.380 |
| 5 | 27 | 6 | 1 | −0.582 |

Five dots appeared on half the alerts. Within this sample more dots correlated negatively with filling (r = −0.246, 52 resolved), hitting TP given a fill (r = −0.544, 14 fills), and mixed net R given a fill (r = −0.547). Two-sided within-signal-day permutation checks give p = 0.143, 0.227 and 0.155 respectively. These small, observational buckets supply no validated probability or reliable inverse signal. Four break-even exits lost **1.575R in total** under mixed execution. Whether moving the stop helped requires the subsequent price paths and a specified counterfactual trigger.

## Reproduction

Run `python discord_audit.py "path/to/Pasted text.txt" --as-of 2026-11-11`. The local `data/discord-audit/` folder contains the full `signals.csv`, all available cumulative posts in `cumulative.csv`, `groups.csv` (every observed UTC signal hour, side, coin and confidence bucket with counts, denominators and each fee scenario), and `reported.json` (source hash, match issues, bootstrap and confidence checks). The SHA-256 of the reviewed paste is `9822e8f60ef2ece58c9e629a7cd40438f22a74fab96e2e8a7be66fb937a7dc93`. Preserve the original copy date when re-running. The script accepts `--maker-bps`, `--taker-bps` and `--slip-bps`.
