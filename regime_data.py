"""Five-minute point-in-time spot anchors and perpetual inputs."""
import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from functools import partial

from compare import COINS
from flow_data import FUTURES, ROOT, dates, depth_file, epoch, prepare_range, request_json, save_json

FIRST = date(2026, 7, 1)
LAST = date(2026, 10, 1)


def rest_candles(coin, start, stop):
    """Fetch a contiguous, closed five-minute interval, in UTC seconds."""
    rows = []
    for left in range(start, stop, 1000*300):
        right = min(stop, left + 1000*300)
        batch = request_json(FUTURES + "/klines", dict(symbol=coin+"USDT", interval="5m",
                             startTime=left*1000, endTime=right*1000-1, limit=1000))
        if ([r[0] for r in batch] != list(range(left*1000, right*1000, 300000))
                or any(r[6] != r[0]+299999 for r in batch)):
            raise ValueError(f"{coin} incomplete REST candles at {left}")
        rows.extend(batch)
    return rows


def october_repair(coin):
    day = date(2026, 10, 28)
    path = ROOT / "candle-repairs" / coin / f"{day}.json"
    if not path.exists():
        rows = rest_candles(coin, epoch(day), epoch(day)+86400)
        save_json(path, rows)
    names = ("open_time", "open", "high", "low", "close", "volume", "quote_volume", "taker_buy_quote_volume")
    return [dict(zip(names, (r[j] for j in (0,1,2,3,4,5,7,10)))) for r in json.loads(path.read_bytes())]


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


def spots(coin, first=FIRST, last=LAST):
    result = {}
    for d in dates(first, last):
        rows = json.loads((ROOT / "spot-kucoin-5m" / coin / f"{d}.json").read_bytes())
        result.update({int(k): v for k,v in rows.items()})
    return result


def prepare(first=FIRST, last=LAST):
    jobs = [(c,d) for d in dates(first,last) for c in COINS]
    for kind in ("candles","funding"):
        prepare_range(kind,first,last)
    for task in (spot_file,partial(depth_file,interval=300)):
        with ThreadPoolExecutor(max_workers=6) as pool:
            for _ in pool.map(task,jobs):
                pass


if __name__ == "__main__":
    prepare()
