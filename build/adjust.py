"""Split and bonus adjustment for NSE daily prices, shared by build.py and backtest_20y.py.

A one-day fall of more than 25% is either a corporate action (split, bonus, demerger) or a real crash. Price data
alone cannot always tell them apart: a 1:2 bonus (-33%) looks like a crash, and so does a real 30% fall. So:
  1. for stocks that trade at least Rs 2 crore a day, look the date up in Yahoo Finance's split history (which
     includes bonuses); a split there within 3 days -> adjust by its ratio, none -> a real fall, keep it;
     answers are kept in splits.json in the repository so each is fetched once;
  2. otherwise (small stocks, or Yahoo unavailable): a fall of 40%+ that fits a usual split or bonus ratio is
     treated as one; a 25-40% fall only if it matches a ratio almost exactly on normal trading; the exchange's
     adjusted previous close is used when it explains the gap; anything else is kept as a real fall.
"""
import os, json, datetime as dt, numpy as np, pandas as pd

STD = np.array([1.25, 4 / 3, 1.5, 5 / 3, 2, 2.5, 3, 4, 5, 6, 8, 10, 11, 20])
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CACHE = os.path.join(ROOT, os.environ.get('SPLITS_FILE', 'splits.json'))

def heuristic(x, q=np.nan, spike=np.nan):
    if not np.isfinite(x) or x >= 0.75: return 1.0
    j = STD[np.argmin(np.abs(1 / STD - x))]; y = x * j
    if x < 0.6 and 0.85 <= y <= 1.15: return float(j)
    if abs(y - 1) < 0.025 and not (np.isfinite(spike) and spike > 4): return float(j)
    if np.isfinite(q) and q > 1.03 and abs(x * q - 1) < 0.25: return float(q)
    return 1.0

_TRIED = {}
def _yahoo(sym, cache, need_after):
    c = cache.get(sym)
    if c and c.get('ok') and c.get('fetched', '') >= need_after: return c
    if sym in _TRIED: return _TRIED[sym]
    try:
        import yfinance as yf
        s = yf.Ticker(sym + '.NS').splits
        h = yf.Ticker(sym + '.NS').history(period='5d') if s is None or len(s) == 0 else None
        ok = (s is not None and len(s) > 0) or (h is not None and len(h) > 0)
        c = dict(ok=bool(ok), splits=[[str(pd.Timestamp(d).date()), float(r)] for d, r in (s.items() if s is not None else [])],
                 fetched=str(dt.date.today()))
    except Exception as e:
        c = dict(ok=False, splits=[], fetched=str(dt.date.today()), err=str(e)[:80])
    _TRIED[sym] = c
    if c['ok']: cache[sym] = c
    return c

def factors(a, use_yahoo=True, min_to_lacs=200, log=print):
    """a: long frame sorted by SYMBOL, DATE with columns SYMBOL, DATE, C, TO (Rs lakh) and optionally PC.
    Returns k (array): the split factor to apply on each row's date (1.0 = none)."""
    prevc = a.groupby('SYMBOL').C.shift()
    tom = a.groupby('SYMBOL').TO.transform(lambda s: s.shift(1).rolling(20, min_periods=5).median())
    x = (a.C / prevc).values
    q = (prevc / a.PC).values if 'PC' in a else np.full(len(a), np.nan)
    spike = (a.TO / tom).values
    k = np.ones(len(a))
    cand = np.nonzero(np.isfinite(x) & (x < 0.75))[0]
    cache = {}
    if use_yahoo:
        try: cache = json.load(open(CACHE))
        except Exception: cache = {}
    syms, dts, liq = a.SYMBOL.values, pd.to_datetime(a.DATE).values, tom.values
    n_y = n_h = 0
    for i in cand:
        decided = False
        if use_yahoo and np.isfinite(liq[i]) and liq[i] >= min_to_lacs:
            d = pd.Timestamp(dts[i])
            c = _yahoo(syms[i], cache, str((d + pd.Timedelta(days=3)).date()))
            if c.get('ok'):
                hit = [r for s_, r in c['splits'] if abs((pd.Timestamp(s_) - d).days) <= 3 and r > 1.05]
                k[i] = float(hit[0]) if hit else 1.0; decided = True; n_y += 1
        if not decided:
            k[i] = heuristic(x[i], q[i], spike[i]); n_h += 1
    if use_yahoo and cache:
        try: json.dump(cache, open(CACHE, 'w'), separators=(',', ':'), sort_keys=True)
        except Exception as e: log('could not save splits.json:', e)
    log(f'falls over 25%: {len(cand)}; decided with Yahoo split history: {n_y}; by price rules: {n_h}; adjusted: {int((k != 1).sum())}')
    return k
