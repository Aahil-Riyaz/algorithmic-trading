"""Dated USDT-perpetual inputs for Aahil Wave's four-contract mandate."""
import argparse
import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from statistics import median
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zlib

from flow_data import ROOT, candle_file, depth_file, funding_file, save_json

COINS = ("BTC", "ETH", "SOL", "AVAX")
FIRST = date(2023,12,1)   # first month supplies lagged membership and warmup
END = date(2026,1,1)
OUT = ROOT.parent / "aahil-wave"


def next_month(m):
    return (m.replace(day=28)+timedelta(days=4)).replace(day=1)


def months(first=FIRST,end=END):
    while first < end:
        yield first
        first = next_month(first)


def quotes_prefix(coin, month):
    """Published first-of-month L1 prefix. Record time range of actual observations."""
    url = f"https://datasets.tardis.dev/v1/binance-futures/quotes/{month:%Y/%m/%d}/{coin}USDT.csv.gz"
    with urlopen(Request(url,headers={"Range":"bytes=0-524287"}),timeout=30) as response:
        blob = response.read(524288)
    data = zlib.decompressobj(31).decompress(blob)
    rows = list(csv.DictReader(io.StringIO(data[:data.rfind(b"\n")].decode())))
    # Reconstruct each update from last observed sizes and prices, retaining local receipt time.
    by_bar = {}
    spreads = []
    previous = None
    for row in rows:
        bid,ask,bq,aq = (float(row[k]) for k in ("bid_price","ask_price","bid_amount","ask_amount"))
        if min(bid,bq,aq) <= 0 or ask <= bid:
            continue
        t = max(int(row["local_timestamp"]),int(row["timestamp"]))//1_000_000
        mid = (ask+bid)/2
        spread = (ask-bid)/mid*10000
        spreads.append(spread)
        key = (t//300+1)*300
        bar = by_bar.setdefault(key, dict(ofi=0., liquidity=0., microprice_bps=0., updates=0))
        if previous is not None:
            pb,pa,pbq,paq = previous
            bar["ofi"] += (bq*(bid>=pb) - pbq*(bid<=pb) - aq*(ask<=pa) + paq*(ask>=pa))
        bar["liquidity"] += bq+aq
        bar["microprice_bps"] = (((ask*bq+bid*aq)/(bq+aq))/mid-1)*10000
        bar["updates"] += 1
        previous = bid,ask,bq,aq
    if len(spreads) < 10:
        raise ValueError("insufficient L1 records")
    if by_bar:
        del by_bar[max(by_bar)]  # partial final five-minute window
    return dict(spread_bps=median(spreads), obs=len(spreads), bars=by_bar, source=url)


def prepare(job):
    c,m = job
    candle_file(job)
    funding_file(job)
    depth_file(job)
    path = OUT/"l1"/c/f"{m}.json"
    if not path.exists():
        try:
            row = quotes_prefix(c,m)
        except HTTPError as e:
            if e.code != 404:
                raise
            row = dict(spread_bps=None, bars={}, status="missing")
        save_json(path,row)


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i,_ in enumerate(pool.map(prepare,[(c,m) for m in months() for c in COINS])):
            if i%10 == 0:
                print(i+1, flush=True)
