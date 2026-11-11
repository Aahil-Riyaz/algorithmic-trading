"""Matched-venue spot candles and first-of-month OI and published liquidation prints."""
import csv
import gzip
import io
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.error import HTTPError
from zipfile import ZipFile

from flow_data import ARCHIVE, archive, fetch, save_json
from wave_inputs import COINS, OUT, months


def csv_zip(blob):
    with ZipFile(io.BytesIO(blob)) as zipped:
        with zipped.open(zipped.namelist()[0]) as f:
            yield from csv.reader(io.TextIOWrapper(f,encoding="ascii"))


def collect(job):
    coin, m = job
    pair = coin+"USDT"
    path = OUT/"context"/coin/f"{m}.json"
    if path.exists():
        return
    url = f"https://data.binance.vision/data/spot/monthly/klines/{pair}/5m/{pair}-5m-{m:%Y-%m}.zip"
    blob,digest = archive(url)
    spot = {}
    for r in csv_zip(blob):
        if not r[0].isdigit():
            continue
        t = int(r[0])
        spot[t//(1_000_000 if t >= 10**15 else 1000)] = float(r[4])
    daily = f"{ARCHIVE}/daily/metrics/{pair}/{pair}-metrics-{m}.zip"
    oi = {}
    try:
        data, _ = archive(daily)
        lines = csv_zip(data)
        header = next(lines)
        for r in lines:
            r = dict(zip(header,r))
            t = int(datetime.fromisoformat(r["create_time"]).replace(tzinfo=timezone.utc).timestamp())
            if r["sum_open_interest"]:
                oi[t] = float(r["sum_open_interest"])
    except HTTPError as e:
        if e.code != 404:
            raise
    liquidations = defaultdict(float)
    url = f"https://datasets.tardis.dev/v1/binance-futures/liquidations/{m:%Y/%m/%d}/{pair}.csv.gz"
    liq_covered = False
    try:
        data = gzip.decompress(fetch(url))
        for r in csv.DictReader(io.StringIO(data.decode())):
            t = max(int(r["timestamp"]),int(r["local_timestamp"]))//1_000_000
            liquidations[t//300*300] += (1 if r["side"]=="buy" else -1)*float(r["price"])*float(r["amount"])
        liq_covered = True
    except HTTPError as e:
        if e.code != 404:
            raise
    save_json(path,dict(spot=spot,spot_sha256=digest,oi=oi,liquidations=liquidations,liq_covered=liq_covered))


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i,_ in enumerate(pool.map(collect,[(c,m) for m in months() for c in COINS])):
            if i%10 == 0:
                print(i+1,flush=True)
