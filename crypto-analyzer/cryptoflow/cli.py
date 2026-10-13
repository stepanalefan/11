"""Command-line interface.  Run `python -m cryptoflow --help`."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

from . import backtest as bt
from . import orderflow as of
from .exchanges import INTERVAL_MS, ExchangeError, get_exchange
from .strategy import Params, generate_signals
from .synthetic import make_bars, make_trades


def _start_ms(days: float) -> int:
    return int((time.time() - days * 86400) * 1000)


def load_bars(a) -> pd.DataFrame:
    if a.demo:
        return make_bars()
    if a.csv:
        df = pd.read_csv(a.csv, index_col=0, parse_dates=True)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df
    return get_exchange(a.exchange).bars(a.symbol, a.interval, _start_ms(a.days))


def load_trades(a) -> pd.DataFrame:
    if a.demo:
        return make_trades(n_bars=40)
    return get_exchange(a.exchange).trades(a.symbol, _start_ms(a.hours / 24))


def _fmt_metrics(m: dict) -> str:
    return "\n".join(f"  {k:<16} {v:>10.2f}" if isinstance(v, float) else f"  {k:<16} {v:>10}" for k, v in m.items())


def _bar_chart(volume, width=40):
    top = max(volume.max(), 1e-12)
    return ["#" * int(round(v / top * width)) for v in volume]


# --------------------------------------------------------------- commands

def cmd_fetch(a):
    bars = load_bars(a)
    out = Path(a.out or f"{a.symbol}_{a.interval}.csv")
    bars.to_csv(out)
    print(f"saved {len(bars)} bars ({bars.index[0]} -> {bars.index[-1]}) to {out}")


def cmd_profile(a):
    bars = load_bars(a)
    if a.last:
        bars = bars.iloc[-a.last:]
    p = of.profile_from_bars(bars.high.values, bars.low.values, bars.volume.values, a.bins)
    last = bars.close.iloc[-1]
    print(f"Volume profile, {len(bars)} bars  ({bars.index[0]:%Y-%m-%d %H:%M} -> {bars.index[-1]:%Y-%m-%d %H:%M} UTC)")
    print(f"  POC {p.poc:.2f}   VAH {p.vah:.2f}   VAL {p.val:.2f}   last {last:.2f}")
    where = "ABOVE value" if last > p.vah else "BELOW value" if last < p.val else "inside value"
    print(f"  price is {where}")
    if bars["buy_volume"].notna().any():
        d = of.bar_delta(bars)
        print(f"  net delta {d.sum():+.2f}  ({100 * d.sum() / bars.volume.sum():+.1f}% of volume)")
    print()
    for price, vol, bar in reversed(list(zip(p.prices + p.step / 2, p.volume, _bar_chart(p.volume)))):
        tag = " POC" if abs(price - p.poc) < p.step / 2 else (" VA" if p.val <= price <= p.vah else "")
        print(f"  {price:>12.2f} {bar:<40} {vol:>10.2f}{tag}")


def cmd_footprint(a):
    trades = load_trades(a)
    interval = a.interval
    tick = a.tick or of.auto_tick(trades["price"], 30)
    fp = of.footprint(trades, interval, tick)
    imb = of.imbalances(fp, tick, a.ratio, a.min_volume)
    stacks = of.stacked_imbalances(imb, tick, a.stack)
    bars = sorted(fp.index.get_level_values("bar").unique())[-a.bars:]
    print(f"Footprint  tick={tick:g}  imbalance ratio={a.ratio}x   (bid x ask, * = imbalance)")
    for bar in bars:
        g = fp.loc[bar].sort_index(ascending=False)
        ib = imb.loc[bar]
        print(f"\n== {bar:%Y-%m-%d %H:%M}  vol {g.volume.sum():.3f}  delta {g.delta.sum():+.3f}")
        poc = g.volume.idxmax()
        for price, row in g.iterrows():
            sb = "*" if ib.loc[price, "sell_imb"] else " "
            bb = "*" if ib.loc[price, "buy_imb"] else " "
            tag = "  <POC" if price == poc else ""
            print(f"  {price:>12.2f}  {sb}{row.bid:>10.3f} x {row.ask:<10.3f}{bb}{tag}")
    if len(stacks):
        print("\nStacked imbalances:")
        for z in stacks[stacks.bar.isin(bars)].itertuples():
            print(f"  {z.bar:%m-%d %H:%M}  {z.side:<4}  {z.low:.2f} - {z.high:.2f}  ({z.levels} levels)")
    cvd = of.delta_from_trades(trades, interval)
    print(f"\nCumulative delta over window: {cvd.cum_delta.iloc[-1]:+.3f}")


def _params(a) -> Params:
    return Params(lookback=a.lookback, min_delta_ratio=a.min_delta, min_rr=a.min_rr,
                  stop_atr=a.stop_atr, max_hold=a.max_hold, trend_filter=a.trend)


def _costs(a) -> bt.Costs:
    return bt.Costs(fee=a.fee, slippage=a.slippage, risk_per_trade=a.risk, max_leverage=a.leverage)


def cmd_backtest(a):
    bars = load_bars(a)
    p, c = _params(a), _costs(a)
    if a.walk_forward:
        grid = {"lookback": [48, 96, 192], "min_delta_ratio": [0.05, 0.1, 0.2], "stop_atr": [0.3, 0.6]}
        wf = bt.walk_forward(bars, p, grid, c)
        print(f"Walk-forward on {len(bars)} bars ({wf['tested']} parameter sets tried)")
        print("Best params:", json.dumps({k: wf['params'].to_dict()[k] for k in grid}))
        print("\nIn-sample (optimised, optimistic):\n" + _fmt_metrics(wf["in_sample"]))
        print("\nOut-of-sample (untouched, trust this one):\n" + _fmt_metrics(wf["out_of_sample"]))
        res = wf["oos_result"]
    else:
        res = bt.run(generate_signals(bars, p), p, c)
        print(f"Backtest {len(bars)} bars  {bars.index[0]:%Y-%m-%d} -> {bars.index[-1]:%Y-%m-%d}")
        print(_fmt_metrics(res.metrics))
    if a.trades_out and len(res.trades):
        res.trades.to_csv(a.trades_out, index=False)
        print(f"\ntrades written to {a.trades_out}")


def cmd_scan(a):
    p = _params(a)
    rows = []
    for sym in a.symbols:
        try:
            bars = get_exchange(a.exchange).bars(sym, a.interval, _start_ms(a.days)) if not a.demo else make_bars(seed=sum(map(ord, sym)))
            f = generate_signals(bars, p)
        except (ExchangeError, ValueError) as e:
            print(f"{sym}: {e}", file=sys.stderr)
            continue
        last = f.iloc[-1]
        recent = f["delta"].iloc[-a.delta_bars:].sum() / f["volume"].iloc[-a.delta_bars:].sum()
        loc = "above VA" if last.close > last.vah else "below VA" if last.close < last.val else "in VA"
        rows.append({"symbol": sym, "close": last.close, "poc": last.poc, "vah": last.vah, "val": last.val,
                     "location": loc, f"delta%_{a.delta_bars}": 100 * recent,
                     "signal": {1: "LONG", -1: "SHORT"}.get(int(last.signal), "-")})
    if rows:
        print(pd.DataFrame(rows).set_index("symbol").round(4).to_string())


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cryptoflow", description="Crypto order-flow analyzer & backtester")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def source(sp, bars=True):
        sp.add_argument("--exchange", default="binance", choices=["binance", "binance-futures", "bybit", "bybit-spot"])
        sp.add_argument("--symbol", default="BTCUSDT")
        sp.add_argument("--interval", default="15m", choices=list(INTERVAL_MS))
        sp.add_argument("--demo", action="store_true", help="use synthetic data (offline)")
        if bars:
            sp.add_argument("--days", type=float, default=60)
            sp.add_argument("--csv", help="load bars from a CSV made by `fetch`")

    def strat(sp):
        sp.add_argument("--lookback", type=int, default=96)
        sp.add_argument("--min-delta", type=float, default=0.10)
        sp.add_argument("--min-rr", type=float, default=1.0)
        sp.add_argument("--stop-atr", type=float, default=0.5)
        sp.add_argument("--max-hold", type=int, default=48)
        sp.add_argument("--trend", type=int, default=0, help="EMA trend filter length (0 = off)")

    s = sub.add_parser("fetch", help="download bars to CSV")
    source(s)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_fetch)

    s = sub.add_parser("profile", help="volume profile with POC / value area")
    source(s)
    s.add_argument("--bins", type=int, default=30)
    s.add_argument("--last", type=int, default=96, help="use only the last N bars (0 = all)")
    s.set_defaults(fn=cmd_profile)

    s = sub.add_parser("footprint", help="footprint, imbalances and delta from trades")
    source(s, bars=False)
    s.add_argument("--hours", type=float, default=2)
    s.add_argument("--bars", type=int, default=3, help="how many recent bars to print")
    s.add_argument("--tick", type=float, default=0, help="price step per row (0 = auto)")
    s.add_argument("--ratio", type=float, default=3.0)
    s.add_argument("--min-volume", type=float, default=0.0)
    s.add_argument("--stack", type=int, default=3)
    s.set_defaults(fn=cmd_footprint)

    s = sub.add_parser("backtest", help="backtest the value-area + delta strategy")
    source(s)
    strat(s)
    s.add_argument("--fee", type=float, default=0.0005)
    s.add_argument("--slippage", type=float, default=0.0002)
    s.add_argument("--risk", type=float, default=0.01, help="fraction of equity risked per trade")
    s.add_argument("--leverage", type=float, default=1.0)
    s.add_argument("--walk-forward", action="store_true", help="optimise in-sample, report out-of-sample")
    s.add_argument("--trades-out", help="write the trade list to CSV")
    s.set_defaults(fn=cmd_backtest)

    s = sub.add_parser("scan", help="snapshot many symbols")
    source(s)
    strat(s)
    s.add_argument("symbols", nargs="+")
    s.add_argument("--delta-bars", type=int, default=20)
    s.set_defaults(fn=cmd_scan)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        a.fn(a)
    except ExchangeError as e:
        sys.exit(f"exchange error: {e}")
