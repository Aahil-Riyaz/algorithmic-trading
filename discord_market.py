"""Download point-in-time Binance USD-M trade candles and realized funding for an audit."""
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import NamedTuple

from flow_data import FUTURES, persist, request_json


class Bar(NamedTuple):
    time: int
    open: float
    high: float
    low: float
    close: float


def interval_data(coin, start, end, folder):
    """Return contiguous closed minute bars in [start,end) and their source digest."""
    key = folder / f"{coin}-{start}-{end}.json.gz"
    if key.exists():
        blob = gzip.decompress(key.read_bytes())
    else:
        rows = []
        for left in range(start, end, 1000*60):
            right = min(left+1000*60,end)
            chunk = request_json(FUTURES+"/klines",dict(symbol=coin+"USDT",interval="1m",
                                 startTime=left*1000,endTime=right*1000-1,limit=1000))
            if [r[0] for r in chunk] != list(range(left*1000,right*1000,60000)):
                raise ValueError(f"{coin} missing minute candles near {left}")
            rows.extend(chunk)
        funding = []
        for t in range(start,end,7*86400):
            funding.extend(request_json(FUTURES+"/fundingRate",dict(symbol=coin+"USDT",startTime=t*1000,
                                      endTime=min(t+7*86400,end)*1000-1,limit=1000)))
        blob = json.dumps(dict(rows=rows,funding=funding),separators=(",",":")).encode()
        persist(key,gzip.compress(blob))
    source = json.loads(blob)
    bars = []
    for r in source["rows"]:
        b = Bar(r[0]//1000,*(float(x) for x in r[1:5]))
        if (r[0] != (start+len(bars)*60)*1000 or r[6] != r[0]+59999
                or not all(math.isfinite(x) for x in b) or b.low <= 0
                or not b.low <= min(b.open,b.close) <= max(b.open,b.close) <= b.high):
            raise ValueError(f"{coin} invalid bar {r[0]}")
        bars.append(b)
    if len(bars)*60 != end-start:
        raise ValueError(f"{coin} truncated cache")
    funds = [(int(r["fundingTime"]),float(r["fundingRate"]),float(r["markPrice"])) for r in source["funding"]]
    if [x[0] for x in funds] != sorted({x[0] for x in funds}) or any(
        not (start*1000 <= t < end*1000 and math.isfinite(f) and math.isfinite(p) and p>0) for t,f,p in funds):
        raise ValueError(f"{coin} invalid funding records")
    return bars,funds,hashlib.sha256(blob).hexdigest()
