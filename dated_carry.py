"""Seven- and 84-day spot versus linear delivery futures with settlement reconciliation."""
from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import json
from statistics import mean
from urllib.error import HTTPError
import numpy as np

from carry_prices import ARCHIVE, CACHE, BAR, dated_day, mark_rows, spot_month, verified_zip
from flow_data import epoch, request_json, save_json
from perp_carry import CAPITAL, HURDLE, OUT, PERP_FEE, SLIP, SPOT_FEE, WEIGHT
from wave_context import csv_zip
from wave_validation import write_csv
from wave_inputs import months, next_month

COINS = ("BTC","ETH")
DATES = {"development":(date(2024,1,1),date(2026,1,1)),
         "later":(date(2026,1,1),date(2026,10,1))}


def expiries(start,end):
    for year in range(start.year,end.year+1):
        for month in (3,6,9,12):
            last=date(year,month,monthrange(year,month)[1])
            day=last-timedelta(days=(last.weekday()-4)%7)
            if start<=day<end:
                yield day


def delivery_table(coin):
    url="https://fapi.binance.com/futures/data/delivery-price"
    path=CACHE/"published-settlements"/f"{coin}.json"
    if not path.exists():
        response=request_json(url,dict(pair=coin+"USDT"))
        save_json(path,dict(source=url,pair=coin+"USDT",retrieved=datetime.now(timezone.utc).isoformat(),records=response))
    rows=json.loads(path.read_bytes())["records"]
    result={}
    for row in rows:
        # The endpoint may identify the delivery date at 00:00 UTC. Contract expiry is at 08:00.
        day=datetime.fromtimestamp(int(row["deliveryTime"])/1000,timezone.utc).date()
        price=float(row["deliveryPrice"])
        if day in result or not 0<price<float("inf"):
            raise ValueError(f"Invalid {coin} delivery record {row}")
        result[day]=price
    return result


def index_range(coin,day):
    pair=coin+"USDT"
    file=f"{pair}-1m-{day}.zip"
    blob=verified_zip(CACHE/"index"/coin/file,
                      f"{ARCHIVE}/daily/indexPriceKlines/{pair}/1m/{file}")
    delivery=epoch(day)+8*3600
    minutes=60 if day<date(2024,11,11) else 30
    window=range(delivery-minutes*60,delivery,60)
    bands={}
    for r in csv_zip(blob):
        if r[0].isdigit() and int(r[0])//1000 in window:
            t=int(r[0])//1000
            low,high=float(r[3]),float(r[2])
            if t in bands or not 0<low<=high<float("inf"):
                raise ValueError("Invalid index bar")
            bands[t]=(low,high)
    if set(bands)!=set(window):
        raise ValueError("Incomplete settlement window")
    return mean(x[0] for x in bands.values()),mean(x[1] for x in bands.values())


def projected_edge(spot,future,days):
    # Approximate exit fee notionals with today's spot. Wallet hurdle includes idle collateral.
    friction=spot*(2*SPOT_FEE+2*SLIP+PERP_FEE)+future*(PERP_FEE+SLIP)
    hurdle=max(spot,future)/WEIGHT*HURDLE*days/365
    return future-spot-friction-hurdle-.0005*spot


def net_per_unit(spot,future,spot_exit,delivery):
    gross=(future-spot)+(spot_exit-delivery)
    slip=SLIP*(spot+future+spot_exit)
    fees=SPOT_FEE*(spot*(1+SLIP)+spot_exit*(1-SLIP))+PERP_FEE*(future*(1-SLIP)+delivery)
    return gross,fees,slip,gross-fees-slip


def margin_path(symbol, start, stop):
    """Maximum intrabar contract mark and last pre-delivery mark during the hedge."""
    first=datetime.fromtimestamp(start,timezone.utc).date().replace(day=1)
    last=datetime.fromtimestamp(stop,timezone.utc).date().replace(day=1)
    peak,final,count,expected=0.,None,0,start
    for m in months(first,next_month(last)):
        for t,high,close in mark_rows(symbol,m):
            if start<=t<stop:
                if t!=expected:
                    raise ValueError(f"Invalid intrahold mark {symbol} {t}")
                peak=max(peak,high)
                final=close
                count+=1
                expected+=BAR
    if count!=(stop-start)//BAR:
        raise ValueError(f"Missing marks for {symbol}")
    return peak,final


def observation(coin,day,settlements,horizon):
    opening=day-timedelta(days=horizon)
    symbol=f"{coin}USDT_{day:%y%m%d}"
    boundary=epoch(opening)+8*3600
    expiry=epoch(day)+8*3600
    row=dict(coin=coin,symbol=symbol,expiry=str(day),decision_utc=boundary,execution_utc=boundary+BAR,
             delivery_utc=expiry,issue="",published_settlement=settlements.get(day))
    try:
        f=dated_day(symbol,opening)
        s=spot_month(coin,opening.replace(day=1))
        exit_month=day.replace(day=1)
        exit_spots=s if exit_month==opening.replace(day=1) else spot_month(coin,exit_month)
        exit_bar=exit_spots[expiry-BAR]
        sf,ff=s[boundary-BAR],f[boundary-BAR]
        se,fe=s[boundary],f[boundary]
        index_low,index_high=index_range(coin,day)
        peak_mark,final_mark=margin_path(symbol,boundary+BAR,expiry)
    except (KeyError,HTTPError) as e:
        if isinstance(e,HTTPError) and e.code!=404:
            raise
        return dict(row,issue=f"missing market data: {e}")
    if min(x.trades for x in (sf,ff,se,fe,exit_bar))<1 or min(x.qty for x in (sf,ff,se,fe,exit_bar))<=0:
        return dict(row,issue="bar without trades")
    published=settlements.get(day)
    tick=.1 if coin=="BTC" else .01
    status="missing" if published is None else "verified" if index_low-tick<=published<=index_high+tick else "outside_index_bounds"
    # Reserve the entire unspent sleeve as USDT margin; the spot coin is not collateral.
    q=WEIGHT/max(sf.price,ff.price)
    margin=1-q*(se.price*(1+SLIP)*(1+SPOT_FEE)+fe.price*(1-SLIP)*PERP_FEE)
    worst_margin=(margin+q*(fe.price*(1-SLIP)-peak_mark))/(q*peak_mark)
    return dict(row,decision_spot=sf.price,decision_future=ff.price,
                decision_basis_bps=10000*(ff.price/sf.price-1),gate=projected_edge(sf.price,ff.price,horizon)>0,
                entry_spot=se.price,entry_future=fe.price,spot_exit=exit_bar.price,
                entry_volume_proxy=min(se.qty,fe.qty),exit_spot_volume=exit_bar.qty,
                settlement_status=status,index_low=index_low,index_high=index_high,
                max_mark=peak_mark,last_pre_delivery_mark=final_mark,min_short_margin_ratio=worst_margin)


def replay(rows,start,end,select):
    cash=dict.fromkeys(COINS,CAPITAL/len(COINS))
    # Exact ledger where available; carry ranges through uncertain settlements and compounding.
    bounds={c:[v,v] for c,v in cash.items()}
    ledger=[]
    complete=True
    for row in sorted(rows,key=lambda r:(r["expiry"],r["coin"])):
        coin=row["coin"]
        if row["issue"]:
            complete=False
            ledger.append(dict(coin=coin,expiry=row["expiry"],action="unavailable",net=None))
            continue
        if select and not row["gate"]:
            ledger.append(dict(coin=coin,expiry=row["expiry"],action="skip",net=0.))
            continue
        if row["settlement_status"]=="outside_index_bounds":
            complete=False
            ledger.append(dict(coin=coin,expiry=row["expiry"],action="unreconciled_settlement",net=None))
            continue
        unit_size=WEIGHT/max(row["decision_spot"],row["decision_future"])
        # Budget is chosen from previous settlements. Size and P&L become intervals after a gap.
        if bounds[coin][1]*unit_size>row["entry_volume_proxy"]:
            ledger.append(dict(coin=coin,expiry=row["expiry"],action="too_large_for_bar",net=0.))
            continue
        if bounds[coin][1]*unit_size>row["exit_spot_volume"]:
            # The exit bar was unknowable at entry. Never reclassify this hedge as a nonfill.
            complete=False
            ledger.append(dict(coin=coin,expiry=row["expiry"],action="unpriced_unwind",net=None))
            continue
        if row["min_short_margin_ratio"]<.01:
            raise ValueError(f"Short margin stress breached at {row['symbol']}; liquidation replay needed")
        args=[row[k] for k in ("entry_spot","entry_future","spot_exit")]
        if row["settlement_status"]=="verified":
            delivery=row["published_settlement"]
            gross,fees,slip,per_unit=net_per_unit(*args,delivery)
            low=high=per_unit
            qty=cash[coin]*unit_size if cash[coin] is not None else None
            net=qty*per_unit if qty is not None else None
            if net is not None:
                cash[coin]+=net
            turnover=row["entry_spot"]+row["entry_future"]+row["spot_exit"]+delivery
            ledger.append(dict(coin=coin,expiry=row["expiry"],action="settled",qty=qty,net=net,
                               fees=fees*qty if qty is not None else None,slip=slip*qty if qty is not None else None,
                               gross=gross*qty if qty is not None else None,
                               exposure_cost_4pct=qty/unit_size*HURDLE*(row["delivery_utc"]-row["execution_utc"])/(365*86400)
                               if qty is not None else None,
                               turnover=turnover*qty if qty is not None else None,
                               net_sleeve_fraction=per_unit*unit_size))
        else:
            # A short's worst payoff corresponds to the upper settlement bound.
            tick=.1 if coin=="BTC" else .01
            low=net_per_unit(*args,row["index_high"]+tick)[-1]
            high=net_per_unit(*args,row["index_low"]-tick)[-1]
            cash[coin]=None
            possible=[equity*unit_size*v for equity in bounds[coin] for v in (low,high)]
            ledger.append(dict(coin=coin,expiry=row["expiry"],action="bounded_settlement",net=None,
                               min_net=min(possible),max_net=max(possible)))
        bounds[coin][0]*=1+unit_size*low
        bounds[coin][1]*=1+unit_size*high
    exact=complete and all(v is not None for v in cash.values())
    net=sum(cash.values())-CAPITAL if exact else None
    interval=[sum(b[i] for b in bounds.values())-CAPITAL for i in (0,1)] if complete else None
    settled=[r["net"] for r in ledger if r["action"]=="settled" and r["net"] is not None]
    by_expiry={}
    for r in ledger:
        if r["action"]=="settled" and r["net"] is not None:
            by_expiry[r["expiry"]]=by_expiry.get(r["expiry"],0.)+r["net"]
    observed_fees=sum(r.get("fees") or 0 for r in ledger)
    exposure_cost=sum(r.get("exposure_cost_4pct") or 0 for r in ledger)
    turnover=sum(r.get("turnover") or 0 for r in ledger)
    hurdle=CAPITAL*HURDLE*(end-start).days/365
    return ledger,dict(exact_net=net,net_range=interval,excess_over_cash_yield_range=[v-hurdle for v in interval] if interval else None,
                       settled_pairs=len(settled),winning_settled_pairs=sum(v>0 for v in settled),
                       bounded_pairs=sum(r["action"]=="bounded_settlement" for r in ledger),cash_hurdle=hurdle,
                       known_fees=observed_fees,best_known_expiry=max(by_expiry.values(),default=None),
                       excess_over_deployed_hurdle=net-exposure_cost if net is not None else None,
                       extra_break_even_cost_bps=10000*net/turnover if net is not None and turnover else None,
                       net_ex_best_expiry=net-max(by_expiry.values()) if net is not None and by_expiry else None)


def export_rows(path,rows):
    columns=dict.fromkeys(k for r in rows for k in r)
    write_csv(path,[{k:r.get(k) for k in columns} for r in rows])


def marked_drawdown(opportunities,ledger,start,end):
    """Mark open hedges on five-minute closes; book the recorded cash payoff at delivery."""
    observations={(r["coin"],r["expiry"]):r for r in opportunities}
    curve=np.full((epoch(end)-epoch(start))//BAR,CAPITAL)
    for trade in ledger:
        if trade["action"]!="settled":
            continue
        r=observations[trade["coin"],trade["expiry"]]
        coin,symbol=trade["coin"],r["symbol"]
        entry,delivery=r["execution_utc"],r["delivery_utc"]
        qty=trade["qty"]
        s0,f0=r["entry_spot"],r["entry_future"]
        entry_cost=qty*(s0*(SLIP+(1+SLIP)*SPOT_FEE)+f0*(SLIP+(1-SLIP)*PERP_FEE))
        first=datetime.fromtimestamp(entry,timezone.utc).date().replace(day=1)
        last=date.fromisoformat(r["expiry"]).replace(day=1)
        for m in months(first,next_month(last)):
            spot=spot_month(coin,m)
            for t,_,mark in mark_rows(symbol,m):
                if entry<=t+BAR<delivery:
                    curve[(t-epoch(start))//BAR]+=qty*(spot[t].price-s0+f0-mark)-entry_cost
        curve[(delivery-epoch(start))//BAR-1:]+=trade["net"]
    if not np.isclose(curve[-1]-CAPITAL,sum(r["net"] for r in ledger),atol=1e-7):
        raise ValueError("Delivery equity curve does not reconcile")
    peaks=np.maximum.accumulate(curve)
    return float(100*np.max((peaks-curve)/peaks))


def run():
    OUT.mkdir(parents=True,exist_ok=True)
    settlements={coin:delivery_table(coin) for coin in COINS}
    report,observations,ledger={},[],[]
    for horizon in (7,84):
        report[horizon]={}
        for name,(start,end) in DATES.items():
            jobs=[(c,day,settlements[c],horizon) for day in expiries(start,end)
                  if day-timedelta(days=horizon)>=start for c in COINS]
            with ThreadPoolExecutor(4) as pool:
                rows=list(pool.map(lambda job:observation(*job),jobs))
            observations.extend(dict(days=horizon,period=name,**r) for r in rows)
            report[horizon][name]={}
            for label,select in (("threshold",True),("all_expiries",False)):
                trades,metrics=replay(rows,start,end,select)
                metrics["marked_drawdown_pct"]=(marked_drawdown(rows,trades,start,end)
                                                if metrics["exact_net"] is not None else None)
                report[horizon][name][label]=metrics
                ledger.extend(dict(days=horizon,period=name,rule=label,**r) for r in trades)
            print(horizon,name,report[horizon][name]["threshold"]["net_range"],flush=True)
    export_rows(OUT/"dated-opportunities.csv",observations)
    export_rows(OUT/"dated-orders.csv",ledger)
    save_json(OUT/"dated-results.json",report)


if __name__=="__main__":
    run()
