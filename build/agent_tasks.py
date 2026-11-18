#!/usr/bin/env python3
"""Helper for the weekly news and results update.

  python3 build/agent_tasks.py todo           Lists the stocks whose news should be checked this week, as JSON.
  python3 build/agent_tasks.py apply FILE     Merges researched notes from FILE into static.json.

FILE format:
{"news": {"SYMBOL": {"tone": "Positive|Mixed|Negative|Nothing found", "date": "18 Nov 2026",
                     "text": "two or three plain sentences", "src": "Site name", "url": "https://..."}},
 "results": {"SYMBOL": {"q": "Sep 2026", "np": 56.2, "npYoY": 24.1, "sales": 187.9, "salesYoY": 84.4}}}
Amounts in rupees crore, consolidated where available. "results" is optional; it may also carry
"pe", "roe", "roce" (percent), "de" (debt to equity) and "mcap" (rupees crore) when a source states them.
"""
import sys, os, json, datetime as dt
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
D = json.load(open(os.path.join(ROOT, 'data.json')))
SP = os.path.join(ROOT, 'static.json')
ST = json.load(open(SP))
TODAY = dt.date.today()

def age(d):
    try: return (TODAY - dt.datetime.strptime(d, '%d %b %Y').date()).days
    except Exception: return None

def todo():
    W = dict(fMom=35, tscore=20, fSeas=15, fSwing=5)
    rows = []
    for s in D['stocks']:
        if not (s.get('liq300') and s['close'] > s['s200']): continue
        num = sum(W[k] * (s.get(k) if s.get(k) is not None else 50) for k in W)
        rows.append((num / sum(W.values()), s))
    rows.sort(key=lambda r: -r[0])
    pick = {s['sym']: s for _, s in rows[:30]}
    for s in D['stocks']:
        if s.get('mrank') and s['mrank'] <= 30: pick.setdefault(s['sym'], s)
    out = []
    for sym, s in pick.items():
        n = ST.get('news', {}).get(sym); r = ST.get('sc', {}).get(sym)
        a = age(n['date']) if n else None
        out.append(dict(sym=sym, name=s['name'], sector=s['sector'], momentumRank=s.get('mrank'),
                        newsDate=n['date'] if n else None, newsAgeDays=a,
                        needsNews=(n is None or a is None or a > 13),
                        resultsQuarter=r.get('q') if r else None))
    out.sort(key=lambda x: (not x['needsNews'], x['sym']))
    print(json.dumps(dict(asof=D['asof'], count=len(out), needNews=sum(x['needsNews'] for x in out), stocks=out), indent=1, ensure_ascii=False))

def apply(fn):
    new = json.load(open(fn))
    syms = {s['sym'] for s in D['stocks']}
    tones = {'Positive', 'Mixed', 'Negative', 'Nothing found'}
    nn = nr = 0
    for sym, n in (new.get('news') or {}).items():
        sym = sym.strip().upper()
        if sym not in syms: print('skip news, unknown symbol', sym); continue
        if n.get('tone') not in tones or not n.get('text') or age(n.get('date', '')) is None:
            print('skip news, bad entry', sym, n); continue
        if n.get('url') and not str(n['url']).startswith('http'): n['url'] = ''
        ST.setdefault('news', {})[sym] = dict(tone=n['tone'], date=n['date'], text=n['text'].strip(), src=n.get('src', ''), url=n.get('url', ''))
        nn += 1
    for sym, r in (new.get('results') or {}).items():
        sym = sym.strip().upper()
        if sym not in syms: print('skip results, unknown symbol', sym); continue
        vals = {k: r.get(k) for k in ('np', 'npYoY', 'sales', 'salesYoY')}
        if not all(isinstance(v, (int, float)) for v in vals.values()) or not r.get('q'):
            print('skip results, incomplete', sym, r); continue
        e = ST.setdefault('sc', {}).setdefault(sym, {})
        e.update({k: round(float(v), 1) for k, v in vals.items()}); e['q'] = r['q']
        for k in ('pe', 'roe', 'roce', 'de', 'mcap'):
            if isinstance(r.get(k), (int, float)): e[k] = round(float(r[k]), 2)
        nr += 1
    ST['newsAsof'] = TODAY.strftime('%d %b %Y').lstrip('0')
    json.dump(ST, open(SP, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(json.dumps(dict(newsUpdated=nn, resultsUpdated=nr, newsAsof=ST['newsAsof'])))

if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'todo': todo()
    elif len(sys.argv) >= 3 and sys.argv[1] == 'apply': apply(sys.argv[2])
    else: print(__doc__)
