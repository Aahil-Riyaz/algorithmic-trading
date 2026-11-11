"""Build prospective model proposals on UTC hour boundaries from public market data."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import logging
import time

import joblib

from aahil_wave import connect, propose
from flow_data import FUTURES, request_json, save_json
from perp_market import bars_from_rest
from regime_data import rest_candles
from wave_inputs import OUT
from wave_paper_service import catch_up
from wave_research import candidate, indicators, score_candidate
from wave_sealed import policy_digest


def roster(month):
    from wave_research import membership_for_month
    return {r["coin"] for r in membership_for_month(month) if r["member"]}


def collect(coin, t, btc, model, model_id):
    candles=btc if coin=="BTC" else bars_from_rest(rest_candles(coin,t-900*300,t))
    symbol=coin+"USDT"
    spot=request_json("https://api.binance.com/api/v3/klines",dict(symbol=symbol,interval="5m",
                      startTime=(t-300)*1000,endTime=t*1000-1,limit=1))
    funding=request_json(FUTURES+"/fundingRate",dict(symbol=symbol,startTime=(t-9*3600)*1000,endTime=t*1000-1))
    if len(spot)!=1 or spot[0][0]!=(t-300)*1000 or spot[0][6]!=t*1000-1 or not funding:
        raise ValueError("Missing closed spot bar or funding")
    close,atr=indicators(candles)
    result=candidate(coin,candles,len(candles),close,atr,btc[-2].close/btc[-14].close-1,
                     float(spot[0][4]),float(funding[-1]["fundingRate"]))
    if result is None:
        return None
    values,order=result
    quote=request_json(FUTURES+"/ticker/bookTicker",dict(symbol=symbol))
    return dict(coin=coin,decision=t,model_id=model_id,side=int(order.side),entry=float(order.entry),
                stop=float(order.stop),target=float(order.target),wave1=float(values["wave1_price"]),
                atr=float(atr[-1]),bid=float(quote["bidPrice"]),ask=float(quote["askPrice"]),
                quote_time=quote["time"]//1000,features={k:float(values[k]) for k in model["columns"]},
                **score_candidate(model,values))


def run(watch=False):
    path=OUT/"model.joblib"  # locally trained artifact
    model=joblib.load(path)
    version=sha256(path.read_bytes()).hexdigest()
    policy=policy_digest()
    db=connect()
    while True:
        t=(int(time.time())//3600)*3600
        if time.time()-t>45:
            if not watch:
                print("Outside the first minute of a UTC hour. No prospective proposal.")
                return
            t+=3600
        month=datetime.fromtimestamp(t,timezone.utc).date().replace(day=1)
        observation=dict(decision=t,model_id=version,policy_id=policy,coins={})
        try:
            allowed=roster(month)
            observation["members"]=sorted(allowed)
            time.sleep(max(0,t+2-time.time()))
            if time.time()-t<60:
                catch_up(db)
                btc=bars_from_rest(rest_candles("BTC",t-900*300,t))
                for coin in sorted(allowed):
                    try:
                        c=collect(coin,t,btc,model,version)
                        if c:
                            c["policy_id"]=policy
                        if c and time.time()>=t+60:
                            observation["coins"][coin]="unavailable: stale score"
                        else:
                            observation["coins"][coin]=propose(db,c) if c else "no_setup"
                    except (ValueError,OSError,KeyError) as error:
                        observation["coins"][coin]=f"unavailable: {error}"
            else:
                observation["error"]="decision window elapsed"
        except (ValueError,OSError,KeyError) as error:
            observation["error"]=str(error)
            logging.warning("Hourly feed unavailable: %s",error)
        save_json(OUT/"availability"/f"{t}-{time.time_ns()}.json",observation)
        if not watch:
            break
        time.sleep(max(1,t+3600-30-time.time()))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch",action="store_true")
    run(parser.parse_args().watch)
