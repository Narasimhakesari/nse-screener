# NSE Stock Agent

A static website that ranks NSE stocks after every market close and explains each pick in plain words.

Each stock gets a score out of 100 from six factors, each ranked against all other stocks:

| Factor | What it measures | Evidence from 5 years of NSE data |
|---|---|---|
| Momentum | 12-month return (skipping the last month) divided by volatility | Strong: the Momentum 30 model returned about 25% a year against about 15% for an equal-weight basket |
| Trend | Price against its 20, 50 and 200-day averages, RSI, MACD, distance from the 52-week high | Supporting filter |
| Company results | Profit growth, return on equity and capital, debt, valuation (stocks with fundamentals on file only) | Not testable with the data on file |
| Seasonality | How the stock has done in the coming calendar month in past years, against the market | Some: the best-history 10% beat the worst 10% in most months |
| News | Tone of the latest results and announcements, from a web search of the top picks | Not testable |
| Swing setup | Breakout, tight base or pullback in the last few days | Weak: small edge over 20 days |

Visitors choose a style or set their own weights. **Momentum is the default** because it did best when every style was backtested (`build/backtest_styles.py`, re-run nightly into `styles_bt.json`): from Sep 2022 to Nov 2026 the plain Momentum 30 returned about 27.6% a year against 18.6% for the 300 most-traded stocks, while every blend with the other factors returned 22–24%. Holding cash while market breadth falls cut the worst fall from about 30% to about 4%, for about 5% a year less return; the page warns when that applies. The other styles (Balanced, Swing trade, Long-term) only rank stocks above their 200-day average. P/E above 100 or 200, or a loss, cuts a score by 5 or 10 points (untested).

## Alerts (optional)
Every weekday night `build/notify.py` saves the default top 10 to `history.json` (shown on the page as a live track record) and can message you the top 10, what's new or dropped, the market mood and, after each month-end, the Momentum 30 buy and sell list. Add repository secrets (Settings → Secrets and variables → Actions):
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
