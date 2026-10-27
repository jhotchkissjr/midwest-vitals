"""Check every data identifier in config/series.yaml before building.

  python -m pipeline.validate          # FRED IDs + FDIC fields
  python -m pipeline.validate --ncua   # also download one NCUA quarter and check account codes

For each FRED ID that fails, prints FRED search suggestions so the config can
be corrected. Also flags series whose last update looks stale, which usually
means a discontinued series.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import requests

from .build import ROOT, load_config


def check_fred(cfg: dict) -> int:
    from . import fred

    bad = 0
    print("\nFRED series")
    print("-" * 78)
    for sec in cfg["sections"]:
        for chart in sec["charts"]:
            if chart["source"] != "fred":
                continue
            for spec in chart["series"]:
                sid = spec["id"]
                try:
                    info = fred.series_info(sid)
                    updated = info["last_updated"][:10]
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(info["last_updated"].replace(" ", "T")[:19]).replace(tzinfo=timezone.utc)).days
                    flag = "  STALE?" if age > 400 else ""
                    print(f"ok    {sid:<24} {info['frequency_short']:<3} {updated}  {info['title'][:40]}{flag}")
                except Exception as e:  # noqa: BLE001
                    bad += 1
                    print(f"FAIL  {sid:<24} {e}")
                    geo = cfg["geos"][spec["geo"]]["label"]
                    try:
                        for hit in fred.search(f"{chart['title']} {geo}"):
                            print(f"        try {hit['id']:<22} {hit['freq']:<3} {hit['title'][:60]}")
                    except Exception:  # noqa: BLE001
                        pass
    return bad


def check_fdic() -> int:
    from .fdic import FIELDS, URL

    print("\nFDIC fields")
    print("-" * 78)
    r = requests.get(URL, params={
        "filters": "STALP:IL", "fields": ",".join(FIELDS), "limit": 25,
        "sort_by": "REPDTE", "sort_order": "DESC", "format": "json",
    }, timeout=60)
    r.raise_for_status()
    rows = [d["data"] for d in r.json().get("data", [])]
    if not rows:
        print("FAIL  no rows returned for STALP:IL")
        return 1
    bad = 0
    for f, desc in FIELDS.items():
        present = any(row.get(f) not in (None, "") for row in rows)
        bad += not present
        print(f"{'ok  ' if present else 'FAIL'}  {f:<10} {desc}")
    print(f"latest REPDTE: {rows[0].get('REPDTE')}")
    return bad


def check_ncua() -> int:
    from . import ncua

    print("\nNCUA account codes")
    print("-" * 78)
    for y, m in reversed(ncua._quarters("2024-01-01")):
        z = ncua._download(y, m)
        if z is None:
            continue
        print(f"checking {y}-{m:02d}")
        try:
            summary = ncua.summarize_quarter(z, y, m)
            print(summary.to_string(index=False))
            return 0
        except KeyError as e:
            print(f"FAIL  {e}")
            print('Find replacements with: python -m pipeline.ncua describe YYYY-MM "keyword"')
            return 1
    print("FAIL  could not download any recent NCUA quarter; check the URL pattern in pipeline/ncua.py")
    return 1


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    p = argparse.ArgumentParser()
    p.add_argument("--ncua", action="store_true")
    args = p.parse_args()
    cfg = load_config()
    bad = check_fred(cfg) + check_fdic()
    if args.ncua:
        bad += check_ncua()
    print(f"\n{bad} problem(s) found")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
