"""Five-minute point-in-time spot anchors and perpetual inputs."""
import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from functools import partial

from compare import COINS
from flow_data import ROOT, dates, depth_file, epoch, prepare_range, request_json, save_json

FIRST = date(2026, 7, 1)
LAST = date(2026, 10, 1)


def spot_file(job):
    coin, day = job
    path = ROOT / "spot-kucoin-5m" / coin / f"{day}.json"
    if path.exists():
        return
    start = epoch(day)
    response = request_json("https://api.kucoin.com/api/v1/market/candles",
                            dict(symbol=coin + "-USDT", type="5min", startAt=start, endAt=start+86399))
    if response["code"] != "200000":
        raise ValueError(f"KuCoin {coin} {day}: {response['code']}")
    closes = {}
    for row in response["data"]:
        t, price = int(row[0]), float(row[2])
        if not (start <= t < start+86400 and t % 300 == 0 and math.isfinite(price)
                and price > 0 and t not in closes):
            raise ValueError("Invalid spot candle")
        closes[t] = price
    save_json(path, closes)


def spots(coin):
    result = {}
    for d in dates(FIRST, LAST):
        rows = json.loads((ROOT / "spot-kucoin-5m" / coin / f"{d}.json").read_bytes())
        result.update({int(k): v for k,v in rows.items()})
    return result


def prepare():
    jobs = [(c,d) for d in dates(FIRST,LAST) for c in COINS]
    for kind in ("candles","funding"):
        prepare_range(kind,FIRST,LAST)
    for task in (spot_file,partial(depth_file,interval=300)):
        with ThreadPoolExecutor(max_workers=6) as pool:
            for _ in pool.map(task,jobs):
                pass


if __name__ == "__main__":
    prepare()
