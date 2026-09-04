"""Script to sync upcoming matches and Best-of formats from Liquipedia."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from betting_app.services.liquipedia_service import sync_liquipedia_best_of

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronize Best-of series format from Liquipedia.")
    parser.add_argument("--limit", type=int, default=50, help="Number of match ticker entries to fetch (default: 50)")
    args = parser.parse_args()

    result = sync_liquipedia_best_of(limit=args.limit)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
