#!/usr/bin/env python3
"""Nightly news headlines and company numbers for the top-ranked stocks.

Usage: python3 build/news_fund.py            (run from the repository root, after data.json is rebuilt)
Reads data.json and static.json, writes auto.json:
  news: latest Google News headlines per stock, with a tone judged from headline wording
  sc:   company numbers from Screener.in public pages (quarterly profit and sales vs a year earlier, P/E, ROE,
        ROCE, market cap, promoter/FII/DII holdings, latest exchange announcements); Yahoo Finance fills gaps
Anything that fails to download keeps its previous value (up to 60 days old). Never fails the build.
Each stock's news is then read from the facts: reported results, the company's own exchange announcements, shareholding
changes, and (weakly) headlines. If an ANTHROPIC_API_KEY secret is set, Claude reads the same facts instead.
Needs network access to news.google.com and Yahoo Finance; yfinance is optional.
"""
import json, os, re, sys, time, datetime as dt, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
NOW = dt.datetime.now(dt.timezone.utc)
LOG = dict(started=NOW.strftime('%Y-%m-%dT%H:%MZ'), news_ok=0, news_fail=0, fund_ok=0, fund_fail=0, errors=[])

def note(e):
    if len(LOG['errors']) < 40: LOG['errors'].append(str(e)[:1200])

# ---------- which stocks ----------
def pick_list(D, n_top=50):
    W = dict(fMom=35, tscore=20, fSeas=15, fSwing=5)
    rows = []
    for s in D['stocks']:
        if not (s.get('liq300') and s['close'] > s['s200']): continue
        rows.append((sum(W[k] * (s.get(k) if s.get(k) is not None else 50) for k in W) / sum(W.values()), s))
    rows.sort(key=lambda r: -r[0])
    out = {s['sym']: s for _, s in rows[:n_top]}
    for s in D['stocks']:
        if s.get('mrank') and s['mrank'] <= 30: out.setdefault(s['sym'], s)
    return list(out.values())

def short_name(name):
    n = re.sub(r'\b(Limited|Ltd\.?|India|Industries|Corporation|Company|Co\.?|The)\b', ' ', name, flags=re.I)
    n = re.sub(r'\s+', ' ', n).strip(' .,&')
    n = re.sub(r'\s+(of|and|&)$', '', n, flags=re.I)
    return n or name

# ---------- news ----------
POS = r"\b(rise[sn]?|rising|jumps?|jumped|surges?|surged|soars?|soared|gains?|gained|rall(y|ies|ied)|record|beats?|upgrades?d?|raises?d?|hikes?|strong|robust|bags?|wins?|won|order[s]? worth|expansion|approval|approves|profit (up|rises|jumps|surges|grows)|turns profitable|all-time high|52-week high|outperform|buy rating|target raised)\b"
NEG = r"\b(falls?|fell|drops?|dropped|slumps?|slumped|plunges?|plunged|declines?|declined|slips?|slipped|tumbles?|tumbled|crash(es|ed)?|sinks?|sank|loss(es)?|misses|missed|downgrades?d?|cuts?|weak|probe|raid|penalty|fine[ds]?|resigns?|resignation|fraud|default|lower circuit|52-week low|sell rating|target cut|block deal|stake sale|pledge|tax demand|show cause|warning)\b"

def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (screener-bot)'})
    with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()

def parse_rss(xml_bytes, must):
    items = []
    root = ET.fromstring(xml_bytes)
    for it in root.iter('item'):
        title = (it.findtext('title') or '').strip(); link = (it.findtext('link') or '').strip()
        src_el = it.find('source'); src = (src_el.text or '').strip() if src_el is not None else ''
        try: when = parsedate_to_datetime(it.findtext('pubDate'))
        except Exception: continue
        if src and title.endswith(' - ' + src): title = title[:-(len(src) + 3)]
        if (NOW - when).days > 30: continue
        if must and not re.search(must, title, re.I): continue
        items.append(dict(t=title, src=src, url=link, when=when))
    items.sort(key=lambda x: x['when'], reverse=True)
    seen, out = set(), []
    for x in items:
        k = re.sub(r'\W+', '', x['t'].lower())[:60]
        if k in seen: continue
        seen.add(k); out.append(x)
    return out[:8]

def tone(items):
    p = sum(1 for x in items if re.search(POS, x['t'], re.I))
    n = sum(1 for x in items if re.search(NEG, x['t'], re.I))
    if not items: return 'Nothing found'
    if p and n and abs(p - n) <= 1: return 'Mixed'
    if p > n: return 'Positive'
    if n > p: return 'Negative'
    return 'Neutral'

def news_for(s):
    nm = short_name(s['name'])
    first = re.escape(nm.split()[0]) if nm.split() else re.escape(s['sym'])
    q = f'("{nm}" OR "{s["sym"]}") (share OR stock OR shares OR results OR profit) when:30d'
    url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode(dict(q=q, hl='en-IN', gl='IN', ceid='IN:en'))
    items = parse_rss(fetch(url), rf'{first}|\b{re.escape(s["sym"])}\b')
    d = lambda w: w.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime('%d %b %Y').lstrip('0')
    if not items:
        return dict(tone='Nothing found', date=d(NOW), text='No company-specific headlines in the last 30 days.', src='', url='', items=[], auto=True)
    top = items[0]
    return dict(tone=tone(items), date=d(top['when']), text=top['t'], src=top['src'], url=top['url'], auto=True,
                items=[dict(t=x['t'], src=x['src'], url=x['url'], date=d(x['when'])) for x in items])

# ---------- company numbers: Screener.in (public company pages, no login) ----------
def _txt(h):
    import html as _h
    h = _h.unescape(re.sub(r'<[^>]+>', ' ', h))
    return re.sub(r'\s+', ' ', h).strip(' +')

def _num(t):
    t = t.replace(',', '').replace('%', '').replace('₹', '').replace('Cr.', '').strip()
    try: return float(t)
    except Exception: return None

def _section(html, sid):
    m = re.search(r'<section[^>]*id="%s"[^>]*>(.*?)</section>' % sid, html, re.S)
    return m.group(1) if m else ''

def _table(sec):
    m = re.search(r'<table[^>]*>(.*?)</table>', sec, re.S)
    if not m: return [], {}
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', m.group(1), re.S)
    head, body = [], {}
    for r in rows:
        cells = [_txt(c) for c in re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', r, re.S)]
        if not cells: continue
        if not head and re.search(r'<th', r): head = cells[1:]; continue
        body[cells[0]] = cells[1:]
    return head, body

def _ratio(html, name):
    m = re.search(r'<span class="name">\s*%s\s*</span>(.*?)</li>' % re.escape(name), html, re.S)
    if not m: return None
    nums = re.findall(r'<span class="number">([^<]*)</span>', m.group(1))
    return _num(nums[0]) if nums else None

def screener_for(sym):
    out = {}
    for path in ('consolidated/', ''):
        if path == '': time.sleep(5)
        html = fetch(f'https://www.screener.in/company/{urllib.parse.quote(sym)}/{path}', timeout=25).decode('utf-8', 'replace')
        head, body = _table(_section(html, 'quarters'))
        npr = next((body[k] for k in body if k.lower().startswith('net profit')), None)
        rev = next((body[k] for k in body if k.lower().split()[0] in ('sales', 'revenue')), None) if body else None
        if head and npr:
            break
    out.update(mcap=_ratio(html, 'Market Cap'), pe=_ratio(html, 'Stock P/E'), roce=_ratio(html, 'ROCE'), roe=_ratio(html, 'ROE'))
    if head and npr:
        last = head[-1]
        try:
            mon, yr = last.split()[0], int(last.split()[1])
            prev = f'{mon} {yr - 1}'
            if prev in head:
                i0, i1 = len(head) - 1, head.index(prev)
                v = dict(np=_num(npr[i0]), npYoY=_num(npr[i1]))
                if rev: v.update(sales=_num(rev[i0]), salesYoY=_num(rev[i1]))
                if v['np'] is not None and v['npYoY'] is not None:
                    out.update(v); out['q'] = last
        except Exception as e:
            note(f'screener quarters {sym}: {e}')
    sh_head, sh = _table(_section(html, 'shareholding'))
    for lab, key in (('Promoters', 'prom'), ('FIIs', 'fii'), ('DIIs', 'dii')):
        row = next((sh[k] for k in sh if k.startswith(lab)), None)
        if row and len(row) >= 2 and _num(row[-1]) is not None and _num(row[-2]) is not None:
            out[key] = [_num(row[-2]), _num(row[-1])]
    fil = []
    docs = _section(html, 'documents')
    m = re.search(r'Announcements.*?<ul[^>]*>(.*?)</ul>', docs, re.S)
    if m:
        for a in re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', m.group(1), re.S)[:4]:
            inner = a[1]
            sub = re.search(r'<div[^>]*>(.*?)</div>', inner, re.S)
            title = _txt(re.sub(r'<div[^>]*>.*?</div>', '', inner, flags=re.S))
            detail = _txt(sub.group(1)) if sub else ''
            if title: fil.append(dict(t=title[:160], d=detail[:220], url=a[0] if a[0].startswith('http') else 'https://www.screener.in' + a[0]))
    if fil: out['filings'] = fil
    out = {k: v for k, v in out.items() if v is not None}
    if out: out['src'] = 'Screener.in'
    return out

# ---------- company numbers ----------
def fund_for(sym):
    import yfinance as yf
    t = yf.Ticker(sym + '.NS')
    info = t.info or {}
    cr = lambda v: None if v is None else round(float(v) / 1e7, 1)
    out = dict(mcap=cr(info.get('marketCap')), pe=info.get('trailingPE'),
               roe=None if info.get('returnOnEquity') is None else round(info['returnOnEquity'] * 100, 1),
               de=None if info.get('debtToEquity') is None else round(info['debtToEquity'] / 100, 2), src='Yahoo Finance')
    if out['pe'] is not None: out['pe'] = round(float(out['pe']), 1)
    q = t.quarterly_income_stmt
    if q is not None and not q.empty:
        cols = sorted(q.columns, reverse=True)
        def row(*names):
            for n in names:
                if n in q.index: return q.loc[n]
        ni = row('Net Income', 'Net Income Common Stockholders', 'Net Income From Continuing Operation Net Minority Interest')
        rv = row('Total Revenue', 'Operating Revenue')
        c0 = cols[0]
        yago = [c for c in cols[1:] if 330 <= (c0 - c).days <= 400]
        if ni is not None and rv is not None and yago:
            c1 = yago[0]
            vals = [ni.get(c0), ni.get(c1), rv.get(c0), rv.get(c1)]
            if all(v is not None and v == v for v in vals):
                out.update(q=c0.strftime('%b %Y'), np=cr(vals[0]), npYoY=cr(vals[1]), sales=cr(vals[2]), salesYoY=cr(vals[3]))
    return {k: v for k, v in out.items() if v is not None}

# ---------- reading the news: facts first ----------
ROUTINE = re.compile(r"newspaper|trading window|investor meet|analyst\s*/?\s*investor|analysts? meet|con(ference)? call|earnings call|transcript|audio recording|"
                     r"certificate under|regulation 74|loss of share|duplicate share|book closure|record date|compliance certificate|"
                     r"intimation of (board )?meeting|board meeting intimation|change in (rta|registrar)|esop|esos|allotment of .*options|"
                     r"postal ballot|scrutinizer|voting results|closure of|presentation|sustainability|brsr|interest rates? update|"
                     r"appoint\w* .{0,40}(assistant|associate|senior manager|manager|\bvp\b|vice president|company secretary)|"
                     r"superannuat|retire(s|d|ment)\b|credit rating.{0,40}reaffirm|reaffirm|press release.{0,20}results|disclosure under regulation 30.{0,20}$", re.I)
POSF = re.compile(r"\border\b|orders worth|contract|award|letter of (intent|acceptance)|acqui|buy-?back|bonus|stock split|sub-?division|"
                  r"dividend|upgrade|approval|approves|commission(ed|ing)|capacity|expansion|launch|partnership|joint venture|wins?\b|bags?\b", re.I)
NEGF = re.compile(r"penalt|fine[ds]?\b|show cause|sebi order|adjudicat|resign|auditor|default|fraud|search|raid|downgrade|pledge|invocation|"
                  r"litigation|tax demand|demand order|strike|fire\b|shutdown|recall|warning letter|import alert|form 483|observations|"
                  r"insolvency|nclt|suspension|qualified opinion|reduc(ed|tion) in (stake|holding)", re.I)

def _clean_detail(d):
    import html as _h
    d = _h.unescape(d or '')
    return re.sub(r'^\s*\d{1,2}\s+[A-Za-z]{3}\s*-\s*', '', d or '').strip()

def read_facts(stock, n, f):
    """Deterministic reading of the collected facts. Returns tone, 2-3 sentence summary, main risk."""
    score, pos, neg, parts = 0, [], [], []
    np_, npy, sl, sly = f.get('np'), f.get('npYoY'), f.get('sales'), f.get('salesYoY')
    if np_ is not None and npy is not None:
        q = f.get('q', 'latest quarter')
        if npy > 0 and np_ > 0:
            g = (np_ / npy - 1) * 100
            txt = f"In the {q} quarter, profit was Rs {np_:,.0f} crore, {'up' if g >= 0 else 'down'} {abs(g):.0f}% on a year earlier"
            score += 2 if g > 15 else 1 if g > 0 else -2 if g < -15 else -1
            (pos if g > 0 else neg).append(f"profit {'up' if g >= 0 else 'down'} {abs(g):.0f}%")
        elif npy <= 0 < np_:
            txt = f"In the {q} quarter, it made a profit of Rs {np_:,.0f} crore against a loss a year earlier"; score += 2; pos.append('back to profit')
        elif np_ <= 0:
            txt = f"In the {q} quarter, it made a loss of Rs {abs(np_):,.0f} crore"; score -= 2; neg.append('quarterly loss')
        else:
            txt = ''
        if txt and sl and sly and sly > 0:
            sg = (sl / sly - 1) * 100
            txt += f", on sales {'up' if sg >= 0 else 'down'} {abs(sg):.0f}%"
            score += 1 if sg > 10 else -1 if sg < 0 else 0
        if txt: parts.append(txt + '.')
    own = []
    p_, fi = f.get('prom'), f.get('fii')
    if isinstance(p_, list) and abs(p_[1] - p_[0]) >= 0.5:
        own.append(f"promoters {'raised' if p_[1] > p_[0] else 'cut'} their stake from {p_[0]}% to {p_[1]}%")
        if p_[1] < p_[0]: score -= 1; neg.append(f'promoters cut their stake to {p_[1]}%')
        else: score += 1
    if isinstance(fi, list) and abs(fi[1] - fi[0]) >= 1:
        own.append(f"foreign investors {'raised' if fi[1] > fi[0] else 'cut'} {'theirs' if own else 'their stake'} from {fi[0]}% to {fi[1]}%")
        if fi[1] > fi[0]: score += 1
        else: score -= 1; neg.append(f'foreign investors cut their stake from {fi[0]}% to {fi[1]}%')
    if own: parts.append((own[0][0].upper() + own[0][1:] + (', and ' + own[1] if len(own) > 1 else '')) + ' last quarter.')
    key = []
    for x in (f.get('filings') or []):
        import html as _h
        t, d = _h.unescape(x.get('t', '')), _clean_detail(x.get('d', ''))
        blob = f'{t} {d}'
        if (ROUTINE.search(t) or ROUTINE.search(d)) and not NEGF.search(blob): continue
        if re.search(r'financial results|results for the quarter', blob, re.I) and np_ is not None: continue
        isneg, ispos = bool(NEGF.search(blob)), bool(POSF.search(blob))
        if re.search(r'set aside|quash|dropp(ed|ing)|favou?rable|in (its|our) favou?r|withdrawn|succeed|dismiss(ed|al) of the (demand|notice)|no (material )?impact|not material', blob, re.I):
            isneg, ispos = False, True
        if re.search(r'promoter', blob, re.I) and re.search(r'\bsale|sold|sell', blob, re.I): isneg, ispos = True, False
        if isneg: score -= 2; neg.append(d or t)
        elif ispos: score += 1; pos.append(d or t)
        key.append(d or t)
        if len(key) >= 2: break
    if key: parts.append('Latest filing: ' + key[0].rstrip('.') + '.' + (' Also: ' + key[1].rstrip('.') + '.' if len(key) > 1 else ''))
    if np_ is None and not key:   # headlines only count when there is nothing firmer
        ht = tone(n.get('items') or [])
        if ht == 'Positive': score += 1
        elif ht == 'Negative': score -= 1
    if not parts:
        items = n.get('items') or []
        if items: parts.append(f"No new results or significant filings on record. Latest headline: {items[0]['t']} ({items[0].get('src','')}, {items[0].get('date','')}).")
        else: parts.append('No new results, significant filings or company-specific headlines in the last 30 days.')
    strong_neg = any(NEGF.search(x) for x in neg)
    tone_ = 'Positive' if score >= 2 and not strong_neg else 'Negative' if score <= -2 else 'Mixed' if (pos and neg) else 'Neutral'
    watch = neg[0] if neg else ''
    watch = watch[0].upper() + watch[1:] if watch else ''
    return dict(tone=tone_, summary=' '.join(parts[:3]), watch=watch)

# Optional: a real AI model reads the same facts if an Anthropic API key is set as the ANTHROPIC_API_KEY secret.
SYSTEM = (
 "You are a careful equity research assistant for Indian (NSE) stocks. You are given facts collected today: the latest quarterly "
 "results, the company's own stock-exchange announcements (with one-line summaries), shareholding changes and recent headlines. "
 "Using ONLY these facts, say what the recent news means for a shareholder. Never invent numbers, events or dates; prefer "
 "announcements and reported results over headlines; ignore generic market-wrap headlines and routine filings. Reply with JSON only: "
 "{\"tone\": \"Positive\"|\"Mixed\"|\"Negative\"|\"Neutral\", \"summary\": \"2-3 plain-English sentences with the key facts and numbers\", "
 "\"watch\": \"one short risk a shareholder should know, or empty string\"}.")

def facts_for(stock, n, f):
    lines = [f"Company: {stock['name']} (NSE: {stock['sym']}), sector {stock['sector']}. Today: {NOW.strftime('%d %b %Y')}."]
    if f.get('np') is not None and f.get('npYoY') is not None:
        r = f"Results for quarter ending {f.get('q','?')}: net profit Rs {f['np']} cr vs Rs {f['npYoY']} cr a year earlier"
        if f.get('sales') is not None and f.get('salesYoY') is not None: r += f"; sales Rs {f['sales']} cr vs Rs {f['salesYoY']} cr"
        lines.append(r + '.')
    for k, lab in (('prom', 'Promoter'), ('fii', 'FII'), ('dii', 'DII')):
        if isinstance(f.get(k), list): lines.append(f"{lab} holding: {f[k][0]}% previous quarter -> {f[k][1]}% latest.")
    for x in (f.get('filings') or [])[:5]: lines.append(f"Exchange announcement: {x['t']}. {x.get('d','')}")
    for x in (n.get('items') or [])[:8]: lines.append(f"Headline ({x.get('src','')}, {x.get('date','')}): {x['t']}")
    return '\n'.join(lines)

def _parse_reply(content):
    c = re.sub(r'^```(?:json)?\s*|\s*```$', '', (content or '').strip())
    m = re.search(r'\{.*\}', c, re.S)
    return json.loads(m.group(0) if m else c)

def claude_read(text, key):
    body = json.dumps(dict(model=os.environ.get('CLAUDE_MODEL', 'claude-haiku-5-5'), max_tokens=400, temperature=0.1, system=SYSTEM,
                           messages=[dict(role='user', content=text)])).encode()
    req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=body, method='POST',
                                 headers={'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r: res = json.loads(r.read())
    out = _parse_reply(''.join(b.get('text', '') for b in res.get('content', [])))
    if out.get('tone') not in ('Positive', 'Mixed', 'Negative', 'Neutral') or not out.get('summary'): raise ValueError(f'bad reply {out}')
    return out, res.get('model', 'claude')

def main():
    D = json.load(open(os.path.join(ROOT, 'data.json')))
    ap = os.path.join(ROOT, 'auto.json')
    try: OLD = json.load(open(ap))
    except Exception: OLD = {}
    news, sc = {}, {}
    def fresh(e):
        try: return (NOW.date() - dt.datetime.strptime(e.get('fetched', ''), '%Y-%m-%d').date()).days <= 60
        except Exception: return False
    for k, v in (OLD.get('news') or {}).items():
        if fresh(v): news[k] = v
    for k, v in (OLD.get('sc') or {}).items():
        if fresh(v): sc[k] = v
    picks = pick_list(D)
    LOG['stocks'] = len(picks)
    for s in picks:
        try:
            n = news_for(s); n['fetched'] = NOW.strftime('%Y-%m-%d'); news[s['sym']] = n; LOG['news_ok'] += 1
        except Exception as e:
            LOG['news_fail'] += 1; note(f"news {s['sym']}: {e}")
        time.sleep(1.2)
    try:
        import yfinance  # noqa: F401
        have_yf = True
    except Exception as e:
        have_yf = False; note(f'yfinance not installed: {e}')
    LOG['screener_ok'] = LOG['screener_fail'] = LOG['screener_kept'] = 0
    def age_days(e):
        try: return (NOW.date() - dt.datetime.strptime(e.get('fetched', ''), '%Y-%m-%d').date()).days
        except Exception: return 999
    # Oldest (or missing) Screener numbers first; at most SCREENER_MAX pages a night, a few seconds apart.
    SCREENER_MAX, budget, blocked = 30, 30, False
    order = sorted(picks, key=lambda s: -(age_days(sc[s['sym']]) if sc.get(s['sym'], {}).get('src') == 'Screener.in' else 999))
    for s in order:
        prev = sc.get(s['sym'])
        have_recent = prev is not None and prev.get('src') == 'Screener.in' and age_days(prev) <= 6
        f = {}
        if (budget <= 0 or blocked) and prev is not None and prev.get('src') == 'Screener.in':
            LOG['screener_kept'] += 1; continue
        if have_recent:
            LOG['screener_kept'] += 1; continue
        if budget > 0 and not blocked:
            budget -= 1
            for attempt in (1, 2):
                try:
                    f = screener_for(s['sym'])
                    if f.get('np') is not None or f.get('pe') is not None: LOG['screener_ok'] += 1
                    else: LOG['screener_fail'] += 1; note(f"screener {s['sym']}: no numbers parsed")
                    break
                except Exception as e:
                    if '429' in str(e) and attempt == 1:
                        time.sleep(90); continue
                    LOG['screener_fail'] += 1; note(f"screener {s['sym']}: {e}")
                    if '429' in str(e): blocked = True
                    break
            time.sleep(5)
        if not f and prev is not None and prev.get('src') == 'Screener.in':
            LOG['screener_kept'] += 1; continue
        if have_yf:
            try:
                y = fund_for(s['sym'])
                for k, v in y.items():
                    if k == 'src': continue
                    if k in ('q', 'np', 'npYoY', 'sales', 'salesYoY'):
                        if f.get('np') is None and y.get('np') is not None: f[k] = v
                    elif f.get(k) is None: f[k] = v
                if not f.get('src') and len(y) > 1: f['src'] = 'Yahoo Finance'
            except Exception as e:
                note(f"yahoo {s['sym']}: {e}")
            time.sleep(0.8)
        if len(f) > 1:
            f['fetched'] = NOW.strftime('%Y-%m-%d'); sc[s['sym']] = f; LOG['fund_ok'] += 1
        else:
            LOG['fund_fail'] += 1
    key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    LOG['read_rules'] = LOG['read_ai'] = LOG['read_ai_kept'] = LOG['read_ai_fail'] = 0
    import hashlib
    for s in picks:
        sym = s['sym']; n = news.get(sym)
        if not n: continue
        f = sc.get(sym, {})
        r = read_facts(s, n, f)
        n.update(tone=r['tone'], text=r['summary'], watch=r['watch'], read='rules'); n.pop('ai', None); n.pop('model', None)
        LOG['read_rules'] += 1
        if not key: continue
        text = facts_for(s, n, f); h = hashlib.sha1(text.split('\n', 1)[-1].encode()).hexdigest()[:12]
        old = (OLD.get('news') or {}).get(sym, {})
        if old.get('read') == 'ai' and old.get('ihash') == h:
            for k in ('tone', 'text', 'watch', 'model'): n[k] = old.get(k, n.get(k))
            n.update(read='ai', ihash=h); LOG['read_ai_kept'] += 1; continue
        try:
            out, model = claude_read(text, key)
            n.update(tone=out['tone'], text=out['summary'].strip(), watch=(out.get('watch') or '').strip(), read='ai', ihash=h, model=model)
            LOG['read_ai'] += 1
        except Exception as e:
            LOG['read_ai_fail'] += 1; note(f'ai {sym}: {e}')
            if LOG['read_ai_fail'] >= 3 and LOG['read_ai'] == 0: key = ''
        time.sleep(1)
    LOG['finished'] = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    out = dict(asof=NOW.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime('%d %b %Y').lstrip('0'), news=news, sc=sc, log=LOG)
    json.dump(out, open(ap, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(json.dumps({k: v for k, v in LOG.items() if k != 'errors'}), 'errors:', LOG['errors'][:5])

if __name__ == '__main__':
    try: main()
    except Exception as e:
        print('news_fund failed:', e); sys.exit(0)
