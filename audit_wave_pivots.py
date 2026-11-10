"""Does a two-sided five-minute swing at the disclosed Wave 1 level predate the alert?"""
import csv
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from perp_market import bars_from_rest
from regime_data import rest_candles

OUT = Path("data/discord-audit")


def clock(s):
    return int(datetime.fromisoformat(s).timestamp())


def probe(bars, at, level, side):
    # The actual implementation/timeframe is unknown. Test a specific common five-bar pivot.
    tol=float(Decimal(1).scaleb(Decimal(level).as_tuple().exponent))/2
    values=[b.high if side=="LONG" else -b.low for b in bars]
    confirmed,late=[],[]
    for j in range(2,len(bars)-2):
        end=bars[j].time+300
        if not at-48*3600 <= end <= at or abs(abs(values[j])-float(level))>tol+1e-10:
            continue
        if values[j]>max(values[j-2:j]+values[j+1:j+3]):
            known=bars[j+2].time+300
            (confirmed if known<=at else late).append(known)
    status="prior_match" if confirmed else "confirmation_after_post_only" if late else "no_matching_pivot"
    return dict(probe=status,prior_matches=len(confirmed),late_matches=len(late),
                latest_prior_confirmation=max(confirmed,default=""),earliest_late_confirmation=min(late,default=""))


def run():
    with (OUT/"signals.csv").open() as file:
        alerts=[r for r in csv.DictReader(file) if r["wave1"]]
    results=[]
    for coin in sorted({r["coin"] for r in alerts}):
        group=[r for r in alerts if r["coin"]==coin]
        stamps=[clock(r["signal_time"]) for r in group]
        first=min(stamps)//300*300-48*3600-900
        last=max(stamps)//300*300+900
        bars=bars_from_rest(rest_candles(coin,first,last))
        for r,t in zip(group,stamps):
            results.append(dict(signal=r["signal_id"],utc=r["signal_time"],side=r["side"],wave1=r["wave1"],
                           **probe(bars,t,r["wave1"],r["side"])))
    with (OUT/"pivot-probes.csv").open("w",newline="") as file:
        w=csv.DictWriter(file,fieldnames=list(results[0]))
        w.writeheader()
        w.writerows(results)
    print(Counter(r["probe"] for r in results))


if __name__=="__main__":
    run()
