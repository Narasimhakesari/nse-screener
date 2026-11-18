#!/usr/bin/env python3
"""Backtest target / stop-loss swing trades on NSE daily data.

Usage: DUMP=1 python3 build/build.py WD ; python3 build/backtest_trades.py WD
Each signal is bought at the next day's close. Exit at the target or the stop, whichever the daily high/low reaches
first (if both on the same day, the stop is assumed: the cautious choice), or at the close after MAX_DAYS.
Costs 0.3% per round trip (brokerage, STT, slippage). Universe: the 300 most-traded stocks at the time, price >= Rs 10.
Every entry rule is compared with random entries in the same universe on the same days, with the same exits.
"""
import sys, json, numpy as np, pandas as pd
WD = sys.argv[1]
M = pd.read_pickle(f'{WD}/mats.pkl')
C, H, L, TO, s50, s200, rsi, BRK = M['C'], M['H'], M['L'], M['TO'], M['s50'], M['s200'], M['rsi'], M['BRK']
breadth, bavg = M['breadth'], M['bavg']
COST, MAX_DAYS = 0.003, 40
ret = C.pct_change(fill_method=None).clip(-0.5, 0.5)
m121 = C.shift(21) / C.shift(252) - 1
vol = ret.rolling(126, min_periods=100).std() * 252 ** .5
tom = TO.rolling(60, min_periods=40).median()
liq = tom.where(C >= 10).rank(axis=1, ascending=False) <= 300
mq = (m121 / vol).where(liq & C.shift(252).notna())
mrank = mq.rank(axis=1, ascending=False)
ema12, ema26 = C.ewm(span=12, adjust=False, ignore_na=True).mean(), C.ewm(span=26, adjust=False, ignore_na=True).mean()
macd = ema12 - ema26; sig = macd.ewm(span=9, adjust=False, ignore_na=True).mean(); mh = macd - sig
low20 = L.rolling(20).min()
start = 260  # a year of history first

SIG = {
 'Momentum top 30 (newly entered)': (mrank <= 30) & ~(mrank.shift(1) <= 30),
 'Trend turn: close back above 50-day, above 200-day': liq & (C > s50) & (C.shift(1) <= s50.shift(1)) & (C > s200),
 'Trend turn + MACD turning up + RSI < 70': liq & (C > s50) & (C.shift(1) <= s50.shift(1)) & (C > s200) & (mh > 0) & (mh.shift(1) <= 0) & (rsi < 70),
 'Support: within 3% of 200-day, RSI < 40': liq & (C >= s200) & (C <= s200 * 1.03) & (rsi < 40),
 'Oversold: RSI < 30': liq & (rsi < 30),
 'Breakout: 50-day high on 1.5x volume': liq & BRK,
 'Momentum top 30 + trend turn above 50-day': (mrank <= 30) & (C > s50) & (C.shift(1) <= s50.shift(1)),
}

Cv, Hv, Lv = C.values, H.values, L.values
dates = C.index

def trade(i, j, tgt, stp):
    if i + 1 >= len(dates): return None
    e = Cv[i + 1, j]
    if not np.isfinite(e) or e <= 0: return None
    T, S = e * (1 + tgt), e * (1 - stp)
    end = min(len(dates) - 1, i + 1 + MAX_DAYS)
    for k in range(i + 2, end + 1):
        h, l = Hv[k, j], Lv[k, j]
        if not np.isfinite(l): continue
        if l <= S: return (-stp - COST, k - i - 1, 'stop')
        if h >= T: return (tgt - COST, k - i - 1, 'target')
    c = Cv[end, j]
    if not np.isfinite(c): return None
    return (c / e - 1 - COST, end - i - 1, 'time')

def run(mask, tgt, stp, cap=None, seed=0):
    m = mask.values.copy(); m[:start] = False; m[-2:] = False
    ii, jj = np.nonzero(m)
    if cap and len(ii) > cap:
        r = np.random.default_rng(seed).choice(len(ii), cap, replace=False); ii, jj = ii[r], jj[r]
    out = [(dates[i], trade(i, j, tgt, stp), bool(breadth.iloc[i] > bavg.iloc[i])) for i, j in zip(ii, jj)]
    return [(d, t, up) for d, t, up in out if t]

def summ(tr):
    if not tr: return None
    r = np.array([t[1][0] for t in tr]); days = np.array([t[1][1] for t in tr])
    win = (r > 0).mean(); hit = np.mean([t[1][2] == 'target' for t in tr])
    yrs = pd.Series(r, index=[t[0].year for t in tr]).groupby(level=0).mean() * 100
    up = np.array([t[2] for t in tr])
    return dict(n=len(r), avg=round(r.mean() * 100, 2), win=round(win * 100, 1), target_hit=round(hit * 100, 1),
                days=round(days.mean(), 1), per_month=round(r.mean() / max(days.mean(), 1) * 21 * 100, 2),
                rising_avg=round(r[up].mean() * 100, 2) if up.any() else None, falling_avg=round(r[~up].mean() * 100, 2) if (~up).any() else None,
                years={int(k): round(v, 2) for k, v in yrs.items()})

GRID = [(0.10, 0.05), (0.10, 0.08), (0.15, 0.08), (0.20, 0.10), (0.08, 0.04)]
res = {}
base_mask = liq & C.shift(252).notna()
for tgt, stp in GRID:
    key = f'target {int(tgt*100)}% / stop {int(stp*100)}%'
    res[key] = {'Random entry (baseline)': summ(run(base_mask, tgt, stp, cap=20000))}
    for name, mask in SIG.items():
        res[key][name] = summ(run(mask, tgt, stp, cap=20000))
    print('\n==', key, '| bought next day, exit at target, stop or after', MAX_DAYS, 'days, 0.3% costs')
    b = res[key]['Random entry (baseline)']
    for name, s in res[key].items():
        if not s: continue
        print(f"  {name:52s} trades {s['n']:6d} avg {s['avg']:+5.2f}% (vs random {s['avg']-b['avg']:+5.2f})  win {s['win']:4.1f}%  target hit {s['target_hit']:4.1f}%  {s['days']:4.1f} days  "
              f"market up {s['rising_avg']}% / down {s['falling_avg']}%  years {s['years']}")
json.dump(dict(max_days=MAX_DAYS, cost=COST, results=res), open(f'{WD}/trades_bt.json', 'w'), indent=1)
