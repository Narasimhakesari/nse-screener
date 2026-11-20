#!/usr/bin/env python3
"""Can the home page's 'Best tested' top 10 be improved? 20-year test, one change at a time. Run on GitHub Actions.

Usage: python3 build/backtest_improve20.py WD     (writes WD/improve_bt.json; prints a summary)

Baseline (what the page does now): every month-end, rank the 300 most-traded stocks above their 200-day average by
momentum (12-month return skipping the last month, divided by 6-month volatility), take the best 10 with at most 2 per
industry, equal amounts, bought at the next open, 0.15% cost each side. Cash while an equal-weight index of the 300
most-traded stocks is below its 200-day average.

Changes tested, each against that baseline:
- hold 15 or 20 stocks;
- buffer: keep a stock until it falls out of the top 20 (or 30), instead of the top 10;
- market filter: 100- or 150-day average; half the stocks instead of cash; no filter;
- momentum: blend of 12- and 6-month (both skipping a month, volatility-adjusted); plain 12-month return;
- trailing stop: sell at the next open after a close 15% or 20% below the stock's highest close since buying;
- review every 10 trading days instead of monthly.
A change counts only if it beats the baseline in at least 3 of the 4 periods, not just on the 20-year total.
"""
import os, sys, json, subprocess
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('SKIP_DL', '1')
from backtest_20y import (WD, O, C, ret, LIQ, mq, s200, bret, dates, n, START, ISME, PERIODS, idx, stats, bench)

COST = 0.0015
Ov, Cv = O.values, C.values
ELIG = (LIQ & (C > s200)).values
vol = ret.rolling(126, min_periods=100).std() * 252 ** .5
m6 = ((C.shift(21) / C.shift(126) - 1) / vol).where(LIQ)
MOM = {
    '12-1 vol-adjusted': mq,
    '12-1 + 6-1 blend': (mq.rank(axis=1, pct=True) + m6.rank(axis=1, pct=True)) / 2,
    'plain 12-1 return': (C.shift(21) / C.shift(252) - 1).where(LIQ),
}
SEC = {}
try:
    subprocess.run(['curl', '-s', '-m', '40', '-A', 'Mozilla/5.0', '-o', f'{WD}/tm.csv', 'https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv'])
    SEC = pd.read_csv(f'{WD}/tm.csv').set_index('Symbol').Industry.to_dict()
except Exception as e: print('industry list skipped', e)
secv = np.array([SEC.get(s, '_' + s) for s in C.columns])
bidx = (1 + bret).cumprod()
FILT = {k: (bidx > bidx.rolling(k, min_periods=int(k * .75)).mean()).values for k in (100, 150, 200)}

def sim(score, N=10, buf=None, filt=200, half=False, trail=None, every=None, cap=2, lo=None, hi=None):
    lo = START if lo is None else lo; hi = n - 1 if hi is None else hi
    Sv = score.values; up = np.ones(n, bool) if filt is None else FILT[filt]
    buf = buf or N
    cash, pos, eq, pend, sells = 1.0, {}, [], [], set()
    for i in range(lo, hi + 1):
        # sells at today's open (decided yesterday), or a delisted stock at its last price
        for j in list(pos):
            p = pos[j]; o = Ov[i, j]
            if not np.isfinite(Cv[i, j]) and i > p['bi']:
                cash += p['sh'] * p['lc'] * (1 - COST); del pos[j]; continue
            if j in sells and np.isfinite(o):
                cash += p['sh'] * o * (1 - COST); del pos[j]
        sells = set()
        eqv = cash + sum(p['sh'] * p['lc'] for p in pos.values())
        for j, slot in pend:
            o = Ov[i, j]
            if j in pos or not np.isfinite(o) or o <= 0: continue
            val = min(cash, eqv * slot)
            if val < eqv * slot * 0.5: continue
            cash -= val; pos[j] = dict(sh=val / (o * (1 + COST)), bi=i, lc=o, pk=o)
        pend = []
        for j, p in pos.items():
            c = Cv[i, j]
            if np.isfinite(c): p['lc'] = c; p['pk'] = max(p['pk'], c)
            if trail and p['lc'] < p['pk'] * (1 - trail): sells.add(j)
        eqv = cash + sum(p['sh'] * p['lc'] for p in pos.values()); eq.append(eqv)
        review = ISME[i] if not every else ((i - lo) % every == every - 1)
        if not review: continue
        k = N if up[i] else (N // 2 if half else 0)
        if k == 0:
            sells |= set(pos); continue
        row = Sv[i]; ok = np.isfinite(row) & ELIG[i]
        order = np.argsort(-np.where(ok, row, -np.inf))[:ok.sum()]
        rank = {j: r for r, j in enumerate(order)}
        keep = [j for j in pos if j not in sells and rank.get(j, 1e9) < max(buf, k)]
        keep = sorted(keep, key=lambda j: rank[j])[:k]
        cnt = {}
        for j in keep: cnt[secv[j]] = cnt.get(secv[j], 0) + 1
        new = []
        for j in order:
            if len(keep) + len(new) >= k: break
            if j in pos: continue
            if cnt.get(secv[j], 0) >= cap: continue
            cnt[secv[j]] = cnt.get(secv[j], 0) + 1; new.append(j)
        for j in pos:
            if j not in keep: sells.add(j)
        pend = [(j, 1.0 / N) for j in new]
    return pd.Series(eq, index=dates[lo:hi + 1])

def evaluate(**kw):
    e = sim(**kw); s = stats(e); s.pop('trades', None); s.pop('win', None); s.pop('avg', None)
    s['periods'] = []
    for lab, a_, b_ in PERIODS:
        lo, hi = max(START, idx(a_)), min(n - 1, idx(b_) - 1 if idx(b_) < n else n - 1)
        if hi - lo < 100: continue
        s['periods'].append(stats(sim(lo=lo, hi=hi, **kw))['cagr'])
    return s, e

if __name__ == '__main__':
    out = dict(built=pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%MZ'), periods=[p[0] for p in PERIODS])
    be = bench(); out['bench'] = stats(be)
    out['bench']['periods'] = [stats(bench(max(START, idx(a_)), min(n - 1, idx(b_) - 1 if idx(b_) < n else n - 1)))['cagr'] for _, a_, b_ in PERIODS]
    print(f"MARKET {out['bench']['cagr']}% worst {out['bench']['dd']}% periods {out['bench']['periods']}", flush=True)
    M = MOM['12-1 vol-adjusted']
    base = dict(score=M, N=10, buf=None, filt=200, half=False, trail=None, every=None)
    tests = [('Baseline: top 10, 2 per industry, cash below the 200-day average', {}),
             ('Hold 15', dict(N=15)), ('Hold 20', dict(N=20)),
             ('Buffer: keep until out of the top 20', dict(buf=20)), ('Buffer: keep until out of the top 30', dict(buf=30)),
             ('Market filter on the 150-day average', dict(filt=150)), ('Market filter on the 100-day average', dict(filt=100)),
             ('Half the stocks (not cash) below the 200-day average', dict(half=True)), ('No market filter', dict(filt=None)),
             ('Momentum: 12- and 6-month blend', dict(score=MOM['12-1 + 6-1 blend'])), ('Momentum: plain 12-month return', dict(score=MOM['plain 12-1 return'])),
             ('Trailing stop 15%', dict(trail=.15)), ('Trailing stop 20%', dict(trail=.20)),
             ('Review every 10 trading days', dict(every=10))]
    res = {}; curves = {}
    b0 = None
    for lab, ch in tests:
        kw = {**base, **ch}; s, e = evaluate(**kw)
        if b0 is None: b0 = s
        beat = sum(1 for a, b in zip(s['periods'], b0['periods']) if a > b)
        s['beat'] = beat; res[lab] = s; curves[lab] = e
        print(f"{lab:62s} {s['cagr']:6.1f}% worst {s['dd']:6.1f}% sharpe {s['sharpe']:.2f} | periods {s['periods']} | beats baseline in {beat}/4", flush=True)
    # combine every single change that beat the baseline in 3+ periods without a deeper worst fall
    win = [(lab, ch) for lab, ch in tests[1:] if res[lab]['beat'] >= 3 and res[lab]['dd'] >= b0['dd'] - 3 and res[lab]['sharpe'] >= b0['sharpe']]
    print('\nchanges that passed:', [w[0] for w in win], flush=True)
    combos = []
    if win:
        merged = {}
        for _, ch in win: merged.update(ch)
        combos.append(('All passing changes together', merged))
        for i_ in range(len(win)):
            for j_ in range(i_ + 1, len(win)):
                combos.append((f'{win[i_][0]} + {win[j_][0]}', {**win[i_][1], **win[j_][1]}))
    for lab, ch in combos[:12]:
        kw = {**base, **ch}; s, e = evaluate(**kw)
        s['beat'] = sum(1 for a, b in zip(s['periods'], b0['periods']) if a > b); res[lab] = s; curves[lab] = e
        print(f"{lab[:62]:62s} {s['cagr']:6.1f}% worst {s['dd']:6.1f}% sharpe {s['sharpe']:.2f} | periods {s['periods']} | beats baseline in {s['beat']}/4", flush=True)
    out['results'] = res; out['passed'] = [w[0] for w in win]
    print('\nBY YEAR')
    for lab in list(res)[:1] + [c[0] for c in combos[:1]]: print(f'{lab[:62]:62s}', res[lab]['years'])
    print(f"{'market':62s}", out['bench']['years'])
    json.dump(out, open(f'{WD}/improve_bt.json', 'w'), separators=(',', ':'), default=float)
    print('\nwrote improve_bt.json')
