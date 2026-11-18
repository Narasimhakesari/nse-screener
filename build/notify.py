#!/usr/bin/env python3
"""Nightly: keep the live record of the monthly top-5 momentum rule (history.json) and send alerts when useful.

Run from the repository root after data.json and auto.json are rebuilt:  python3 build/notify.py
Messages: the month-end review (what to sell and buy at the next open), a change in market mood, and a Friday summary of
the five holdings (flagging any at risk of being swapped). Sent only if these repository secrets exist
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
H.setdefault('days', []); H.setdefault('reviews', [])
for k in ('trades', 'months', 'sent'): H.pop(k, None)
BY = {s['sym']: s for s in D['stocks']}
nice = lambda d: dt.datetime.strptime(d, '%Y-%m-%d').strftime('%d %b %Y').lstrip('0')

def close_on(sym, day):
    s = BY.get(sym)
    if not s or day not in D['dates']: return None
    v = s['px'][D['dates'].index(day)]
    return v if v else None

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
    if prevday and prevday['date'] == today and prevday.get('v') == 4:
        print('already processed', today); return
    if prevday and prevday['date'] == today: H['days'].pop(); prevday = H['days'][-1] if H['days'] else None
    H['days'].append(dict(v=4, date=today, rising=rising, breadth=D['bt']['bnow'], rank=M.get('rankNow', [])[:10]))
    H['days'] = H['days'][-500:]
    H.setdefault('since', today)
    review = M.get('review'); held = [h['sym'] for h in M.get('holdings', [])]
    newreview = bool(review) and review >= H['since'] and not any(r['review'] == review for r in H['reviews'])
    if newreview:
        if H['reviews'] and H['reviews'][-1].get('ret') is None:   # close the previous live review
            pr = H['reviews'][-1]
            rs = [close_on(z, review) / close_on(z, pr['review']) - 1 for z in pr['held'] if close_on(z, review) and close_on(z, pr['review'])]
            liq = [s for s in D['stocks'] if s.get('liq300')]
            br = [close_on(s['sym'], review) / close_on(s['sym'], pr['review']) - 1 for s in liq if close_on(s['sym'], review) and close_on(s['sym'], pr['review'])]
            if rs: pr['ret'] = round(sum(rs) / len(rs) * 100, 2)
            if br: pr['bench'] = round(sum(br) / len(br) * 100, 2)
        H['reviews'].append(dict(review=review, held=held, ret=None, bench=None))
    json.dump(H, open(HP, 'w'), separators=(',', ':'))

    repo = os.environ.get('GITHUB_REPOSITORY', '')
    site = os.environ.get('SITE_URL') or (f"https://{repo.split('/')[0].lower()}.github.io/{repo.split('/')[1]}/" if '/' in repo else '')
    mood = f"Market mood: {'healthy' if rising else 'cautious'} ({D['bt']['bnow']}% of stocks above their 200-day average)."
    foot = ['', mood] + ([site] if site else []) + ['Rules-based, for education; not investment advice.']
    msgs = []
    if M.get('reviewIsToday') and newreview:
        L = [f'NSE top-5 momentum: month-end review, {nice(today)}', '']
        sells = [x['sym'] for x in M.get('sells', [])]; buys = M.get('buys', [])
        L += ["SELL at tomorrow's open: " + (', '.join(sells) or 'nothing'), "BUY at tomorrow's open: " + (', '.join(buys) or 'nothing'), '']
        L += ['Hold these five, in equal amounts:'] + [f"{h['rankAtReview']}. {h['sym']} (Rs {BY[h['sym']]['close']:,.2f})" for h in M.get('holdings', []) if h['sym'] in BY]
        if not rising: L += ['', 'Market is cautious. In the test, holding cash at times like this gave smaller falls but less return. Your choice.']
        msgs.append(('\n'.join(L + foot), f'Month-end review {nice(today)}'))
    if prevday and prevday.get('rising') != rising:
        msgs.append(('\n'.join([f"NSE top-5 momentum: market mood changed to {'HEALTHY' if rising else 'CAUTIOUS'}, {nice(today)}",
                                'Nothing to do until the month-end review.'] + foot), 'Market mood changed'))
    if dt.datetime.strptime(today, '%Y-%m-%d').weekday() == 4 and not M.get('reviewIsToday'):
        hs = [h for h in M.get('holdings', []) if h['sym'] in BY and h.get('buy')]
        if hs:
            L = [f'NSE top-5 momentum: weekly summary, {nice(today)}', '']
            for h in hs:
                s = BY[h['sym']]; risk = h.get('rankNow') is None or h['rankNow'] > 5
                L.append(f"- {h['sym']}: {(s['close']/h['buy']-1)*100:+.1f}% since bought, rank today {h.get('rankNow') or '-'}{'  <- would be swapped if the review were today' if risk else ''}")
            would = [z for z in M.get('rankNow', [])[:5] if z not in [h['sym'] for h in hs]]
            if would: L.append('Would come in if the review were today: ' + ', '.join(would))
            neg = [f"{h['sym']}: {AUTO['news'][h['sym']]['watch']}" for h in hs if (AUTO.get('news') or {}).get(h['sym'], {}).get('tone') == 'Negative' and AUTO['news'][h['sym']].get('watch')]
            if neg: L += ['', 'Negative news:'] + neg
            msgs.append(('\n'.join(L + foot), f'Weekly summary {nice(today)}'))
    if not msgs: print('Nothing to report today.')
    for m, t in msgs: send(m, t)

if __name__ == '__main__':
    try: main()
    except Exception as e: print('notify failed:', e); sys.exit(0)
