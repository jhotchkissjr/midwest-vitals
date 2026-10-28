import pandas as pd
import pytest

from pipeline import transforms


def monthly(values, start="2018-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"), dtype=float)


def test_yoy_monthly():
    s = monthly([100.0] * 12 + [110.0] * 12)
    out = transforms.apply(s, ["yoy"], "M")
    assert out.iloc[0] == pytest.approx(10.0)
    assert len(out) == 12


def test_yoy_weekly_nearest_match():
    idx = pd.date_range("2018-01-06", periods=120, freq="W-SAT")
    s = pd.Series(range(1, 121), index=idx, dtype=float)
    out = transforms.apply(s, ["yoy"], "W")
    assert not out.empty
    assert out.iloc[-1] == pytest.approx((120 / 68 - 1) * 100, rel=0.05)


def test_ann_rate_quarterly():
    s = pd.Series([100.0, 101.0], index=pd.to_datetime(["2020-01-01", "2020-04-01"]))
    out = transforms.apply(s, ["ann_rate"], "Q")
    assert out.iloc[0] == pytest.approx((1.01 ** 4 - 1) * 100)


def test_index_2019():
    s = monthly([50.0] * 12 + [75.0] * 12, start="2019-01-01")
    out = transforms.apply(s, ["index_2019"], "M")
    assert out.loc["2019-06-01"] == pytest.approx(100.0)
    assert out.loc["2020-06-01"] == pytest.approx(150.0)


def test_index_2019_seasonal_monthly():
    # Strong seasonal pattern: January high, other months low, both years identical
    s = monthly(([200.0] + [50.0] * 11) * 2, start="2019-01-01")
    out = transforms.apply(s, ["index_2019_seasonal"], "M")
    assert out.loc["2020-01-01"] == pytest.approx(100.0)
    assert out.loc["2020-07-01"] == pytest.approx(100.0)  # annual base would give 80


def test_index_2019_seasonal_weekly():
    idx = pd.date_range("2019-01-05", periods=104, freq="W-SAT")
    s = pd.Series([float(w.isocalendar()[1]) for w in idx], index=idx)
    out = transforms.apply(s, ["index_2019_seasonal"], "W")
    assert (out.loc["2020-01-01":] == 100.0).all()


def test_chain_ma_then_index_and_scale():
    s = monthly(list(range(1, 37)), start="2018-01-01")
    out = transforms.apply(s, ["ma3", "scale:2"], "M")
    assert out.iloc[0] == pytest.approx(4.0)  # mean(1,2,3) * 2


def test_unknown_step_raises():
    with pytest.raises(ValueError):
        transforms.apply(monthly([1.0, 2.0]), ["bogus"], "M")


def test_resample_daily_to_monthly():
    idx = pd.date_range("2020-01-01", "2020-02-29", freq="D")
    s = pd.Series(1.0, index=idx)
    out = transforms.resample(s, "M")
    assert list(out.index.strftime("%Y-%m-%d")) == ["2020-01-01", "2020-02-01"]


def test_to_points_trims():
    s = monthly([1.0, 2.0, 3.0], start="2020-01-01")
    assert transforms.to_points(s, "2020-02-01") == [["2020-02-01", 2.0], ["2020-03-01", 3.0]]
