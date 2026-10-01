"""CLI.

    python -m fitapp --demo                 # write site/data/demo.json
    python -m fitapp                        # real run (needs secrets, see README)
    python -m fitapp --dry-run --plain out.json   # real data, no writes to Garmin/Calendar
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(prog="fitapp")
    parser.add_argument("--config", default=None, help="path to config.yml")
    parser.add_argument("--out", default="site/data", help="directory for the dashboard data")
    parser.add_argument("--cache", default=".cache/state.enc.json", help="encrypted state file")
    parser.add_argument("--demo", action="store_true", help="write synthetic demo data only")
    parser.add_argument("--dry-run", action="store_true", help="don't change Garmin or the calendar")
    parser.add_argument("--plain", default=None,
                        help="also write unencrypted JSON here (local debugging only, never publish)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    # Library loggers can echo request details; keep them quiet in public Actions logs.
    for noisy in ("garminconnect", "urllib3", "googleapiclient", "gkeepapi"):
        logging.getLogger(noisy).setLevel(logging.CRITICAL)

    cfg = load_config(args.config)
    out = Path(args.out)
    if args.demo:
        from .demo import build

        out.mkdir(parents=True, exist_ok=True)
        (out / "demo.json").write_text(json.dumps(build(cfg), separators=(",", ":")))
        logging.info("Wrote %s", out / "demo.json")
        return

    from .pipeline import run

    run(cfg, out, Path(args.cache), dry_run=args.dry_run,
        plain_path=Path(args.plain) if args.plain else None)


if __name__ == "__main__":
    main()
