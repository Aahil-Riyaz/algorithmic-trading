"""Break the untouched-coin trend basket into gross return, costs, time invested and a cash-yield case, by period."""
import csv, numpy as np
from datetime import date
import trend as T, trend_fresh as F, trend_improve as I
coins=[r["coin"] for r in csv.DictReader(open("research/trend-fresh/coins.csv"))]
acc={}
for sym in coins:
    a=F.candles(sym,I.months(sym))
    if len(a)<T.WARM+1+365: continue
    d=[T.day(t) for t in a[:,0]]; o,c=a[:,1],a[:,4]; w=T.targets(c,"trend")
    T.FEE,T.SLIP=.001,.001; n=T.simulate(o,c,w)
    T.FEE,T.SLIP=0.,0.; g=T.simulate(o,c,w)
    f=n["first"]
    rn=n["eq"][f:]/n["eq"][f-1:-1]-1; rg=g["eq"][f:]/g["eq"][f-1:-1]-1
    rh=c[f:]/c[f-1:-1]-1
    for i,day in enumerate(d[f:]):
        x=acc.setdefault(day,[[],[],[],[],[]])
        x[0].append(rn[i]);x[1].append(rg[i]);x[2].append(n["held"][f+i]);x[3].append(rh[i])
        x[4].append(abs(n["held"][f+i]-n["held"][f+i-1]))
days=sorted(acc)
M=lambda k:np.array([np.mean(acc[x][k]) for x in days])
net,gross,held,hold,turn=M(0),M(1),M(2),M(3),M(4)
cash=net+(1-held)*.04/365
for name,m in (("full",np.ones(len(days),bool)),("2024+",np.array([x>=date(2024,1,1) for x in days])),("2025+",np.array([x>=date(2025,1,1) for x in days]))):
    cg=lambda r:np.prod(1+r[m])**(365/m.sum())-1
    print(name,"net",round(cg(net),3),"gross",round(cg(gross),3),"net+4%cash",round(cg(cash),3),"hold",round(cg(hold),3),
          "avg invested",round(held[m].mean(),2),"weight turnover/yr",round(turn[m].mean()*365,1),"cost drag/yr",round(cg(gross)-cg(net),3))
# return while invested vs alt market direction
m=np.array([x>=date(2024,1,1) for x in days])
up=hold>0
print("2024+ days alts up",round(up[m].mean(),2),"| avg basket ret on up days",round(net[m&up].mean()*1e4,1),"bp, down days",round(net[m&~up].mean()*1e4,1),"bp")
