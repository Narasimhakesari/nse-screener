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

Visitors choose a style (Balanced, Momentum, Swing trade, Long-term) or set their own weights. Only stocks above their 200-day average are ranked as picks.

## Files
- `index.html`: the page.
- `data.json`: prices, indicators, factor scores, seasonality and evidence tests. Rebuilt every weekday.
- `static.json`: backtest report, news notes and fundamentals.
- `build/build.py`: rebuilds `data.json` from NSE's daily files (keeps about 5 years in `wd/bhav`).
- `.github/workflows/refresh.yml`: runs the build every weekday at 8:37 pm IST and commits the new `data.json`. The daily files are cached between runs, so only new days are downloaded.

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

## Updating news (automatic)
A weekly scheduled task runs `python3 build/agent_tasks.py todo`, researches news and the latest quarterly results for the listed stocks, merges them with `python3 build/agent_tasks.py apply notes.json` and commits `static.json`. To do it by hand:
News notes live in `static.json` under `news`, one entry per symbol: `tone` (Positive, Mixed, Negative or Nothing found), `date`, `text`, `src` and `url`. Refresh them for the current top picks every week or two.

Not investment advice.
