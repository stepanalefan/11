"""Synthetic market data for offline demos and tests (no network needed)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_trades(n_bars: int = 500, interval_min: int = 15, trades_per_bar: int = 200,
                start_price: float = 60_000.0, seed: int = 7) -> pd.DataFrame:
    """Random-walk trades with order-flow-driven drift, so delta carries some signal."""
    rng = np.random.default_rng(seed)
    n = n_bars * trades_per_bar
    start = pd.Timestamp("2025-01-01", tz="UTC")
    offsets = np.sort(rng.uniform(0, n_bars * interval_min * 60, n))
    regime = np.repeat(rng.normal(0, 0.15, n_bars // 20 + 1), 20)[: n_bars]
    p_buy = np.clip(0.5 + np.repeat(regime, trades_per_bar)[:n] * 0.5, 0.2, 0.8)
    buyer = rng.random(n) < p_buy
    qty = rng.lognormal(-3, 1, n)
    steps = np.where(buyer, 1, -1) * qty * start_price * 2e-4 + rng.normal(0, start_price * 1e-4, n)
    price = start_price + np.cumsum(steps)
    return pd.DataFrame({"price": price, "qty": qty, "buyer_aggressor": buyer},
                        index=start + pd.to_timedelta(offsets, unit="s"))


def bars_from_trades(trades: pd.DataFrame, interval: str = "15min") -> pd.DataFrame:
    g = trades.resample(interval, label="left", closed="left")
    bars = g["price"].ohlc()
    bars["volume"] = g["qty"].sum()
    bars["buy_volume"] = trades["qty"].where(trades["buyer_aggressor"], 0).resample(interval).sum()
    return bars.dropna()


def make_bars(n_bars: int = 3000, seed: int = 7) -> pd.DataFrame:
    return bars_from_trades(make_trades(n_bars=n_bars, trades_per_bar=60, seed=seed))
