"""Optional: add a short AI-written read to each section of dashboard.json.

  python -m pipeline.ai_notes

Requires ANTHROPIC_API_KEY. Skips quietly if the key is missing, so the
scheduled build never fails because of this step. The model only sees the
numbers in dashboard.json and is told not to add outside facts.
"""
from __future__ import annotations

import json
import logging
import os

from .build import OUT, ROOT

log = logging.getLogger("ai_notes")
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")

SYSTEM = """You write the one-paragraph summary that sits above a section of an
economic dashboard read by bank and credit union executives and economists.

Rules:
- 2 to 3 sentences, plain and specific, peer-level tone.
- Use only the numbers provided. Do not add outside facts, forecasts or causes.
- Lead with the most notable change; compare Illinois and Wisconsin to the U.S. where relevant.
- Name the reference period for any figure you cite (e.g. "in Q2", "in September").
- No em dashes. No hedging boilerplate. No recommendations."""


def _digest(section: dict) -> str:
    lines = [f"Section: {section['title']}"]
    for c in section["charts"]:
        lines.append(f"\n{c['title']} ({c['units']})")
        for s in c["series"]:
            pts = s["points"]
            if len(pts) < 2:
                continue
            last, prior = pts[-1], pts[-2]
            year_ago = next((p for p in reversed(pts) if p[0] <= f"{int(last[0][:4]) - 1}{last[0][4:]}"), None)
            ya = f", year earlier {year_ago[1]}" if year_ago else ""
            lines.append(f"  {s['label']}: {last[1]} as of {last[0]} (prior {prior[1]} as of {prior[0]}{ya})")
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.info("ANTHROPIC_API_KEY not set; skipping AI notes")
        return
    import anthropic

    client = anthropic.Anthropic()
    dash = json.loads(OUT.read_text())
    if dash.get("sample"):
        log.info("Sample data; skipping AI notes")
        return
    for section in dash["sections"]:
        try:
            msg = client.messages.create(
                model=MODEL,
                max_tokens=300,
                system=SYSTEM,
                messages=[{"role": "user", "content": _digest(section)}],
            )
            text = "".join(b.text for b in msg.content if b.type == "text").strip()
            section["ai_read"] = text.replace("\u2014", ", ")
            log.info("Wrote read for %s", section["id"])
        except Exception as e:  # noqa: BLE001
            log.warning("AI read failed for %s: %s", section["id"], e)
    OUT.write_text(json.dumps(dash, separators=(",", ":")))


if __name__ == "__main__":
    main()
