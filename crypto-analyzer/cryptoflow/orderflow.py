"""Order-flow analytics: delta, footprint, imbalances, volume profile."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- delta

def bar_delta(bars: pd.DataFrame) -> pd.Series:
    """Delta per bar = aggressive buys - aggressive sells (from taker buy volume)."""
    return 2 * bars["buy_volume"] - bars["volume"]


def delta_from_trades(trades: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Exact per-bar buy/sell/delta aggregated from individual trades."""
    signed = np.where(trades["buyer_aggressor"], trades["qty"], -trades["qty"])
    df = pd.DataFrame({"qty": trades["qty"], "signed": signed}, index=trades.index)
    g = df.resample(_pandas_freq(interval), label="left", closed="left")
    out = pd.DataFrame({"volume": g["qty"].sum(), "delta": g["signed"].sum()})
    out["buy_volume"] = (out["volume"] + out["delta"]) / 2
    out["sell_volume"] = out["volume"] - out["buy_volume"]
    out["cum_delta"] = out["delta"].cumsum()
    return out


def _pandas_freq(interval: str) -> str:
    unit = interval[-1]
    return interval[:-1] + {"m": "min", "h": "h", "d": "D"}[unit]


# ------------------------------------------------------------ footprint

def auto_tick(prices: pd.Series, levels: int = 40) -> float:
    """A 'nice' price step that gives roughly `levels` rows across the range."""
    rng = float(prices.max() - prices.min()) or float(prices.iloc[-1]) * 0.001
    raw = rng / levels
    mag = 10 ** np.floor(np.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return float(m * mag)
    return float(10 * mag)


def footprint(trades: pd.DataFrame, interval: str, tick: float) -> pd.DataFrame:
    """Footprint table: one row per (bar, price level) with bid/ask volume.

    `ask` = volume traded by aggressive buyers (lifting the ask),
    `bid` = volume traded by aggressive sellers (hitting the bid).
    """
    level = np.floor(trades["price"].values / tick) * tick
    df = pd.DataFrame({
        "bar": trades.index.floor(_pandas_freq(interval)),
        "price": np.round(level, 10),
        "ask": np.where(trades["buyer_aggressor"], trades["qty"], 0.0),
        "bid": np.where(trades["buyer_aggressor"], 0.0, trades["qty"]),
    })
    fp = df.groupby(["bar", "price"], sort=True)[["bid", "ask"]].sum()
    fp["delta"] = fp["ask"] - fp["bid"]
    fp["volume"] = fp["ask"] + fp["bid"]
    return fp


def imbalances(fp: pd.DataFrame, tick: float, ratio: float = 3.0, min_volume: float = 0.0) -> pd.DataFrame:
    """Diagonal imbalances, the way footprint charts compute them.

    Buy imbalance at price P: ask(P) >= ratio * bid(P - tick)
    Sell imbalance at price P: bid(P) >= ratio * ask(P + tick)
    """
    out = []
    for bar, g in fp.groupby(level="bar"):
        g = g.droplevel("bar")
        prices = g.index.values
        bid = pd.Series(g["bid"].values, index=np.round(prices, 10))
        ask = pd.Series(g["ask"].values, index=np.round(prices, 10))
        below = bid.reindex(np.round(prices - tick, 10)).fillna(0).values
        above = ask.reindex(np.round(prices + tick, 10)).fillna(0).values
        buy = (ask.values >= ratio * np.maximum(below, 1e-12)) & (ask.values > min_volume)
        sell = (bid.values >= ratio * np.maximum(above, 1e-12)) & (bid.values > min_volume)
        out.append(pd.DataFrame({"bar": bar, "price": prices, "buy_imb": buy, "sell_imb": sell}))
    if not out:
        return pd.DataFrame(columns=["bar", "price", "buy_imb", "sell_imb"])
    return pd.concat(out, ignore_index=True).set_index(["bar", "price"])


def stacked_imbalances(imb: pd.DataFrame, tick: float, min_stack: int = 3) -> pd.DataFrame:
    """Runs of >= `min_stack` consecutive imbalanced price levels within one bar.

    Stacked buy imbalances often act as support; stacked sell imbalances as resistance.
    """
    zones = []
    for bar, g in imb.groupby(level="bar"):
        g = g.droplevel("bar").sort_index()
        for side, col in (("buy", "buy_imb"), ("sell", "sell_imb")):
            run: list[float] = []
            for price, flag in zip(g.index, g[col]):
                if flag and (not run or abs(price - run[-1] - tick) < tick * 1e-6):
                    run.append(price)
                    continue
                if len(run) >= min_stack:
                    zones.append((bar, side, run[0], run[-1] + tick, len(run)))
                run = [price] if flag else []
            if len(run) >= min_stack:
                zones.append((bar, side, run[0], run[-1] + tick, len(run)))
    return pd.DataFrame(zones, columns=["bar", "side", "low", "high", "levels"])


# ------------------------------------------------------- volume profile

@dataclass
class Profile:
    prices: np.ndarray      # bin lower edges
    volume: np.ndarray      # volume per bin
    step: float
    poc: float              # point of control (bin centre)
    vah: float              # value-area high
    val: float              # value-area low

    def as_frame(self) -> pd.DataFrame:
        return pd.DataFrame({"price": self.prices + self.step / 2, "volume": self.volume})


def value_area(volume: np.ndarray, pct: float = 0.70) -> tuple[int, int, int]:
    """Standard CBOT value area: start at POC, add the larger neighbour until pct is reached.
    Returns (poc_idx, low_idx, high_idx)."""
    poc = int(np.argmax(volume))
    target = volume.sum() * pct
    lo = hi = poc
    acc = volume[poc]
    while acc < target and (lo > 0 or hi < len(volume) - 1):
        up = volume[hi + 1] if hi < len(volume) - 1 else -1.0
        dn = volume[lo - 1] if lo > 0 else -1.0
        if up >= dn:
            hi += 1
            acc += up
        else:
            lo -= 1
            acc += dn
    return poc, lo, hi


def _make_profile(edges: np.ndarray, vol: np.ndarray, pct: float) -> Profile:
    step = edges[1] - edges[0]
    poc, lo, hi = value_area(vol, pct)
    return Profile(edges[:-1], vol, step, edges[poc] + step / 2, edges[hi + 1], edges[lo])


def profile_from_trades(trades: pd.DataFrame, bins: int = 50, pct: float = 0.70) -> Profile:
    """Exact volume-at-price profile from trades."""
    lo, hi = trades["price"].min(), trades["price"].max()
    if hi <= lo:
        hi = lo * 1.0001 + 1e-9
    edges = np.linspace(lo, hi, bins + 1)
    vol, _ = np.histogram(trades["price"], bins=edges, weights=trades["qty"])
    return _make_profile(edges, vol.astype(float), pct)


def profile_from_bars(high: np.ndarray, low: np.ndarray, volume: np.ndarray,
                      bins: int = 50, pct: float = 0.70) -> Profile:
    """Approximate profile from OHLCV: each bar's volume is spread evenly over its range.

    Cheaper than trades and works on years of history; accuracy improves with
    smaller bars (e.g. build a daily profile from 5m bars).
    """
    high, low, volume = map(np.asarray, (high, low, volume))
    lo, hi = float(low.min()), float(high.max())
    if hi <= lo:
        hi = lo * 1.0001 + 1e-9
    edges = np.linspace(lo, hi, bins + 1)
    # Overlap of [low, high] with each bin, vectorised as (bars x bins).
    ov = np.clip(np.minimum(high[:, None], edges[None, 1:]) - np.maximum(low[:, None], edges[None, :-1]), 0, None)
    rng = high - low
    share = np.where(rng[:, None] > 0, ov / np.where(rng > 0, rng, 1)[:, None], 0.0)
    # Zero-range bars (high == low): put all volume in their bin.
    flat = rng <= 0
    if flat.any():
        idx = np.clip(np.searchsorted(edges, low[flat], side="right") - 1, 0, bins - 1)
        share[np.where(flat)[0], idx] = 1.0
    vol = (share * volume[:, None]).sum(axis=0)
    return _make_profile(edges, vol, pct)


def rolling_value_area(bars: pd.DataFrame, lookback: int, bins: int = 40, pct: float = 0.70) -> pd.DataFrame:
    """POC/VAH/VAL for every bar, built ONLY from the `lookback` bars before it.

    The current bar is excluded so signals never see the future.
    """
    h, l, v = bars["high"].values, bars["low"].values, bars["volume"].values
    n = len(bars)
    poc = np.full(n, np.nan)
    vah = np.full(n, np.nan)
    val = np.full(n, np.nan)
    for i in range(lookback, n):
        p = profile_from_bars(h[i - lookback:i], l[i - lookback:i], v[i - lookback:i], bins, pct)
        poc[i], vah[i], val[i] = p.poc, p.vah, p.val
    return pd.DataFrame({"poc": poc, "vah": vah, "val": val}, index=bars.index)
