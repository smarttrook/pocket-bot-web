# Trade Radar — Railway build
Auto-scanning radar with 11 indicators: EMA 20/50, MACD, ADX/DMI, Supertrend, RSI, Stochastic,
CCI, Williams %R, Bollinger, Candles, Support/Resistance. Shows the top 3 setups above the minimum score.
Markets:
- Pocket Option OTC via OTCharts (OTCHARTS_API_KEY in Railway Variables). Scan rate adapts to the plan's remaining requests.
- Real market pairs via Yahoo Finance (weekdays only).
Optional: MAX_OTC_PAIRS (default 20).
