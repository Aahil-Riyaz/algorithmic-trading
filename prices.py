"""Fetch the fixed 2024 BTC/USDT hourly spot dataset."""
import csv
import hashlib
import io
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple
from urllib.request import urlopen
from zipfile import ZipFile


class Candle(NamedTuple):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def month_rows(month):
    name = f"BTCUSDT-1h-2024-{month:02d}"
    url = f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/{name}.zip"
    with urlopen(url, timeout=30) as response:
        archive = response.read()
    with urlopen(url + ".CHECKSUM", timeout=30) as response:
        expected = response.read().decode().split()[0]
    if hashlib.sha256(archive).hexdigest() != expected:
        raise ValueError(f"Checksum mismatch for {name}")
    with ZipFile(io.BytesIO(archive)) as zipped:
        rows = csv.reader(zipped.read(name + ".csv").decode().splitlines())
        return [Candle(int(row[0]) // 1000, *map(float, row[1:6])) for row in rows]


def validate(rows):
    for i, bar in enumerate(rows):
        if i and bar.time != rows[i - 1].time + 3600:
            raise ValueError(f"Missing or unordered hour at {bar.time}")
        if not all(map(math.isfinite, bar[1:])) or bar.volume < 0 or bar.low <= 0:
            raise ValueError(f"Invalid candle at {bar.time}")
        if not (bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high):
            raise ValueError(f"Inconsistent prices at {bar.time}")


def load(path=Path("market.csv")):
    with path.open(newline="") as file:
        rows = [Candle(int(r["time"]), *(float(r[k]) for k in Candle._fields[1:]))
                for r in csv.DictReader(file)]
    validate(rows)
    return rows


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=4) as pool:
        bars = [bar for month in pool.map(month_rows, range(1, 13)) for bar in month]
    validate(bars)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
    if len(bars) != 366 * 24 or bars[0].time != start:
        raise ValueError("Incomplete 2024 dataset")
    temp = Path("market.csv.tmp")
    with temp.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(Candle._fields)
        writer.writerows(bars)
    temp.replace("market.csv")
    print(f"Saved {len(bars)} hourly candles to market.csv")
