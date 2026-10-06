# Trade Radar — Railway build
Auto-scanning radar with 11 indicators: EMA 20/50, MACD, ADX/DMI, Supertrend, RSI, Stochastic,
CCI, Williams %R, Bollinger, Candles, Support/Resistance. Shows the top 3 setups above the minimum score.
Markets:
- Pocket Option OTC via OTCharts (OTCHARTS_API_KEY in Railway Variables). Scan rate adapts to the plan's remaining requests.
- Real market pairs via Yahoo Finance (weekdays only).
Optional: MAX_OTC_PAIRS (default 20).

## 2026 radar revision
- Radar UI with rotating sweep.
- Strict consensus: a signal is published only when every selected indicator emits the same direction.
- The displayed percentage is indicator agreement, not a promised win probability.
- Signal and outcome logs are stored in SQLite and expiry results are settled from the market feed.
- No below-threshold "closest" cards are shown.
