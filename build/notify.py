#!/usr/bin/env python3
"""Nightly: record today's picks (history.json, for the live track record) and send an alert.

Run from the repository root after data.json and auto.json are rebuilt:  python3 build/notify.py
Alerts go out only if these repository secrets exist (Settings > Secrets and variables > Actions):
  TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID   (a bot made with @BotFather; the chat id of you or your group)
  NTFY_TOPIC                                (a private topic name you subscribe to in the free ntfy app)
Optional: SITE_URL (defaults to https://<owner>.github.io/<repo>/).
The ranking mirrors the page's default Momentum style: 12-month momentum (skipping the last month) divided by
volatility, ranked within the 300 most-traded stocks, minus 5 or 10 points for P/E above 100 or 200, or losses.
"""
import json, os, sys, datetime as dt, urllib.request, urllib.parse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
J = lambda n, d=None: (json.load(open(os.path.join(ROOT, n))) if os.path.exists(os.path.join(ROOT, n)) else d)
D, ST, AUTO = J('data.json'), J('static.json', {}), J('auto.json', {})
HP = os.path.join(ROOT, 'history.json')
H = J('history.json', {'days': [], 'bench': []})
H.setdefault('days', []); H.setdefault('bench', [])
MON = {m: i for i, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}

def qnum(q):
    try: m, y = q.split()[:2]; return int(y) * 100 + MON[m[:3]]
    except Exception: return 0

def company(sym):
    man = (D.get('sc') or {}).get(sym) or (ST.get('sc') or {}).get(sym)
    au = (AUTO.get('sc') or {}).get(sym)
    if au and (not man or man.get('np') is None or (au.get('q') and qnum(au['q']) >= qnum(man.get('q', ''))) or (not au.get('q') and au.get('src') == 'Screener.in')):
        m = dict(man or {}); m.update(au); return m
    return man or {}

def penalty(s):
    c = company(s['sym']); pe = c.get('pe')
    if pe is None: pe = ((ST.get('fund') or {}).get(s['sym']) or {}).get('pe')
    if c.get('np') is not None and c['np'] < 0: return 10
    if pe is None: return 0
    return 10 if pe > 200 else 5 if pe > 100 else 0

def rank():
    L = sorted([s for s in D['stocks'] if s.get('liq300') and s.get('fMom') is not None], key=lambda s: s['fMom'])
    for i, s in enumerate(L): s['_m'] = (i + .5) / len(L) * 100
    for s in L: s['_score'] = max(0, s['_m'] - penalty(s))
    return sorted(L, key=lambda s: -s['_score'])

def bench_update():
    """Equal-weight index of the 300 most-traded stocks, extended day by day from the 120-day price arrays."""
    dates = D['dates']; liq = [s for s in D['stocks'] if s.get('liq300') and s.get('px') and len(s['px']) == len(dates)]
    level = H['bench'][-1][1] if H['bench'] else 100.0
    last = H['bench'][-1][0] if H['bench'] else dates[-2]
    for i, d in enumerate(dates):
        if d <= last or i == 0: continue
        rs = [s['px'][i] / s['px'][i - 1] - 1 for s in liq if s['px'][i] and s['px'][i - 1]]
        rs = [max(-0.5, min(0.5, r)) for r in rs]
        if rs: level *= 1 + sum(rs) / len(rs); H['bench'].append([d, round(level, 4)])
    H['bench'] = H['bench'][-800:]

def main():
    today = D['dates'][-1]
    if H['days'] and H['days'][-1]['date'] == today:
        print('already recorded', today); return
    R = rank(); top = R[:10]
    m30 = [s['sym'] for s in sorted([s for s in D['stocks'] if s.get('mrank') and s['mrank'] <= 30], key=lambda s: s['mrank'])]
    rising = bool(D['bt']['rising'])
    prev = H['days'][-1] if H['days'] else None
    bench_update()
    H['days'].append(dict(date=today, rising=rising, breadth=D['bt']['bnow'],
                          top10=[[s['sym'], s['close'], round(s['_score'], 1)] for s in top], m30=m30))
    H['days'] = H['days'][-500:]
    json.dump(H, open(HP, 'w'), separators=(',', ':'))

    # ---- message ----
    nice = dt.datetime.strptime(today, '%Y-%m-%d').strftime('%d %b %Y').lstrip('0')
    lines = [f'NSE Stock Agent, {nice}']
    lines.append(f"Market mood: {'healthy' if rising else 'CAUTIOUS'} ({D['bt']['bnow']}% of stocks above their 200-day average, {'rising' if rising else 'falling'}).")
    if not rising: lines.append('The tested model is holding cash. Treat the list as a watchlist; use half-size positions if you buy.')
    if prev and prev.get('rising') != rising:
        lines.append('>> Market mood CHANGED today: ' + ('the tested model would start buying again.' if rising else 'the tested model would sell everything and wait.'))
    lines.append('')
    lines.append('Top 10 (Momentum, the tested style):')
    old = {x[0] for x in prev['top10']} if prev else set()
    for i, s in enumerate(top, 1):
        tag = '  NEW' if prev and s['sym'] not in old else ''
        lines.append(f"{i}. {s['sym']}  score {round(s['_score'])}  Rs {s['close']:,.2f} ({s['chg']:+.1f}%){tag}")
    if prev:
        gone = [x[0] for x in prev['top10'] if x[0] not in {s['sym'] for s in top}]
        if gone: lines.append('Dropped out: ' + ', '.join(gone))
    # month-end review: first run of a new month compares the last two month-end Momentum 30 lists
    if prev and prev['date'][:7] != today[:7]:
        ends = {}
        for d in H['days'][:-1]: ends[d['date'][:7]] = d
        ks = sorted(ends)
        if len(ks) >= 2:
            new, old30 = set(ends[ks[-1]]['m30']), set(ends[ks[-2]]['m30'])
            lines += ['', f"Monthly review (Momentum 30 at the {ks[-1]} month-end close):",
                      'Sell: ' + (', '.join(sorted(old30 - new)) or 'none'), 'Buy: ' + (', '.join(sorted(new - old30)) or 'none')]
            if not ends[ks[-1]]['rising']: lines.append('Cautious version: market breadth was falling at month-end, so it holds cash.')
    RN = {'breakout': 'Breakout', 'momtrend': 'Momentum + trend turn', 'new30': 'New momentum leader'}
    setups = sorted([x for x in D['stocks'] if x.get('trade') and x['trade']['daysAgo'] == 0],
                    key=lambda x: (['breakout', 'momtrend', 'new30'].index(x['trade']['rule']), -(x.get('fMom') or 0)))
    if setups:
        lines += ['', f"New swing setups today ({len(setups)}): buy near the price, target +20%, stop -10%, sell by 40 trading days."]
        if not rising: lines.append('Market is cautious: in the test these setups made much less in falling markets. Consider waiting.')
        for x in setups[:8]:
            lines.append(f"- {x['sym']} ({RN[x['trade']['rule']]}): Rs {x['close']:,.2f}, target {x['close']*1.2:,.2f}, stop {x['close']*0.9:,.2f}")
        if len(setups) > 8: lines.append(f"  and {len(setups)-8} more on the site.")
    H['days'][-1]['setups'] = [[x['sym'], x['close'], x['trade']['rule']] for x in setups]
    json.dump(H, open(HP, 'w'), separators=(',', ':'))
    news = AUTO.get('news') or {}
    flags = [f"{s['sym']}: {news[s['sym']]['watch']}" for s in top if news.get(s['sym'], {}).get('tone') == 'Negative' and news[s['sym']].get('watch')]
    if flags: lines += ['', 'Negative news in the top 10:'] + flags[:4]
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    site = os.environ.get('SITE_URL') or (f"https://{repo.split('/')[0].lower()}.github.io/{repo.split('/')[1]}/" if '/' in repo else '')
    if site: lines += ['', site]
    lines.append('Rules-based ranking for education, not investment advice.')
    msg = '\n'.join(lines)
    print(msg)

    tok, chat, topic = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip(), os.environ.get('TELEGRAM_CHAT_ID', '').strip(), os.environ.get('NTFY_TOPIC', '').strip()
    if tok and chat:
        try:
            body = urllib.parse.urlencode(dict(chat_id=chat, text=msg[:4000], disable_web_page_preview='true')).encode()
            urllib.request.urlopen(urllib.request.Request(f'https://api.telegram.org/bot{tok}/sendMessage', data=body), timeout=30).read()
            print('sent to Telegram')
        except Exception as e: print('Telegram failed:', e)
    if topic:
        try:
            req = urllib.request.Request(f'https://ntfy.sh/{urllib.parse.quote(topic)}', data=msg.encode(), method='POST',
                                         headers={'Title': f"NSE Stock Agent {nice}: market {'healthy' if rising else 'cautious'}"})
            urllib.request.urlopen(req, timeout=30).read(); print('sent to ntfy')
        except Exception as e: print('ntfy failed:', e)
    if not (tok and chat) and not topic: print('No alert secrets set; message not sent.')

if __name__ == '__main__':
    try: main()
    except Exception as e: print('notify failed:', e); sys.exit(0)
