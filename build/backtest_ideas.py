#!/usr/bin/env python3
"""From scratch: which stock-picking idea works best for 2-6 week trades with a target and a stop-loss?

Usage: DUMP=1 python3 build/build.py WD ; python3 build/backtest_ideas.py WD     (writes WD/ideas_bt.json)

Method (to avoid fooling ourselves):
  * every idea is run as a real portfolio: buy at the next open after the signal, 1/N of equity per trade, at most N
    trades, stop fills at the stop (or the open if it gaps below), target likewise, stop assumed first if both touched
    in one day, time limit sells at the open, 0.15% cost per side;
  * for each idea, the exit settings (target, stop, days, N) are chosen using 2022-24 ONLY ("training");
  * the chosen settings are then run on 2025-26, which played no part in choosing them ("test"). Only the test
    result counts as evidence.
Universe: the 300 most-traded NSE stocks each day (price >= Rs 10, a year of history).
"""
import sys, json, itertools, numpy as np, pandas as pd
from backtest_algos import dates, n, C, O, H, L, V, DV, MR, LIQ, ret, UP, Ov, Hv, Lv, Cv, START, COST, stats, s50, s200

WD = sys.argv[1]
MID = dates.searchsorted(pd.Timestamp('2025-01-01'))
sector = {}
try:
    sector = {s['sym']: s['sector'] for s in json.load(open(f'{WD}/data.json'))['stocks']}
except Exception: pass

# ---------- features ----------
e20 = C.ewm(span=20, adjust=False).mean(); e50 = C.ewm(span=50, adjust=False).mean()
vol50 = V.rolling(50, min_periods=40).mean()
hi20p = H.rolling(20).max().shift(1); lo20p = L.rolling(20).min().shift(1)
hi30p = H.rolling(30).max().shift(1); lo30p = L.rolling(30).min().shift(1)
hi250 = C.rolling(250, min_periods=200).max()
r21, r63, r126 = C.pct_change(21, fill_method=None), C.pct_change(63, fill_method=None), C.pct_change(126, fill_method=None)
up_tr = LIQ & (C > s200) & (s50 > s200) & (s50 > s50.shift(10))
tr_ = pd.concat([H - L, (H - C.shift()).abs(), (L - C.shift()).abs()]).groupby(level=0).max() if False else np.maximum(H - L, np.maximum((H - C.shift()).abs(), (L - C.shift()).abs()))
atr = tr_.rolling(14, min_periods=10).mean()
macd = C.ewm(span=12, adjust=False).mean() - C.ewm(span=26, adjust=False).mean(); sig = macd.ewm(span=9, adjust=False).mean()
sd20 = C.rolling(20).std(); ma20 = C.rolling(20).mean(); bw = (4 * sd20 / ma20)
bwlow = bw <= bw.rolling(120, min_periods=100).min() * 1.1
rng = H - L; nr7 = rng <= rng.rolling(7).min()
bench_r = ret.where(LIQ.shift(1).fillna(False)).mean(axis=1)
b63 = (1 + bench_r.fillna(0)).rolling(63).apply(np.prod, raw=True) - 1
rs63 = r63.sub(b63, axis=0)
def fresh(cond, k=20):
    return cond & ~(cond.rolling(k, min_periods=1).max().shift(1).fillna(0).astype(bool))
def rank_in(x, top):  # top-N by x among LIQ
    return x.where(LIQ).rank(axis=1, ascending=False) <= top
# sector strength: average 63-day return of each sector's liquid members, top 3 sectors
secs = pd.Series({c: sector.get(c, 'Other') for c in C.columns})
sec_r = r63.where(LIQ).T.groupby(secs).mean().T
sec_rank = sec_r.rank(axis=1, ascending=False)
in_top_sec = pd.DataFrame({c: sec_rank[secs[c]] <= 3 if secs[c] in sec_rank.columns else False for c in C.columns}, index=dates)

IDEAS = {
 'Pullback in an uptrend: dips to the 20-day average, then closes above yesterday\'s high':
    (up_tr & (L.rolling(3).min() <= e20 * 1.01) & (C > H.shift(1)) & (C > e20), r126),
 'Pullback in a momentum leader (top 50): dips to the 20-day average, then bounces':
    (up_tr & rank_in(MR * -1, 50) & (L.rolling(3).min() <= e20 * 1.01) & (C > H.shift(1)) & (C > e20), -MR),
 'Base breakout: 30-day range under 15%, closes above it on 1.5x volume, above 200-day':
    (LIQ & (C > s200) & ((hi30p / lo30p - 1) < .15) & (C > hi30p) & (V > 1.5 * vol50), V / vol50),
 'Base breakout in a momentum leader (top 100)':
    (LIQ & rank_in(-MR, 100) & ((hi30p / lo30p - 1) < .15) & (C > hi30p) & (V > 1.5 * vol50), -MR),
 'First new 52-week high in a month, on above-average volume':
    (fresh(LIQ & (C >= hi250), 20) & (V > vol50), r126),
 'Near the 52-week high (within 5%), strongest 3-month gain, newly in top 30':
    (fresh(rank_in(r63.where(C >= .95 * hi250), 30)), r63),
 '3-month momentum: newly in the top 30':
    (fresh(rank_in(r63, 30)), r63),
 '6-month momentum: newly in the top 30':
    (fresh(rank_in(r126 / (ret.rolling(126, min_periods=100).std()), 30)), r126),
 '12-month momentum: newly in the top 50 (this site\'s rule)':
    (fresh(MR <= 50), -MR),
 '12-month momentum: newly in the top 30':
    (fresh(MR <= 30), -MR),
 'Beating the market by the most over 3 months, above 50-day, newly in the top 20':
    (fresh(rank_in(rs63.where(C > s50), 20)), rs63),
 'Narrow-range day (NR7) in an uptrend, then a close above its high':
    (up_tr & nr7.shift(1).fillna(False) & (C > H.shift(1)), r126),
 'MACD crosses up above zero, above 200-day':
    (LIQ & (C > s200) & (macd > sig) & (macd.shift(1) <= sig.shift(1)) & (macd > 0), r126),
 'Bollinger squeeze breakout: tightest bands in 6 months, close above the upper band':
    (LIQ & (C > s200) & bwlow.shift(1).fillna(False) & (C > ma20 + 2 * sd20), V / vol50),
 'Golden cross: 50-day crosses above 200-day':
    (LIQ & (s50 > s200) & (s50.shift(1) <= s200.shift(1)), r63),
 'Strongest sectors: top-3 sectors by 3-month return, stock newly in its top 30 by 3-month gain':
    (fresh(in_top_sec & rank_in(r63, 60) & (C > s50)), r63),
 'Gap up 3%+ on 2x volume that holds into the close, above 200-day':
    (LIQ & (C > s200) & (O > H.shift(1) * 1.03) & (C > O) & (V > 2 * vol50), V / vol50),
 'Delivery-backed rise: delivery % 1.5x normal, up 3%+, in an uptrend':
    (up_tr & (DV > 1.5 * DV.rolling(20, min_periods=10).mean()) & (C.pct_change(fill_method=None) > .03), DV),
}

def sim(entry, prio, target=None, stop=.08, days=20, maxpos=5, lo=START, hi=None, log=None, state=None, atrstop=None):
    hi = hi or n - 1
    Ev = entry.reindex(index=dates, columns=C.columns).fillna(False).values
    Pv = prio.reindex(index=dates, columns=C.columns).values
    ATv = atr.values
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
                sp = stop if not atrstop else min(.15, max(.03, atrstop * ATv[i - 1, j] / o)) if np.isfinite(ATv[i - 1, j]) else stop
                tg = target if not (atrstop and target) else sp * target   # with ATR stops, target is a multiple of the stop
                pos[j] = dict(e=o, sh=val / (o * (1 + COST)), bi=i, stop=o * (1 - sp), tgt=o * (1 + (tg or 9)))
        for j, p in pos.items():
            if np.isfinite(Cv[i, j]): p['lc'] = Cv[i, j]
        eqv = cash + sum(p['sh'] * p.get('lc', p['e']) for j, p in pos.items())
        eq.append(eqv)
        for j, p in pos.items():
            if days and i - p['bi'] + 1 >= days: p['sell_open'] = True
        pend = []
        sg = np.nonzero(Ev[i])[0]
        if len(sg):
            sg = sg[np.argsort(-np.nan_to_num(Pv[i, sg], nan=-1e9))]
            pend = [j for j in sg if j not in pos]
    if state is not None: state.update(pos=pos, pend=pend)
    return pd.Series(eq, index=dates[lo:hi + 1]), np.array(trades), why

def bench(lo, hi):
    e = (1 + bret.iloc[lo:hi + 1]).cumprod(); return stats(e, np.array([]))
bret = bench_r.fillna(0)
GRID = dict(target=[None, .08, .10, .15, .20], stop=[.05, .08, .10], days=[10, 20, 30], maxpos=[5, 10])

if __name__ == '__main__':
    bT, bS, bF = bench(START, MID - 1), bench(MID, n - 1), bench(START, n - 1)
    print(f"benchmark: train {bT['cagr']}% (dd {bT['dd']}), test {bS['cagr']}% (dd {bS['dd']}), full {bF['cagr']}%", flush=True)
    res = {}
    for name, (en, pr) in IDEAS.items():
        cnt = int(en.iloc[START:].fillna(False).values.sum())
        best = None; rows = []
        for tg, sp, dy, mp in itertools.product(*GRID.values()):
            e, tr, why = sim(en, pr, tg, sp, dy, mp, hi=MID - 1)
            s = stats(e, tr); rows.append((s['sharpe'], s['cagr'], s['dd'], tg, sp, dy, mp))
        rows.sort(key=lambda r: (-r[0], -r[1]))
        sh, cg, dd_, tg, sp, dy, mp = rows[0]
        e, tr, why = sim(en, pr, tg, sp, dy, mp, lo=MID); st = stats(e, tr)
        w = pd.Series(why).value_counts(normalize=True).mul(100).round(0).to_dict() if why else {}
        # how sensitive: median test result over the 10 best training settings
        top10 = []
        for r in rows[:10]:
            e2, _, _ = sim(en, pr, r[3], r[4], r[5], r[6], lo=MID); top10.append(stats(e2, np.array([]))['cagr'])
        res[name] = dict(signals=cnt, target=tg, stop=sp, days=dy, maxpos=mp, train=dict(cagr=cg, dd=dd_, sharpe=sh),
                         test=dict(cagr=st['cagr'], dd=st['dd'], sharpe=st['sharpe'], trades=st['trades'], win=st['win'], avg=st['avg'], why=w),
                         test_top10_median=float(np.median(top10)), test_top10_range=[min(top10), max(top10)])
        print(f"{name[:95]:95s} sig {cnt:6d} | pick T{tg} S{sp} D{dy} N{mp} | train {cg:6.1f}% dd {dd_:6.1f} sh {sh:4.2f} | "
              f"TEST {st['cagr']:6.1f}% dd {st['dd']:6.1f} sh {st['sharpe']:4.2f} n {st['trades']} win {st['win']} | top10 median {np.median(top10):.1f} [{min(top10)}..{max(top10)}]", flush=True)
    json.dump(dict(built=pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%MZ'), train=[str(dates[START].date()), str(dates[MID - 1].date())],
                   test=[str(dates[MID].date()), str(dates[-1].date())], bench=dict(train=bT, test=bS, full=bF), grid=GRID, ideas=res),
              open(f'{WD}/ideas_bt.json', 'w'), indent=1, default=float)
