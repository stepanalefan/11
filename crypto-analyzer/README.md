# cryptoflow: crypto order-flow analyzer and backtester

Standalone Python tool that pulls **free public data** from Binance or Bybit (no API keys)
and gives you the order-flow views of platforms like ATAS:

| Feature | What it shows |
|---|---|
| **Delta / CVD** | Aggressive buys minus aggressive sells, per bar and cumulative |
| **Footprint** | Bid x ask volume at every price level inside each bar |
| **Imbalances** | Diagonal bid/ask imbalances (default 3x) and *stacked* imbalance zones |
| **Volume profile** | POC, value-area high/low (70%), text histogram |
| **Backtest** | Value-area rejection + delta strategy with fees, slippage and walk-forward testing |
| **Scan** | One-line snapshot of many symbols |

## Install

```bash
cd crypto-analyzer
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Use

Add `--demo` to any command to try it offline with synthetic data.

```bash
# Volume profile of the last 96 x 15m bars (= 24h)
python -m cryptoflow profile --symbol BTCUSDT --interval 15m

# Footprint + imbalances from the last 2 hours of trades
python -m cryptoflow footprint --symbol ETHUSDT --interval 5m --hours 2 --bars 3

# Backtest 180 days on Binance USD-M perps
python -m cryptoflow backtest --exchange binance-futures --symbol BTCUSDT --interval 15m --days 180

# Optimise on the first 70% of history, report the untouched last 30%
python -m cryptoflow backtest --symbol SOLUSDT --days 365 --walk-forward --trades-out trades.csv

# Scan several coins
python -m cryptoflow scan BTCUSDT ETHUSDT SOLUSDT BNBUSDT --interval 1h --days 30

# Save data once, re-test many times without re-downloading
python -m cryptoflow fetch --symbol BTCUSDT --interval 15m --days 365 --out btc15.csv
python -m cryptoflow backtest --csv btc15.csv --trend 200
```

Run `python -m cryptoflow <command> --help` for every option.

## The strategy

**Value-area rejection confirmed by delta.** For each bar it builds a volume profile from the
previous `--lookback` bars only, never the current or future bars.

- **Long:** the bar wicks below the value-area low, closes back above it, and aggressive buyers
  dominated (delta/volume >= `--min-delta`). Target is the POC. Stop is below the wick minus
  `--stop-atr` x ATR.
- **Short:** the mirror image at the value-area high.
- Trades whose reward:risk to the POC is below `--min-rr` are skipped. Optional `--trend N` EMA filter.

## How the backtest stays honest

- The signal fires on the bar's **close**, and the entry fills at the **next bar's open**.
- If a bar touches both the stop and the target, it counts as a **stop** (worst case).
- Gaps through the stop fill at the open, not at the stop price.
- Fees (default 0.05%/side) and slippage (0.02%/side) apply on every entry and exit.
- The still-forming live bar is dropped from downloads.
- `--walk-forward` shows in-sample and out-of-sample results side by side. **Trust the
  out-of-sample numbers.** A big gap between the two means the parameters are curve-fit.
- Tests in `tests/` change future prices and confirm that earlier signals don't move.

## Data notes

- **Binance** klines include taker-buy volume, so bar delta is **exact** and backtests can span years.
- **Bybit** klines don't include taker-buy volume, so `backtest` and `scan` need Binance bars.
  Bybit still works for `profile`, and for `footprint` on its most recent ~1000 trades.
- The footprint downloads every trade. Keep `--hours` small on busy pairs (BTC can have
  millions of trades a day). Large downloads are capped at `max_trades=500000`.
- Profiles built from bars spread each bar's volume evenly across its range. This is an
  approximation: smaller bars give a more accurate profile.

## Tests

```bash
python -m pytest -q tests
```

## Disclaimer

For research and education. A good backtest doesn't guarantee future profits. Paper-trade
before risking money.
