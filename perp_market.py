"""Read verified five-minute candles and align completed hourly market observations."""
import csv
import hashlib
import io
import json
import math
from dataclasses import dataclass
from typing import NamedTuple
from zipfile import ZipFile

from flow_data import ROOT, dates, epoch


class Bar(NamedTuple):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote: float
    buy_quote: float


class Funding(NamedTuple):
    ms: int
    rate: float
    mark: float


@dataclass
class Market:
    bars: list
    hours: list
    funding: list
    funding_times: list
    depth: dict
    options: dict
    fingerprint: str


def aggregate(bars):
    hours = []
    for i in range(0, len(bars), 12):
        group = bars[i:i + 12]
        hours.append(Bar(group[0].time, group[0].open, max(b.high for b in group),
                         min(b.low for b in group), group[-1].close, sum(b.volume for b in group),
                         sum(b.quote for b in group), sum(b.buy_quote for b in group)))
    return hours


def load_market(coin, first, last):
    """Calendar-month boundaries are required by the archive layout."""
    bars, funding, depth, options = [], [], {}, {}
    first_ms = epoch(first) * 1000
    fingerprint = hashlib.sha256()

    def read(path):
        blob = path.read_bytes()
        fingerprint.update(str(path.relative_to(ROOT).as_posix()).encode())
        fingerprint.update(hashlib.sha256(blob).digest())
        return blob

    for day in dates(first, last):
        if day.day == 1:
            raw = read(ROOT / "candles" / coin / f"{day:%Y-%m}.zip")
            with ZipFile(io.BytesIO(raw)) as zipped:
                with zipped.open(zipped.namelist()[0]) as file:
                    for r in csv.DictReader(io.TextIOWrapper(file, encoding="ascii")):
                        stamp = int(r["open_time"])
                        if stamp != first_ms + len(bars) * 300_000:
                            raise ValueError(f"{coin} missing or duplicate five-minute candle at {stamp}")
                        b = Bar(stamp // 1000, *[float(r[k]) for k in
                                ("open", "high", "low", "close", "volume", "quote_volume", "taker_buy_quote_volume")])
                        if (not all(math.isfinite(v) for v in b[1:]) or b.low <= 0
                                or not b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high
                                or b.volume < 0 or not 0 <= b.buy_quote <= b.quote + 1e-6):
                            raise ValueError(f"{coin} invalid candle at {stamp}")
                        bars.append(b)
            rows = json.loads(read(ROOT / "funding" / coin / f"{day:%Y-%m}.json"))
            funding.extend(Funding(r["fundingTime"], float(r["fundingRate"]), float(r["markPrice"]))
                           for r in rows)
        books = json.loads(read(ROOT / "depth-1-2pct" / coin / f"{day}.json"))["samples"]
        depth.update({int(k): v for k, v in books.items()})
        for currency in ("BTC", "ETH"):
            for sample in json.loads(read(ROOT / "options" / currency / f"{day}.json")):
                options.setdefault(sample["asof"], {})[currency] = sample
    if len(bars) * 300 != epoch(last) - epoch(first):
        raise ValueError(f"Incomplete five-minute history for {coin}")
    times = [f.ms for f in funding]
    if times != sorted(set(times)):
        raise ValueError(f"Inconsistent funding clock for {coin}")
    return Market(bars, aggregate(bars), funding, times, depth, options, fingerprint.hexdigest())
