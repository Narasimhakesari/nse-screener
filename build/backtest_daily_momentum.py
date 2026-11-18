#!/usr/bin/env python3
"""Backtest acting on momentum every day instead of once a month.

Usage: DUMP=1 python3 build/build.py WD ; python3 build/backtest_daily_momentum.py WD   (writes WD/daily_bt.json)
Each day after the close, rank the N most-traded stocks (price >= Rs 10, a year of history) by 12-month return skipping
the last month, divided by volatility. A signal is a stock entering the top K today that was not in the top 30 at any point
in the previous FRESH trading days. Buy at the next day's open; stop-loss 10% below (if a day opens below the stop, sell at
that open); otherwise sell at the open after HOLD trading days, or earlier when it leaves the top 30 if that exit is chosen.
Costs 0.3% per round trip.
"""
import sys, json, numpy as np, pandas as pd
WD = sys.argv[1]
M = pd.read_pickle(f'{WD}/mats.pkl')
O, C, L, TO, breadth, bavg = M['O'], M['C'], M['L'], M['TO'], M['breadth'], M['bavg']
COST, STOP = 0.003, 0.10
ret = C.pct_change(fill_method=None).clip(-0.5, 0.5)
tom = TO.rolling(60, min_periods=40).median()
mom = (C.shift(21) / C.shift(252) - 1) / (ret.rolling(126, min_periods=100).std() * 252 ** .5)
dates = C.index; n = len(dates); Ov, Cv, Lv = O.values, C.values, L.values
up = (breadth > bavg).values

def ranks(N):
    liq = tom.where(C >= 10).rank(axis=1, ascending=False) <= N
    return mom.where(liq & C.shift(252).notna()).rank(axis=1, ascending=False).values

def trade(i, j, R, hold, exit_out):
    if i + 1 >= n: return None
    e = Ov[i + 1, j]
    if not np.isfinite(e) or e <= 0: return None
    S = e * (1 - STOP); end = min(n - 1, i + 1 + hold)
    for k in range(i + 1, end):
        if k > i + 1 and np.isfinite(Ov[k, j]) and Ov[k, j] <= S: return Ov[k, j] / e - 1, k - i
        if np.isfinite(Lv[k, j]) and Lv[k, j] <= S: return -STOP, k - i
        if exit_out and not (R[k, j] <= 30):                     # left the top 30 at this close: sell next open
            x = Ov[k + 1, j] if k + 1 < n and np.isfinite(Ov[k + 1, j]) else Cv[k, j]
            return (x / e - 1, k + 1 - i) if np.isfinite(x) else None
    x = Ov[end, j] if np.isfinite(Ov[end, j]) else Cv[end - 1, j]
    return (x / e - 1, end - i) if np.isfinite(x) else None

def run(N=300, K=30, hold=21, exit_out=False, fresh=20, per_day=None, start=260):
    R = ranks(N); inK = R <= K; in30 = R <= 30
    rec30 = pd.DataFrame(in30).rolling(fresh, min_periods=1).max().shift(1).fillna(0).values.astype(bool) if fresh else np.zeros_like(in30)
    sig = inK & ~rec30 if fresh else inK & ~np.vstack([np.zeros((1, R.shape[1]), bool), inK[:-1]])
    out = []
    for i in range(start, n - 2):
        js = np.nonzero(sig[i])[0]
        if per_day and len(js) > per_day: js = js[np.argsort(R[i, js])[:per_day]]
        for j in js:
            t = trade(i, j, R, hold, exit_out)
            if t: out.append((t[0] - COST, t[1], dates[i], bool(up[i])))
    return out

def summ(tr, label):
    r = np.array([t[0] for t in tr]); d = np.array([t[1] for t in tr]); u = np.array([t[3] for t in tr])
    months = len(set((t[2].year, t[2].month) for t in tr)) or 1
    yrs = pd.Series(r, index=[t[2].year for t in tr]).groupby(level=0).mean() * 100
    s = dict(label=label, n=int(len(r)), per_month=round(len(r) / months, 1), avg=round(r.mean() * 100, 2), win=round((r > 0).mean() * 100, 1),
             days=round(d.mean(), 1), healthy=round(r[u].mean() * 100, 2), cautious=round(r[~u].mean() * 100, 2), worst=round(r.min() * 100, 1),
             years={int(k): round(v, 2) for k, v in yrs.items()})
    print(f"{label:62s} trades {s['n']:5d} ({s['per_month']:4.1f}/month) avg {s['avg']:+5.2f}% win {s['win']}% {s['days']}d "
          f"healthy {s['healthy']:+.2f}% cautious {s['cautious']:+.2f}% worst {s['worst']}% {s['years']}")
    return s

if __name__ == '__main__':
    res = []
    res.append(summ(run(300), 'Daily: entered top 30 of 300, hold 1 month, 10% stop'))
    res.append(summ(run(300, fresh=0), '  same, but any re-entry counts (no 20-day freshness rule)'))
    res.append(summ(run(300, exit_out=True), '  same, but also sell when it leaves the top 30'))
    res.append(summ(run(300, hold=40), '  same, but hold up to 40 days'))
    res.append(summ(run(500), 'Universe 500: entered top 30 of 500, hold 1 month, 10% stop'))
    res.append(summ(run(500, K=30, exit_out=True), '  universe 500, also sell when it leaves the top 30'))
    res.append(summ(run(300, K=10), 'Fewer: entered top 10 of 300 (fresh), 1 month, 10% stop'))
    res.append(summ(run(500, K=10), 'Fewer: entered top 10 of 500 (fresh), 1 month, 10% stop'))
    res.append(summ(run(300, per_day=2), 'Fewer: at most 2 a day (best-ranked), top 30 of 300'))
    res.append(summ(run(500, per_day=2), 'Fewer: at most 2 a day (best-ranked), top 30 of 500'))
    # baseline: random stocks from the same universe, same exits
    rng = np.random.default_rng(0)
    for N in (300, 500):
        R = ranks(N); base = []
        for i in range(260, n - 2, 3):
            js = np.nonzero(np.isfinite(R[i]))[0]
            for j in rng.choice(js, min(4, len(js)), replace=False):
                t = trade(i, j, R, 21, False)
                if t: base.append((t[0] - COST, t[1], dates[i], bool(up[i])))
        res.append(summ(base, f'Baseline: random stocks from the {N} most-traded, 1 month, 10% stop'))
    json.dump(dict(built=pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%MZ'), rows=res), open(f'{WD}/daily_bt.json', 'w'), indent=1)
