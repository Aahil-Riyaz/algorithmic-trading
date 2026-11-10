"""Read verified five-minute candles and align completed hourly market observations."""
import csv
import hashlib
import io
import json
import math
from calendar import monthrange
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


def checked_bar(b):
    if (not all(math.isfinite(v) for v in b[1:]) or b.low <= 0
            or not b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high
            or b.volume < 0 or not 0 <= b.buy_quote <= b.quote + 1e-6):
        raise ValueError(f"Invalid candle at {b.time}")
    return b


def bars_from_rest(rows):
    return [checked_bar(Bar(r[0]//1000, *[float(r[j]) for j in (1,2,3,4,5,7,10)])) for r in rows]


def aggregate(bars):
    hours = []
    for i in range(0, len(bars), 12):
        group = bars[i:i + 12]
        hours.append(Bar(group[0].time, group[0].open, max(b.high for b in group),
                         min(b.low for b in group), group[-1].close, sum(b.volume for b in group),
                         sum(b.quote for b in group), sum(b.buy_quote for b in group)))
    return hours


def load_market(coin, first, last, depth_folder=None, include_options=True, candle_repairs=()):
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
                    rows = list(csv.DictReader(io.TextIOWrapper(file, encoding="ascii")))
                    if candle_repairs:
                        existing = {int(r["open_time"]) for r in rows}
                        month_days = monthrange(day.year, day.month)[1]
                        for r in candle_repairs:
                            stamp = int(r["open_time"])
                            if stamp not in existing and 0 <= stamp - epoch(day)*1000 < month_days*86_400_000:
                                rows.append(r)
                                fingerprint.update(json.dumps(r, sort_keys=True).encode())
                        rows.sort(key=lambda r: int(r["open_time"]))
                    for r in rows:
                        stamp = int(r["open_time"])
                        if stamp != first_ms + len(bars) * 300_000:
                            raise ValueError(f"{coin} missing or duplicate five-minute candle at {stamp}")
                        b = Bar(stamp // 1000, *[float(r[k]) for k in
                                ("open", "high", "low", "close", "volume", "quote_volume", "taker_buy_quote_volume")])
                        bars.append(checked_bar(b))
            rows = json.loads(read(ROOT / "funding" / coin / f"{day:%Y-%m}.json"))
            funding.extend(Funding(r["fundingTime"], float(r["fundingRate"]), float(r["markPrice"]))
                           for r in rows)
        if depth_folder is None:
            book_path = ROOT / "depth-1-2pct" / coin / f"{day}.json"
            books = json.loads(read(book_path))["samples"]
        else:
            book_path = depth_folder / coin / f"{day}.json"
            raw_books = book_path.read_bytes() if book_path.exists() else b'{"samples":{}}'
            fingerprint.update(f"forward/{coin}/{day}".encode())
            fingerprint.update(hashlib.sha256(raw_books).digest())
            books = json.loads(raw_books)["samples"]
        depth.update({int(k): v for k, v in books.items()})
        for currency in (("BTC", "ETH") if include_options else ()):
            for sample in json.loads(read(ROOT / "options" / currency / f"{day}.json")):
                options.setdefault(sample["asof"], {})[currency] = sample
    if len(bars) * 300 != epoch(last) - epoch(first):
        raise ValueError(f"Incomplete five-minute history for {coin}")
    times = [f.ms for f in funding]
    if times != sorted(set(times)):
        raise ValueError(f"Inconsistent funding clock for {coin}")
    return Market(bars, aggregate(bars), funding, times, depth, options, fingerprint.hexdigest())
