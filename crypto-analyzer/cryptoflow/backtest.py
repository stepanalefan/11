"""Bar-by-bar backtester with honest assumptions.

- Signal on bar i's close -> market entry at bar i+1's open (plus slippage).
- Stop/target are checked against each later bar's high/low. If both are hit
  inside the same bar we assume the stop came first (worst case).
- Fees are charged on entry and exit; position size risks a fixed fraction of equity,
  capped at `max_leverage` x equity.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from .strategy import Params, generate_signals


@dataclass
class Costs:
    fee: float = 0.0005        # per side (0.05% = typical taker fee)
    slippage: float = 0.0002   # per side, fraction of price
    risk_per_trade: float = 0.01
    max_leverage: float = 1.0
    start_equity: float = 10_000.0


@dataclass
class Result:
    trades: pd.DataFrame
    equity: pd.Series
    metrics: dict = field(default_factory=dict)


def run(signals: pd.DataFrame, p: Params, c: Costs = Costs()) -> Result:
    o, h, l, cl = (signals[k].values for k in ("open", "high", "low", "close"))
    sig, stops, targets = signals["signal"].values, signals["stop"].values, signals["target"].values
    idx = signals.index
    n = len(signals)

    equity = c.start_equity
    curve = np.full(n, np.nan)
    trades = []
    pos = 0          # +1 / -1 / 0
    qty = entry = stop = target = 0.0
    entry_i = 0

    def close_trade(i, raw_price, reason):
        nonlocal equity, pos
        px = raw_price * (1 - pos * c.slippage)
        pnl = pos * (px - entry) * qty - c.fee * px * qty
        equity += pnl
        risk = abs(entry - stop) * qty
        trades.append({
            "entry_time": idx[entry_i], "exit_time": idx[i], "side": "long" if pos > 0 else "short",
            "entry": entry, "exit": px, "qty": qty, "pnl": pnl,
            "r": pnl / risk if risk else np.nan, "bars": i - entry_i + 1, "reason": reason,
        })
        pos = 0

    for i in range(n):
        # 1) enter on this bar's open if the previous bar signalled
        if pos == 0 and i > 0 and sig[i - 1] != 0:
            side = int(sig[i - 1])
            px = o[i] * (1 + side * c.slippage)
            st, tg = stops[i - 1], targets[i - 1]
            # Gap past the stop or target at the open -> setup is gone, skip it.
            valid = (px - st) * side > 0 and (tg - px) * side > 0
            if valid:
                risk_per_unit = abs(px - st)
                qty = min(c.risk_per_trade * equity / risk_per_unit, c.max_leverage * equity / px)
                equity -= c.fee * px * qty
                pos, entry, stop, target, entry_i = side, px, st, tg, i

        # 2) manage the open position on this bar
        if pos != 0:
            hit_stop = l[i] <= stop if pos > 0 else h[i] >= stop
            hit_tgt = h[i] >= target if pos > 0 else l[i] <= target
            if hit_stop:
                # If the bar opened beyond the stop, fill at the open (gap), not the stop.
                fill = min(o[i], stop) if pos > 0 else max(o[i], stop)
                close_trade(i, fill if i != entry_i else stop, "stop")
            elif hit_tgt:
                close_trade(i, target, "target")
            elif i - entry_i + 1 >= p.max_hold:
                close_trade(i, cl[i], "time")

        # mark-to-market
        curve[i] = equity + (pos * (cl[i] - entry) * qty if pos else 0.0)

    if pos != 0:
        close_trade(n - 1, cl[-1], "end")
        curve[-1] = equity

    eq = pd.Series(curve, index=idx, name="equity")
    tdf = pd.DataFrame(trades)
    return Result(tdf, eq, metrics(tdf, eq, signals, c))


def metrics(trades: pd.DataFrame, eq: pd.Series, bars: pd.DataFrame, c: Costs) -> dict:
    ret = eq.pct_change().dropna()
    bar_secs = (bars.index[1] - bars.index[0]).total_seconds() if len(bars) > 1 else 86400
    per_year = 365 * 86400 / bar_secs   # crypto trades 24/7
    dd = eq / eq.cummax() - 1
    m = {
        "trades": int(len(trades)),
        "total_return_%": 100 * (eq.iloc[-1] / c.start_equity - 1),
        "buy_hold_%": 100 * (bars["close"].iloc[-1] / bars["open"].iloc[0] - 1),
        "max_drawdown_%": 100 * dd.min(),
        "sharpe": float(ret.mean() / ret.std() * np.sqrt(per_year)) if ret.std() > 0 else 0.0,
    }
    if len(trades):
        wins = trades[trades.pnl > 0]
        losses = trades[trades.pnl <= 0]
        m.update({
            "win_rate_%": 100 * len(wins) / len(trades),
            "avg_r": float(trades.r.mean()),
            "profit_factor": float(wins.pnl.sum() / -losses.pnl.sum()) if len(losses) and losses.pnl.sum() < 0 else float("inf"),
            "avg_bars_held": float(trades.bars.mean()),
            "exposure_%": 100 * trades.bars.sum() / len(bars),
        })
    return m


def walk_forward(bars: pd.DataFrame, base: Params, grid: dict, costs: Costs = Costs(),
                 train_frac: float = 0.7, min_trades: int = 10) -> dict:
    """Optimise on the first `train_frac` of history, then report the untouched rest.

    The out-of-sample numbers are the ones to trust; a big gap between in-sample
    and out-of-sample means the parameters are curve-fit.
    """
    split = int(len(bars) * train_frac)
    # Warm-up: the test segment gets the preceding `lookback` bars for its profile,
    # but trades only count from the split onward.
    train = bars.iloc[:split]
    keys = list(grid)
    scored = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        p = replace(base, **dict(zip(keys, combo)))
        r = run(generate_signals(train, p), p, costs)
        if r.metrics["trades"] >= min_trades:
            scored.append((r.metrics["sharpe"], p, r.metrics))
    if not scored:
        raise ValueError("no parameter set produced enough trades in-sample; widen the grid or use more data")
    scored.sort(key=lambda t: t[0], reverse=True)
    best_sharpe, best, is_metrics = scored[0]

    warm = max(split - best.lookback, 0)
    test_sig = generate_signals(bars.iloc[warm:], best).iloc[split - warm:]
    oos = run(test_sig, best, costs)
    return {"params": best, "in_sample": is_metrics, "out_of_sample": oos.metrics,
            "oos_result": oos, "tested": len(scored)}
