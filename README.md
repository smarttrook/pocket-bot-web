# Trade Radar — Railway build
Two markets:
- Pocket Option OTC: real OTC candles from OTCharts (needs OTCHARTS_API_KEY in Railway Variables). Manual scan to save requests.
- Real market pairs: Yahoo Finance candles, auto scan (weekdays only).
Indicators: EMA 20/50, RSI, Bollinger, Candles, Support/Resistance. Top 3 setups above the minimum score.
Files go at the repository root. CSS and JS are inside templates/index.html.
