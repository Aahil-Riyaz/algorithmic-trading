"""Checked Binance spot and linear-futures bars for carry studies."""
from datetime import date, datetime, timezone
import math
from pathlib import Path
from typing import NamedTuple

from flow_data import ARCHIVE, ROOT, archive, epoch, persist
from wave_context import csv_zip
from wave_inputs import next_month

CACHE = Path("data/carry")
SPOT_ARCHIVE = "https://data.binance.vision/data/spot"
BAR = 300


class Close(NamedTuple):
    price: float
    qty: float
    trades: int


def verified_zip(path, url):
    if not path.exists():
        blob, _ = archive(url)
        persist(path,blob)
    return path.read_bytes()


def close_bars(blob, first, end):
    bars = {}
    for row in csv_zip(blob):
        if not row[0].isdigit():
            continue
        stamp = int(row[0])
        scale = 1_000_000 if stamp >= 10**15 else 1000
        t, remainder = divmod(stamp,scale)
        if (remainder or t%BAR or t in bars or not first<=t<end
                or int(row[6])//scale!=t+BAR-1):
            raise ValueError(f"Bad or repeated five-minute timestamp {stamp}")
        bar = Close(float(row[4]),float(row[5]),int(row[8]))
        if not (math.isfinite(bar.price) and bar.price>0 and math.isfinite(bar.qty)
                and bar.qty>=0 and bar.trades>=0):
            raise ValueError(f"Invalid close at {stamp}")
        bars[t] = bar
    return bars


def spot_month(coin, month):
    symbol = coin+"USDT"
    filename = f"{symbol}-5m-{month:%Y-%m}.zip"
    url = f"{SPOT_ARCHIVE}/monthly/klines/{symbol}/5m/{filename}"
    blob = verified_zip(CACHE/"spot"/coin/filename,url)
    return close_bars(blob,epoch(month),epoch(next_month(month)))


def perp_month(coin, month):
    blob = (ROOT/"candles"/coin/f"{month:%Y-%m}.zip").read_bytes()
    return close_bars(blob,epoch(month),epoch(next_month(month)))


def mark_rows(symbol, month, *, daily=False):
    period="daily" if daily else "monthly"
    stamp=month.isoformat() if daily else month.strftime("%Y-%m")
    filename=f"{symbol}-5m-{stamp}.zip"
    url=f"{ARCHIVE}/{period}/markPriceKlines/{symbol}/5m/{filename}"
    blob=verified_zip(CACHE/"marks"/symbol/filename,url)
    previous=-1
    for r in csv_zip(blob):
        if r[0].isdigit():
            t=int(r[0])//1000
            high,close=float(r[2]),float(r[4])
            if (int(r[0])%300000 or t<=previous or int(r[6])!=int(r[0])+299999
                    or not 0<close<=high<float("inf")):
                raise ValueError(f"Invalid mark bar for {symbol} at {t}")
            previous=t
            yield t,high,close


def perp_mark_highs(coin,month):
    symbol=coin+"USDT"
    highs={t:high for t,high,_ in mark_rows(symbol,month)}
    grid=set(range(epoch(month),epoch(next_month(month)),BAR))
    days={datetime.fromtimestamp(t,timezone.utc).date() for t in grid-highs.keys()}
    for day in sorted(days):
        for t,high,_ in mark_rows(symbol,day,daily=True):
            if not epoch(day)<=t<epoch(day)+86400 or (t in highs and highs[t]!=high):
                raise ValueError(f"Inconsistent monthly/daily marks for {symbol} at {t}")
            highs[t]=high
    if set(highs)!=grid:
        raise ValueError(f"Incomplete mark grid for {symbol} {month}")
    return highs


def dated_day(symbol, day: date):
    filename = f"{symbol}-5m-{day}.zip"
    url = f"{ARCHIVE}/daily/klines/{symbol}/5m/{filename}"
    blob = verified_zip(CACHE/"dated"/symbol/filename,url)
    return close_bars(blob,epoch(day),epoch(day)+86400)
