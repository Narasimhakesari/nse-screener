#!/usr/bin/env python3
"""Nightly: keep the record of monthly momentum trades (history.json) and send alerts when there is something to do.

Run from the repository root after data.json and auto.json are rebuilt:  python3 build/notify.py
Messages go out only for: the month-end review (what to sell and buy next morning), a stop-loss hit, a change in market
mood, and a short Friday summary of open trades. They are sent only if these repository secrets exist
(Settings > Secrets and variables > Actions):
  TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID   (a bot made with @BotFather; your chat id)
  NTFY_TOPIC                                (a private topic name you subscribe to in the free ntfy app)
Optional: SITE_URL (defaults to https://<owner>.github.io/<repo>/).
"""
import json, os, sys, datetime as dt, urllib.request, urllib.parse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
J = lambda n, d=None: (json.load(open(os.path.join(ROOT, n))) if os.path.exists(os.path.join(ROOT, n)) else d)
D, AUTO = J('data.json'), J('auto.json', {})
HP = os.path.join(ROOT, 'history.json')
H = J('history.json', {})
H.setdefault('days', []); H.setdefault('months', {}); H.setdefault('sent', {})
BY = {s['sym']: s for s in D['stocks']}
nice = lambda d: dt.datetime.strptime(d, '%Y-%m-%d').strftime('%d %b %Y').lstrip('0')

def send(msg, title):
    print(msg); print('---')
    tok, chat, topic = (os.environ.get(k, '').strip() for k in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'NTFY_TOPIC'))
    if tok and chat:
        try:
            body = urllib.parse.urlencode(dict(chat_id=chat, text=msg[:4000], disable_web_page_preview='true')).encode()
            urllib.request.urlopen(urllib.request.Request(f'https://api.telegram.org/bot{tok}/sendMessage', data=body), timeout=30).read()
            print('sent to Telegram')
        except Exception as e: print('Telegram failed:', e)
    if topic:
        try:
            urllib.request.urlopen(urllib.request.Request(f'https://ntfy.sh/{urllib.parse.quote(topic)}', data=msg.encode(), method='POST',
                                                          headers={'Title': title}), timeout=30).read(); print('sent to ntfy')
        except Exception as e: print('ntfy failed:', e)
    if not (tok and chat) and not topic: print('No alert secrets set; message not sent.')

def main():
    today = D['dates'][-1]; M = D.get('mom') or {}
    rising = bool(D['bt']['rising'])
    prevday = H['days'][-1] if H['days'] else None
    if prevday and prevday['date'] == today and prevday.get('v') == 2:
        print('already processed', today); return
    if prevday and prevday['date'] == today: H['days'].pop(); prevday = H['days'][-1] if H['days'] else None
    H['days'].append(dict(v=2, date=today, rising=rising, breadth=D['bt']['bnow'], top30=M.get('top30Now', [])))
    H['days'] = H['days'][-500:]

    review = M.get('review')
    if review:
        rec = H['months'].setdefault(review, dict(buyDate=M.get('buyDate'), trades=[]))
        rec['trades'] = [dict(sym=t['sym'], buy=t.get('buy'), stop=t.get('stop'), stopped=t.get('stopped'), exit=t.get('exit'),
                              closeAtReview=t.get('closeAtReview')) for t in M.get('trades', [])]
        for k, m in H['months'].items():
            if k < review and not m.get('closed'):
                for t in m['trades']:
                    s = BY.get(t['sym'])
                    if t.get('ret') is None and t.get('buy'):
                        # sold at the open after the review; the review-day close is the nearest price on record
                        px = t['exit'] if t.get('stopped') else (s['px'][D['dates'].index(review)] if s and review in D['dates'] else None)
                        if px: t['ret'] = round((px / t['buy'] - 1) * 100, 2); t['sold'] = px
                m['closed'] = review
    json.dump(H, open(HP, 'w'), separators=(',', ':'))

    repo = os.environ.get('GITHUB_REPOSITORY', '')
    site = os.environ.get('SITE_URL') or (f"https://{repo.split('/')[0].lower()}.github.io/{repo.split('/')[1]}/" if '/' in repo else '')
    foot = ([site] if site else []) + ['Rules-based, for education; not investment advice.']
    mood = f"Market mood: {'healthy' if rising else 'cautious'} ({D['bt']['bnow']}% of stocks above their 200-day average)."
    msgs = []

    if M.get('reviewIsToday') and H['sent'].get('review') != review:
        prev = [k for k in sorted(H['months']) if k < review]
        sell = [t for t in (H['months'][prev[-1]]['trades'] if prev else []) if not t.get('stopped') and t.get('buy') and t['sym'] in BY]
        L = [f'NSE momentum: month-end review, {nice(today)}', mood, '', "SELL at tomorrow's open (last month's trades still open):"]
        L += [f"- {t['sym']} (bought Rs {t['buy']:,.2f}, now Rs {BY[t['sym']]['close']:,.2f}, {((BY[t['sym']]['close']/t['buy']-1)*100):+.1f}%)" for t in sell] or ['- none']
        L += ['', "BUY at tomorrow's open, equal amounts, stop-loss 10% below your price:"]
        L += [f"- {t['sym']} (closed Rs {t['closeAtReview']:,.2f}; stop about Rs {t['closeAtReview']*0.9:,.2f})" for t in M.get('trades', [])] or ['- none']
        if not rising: L += ['', 'The market is cautious: in the test the rule still made money, but about a third as much. Consider half-size positions.']
        msgs.append(('\n'.join(L + [''] + foot), f'Month-end review {nice(today)}'))
        H['sent']['review'] = review

    hits = [t for t in M.get('trades', []) if t.get('stopped') == today]
    if hits:
        L = [f'NSE momentum: stop-loss hit, {nice(today)}']
        L += [f"- {t['sym']}: bought Rs {t['buy']:,.2f}, stop Rs {t['stop']:,.2f}, sold near Rs {t['exit']:,.2f} ({(t['exit']/t['buy']-1)*100:+.1f}%)" for t in hits]
        L += ['If your stop order did not fill, sell at the next open. Do not re-buy until the next review.']
        msgs.append(('\n'.join(L + [''] + foot), 'Stop-loss hit'))

    if prevday and prevday.get('rising') != rising:
        msgs.append(('\n'.join([f'NSE momentum: market mood changed to {"HEALTHY" if rising else "CAUTIOUS"}, {nice(today)}', mood,
                                'Healthy: normal position size at the next review.' if rising else 'Cautious: consider half-size positions at the next review. Keep existing stops.', ''] + foot), 'Market mood changed'))

    if dt.datetime.strptime(today, '%Y-%m-%d').weekday() == 4 and not M.get('reviewIsToday'):
        T = [t for t in M.get('trades', []) if t.get('buy') and t['sym'] in BY]
        if T:
            L = [f'NSE momentum: weekly summary, {nice(today)}', mood, '']
            for t in T:
                s = BY[t['sym']]
                L.append(f"- {t['sym']}: stopped out {((t['exit']/t['buy']-1)*100):+.1f}%" if t.get('stopped') else f"- {t['sym']}: {((s['close']/t['buy']-1)*100):+.1f}%, stop Rs {t['stop']:,.2f}")
            neg = [f"{t['sym']}: {AUTO['news'][t['sym']]['watch']}" for t in T if (AUTO.get('news') or {}).get(t['sym'], {}).get('tone') == 'Negative' and AUTO['news'][t['sym']].get('watch')]
            if neg: L += ['', 'Negative news:'] + neg
            msgs.append(('\n'.join(L + [''] + foot), f'Weekly summary {nice(today)}'))

    json.dump(H, open(HP, 'w'), separators=(',', ':'))
    if not msgs: print('Nothing to report today.')
    for m, t in msgs: send(m, t)

if __name__ == '__main__':
    try: main()
    except Exception as e: print('notify failed:', e); sys.exit(0)
