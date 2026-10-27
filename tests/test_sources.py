"""Offline tests for the FDIC and NCUA metric math, using tiny fake inputs."""
import io
import zipfile

import pandas as pd
import pytest

from pipeline import fdic, ncua


def fake_fdic():
    rows = []
    for d, mult in [("20240630", 1.0), ("20250630", 1.1)]:
        for cert, st, asset in [(1, "IL", 500_000), (2, "IL", 50_000_000), (3, "WI", 800_000)]:
            rows.append({
                "CERT": cert, "REPDTE": d, "STALP": st, "ASSET": asset * mult, "DEP": asset * 0.8 * mult,
                "LNLSNET": asset * 0.6 * mult, "EQ": asset * 0.1, "CHBAL": asset * 0.05, "SC": asset * 0.2,
                "OTHBFHLB": asset * 0.04, "BRO": asset * 0.02, "NIMY": 3.5, "ROA": 1.0, "NCLNLSR": 0.4,
            })
    return pd.DataFrame(rows)


def test_fdic_metrics():
    m = fdic.compute_metrics(fake_fdic())
    get = lambda geo, metric: m[(m.geo == geo) & (m.metric == metric)].sort_values("date")["value"].iloc[-1]
    assert get("IL", "count") == 2
    assert get("US", "count") == 3
    # The $50B Illinois bank is excluded from the community cohort
    assert get("IL", "community_deposits") == pytest.approx(500_000 * 0.8 * 1.1)
    assert get("IL", "community_deposits_yoy") == pytest.approx(10.0)
    assert get("WI", "median_ltd") == pytest.approx(75.0)
    assert get("IL", "community_fhlb_share") == pytest.approx(100 * 0.04 / 1.1, rel=1e-6)


def fake_ncua_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("FOICU.txt", "CU_NUMBER,CU_NAME,STATE\n1,A,IL\n2,B,WI\n3,C,IL\n")
        z.writestr("FS220.txt", "CU_NUMBER,ACCT_010,ACCT_018\n1,100,90\n2,200,170\n3,300,250\n")
        z.writestr("FS220A.txt", "CU_NUMBER,ACCT_025B,ACCT_997,ACCT_661A,ACCT_041B\n1,60,10,0.5,0.6\n2,150,22,1.0,1.5\n3,200,33,1.5,2.0\n")
    buf.seek(0)
    return zipfile.ZipFile(buf)


def test_ncua_summary_and_metrics():
    s = ncua.summarize_quarter(fake_ncua_zip(), 2025, 6)
    il = s[s.geo == "IL"].iloc[0]
    assert il["count"] == 2
    assert il["shares"] == 340
    assert il["delinquency_rate"] == pytest.approx(100 * 2.6 / 260)
    assert il["median_roa"] == pytest.approx(1.0)  # 0.5*2/100 and 1.5*2/300 -> 1.0 both

    later = s.copy()
    later["date"] = "2026-06-01"
    later["shares"] *= 1.05
    m = ncua.compute_metrics(pd.concat([s, later]))
    val = m[(m.geo == "IL") & (m.metric == "shares_yoy")]["value"].iloc[0]
    assert val == pytest.approx(5.0)
