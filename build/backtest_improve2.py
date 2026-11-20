#!/usr/bin/env python3
"""Second round on the home page's top 10 (20-year test). Run on GitHub Actions.

Usage: python3 build/backtest_improve2.py WD   (writes WD/improve2_bt.json)

Current rule: monthly top 10 by momentum, at most 2 per industry, cash when an equal-weight index of the 300 most-traded
stocks is below its 100-day average (checked at month-end).
Tested:
- market filter checked every day (sell at the next open when the index closes below its average; buy back the top 10
  when it closes back above);
- position sizes by inverse volatility instead of equal amounts;
- four staggered parts, each rebalanced every 21 trading days, a week apart (removes the luck of the rebalance day);
- double the costs (0.3% each side);
- walk-forward: for each period, the filter length (75/100/125/150/200 days) with the best risk-adjusted return over
  all earlier years only, then used in that period.
"""
import os, sys, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_improve20 import (WD, sim, evaluate, MOM, stats, bench, PERIODS, START, n, idx, dates)

M = MOM['12-1 vol-adjusted']
base = dict(score=M, N=10, filt=100)

def per_bounds():
    out = []
    for lab, a_, b_ in PERIODS:
        lo, hi = max(START, idx(a_)), min(n - 1, idx(b_) - 1 if idx(b_) < n else n - 1)
        if hi - lo >= 100: out.append((lab, lo, hi))
    return out

def staggered(**kw):
    curves = [sim(every=21, offset=o, **{k: v for k, v in kw.items() if k != 'every'}) for o in (0, 5, 10, 15)]
    return sum(c / c.iloc[0] for c in curves) / 4

if __name__ == '__main__':
    res = {}; B = per_bounds()
    def show(lab, s, b0=None):
        beat = '' if b0 is None else f" | beats current in {sum(1 for a, b in zip(s['periods'], b0['periods']) if a > b)}/4"
        print(f"{lab:66s} {s['cagr']:6.1f}% worst {s['dd']:6.1f}% sharpe {s['sharpe']:.2f} | periods {[float(x) for x in s['periods']]}{beat}", flush=True)
    s0, _ = evaluate(**base); res['Current: 100-day filter, checked at month-end'] = s0; show('Current: 100-day filter, checked at month-end', s0)
    for lab, ch in [('Filter checked every day', dict(daily=True)), ('Sizes by inverse volatility', dict(wt='invvol')),
                    ('Filter checked every day + inverse volatility', dict(daily=True, wt='invvol')),
                    ('Double costs (0.3% each side)', dict(cost=0.003)), ('Double costs, filter checked every day', dict(cost=0.003, daily=True))]:
        s, _ = evaluate(**{**base, **ch}); res[lab] = s; show(lab, s, s0)
    for lab, ch in [('Four staggered parts', {}), ('Four staggered parts, filter checked every day', dict(daily=True))]:
        e = staggered(**{**base, **ch}); s = stats(e)
        s['periods'] = [stats(staggered(lo=lo, hi=hi, **{**base, **ch}))['cagr'] for _, lo, hi in B]
        res[lab] = s; show(lab, s, s0)
    # walk-forward choice of the filter length
    wf = []; chosen = []
    for k_, (lab, lo, hi) in enumerate(B):
        if k_ == 0: chosen.append((lab, 100, 'no earlier data: 100')); wf.append(stats(sim(lo=lo, hi=hi, **base))['cagr']); continue
        best = max((75, 100, 125, 150, 200), key=lambda L: stats(sim(lo=START, hi=lo - 1, **{**base, 'filt': L}))['sharpe'])
        chosen.append((lab, best, '')); wf.append(stats(sim(lo=lo, hi=hi, **{**base, 'filt': best}))['cagr'])
    print('\nWALK-FORWARD filter length chosen from earlier years only:', [(c[0], c[1]) for c in chosen])
    print('walk-forward returns by period:', [float(x) for x in wf], '| fixed 100-day:', [float(x) for x in s0['periods']], flush=True)
    res['walk_forward'] = dict(chosen=[[c[0], c[1]] for c in chosen], periods=[float(x) for x in wf])
    json.dump(res, open(f'{WD}/improve2_bt.json', 'w'), separators=(',', ':'), default=float)
    print('wrote improve2_bt.json')
