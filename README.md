Trade Radar SOL/USDT Binance Spot only. Public market data, 5-minute closed candles, seven strategies, notifications. No OTC keys needed. Deploy to Railway using Procfile. Signal outcomes are reference outcomes, not trade fills.


V2.9 diagnostics: `/api/status` includes `diagnostics` with Binance connection state, candle count, latest price, last successful scan, strategy-by-strategy results, and errors. Each 5-minute scan writes a `[RADAR]` line to Railway deploy logs. A running app is not proof of a successful market scan; verify CONNECTED and timestamp.
