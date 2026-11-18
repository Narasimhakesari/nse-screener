#!/usr/bin/env python3
"""Backtest the monthly momentum trade the site uses, plus the alternatives it was chosen over.

Usage: DUMP=1 python3 build/build.py WD ; python3 build/backtest_momentum.py WD   (writes WD/mom_bt.json)
At each month-end close, rank the 300 most-traded stocks (price >= Rs 10, a year of history) by 12-month return,
skipping the last month, divided by volatility. Buy at the next day's open. Sell at the open after the next month-end,
or earlier at the stop (if a day opens below the stop, sell at that open). Costs 0.3% per round trip.
"""
import sys, json, numpy as np, pandas as pd
WD = sys.argv[1]
M = pd.read_pickle(f'{WD}/mats.pkl')
O, C, L, TO, breadth, bavg = M['O'], M['C'], M['L'], M['TO'], M['breadth'], M['bavg']
COST = 0.003
ret = C.pct_change(fill_method=None).clip(-0.5, 0.5)
tom = TO.rolling(60, min_periods=40).median()
liq = tom.where(C >= 10).rank(axis=1, ascending=False) <= 300
mq = ((C.shift(21) / C.shift(252) - 1) / (ret.rolling(126, min_periods=100).std() * 252 ** .5)).where(liq & C.shift(252).notna())
MR = mq.rank(axis=1, ascending=False).values
dates = C.index; n = len(dates); Ov, Cv, Lv = O.values, C.values, L.values
me = pd.Series(dates, index=dates).groupby([dates.year, dates.month]).last().values
me = [dates.get_loc(pd.Timestamp(d)) for d in me]
me = [m for m in me if m >= 260 and m < n - 1]   # completed month-ends only

def hold(i, j, stop, months=1):
    e = Ov[i + 1, j]
    if not np.isfinite(e) or e <= 0: return None
    later = [m for m in me if m > i]
    if len(later) < months: return None
    end = later[months - 1] + 1
    if end >= n: return None
    for k in range(i + 1, end):
        if stop and np.isfinite(Lv[k, j]):
            S = e * (1 - stop)
            if k > i + 1 and np.isfinite(Ov[k, j]) and Ov[k, j] <= S: return Ov[k, j] / e - 1, k - i
            if Lv[k, j] <= S: return -stop, k - i
    x = Ov[end, j] if np.isfinite(Ov[end, j]) else Cv[end - 1, j]
    return (x / e - 1, end - i) if np.isfinite(x) else None

def run(which, stop):
    R = []
    for x, a in enumerate(me[:-1]):
        now = MR[a] <= 30
        prev = MR[me[x - 1]] <= 30 if x > 0 else np.zeros_like(now)
        js = np.nonzero(now & ~prev)[0] if which == 'new' else np.nonzero(now)[0] if which == 'top30' else np.nonzero(np.isfinite(MR[a]))[0]
        for j in js:
            t = hold(a, j, stop)
            if t: R.append((t[0] - COST, t[1], dates[a], bool(breadth.iloc[a] > bavg.iloc[a])))
    r = np.array([y[0] for y in R]); d = np.array([y[1] for y in R]); u = np.array([y[3] for y in R])
    yrs = pd.Series(r, index=[y[2].year for y in R]).groupby(level=0).mean() * 100
    mon = pd.Series(r, index=[y[2] for y in R]).groupby(level=0).mean()
    return dict(n=int(len(r)), avg=round(r.mean() * 100, 2), win=round((r > 0).mean() * 100, 1), days=round(d.mean(), 1),
                healthy=round(r[u].mean() * 100, 2) if u.any() else None, cautious=round(r[~u].mean() * 100, 2) if (~u).any() else None,
                worst=round(r.min() * 100, 1), months_up=int((mon > 0).sum()), months=int(len(mon)),
                years={int(k): round(v, 2) for k, v in yrs.items()})

ROWS = [('New top-30 entries, 1 month, 10% stop (the site\'s rule)', 'new', 0.10),
        ('New top-30 entries, 1 month, no stop', 'new', 0.0),
        ('All of the top 30, 1 month, 10% stop', 'top30', 0.10),
        ('Any of the 300 most-traded, 1 month, 10% stop (baseline)', 'all', 0.10)]
out = dict(built=pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%MZ'), start=str(dates[me[0]].date()), end=str(dates[me[-1]].date()), rows={})
for label, which, stop in ROWS:
    out['rows'][label] = s = run(which, stop)
    print(f"{label:58s} trades {s['n']:5d} avg {s['avg']:+5.2f}% win {s['win']}% days {s['days']} healthy {s['healthy']:+.2f}% cautious {s['cautious']:+.2f}% worst {s['worst']}% months up {s['months_up']}/{s['months']} {s['years']}")
json.dump(out, open(f'{WD}/mom_bt.json', 'w'), indent=1)
