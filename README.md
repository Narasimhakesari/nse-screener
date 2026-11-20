# NSE Stock Agent

The home page (index.html) scores every actively traded NSE stock after each close on six things: momentum, trend, company results, seasonality, news and swing setups, and lists the 10 best. It is rebuilt every weekday at 8:37 pm IST by `.github/workflows/refresh.yml` (`build/build.py` -> `data.json`, `build/news_fund.py` -> `auto.json`). Over 20 years (2007–2026), holding the monthly top 10 by the momentum score made 24.1% a year against 10.1% for the market, with a worst fall of 77% (`long_log.txt`). stocks.html now redirects to the home page.

**What the default list does (tested on 20 years of NSE prices, `build/backtest_score20.py` -> `score_log.txt`).**
- Ranks the 300 most-traded stocks above their 200-day average by momentum (12-month return skipping the last month, divided by volatility). Mixing in trend, seasonality and swing setups did worse (14.9% a year for the Balanced mix against 25.9% for momentum alone).
- Takes at most 2 stocks from one industry (a small gain in every version tested).
- Leaves out red-flag stocks (`build/redflags.py` -> `flags.json`, nightly): NSE GSM surveillance, price bands of 5% or less, a loss last quarter, over 25% of promoter shares pledged. ASM listing, results due within 7 days, promoter selling and 10-25% pledges are shown as warnings.
- Market filter: when an equal-weight index of the 300 most-traded stocks is below its 100-day average, the page says hold cash (`build/backtest_improve20.py` -> `improve_log.txt`). Monthly top 10 with the industry limit: 24.6% a year, worst fall -30% with the 100-day filter; 19.1% and -47% with a 200-day filter; 25.5% and -69% never in cash. Any length from 75 to 125 days gave similar results. Market: 10.2% a year, worst fall -75%.
- Also tested and rejected: holding 15 or 20, a buffer before selling, 12+6-month momentum, trailing stops of 15-20%, reviewing every 10 trading days.
- Within 10% of the 52-week high was tested and rejected (18.3% a year).


## NIFTY weekly trade (paused)

options.html shows one tested NIFTY weekly options trade, updated every weekday evening by
`.github/workflows/options_daily.yml` from NSE's daily F&O file (`build/options_daily.py` -> `options_live.json`).

**The trade.** On the 2nd trading day before each NIFTY weekly expiry, at about 3:15 pm: buy a call about 4% above
NIFTY and a put about 4% below (protection), then sell the at-the-money call and put, 1 lot each. Hold until 3:15 pm on
expiry day and close all four. No stop-loss; the protective legs cap the loss.

**How it was chosen.**
- `build/options_15y.py`, run by `.github/workflows/options.yml`, tested 12 families of NIFTY and BANKNIFTY option strategies on NSE daily files from 2011 to 2026. Results are in `options_log.txt`.
  - Each family's settings were chosen on the earlier years, then checked on the later years.
  - Only weekly selling 2 days before expiry held up.
  - Monthly selling, iron condors, credit and debit spreads, and every form of option buying did not.
- The result was confirmed on Stockmock's minute data. Per NIFTY lot, after its 0.5% slippage:

| Version | Margin | Mar 2019 – Dec 2022 profit / worst week / worst fall | Jan 2023 – Nov 2026 |
|---|---|---|---|
| With 4% protective buys (this site) | ~Rs 1.56 L | Rs 99,791 / -22,373 / -94,168 | Rs 1,07,782 / -36,881 / -82,846 |
| Without protective buys | ~Rs 2.65 L | Rs 1,93,009 / -42,860 / -79,088 | Rs 1,87,734 / -36,009 / -75,990 |

**What the protective buys do.**
- They cost about half the profit, because NIFTY rarely moved 4% in 2 days.
- They are insurance against a crash larger than anything in 2019–2026; without them that loss is unlimited.
- Strikes further out (5–6%) often did not trade.

**Before trading it.**
- F&O profits are business income, taxed at your slab rate.
- About 9 in 10 individual F&O traders lose money (SEBI).

Not investment advice.

Alerts: `build/options_notify.py` messages the evening before the entry day, on the entry evening and on expiry
evening, using the repository secrets below.

The fresh-entry trade rule (new top-50 entries, +20% / −8%, 30 days) failed the 20-year test (`build/backtest_20y.py`, `long_log.txt`); `build/notify.py` still records it in `history.json` and sends its alerts if the secrets are set.

## Alerts (optional)
`build/notify.py` records every trade the page signals in `history.json` (the page's live record). It sends a message on evenings with something to do:
- what to buy at the next open, with its GTT target and stop-loss;
- what to sell because its 30 days are up;
- which trades hit the target or stop-loss that day.

It also sends a message when the market mood changes and a summary every Friday. Add repository secrets (Settings → Secrets and variables → Actions):
- Telegram: `TELEGRAM_BOT_TOKEN` (create a bot with @BotFather) and `TELEGRAM_CHAT_ID` (send your bot a message, then open `https://api.telegram.org/bot<token>/getUpdates` and copy `chat.id`).
- Or the free ntfy app: `NTFY_TOPIC`, any long private name you also subscribe to in the app.

## Files
- `index.html`: the stock scores page. `options.html`: the paused NIFTY options page.
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
