#!/usr/bin/env python3
"""Red flags for the stocks the home page can rank near the top. Writes flags.json. Run nightly after news_fund.py.

Stocks with any of these are removed from the top 10 (they stay in the full table, marked):
- on NSE's GSM surveillance list, or in a price band of 5% or less (they can get stuck at the band and be hard to sell);
- a net loss in the latest quarter (from the company numbers read nightly);
- more than 25% of promoter shares pledged.
Warnings (shown, not removed):
- on NSE's ASM list (triggered by big price moves, so common among momentum leaders: no leverage, sharp swings);
- quarterly results due within 7 days (prices often jump either way on results);
- promoters cut their stake by 2 percentage points or more last quarter;
- 10-25% of promoter shares pledged.
(High valuation is already flagged on the page.)
Every source is optional: if NSE blocks a request the other checks still run, and flags.json records what was checked.
"""
import os, sys, json, re, time, io, csv, datetime as dt, urllib.request, http.cookiejar
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from news_fund import pick_list

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
IST = dt.timezone(dt.timedelta(hours=5, minutes=30)); TODAY = dt.datetime.now(IST).date()
LOG = dict(checked={}, errors=[])
def note(e):
    if len(LOG['errors']) < 30: LOG['errors'].append(str(e)[:400])

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
jar = http.cookiejar.CookieJar(); OP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def get(url, ref='https://www.nseindia.com/', timeout=25):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.9', 'Referer': ref})
    with OP.open(req, timeout=timeout) as r: return r.read()

def bands():
    out = {}
    for host in ('https://nsearchives.nseindia.com/', 'https://archives.nseindia.com/'):
        try:
            t = get(host + 'content/equities/sec_list.csv').decode('utf-8', 'replace')
            for r in csv.DictReader(io.StringIO(t)):
                r = {k.strip().lower(): (v or '').strip() for k, v in r.items() if k}
                if r.get('series') != 'EQ': continue
                b = re.sub(r'[^0-9.]', '', r.get('band', ''))
                if b: out[r.get('symbol')] = float(b)
            if out: return out
        except Exception as e: note(f'price bands {host}: {e}')
    return out

def nse_api(path):
    return json.loads(get('https://www.nseindia.com/api/' + path).decode('utf-8', 'replace'))

def surveillance():
    syms = {}
    for path, lab in (('reportASM', 'ASM'), ('reportGSM', 'GSM')):
        try:
            d = nse_api(path)
            def walk(x):
                if isinstance(x, dict):
                    s = x.get('symbol') or x.get('Symbol')
                    if isinstance(s, str) and s.strip(): syms.setdefault(s.strip(), set()).add(lab)
                    for v in x.values(): walk(v)
                elif isinstance(x, list):
                    for v in x: walk(v)
            walk(d); LOG['checked'][lab] = True
        except Exception as e: note(f'{lab}: {e}'); LOG['checked'][lab] = False
    return {k: sorted(v) for k, v in syms.items()}

def results_calendar():
    out = {}
    try:
        d = nse_api('event-calendar')
        rows = d if isinstance(d, list) else d.get('data', [])
        for r in rows:
            p = str(r.get('purpose', '')) + ' ' + str(r.get('bm_desc', ''))
            if not re.search(r'result', p, re.I): continue
            try: day = dt.datetime.strptime(str(r.get('date', '')).strip(), '%d-%b-%Y').date()
            except Exception: continue
            if day >= TODAY: out.setdefault(str(r.get('symbol', '')).strip(), day)
        LOG['checked']['results'] = True
    except Exception as e: note(f'event calendar: {e}'); LOG['checked']['results'] = False
    return out

def pledge(sym):
    d = nse_api(f'corporate-pledgedata?index=equities&symbol={urllib.parse.quote(sym)}')
    rows = d.get('data') if isinstance(d, dict) else d
    if not rows: return None
    r = rows[0]
    for k, v in r.items():   # percent of promoter shares pledged
        kl = k.lower()
        if 'perc' in kl and 'pledg' in kl and ('promoter' in kl or 'prom' in kl or kl.endswith('pledged')):
            LOG.setdefault('pledge_field', k); LOG.setdefault('pledge_sample', {kk: r[kk] for kk in list(r)[:16]})
            try: return float(str(v).replace(',', ''))
            except Exception: pass
    LOG.setdefault('pledge_keys', list(r.keys())[:30])
    return None

def main():
    import urllib.parse  # noqa: F401
    D = json.load(open(os.path.join(ROOT, 'data.json')))
    try: A = json.load(open(os.path.join(ROOT, 'auto.json')))
    except Exception: A = {}
    SC = A.get('sc') or {}
    cand = [s['sym'] for s in pick_list(D, n_top=60)]
    try: get('https://www.nseindia.com/')  # sets the cookies the API needs
    except Exception as e: note(f'nse home: {e}')
    BAND = bands(); LOG['checked']['bands'] = bool(BAND)
    SURV = surveillance(); RES = results_calendar()
    PL = {}; okp = 0
    for i, sym in enumerate(cand):
        try:
            v = pledge(sym); okp += 1
            if v is not None: PL[sym] = v
        except Exception as e:
            note(f'pledge {sym}: {e}')
            if i >= 4 and okp == 0: break
        time.sleep(0.7)
    LOG['checked']['pledge'] = okp > 0
    flags = {}
    for s in D['stocks']:
        sym = s['sym']; ex, wn = [], []
        sv = SURV.get(sym, [])
        if 'GSM' in sv: ex.append('On NSE\'s GSM surveillance list (graded measures for suspicious price moves)')
        if 'ASM' in sv: wn.append('On NSE\'s ASM list after big price moves: buy with full cash (no leverage) and expect sharp swings')
        b = BAND.get(sym)
        if b is not None and b <= 5: ex.append(f'Price band of {b:g}%: it can get stuck at the limit and be hard to sell')
        f = SC.get(sym) or {}
        if f.get('np') is not None and f['np'] < 0: ex.append(f"Made a loss last quarter ({f.get('q', 'latest')}: ₹{f['np']:,.0f} cr)")
        p = PL.get(sym)
        if p is not None and p > 25: ex.append(f'{p:.0f}% of promoter shares are pledged')
        elif p is not None and p >= 10: wn.append(f'{p:.0f}% of promoter shares are pledged')
        rd = RES.get(sym)
        if rd is not None and (rd - TODAY).days <= 7: wn.append(f"Results due on {rd:%d %b}: the price often jumps either way")
        pr = f.get('prom')
        if isinstance(pr, list) and len(pr) == 2 and None not in pr and pr[0] - pr[1] >= 2: wn.append(f'Promoters cut their stake from {pr[0]:g}% to {pr[1]:g}% last quarter')
        if ex or wn: flags[sym] = dict(ex=ex, warn=wn)
    out = dict(asof=f'{TODAY:%d %b %Y}', checked=LOG['checked'], counts=dict(bands=len(BAND), surveillance=len(SURV), results=len(RES), pledge=len(PL), candidates=len(cand)),
               flags=flags, errors=LOG['errors'][:10], pledge_keys=LOG.get('pledge_keys'), pledge_field=LOG.get('pledge_field'), pledge_sample=LOG.get('pledge_sample'))
    json.dump(out, open(os.path.join(ROOT, 'flags.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    print(json.dumps({k: v for k, v in out.items() if k != 'flags'}, ensure_ascii=False))
    print('excluded:', {k: v['ex'] for k, v in flags.items() if v['ex'] and k in cand})

if __name__ == '__main__':
    import urllib.parse
    try: main()
    except Exception as e:
        print('redflags failed:', e); sys.exit(0)
