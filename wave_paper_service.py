"""Advance prospective signals using only closed Binance USDT-perp minutes."""
import argparse
import math
import time

from aahil_wave import ACTIVE, advance, checkpoint, connect, states, transaction
from flow_data import FUTURES, request_json


def catch_up(db, now=None):
    now = int(time.time()) if now is None else now
    stop = (now-2)//60*60
    while _advance_page(db,stop):
        pass


def _advance_page(db, stop):
    active = {k:s for k,s in states(db).items() if s["status"] in ACTIVE}
    if not active:
        return False
    # One shared page end keeps every coin's risk marks on the same UTC minute.
    end = min(stop,min(s["last"]+60 for s in active.values())+500*60)
    batches = {}
    for key,s in active.items():
        first = s["last"]+60
        if first>=end:
            continue
        params = dict(symbol=s["coin"]+"USDT",startTime=first*1000,endTime=end*1000-1)
        raw = request_json(FUTURES+"/klines",dict(**params,interval="1m",limit=500))
        if ([r[0] for r in raw]!=list(range(first*1000,end*1000,60000))
                or any(r[6]!=r[0]+59999 for r in raw)):
            raise ValueError("Incomplete exchange minute history")
        events = request_json(FUTURES+"/fundingRate",dict(**params,limit=100))
        funds = [(int(f["fundingTime"])//1000,float(f["fundingRate"]),float(f["markPrice"])) for f in events]
        stamps = [f[0] for f in funds]
        if stamps!=sorted(set(stamps)) or any(not (first<=t<end and math.isfinite(rate) and
                math.isfinite(mark) and mark>0) for t,rate,mark in funds):
            raise ValueError("Invalid funding settlements")
        for r in raw:
            bar = (r[0]//1000,*[float(v) for v in r[1:5]])
            batches.setdefault(bar[0],[]).append((key,bar,funds))
    for t, batch in sorted(batches.items()):
        # Crash recovery must never observe half a portfolio minute or lose the
        # equity checkpoint when the last open position closes.
        with transaction(db):
            for key,bar,funds in batch:
                advance(db,key,bar,funds)
            checkpoint(db,t+60)
    return bool(batches) and end<stop


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch",action="store_true")
    args=parser.parse_args()
    db=connect()
    while True:
        catch_up(db)
        if not args.watch:
            break
        time.sleep(30)
