import numpy as np
import pandas as pd
import pytest

from cryptoflow import backtest as bt
from cryptoflow import orderflow as of
from cryptoflow.strategy import Params, generate_signals
from cryptoflow.synthetic import make_bars, make_trades


def _trades(rows):
    t0 = pd.Timestamp("2025-01-01", tz="UTC")
    return pd.DataFrame(
        {"price": [r[1] for r in rows], "qty": [r[2] for r in rows], "buyer_aggressor": [r[3] for r in rows]},
        index=[t0 + pd.Timedelta(seconds=r[0]) for r in rows])


def test_delta_from_trades_is_exact():
    tr = _trades([(1, 100, 2, True), (2, 101, 1, False), (70, 100, 3, False)])
    d = of.delta_from_trades(tr, "1m")
    assert d.delta.tolist() == [1, -3]
    assert d.cum_delta.tolist() == [1, -2]
    assert d.buy_volume.tolist() == [2, 0]


def test_footprint_and_diagonal_imbalance():
    # ask at 101 (9) vs bid one tick lower at 100 (2) -> buy imbalance at 101
    tr = _trades([(1, 100, 2, False), (2, 101, 9, True), (3, 102, 1, True), (4, 101, 1, False)])
    fp = of.footprint(tr, "1m", tick=1)
    bar = fp.index.get_level_values(0)[0]
    assert fp.loc[(bar, 101.0), "ask"] == 9 and fp.loc[(bar, 101.0), "bid"] == 1
    imb = of.imbalances(fp, tick=1, ratio=3)
    assert imb.loc[(bar, 101.0), "buy_imb"]
    assert not imb.loc[(bar, 102.0), "buy_imb"]  # 1 vs bid(101)=1


def test_stacked_imbalances():
    rows = [(i, 100 + i, 10, True) for i in range(4)] + [(10, 99, 1, False)]
    tr = _trades(rows)
    imb = of.imbalances(of.footprint(tr, "1m", 1), 1, 3)
    zones = of.stacked_imbalances(imb, 1, 3)
    assert len(zones) == 1 and zones.iloc[0].side == "buy" and zones.iloc[0].levels == 4


def test_value_area_contains_70pct_and_poc():
    vol = np.array([1, 2, 10, 30, 12, 3, 1], float)
    poc, lo, hi = of.value_area(vol, 0.7)
    assert poc == 3
    assert vol[lo:hi + 1].sum() >= 0.7 * vol.sum()
    assert lo <= poc <= hi


def test_profile_from_bars_conserves_volume():
    b = make_bars(300)
    p = of.profile_from_bars(b.high.values, b.low.values, b.volume.values, 30)
    assert p.volume.sum() == pytest.approx(b.volume.sum())
    assert p.val <= p.poc <= p.vah


def test_rolling_value_area_has_no_lookahead():
    b = make_bars(400)
    va = of.rolling_value_area(b, 50)
    altered = b.copy()
    altered.iloc[300:, altered.columns.get_loc("high")] *= 1.5  # change the future
    va2 = of.rolling_value_area(altered, 50)
    pd.testing.assert_frame_equal(va.iloc[:301], va2.iloc[:301])


def test_signals_do_not_change_when_future_changes():
    b = make_bars(800)
    p = Params(lookback=48)
    s1 = generate_signals(b, p)
    fut = b.copy()
    fut.iloc[600:, :] = fut.iloc[600:, :] * 0.8
    s2 = generate_signals(fut, p)
    assert (s1.signal.iloc[:600] == s2.signal.iloc[:600]).all()


def test_backtest_costs_reduce_returns():
    b = make_bars(2000)
    p = Params(lookback=48, min_delta_ratio=0.05)
    sig = generate_signals(b, p)
    free = bt.run(sig, p, bt.Costs(fee=0, slippage=0))
    paid = bt.run(sig, p, bt.Costs(fee=0.001, slippage=0.0005))
    assert free.metrics["trades"] > 0
    assert paid.equity.iloc[-1] < free.equity.iloc[-1]


def test_entry_is_next_bar_open_and_stop_wins_ties():
    idx = pd.date_range("2025-01-01", periods=4, freq="15min", tz="UTC")
    sig = pd.DataFrame({
        "open":  [100, 101, 100, 100], "high": [101, 106, 101, 101],
        "low":   [99, 94, 99, 99],     "close": [100, 100, 100, 100],
        "signal": [1, 0, 0, 0], "stop": [95, np.nan, np.nan, np.nan], "target": [105, np.nan, np.nan, np.nan],
    }, index=idx)
    r = bt.run(sig, Params(max_hold=10), bt.Costs(fee=0, slippage=0))
    t = r.trades.iloc[0]
    assert t.entry == 101 and t.entry_time == idx[1]
    assert t.reason == "stop" and t.exit == 95  # bar touched both; assume the worst


def test_bybit_style_bars_without_taker_volume_are_rejected():
    b = make_bars(200)
    b["buy_volume"] = np.nan
    with pytest.raises(ValueError):
        generate_signals(b, Params(lookback=48))


def test_walk_forward_runs():
    b = make_bars(3000)
    wf = bt.walk_forward(b, Params(), {"lookback": [48, 96], "min_delta_ratio": [0.05, 0.1]}, min_trades=1)
    assert "trades" in wf["out_of_sample"]
