"""Build site/data/dashboard.json from config/series.yaml.

Usage:
  python -m pipeline.build              # full build (needs FRED_API_KEY)
  python -m pipeline.build --sample     # synthetic data, no keys or network
  python -m pipeline.build --skip ncua  # skip a source (fred, fdic, ncua)

If a chart fails to refresh, the previous version of that chart is kept and
flagged as stale, so one broken series never takes the whole page down.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from . import transforms

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "series.yaml"
OUT = ROOT / "site" / "data" / "dashboard.json"
FETCH_START = "2014-01-01"  # earlier than display_start so y/y and indexes have history

log = logging.getLogger("build")


def load_config() -> dict:
    with open(CONFIG) as f:
        return yaml.safe_load(f)


def load_previous() -> dict:
    if OUT.exists():
        prev = json.loads(OUT.read_text())
        return {c["id"]: c for sec in prev.get("sections", []) for c in sec["charts"]}
    return {}


def _series_entry(cfg: dict, spec: dict, points: list, **meta) -> dict:
    geo = spec["geo"]
    return {
        "geo": geo,
        "label": spec.get("label") or cfg["geos"][geo]["label"],
        "slot": cfg["geos"][geo]["slot"],
        "points": points,
        **meta,
    }


def build_fred_chart(cfg: dict, chart: dict, start: str) -> list[dict]:
    from . import fred

    out = []
    for spec in chart["series"]:
        info = fred.series_info(spec["id"])
        s = fred.observations(spec["id"], FETCH_START)
        s = transforms.resample(s, spec.get("resample"))
        freq = spec.get("resample") or info["frequency_short"]
        s = transforms.apply(s, spec.get("transform"), freq)
        out.append(_series_entry(
            cfg, spec, transforms.to_points(s, start),
            source_id=spec["id"],
            source_url=f"https://fred.stlouisfed.org/series/{spec['id']}",
            freq=freq,
            last_updated=info.get("last_updated"),
        ))
    return out


def build_metric_chart(cfg: dict, chart: dict, start: str, metrics: pd.DataFrame, source: str) -> list[dict]:
    out = []
    for spec in chart["series"]:
        m = metrics[(metrics["geo"] == spec["geo"]) & (metrics["metric"] == spec["metric"])]
        if m.empty:
            raise ValueError(f"{source}: no data for {spec['geo']} {spec['metric']}")
        s = m.set_index("date")["value"].astype(float).sort_index()
        out.append(_series_entry(cfg, spec, transforms.to_points(s, start), freq="Q", source_id=source.upper()))
    return out


def scorecard(cfg: dict, charts: dict) -> list[dict]:
    rows = []
    for cid in cfg.get("scorecard", []):
        c = charts.get(cid)
        if not c:
            continue
        items = []
        for s in c["series"]:
            pts = s["points"]
            if not pts:
                continue
            items.append({
                "label": s["label"], "geo": s["geo"], "slot": s["slot"],
                "date": pts[-1][0], "value": pts[-1][1],
                "prior": pts[-2][1] if len(pts) > 1 else None,
            })
        rows.append({"id": cid, "title": c["title"], "units": c["units"], "items": items})
    return rows


def build(sample: bool = False, skip: set[str] | None = None) -> dict:
    cfg = load_config()
    skip = skip or set()
    previous = load_previous()
    default_start = cfg["site"]["display_start"]

    metrics: dict[str, pd.DataFrame] = {}
    if sample:
        from .sample import fake_chart
    else:
        if "fdic" not in skip:
            try:
                from . import fdic
                metrics["fdic"] = fdic.compute_metrics(fdic.fetch(FETCH_START))
            except Exception as e:  # noqa: BLE001
                log.error("FDIC source failed: %s", e)
        if "ncua" not in skip:
            try:
                from . import ncua
                metrics["ncua"] = ncua.compute_metrics(ncua.update_summary(FETCH_START))
            except Exception as e:  # noqa: BLE001
                log.error("NCUA source failed: %s", e)

    sections, charts_by_id, failures = [], {}, []
    for sec in cfg["sections"]:
        built = []
        for chart in sec["charts"]:
            start = chart.get("display_start", default_start)
            source = chart["source"]
            base = {k: chart.get(k) for k in ("id", "title", "units", "note", "style")}
            base["source"] = source
            try:
                if sample:
                    series = fake_chart(cfg, chart, start)
                elif source in skip:
                    raise RuntimeError(f"{source} skipped")
                elif source == "fred":
                    series = build_fred_chart(cfg, chart, start)
                elif source in ("fdic", "ncua"):
                    if source not in metrics:
                        raise RuntimeError(f"{source} data unavailable")
                    series = build_metric_chart(cfg, chart, start, metrics[source], source)
                else:
                    raise ValueError(f"Unknown source {source}")
                entry = {**base, "series": series, "stale": False}
            except Exception as e:  # noqa: BLE001
                failures.append(f"{chart['id']}: {e}")
                log.warning("Chart %s failed: %s", chart["id"], e)
                if chart["id"] in previous:
                    entry = {**previous[chart["id"]], "stale": True}
                else:
                    continue
            built.append(entry)
            charts_by_id[chart["id"]] = entry
        sections.append({"id": sec["id"], "title": sec["title"], "intro": sec.get("intro"), "charts": built})

    dashboard = {
        "site": cfg["site"],
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "sample": sample,
        "scorecard": scorecard(cfg, charts_by_id),
        "sections": sections,
        "failures": failures,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dashboard, separators=(",", ":")))
    log.info("Wrote %s (%d charts, %d failures)", OUT.relative_to(ROOT), len(charts_by_id), len(failures))
    for f in failures:
        log.info("  failed: %s", f)
    return dashboard


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    p = argparse.ArgumentParser()
    p.add_argument("--sample", action="store_true", help="synthetic data, no network")
    p.add_argument("--skip", action="append", default=[], choices=["fred", "fdic", "ncua"])
    p.add_argument("--strict", action="store_true", help="exit non-zero if any chart fails")
    args = p.parse_args()
    os.chdir(ROOT)
    result = build(sample=args.sample, skip=set(args.skip))
    if args.strict and result["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
