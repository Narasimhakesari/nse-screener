#!/usr/bin/env python3
"""Which profit target and stop-loss work best for buy-then-exit trades on NSE momentum stocks?

Usage: DUMP=1 python3 build/build.py WD ; python3 build/backtest_exits.py WD [--grid]   (writes WD/exits_bt.json)

Each rule is run as a real portfolio (same engine and costs as backtest_algos.py): buy at the next open after the
signal, each position gets 1/N of equity, 0.15% cost per side. Exits work like a Zerodha GTT OCO order placed right
after buying: the stop sells at the stop price (or at the open if the stock gaps below it), the target sells at the
target price (or at the open if it gaps above it). If both prices are touched on the same day the stop is assumed to
hit first (the cautious assumption). A time limit sells at the open after N trading days. A trailing stop is moved up
each evening to X% below the highest close since buying (you would edit the GTT).
--grid runs the full grid and prints it; without it only the shortlist is run (for the nightly job).
"""
import sys, json, itertools, numpy as np, pandas as pd
sys.argv = sys.argv[:2] + [a for a in sys.argv[2:]]
from backtest_algos import (dates, n, C, MR, LIQ, ret, UP, Ov, Hv, Lv, Cv, START, COST, stats)

GRID = '--grid' in sys.argv
in30 = MR <= 30
FRESH = in30 & ~(in30.rolling(20, min_periods=1).max().shift(1).fillna(0).astype(bool))
IN10 = MR <= 10
in50 = MR <= 50
FRESH50 = in50 & ~(in50.rolling(20, min_periods=1).max().shift(1).fillna(0).astype(bool))
ENTRIES = {'fresh30': ('Newly entered the top 30 by momentum', FRESH), 'top10': ('In the top 10 by momentum', IN10), 'fresh50': ('Newly entered the top 50 by momentum', FRESH50)}

def sim(entry, target=None, stop=.10, days=40, trail=None, maxpos=10, mood=False, lo=START, hi=None, log=None, state=None):
    hi = hi or n - 1
    Pv = (-MR).reindex(index=dates, columns=C.columns).values
    Ev = entry.reindex(index=dates, columns=C.columns).fillna(False).values
    cash, pos, eq, trades, pend, eqv, why = 1.0, {}, [], [], [], 1.0, []
    for i in range(lo, hi + 1):
        for j in list(pos):
            p = pos[j]; o, l, h = Ov[i, j], Lv[i, j], Hv[i, j]
            px = r = None
            if not np.isfinite(Cv[i, j]) and i > p['bi']: px, r = p.get('lc', p['e']), 'time'   # stopped trading (symbol change, delisting): out at the last price
            elif p.get('sell_open') and np.isfinite(o): px, r = o, 'time'
            elif i > p['bi'] and np.isfinite(o) and o <= p['stop']: px, r = o, 'stop'
            elif np.isfinite(l) and l <= p['stop']: px, r = p['stop'], 'stop'
            elif target and i > p['bi'] and np.isfinite(o) and o >= p['tgt']: px, r = o, 'target'
            elif target and np.isfinite(h) and h >= p['tgt']: px, r = p['tgt'], 'target'
            if px is not None:
                cash += p['sh'] * px * (1 - COST); trades.append(px / p['e'] - 1 - 2 * COST); why.append(r)
                if log is not None: log.append(dict(sym=C.columns[j], buy=str(dates[p['bi']].date()), sell=str(dates[i].date()), why=r, ret=round((px / p['e'] - 1 - 2 * COST) * 100, 2), days=i - p['bi']))
                del pos[j]
        if pend:
            for j in pend:
                if len(pos) >= maxpos: break
                o = Ov[i, j]
                if j in pos or not np.isfinite(o) or o <= 0: continue
                val = min(cash, eqv / maxpos)
                if val < eqv / maxpos * 0.5: break
                cash -= val
                pos[j] = dict(e=o, sh=val / (o * (1 + COST)), bi=i, hc=o, stop=o * (1 - stop), tgt=o * (1 + (target or 9)))
        for j, p in pos.items():
            if np.isfinite(Cv[i, j]): p['lc'] = Cv[i, j]
        eqv = cash + sum(p['sh'] * p.get('lc', p['e']) for j, p in pos.items())
        eq.append(eqv)
        for j, p in pos.items():
            c = Cv[i, j]
            if trail and np.isfinite(c) and c > p['hc']:
                p['hc'] = c; p['stop'] = max(p['stop'], c * (1 - trail))
            if days and i - p['bi'] + 1 >= days: p['sell_open'] = True
        pend = []
        if (not mood) or UP[i]:
            sig = np.nonzero(Ev[i])[0]
            if len(sig):
                sig = sig[np.argsort(-np.nan_to_num(Pv[i, sig], nan=-1e9))]
                pend = [j for j in sig if j not in pos]
    if state is not None: state.update(pos=pos, pend=pend)
    return pd.Series(eq, index=dates[lo:hi + 1]), np.array(trades), why

MID = dates.searchsorted(pd.Timestamp('2025-01-01'))
bret = ret.where(LIQ.shift(1).fillna(False)).mean(axis=1).fillna(0)
def bench(lo, hi):
    e = (1 + bret.iloc[lo:hi + 1]).cumprod(); return stats(e, np.array([]))['cagr'], stats(e, np.array([]))['dd']

def row(key, ent, **kw):
    e, tr, why = sim(ENTRIES[ent][1], **kw)
    s = stats(e, tr)
    a = stats(sim(ENTRIES[ent][1], hi=MID - 1, **kw)[0], np.array([]))['cagr']
    b = stats(sim(ENTRIES[ent][1], lo=MID, **kw)[0], np.array([]))['cagr']
    w = pd.Series(why).value_counts(normalize=True).mul(100).round(1).to_dict() if why else {}
    hold = None
    return dict(key=key, entry=ent, target=kw.get('target'), stop=kw.get('stop'), days=kw.get('days'), trail=kw.get('trail'),
                maxpos=kw.get('maxpos', 10), cagr=s['cagr'], dd=s['dd'], sharpe=s['sharpe'], trades=s['trades'], win=s['win'],
                avg=s['avg'], first=a, second=b, hit_target=w.get('target', 0.0), hit_stop=w.get('stop', 0.0), timed_out=w.get('time', 0.0), years=s['years'])

def label(r):
    t = f"{int(r['target']*100)}% target" if r['target'] else 'no target'
    s = f"{int(r['trail']*100)}% trailing stop" if r['trail'] else f"{int(r['stop']*100)}% stop"
    return f"{t}, {s}, sell after {r['days']} days"

RULE = dict(target=.20, stop=.08, days=30, maxpos=5)   # chosen on 2022-24 data, checked on 2025-26: see build/backtest_ideas.py and README
LIVE_SINCE = '2026-11-20'

def nightly():
    bF, bD = bench(START, n - 1); bA, _ = bench(START, MID - 1); bB, _ = bench(MID, n - 1)
    log, stt = [], {}
    e, tr, why = sim(FRESH50, log=log, state=stt, **RULE)
    full = stats(e, tr); em, trm, _ = sim(FRESH50, mood=True, **RULE); mood = stats(em, trm)
    a = stats(sim(FRESH50, hi=MID - 1, **RULE)[0], np.array([]))['cagr']; b = stats(sim(FRESH50, lo=MID, **RULE)[0], np.array([]))['cagr']
    w = pd.Series(why).value_counts(normalize=True).mul(100).round(1).to_dict()
    rng = [stats(sim(FRESH50, **dict(RULE, days=dy))[0], np.array([]))['cagr'] for dy in (25, 27, 28, 30, 32, 33, 35)]
    grid = []
    for tg in (None, .10, .15, .20, .30, .40):
        for st in (.05, .08, .10):
            r_ = row('', 'fresh50', **dict(RULE, target=tg, stop=st)); grid.append({k: r_[k] for k in ('target', 'stop', 'cagr', 'dd', 'first', 'second', 'hit_target', 'win')})
    others = {}
    for lbl, kw in [('Same, but up to 10 trades at a time', dict(RULE, maxpos=10)), ('Same, but sell after 20 days', dict(RULE, days=20)),
                    ('Same, but no profit target', dict(RULE, target=None))]:
        r_ = row('', 'fresh50', **kw); others[lbl] = {k: r_[k] for k in ('cagr', 'dd', 'first', 'second', 'hit_target', 'win')}
    # live state at the last close
    last = dates[-1]; nb = lambda k: (pd.Timestamp(last) + pd.offsets.BDay(k))
    def sell_by(bi):
        k = bi + RULE['days']   # sold at the open of this trading day
        return str(dates[k].date()) if k < n else str(nb(k - (n - 1)).date())
    opens = []
    for j, p in stt['pos'].items():
        opens.append(dict(sym=C.columns[j], buyDate=str(dates[p['bi']].date()), buy=round(float(p['e']), 2), target=round(float(p['tgt']), 2),
                          stop=round(float(p['stop']), 2), sellBy=sell_by(p['bi']), close=round(float(Cv[-1, j]), 2),
                          days=int(n - 1 - p['bi'] + 1), sellTomorrow=bool(p.get('sell_open'))))
    opens.sort(key=lambda x: x['buyDate'])
    free = RULE['maxpos'] - len(stt['pos']) + sum(1 for p in stt['pos'].values() if p.get('sell_open'))
    cand = [dict(sym=C.columns[j], rank=int(MR.iloc[-1, j]), close=round(float(Cv[-1, j]), 2)) for j in stt['pend']]
    buys, queue = cand[:max(free, 0)], cand[max(free, 0):]
    closed = [x for x in log if x['sell'] == str(last.date())]
    fresh_today = [C.columns[j] for j in np.nonzero(FRESH50.iloc[-1].fillna(False).values)[0]]
    wk = e.resample('W-FRI').last().dropna(); be = (1 + bret.iloc[START:]).cumprod(); bw = be.reindex(wk.index, method='ffill')
    out = dict(built=pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%MZ'), start=str(dates[START].date()), end=str(last.date()), split='2025-01-01',
               rule=dict(RULE, entry='Newly entered the top 50 of the 300 most-traded stocks by momentum (not in the top 50 in the 20 days before)'),
               liveSince=LIVE_SINCE,
               stats=dict(full, first=a, second=b, hit_target=w.get('target', 0.0), hit_stop=w.get('stop', 0.0), timed_out=w.get('time', 0.0),
                          range=[min(rng), max(rng)], per_year=round(len(tr) / ((e.index[-1] - e.index[0]).days / 365.25))),
               mood=mood, bench=dict(cagr=bF, dd=bD, first=bA, second=bB), grid=grid, others=others,
               curve=dict(dates=[f"{x:%Y-%m-%d}" for x in wk.index], rule=[round(v * 100, 2) for v in wk.values], bench=[round(v * 100, 2) for v in bw.values]),
               live=dict(asof=str(last.date()), open=opens, buys=buys, queue=queue[:10], closedToday=closed, freshToday=fresh_today),
               trades=log[-60:])
    json.dump(out, open(f'{sys.argv[1]}/exits_bt.json', 'w'), separators=(',', ':'))
    print('rule', full, 'halves', a, b, 'range', rng, 'mood', mood['cagr'], mood['dd'])
    print('open', opens); print('buys', buys, 'queue', queue[:5]); print('closed today', closed)

if __name__ == '__main__':
    bF, bD = bench(START, n - 1); bA, _ = bench(START, MID - 1); bB, _ = bench(MID, n - 1)
    print(f'benchmark CAGR {bF}% DD {bD}% halves {bA}% / {bB}%')
    rows = []
    if not GRID: nightly()
    if GRID:
        for ent, mp in [('fresh30', 10), ('top10', 10), ('fresh30', 5), ('top10', 5)]:
            for tg, st, dy in itertools.product([None, .08, .10, .15, .20, .25, .30, .40], [.05, .07, .10, .12, .15], [21, 40, 60]):
                rows.append(row('', ent, target=tg, stop=st, days=dy, maxpos=mp))
            for tr_, dy in itertools.product([.08, .10, .12, .15, .20], [40, 60, 120]):
                rows.append(row('', ent, target=None, stop=tr_, trail=tr_, days=dy, maxpos=mp))
            print(ent, mp, 'done', flush=True)
        df = pd.DataFrame(rows); df.to_pickle(sys.argv[1] + '/exits_grid.pkl')
        df['both'] = (df['first'] > bA) & (df['second'] > bB)
        pd.set_option('display.width', 250); pd.set_option('display.max_rows', 300)
        cols = ['entry', 'maxpos', 'target', 'stop', 'trail', 'days', 'cagr', 'dd', 'sharpe', 'trades', 'win', 'avg', 'first', 'second', 'hit_target', 'hit_stop', 'timed_out', 'both']
        print(df.sort_values('cagr', ascending=False)[cols].head(60).to_string())
