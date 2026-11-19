# NSE Stock Agent: tonight's trades

A one-page website that runs one tested trading rule on NSE stocks and updates itself every weekday night (GitHub Actions, after 8:30 pm IST).

**The rule**
- **Buy:** each evening, find stocks that have just entered the top 50 of the 300 most-traded NSE stocks by 12-month momentum (return from 12 months ago to 1 month ago, divided by volatility). "Just entered" means not in the top 50 in the 20 trading days before. Buy at the next open, strongest first.
- **Size:** at most 5 trades at a time, one fifth of your money each.
- **Exit:** right after buying, place one Zerodha GTT OCO order:
  - stop-loss trigger at the buy price −8% (market order with protection);
  - target at +20% (limit order).
- **Time limit:** if neither hits in 30 trading days, sell at the open and delete the GTT.

**How it was chosen** (`build/backtest_ideas.py`, re-run nightly into `ideas_bt.json`). Eighteen stock-picking ideas were tested: pullbacks, base breakouts, 52-week highs, NR7, MACD, Bollinger squeezes, golden crosses, strong sectors, gap-ups, delivery surges and 3-, 6- and 12-month momentum.
- Each idea ran as a real portfolio: buys at the next open; the stop filled at the stop or at the open on a gap, and the target likewise; 0.3% costs per round trip.
- Each idea's target, stop, holding time and number of trades were chosen on Sep 2022 to Dec 2024 only.
- Those settings were then checked on 2025–26, which played no part in choosing them.

This rule had the best check result: 24% a year in 2025–26, when the market (the 300 most-traded stocks, equal weight) made 5.5%. Over the full period it made about 30% a year against 18%, with a worst fall of about −31%. Similar settings gave roughly 17–31% a year. About half the trades lose money; 22% reach the +20% target.

Most chart patterns did well in 2022–24 and lost money in 2025–26. Adding a 52-week-high breakout to momentum made results worse.

Figures are before the 20% tax on short-term gains. The test covers about four years. Not investment advice.

Other files:
- `build/backtest_exits.py` runs the live rule each night into `exits_bt.json`: open trades, tomorrow's buys, the growth curve.
- `build/backtest_algos.py` is an older strategy contest.

## Alerts (optional)
`build/notify.py` records every trade the page signals in `history.json` (the page's live record). It sends a message on evenings with something to do:
- what to buy at the next open, with its GTT target and stop-loss;
- what to sell because its 30 days are up;
- which trades hit the target or stop-loss that day.

It also sends a message when the market mood changes and a summary every Friday. Add repository secrets (Settings → Secrets and variables → Actions):
- Telegram: `TELEGRAM_BOT_TOKEN` (create a bot with @BotFather) and `TELEGRAM_CHAT_ID` (send your bot a message, then open `https://api.telegram.org/bot<token>/getUpdates` and copy `chat.id`).
- Or the free ntfy app: `NTFY_TOPIC`, any long private name you also subscribe to in the app.

## Files
- `index.html`: the page.
- `data.json`: prices, indicators, factor scores, seasonality and evidence tests. Rebuilt every weekday.
- `static.json`: backtest report, news notes and fundamentals.
- `build/build.py`: rebuilds `data.json` from NSE's daily files (keeps about 5 years in `wd/bhav`).
- `auto.json`: nightly news headlines and company numbers for the top-ranked stocks (`build/news_fund.py`).
- `.github/workflows/refresh.yml`: runs everything every weekday at 8:37 pm IST and commits `data.json` and `auto.json`. The daily files are cached between runs, so only new days are downloaded.

## Setup
1. Push this folder to a public GitHub repository, including the hidden `.github` folder.
2. Settings → Pages → Source: "Deploy from a branch", branch `main`, folder `/ (root)`.
3. Actions tab → "Refresh screener data" → "Run workflow" once. The first run downloads about 5 years of files and takes longer; later runs take a minute or two.

## Updating fundamentals (monthly or after results season)
1. In Screener.in, open your saved screen and click **Export**.
2. Rename the file to `fundamentals.csv`.
3. On the repository page: **Add file → Upload files**, drop it in, **Commit changes**.
4. The refresh runs automatically and the site shows the new numbers.

The file needs an `NSE Code` column. Recognised columns: Market Capitalization, Price to Earning, Return on equity, Return on capital employed, Debt to equity, Sales growth 3Years, Profit growth 3Years, YOY Quarterly profit growth, YOY Quarterly sales growth, Promoter holding, Change in promoter holding, Pledged percentage, FII holding, Change in FII holding, DII holding, Change in DII holding.

## News and company numbers (automatic)
Every weekday night, after prices are rebuilt, `build/news_fund.py` takes the top-ranked stocks (about 70) and:
- collects their last 30 days of Google News headlines;
- reads each company's public Screener.in page: latest quarterly profit and sales against a year earlier, P/E, ROE, ROCE, market cap, promoter, FII and DII holdings, and the latest stock-exchange announcements. Yahoo Finance fills anything missing (such as debt to equity). About 60 pages a night, a few seconds apart.

Then it reads each stock's news from the facts: the reported quarterly results, the company's own stock-exchange announcements (routine notices skipped), and promoter and FII holding changes; headlines count only when there is nothing firmer. It writes a 2–3 sentence summary, a tone (Positive, Mixed, Negative or Neutral) and the main risk.

Optional: add a repository secret named `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions) and Claude will write the summaries from the same facts instead. Only stocks whose facts changed are re-read.

It writes `auto.json`, which the page merges with `static.json`: the newer news wins, and the nightly company numbers replace the uploaded `fundamentals.csv` figures when they are for the same or a newer quarter. Uploading `fundamentals.csv` is now optional. If a source fails, the previous values are kept for up to 60 days and the price refresh still publishes.

`build/agent_tasks.py` is optional: it lets someone add hand-written news notes (`todo` lists the stocks, `apply notes.json` merges them into `static.json`).

Not investment advice.
