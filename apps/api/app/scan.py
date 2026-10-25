"""Run a Campus Radar scan from the command line (PROJECT.md §8.3).

    uv run python -m app.scan <feed> [<feed> ...]   # scan on Apify, wait, upsert into Supabase
    uv run python -m app.scan <feed> --via-webhook  # start the run; Apify POSTs /webhooks/apify when done

A feed is a campus's `opportunities.feed` in the campus registry (data/campuses/<id>.json).

Needs APIFY_TOKEN and SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY in the repo-root .env.
--via-webhook also needs PUBLIC_API_URL (reachable by Apify) and APIFY_WEBHOOK_SECRET.
"""

import argparse
import logging
import os
import sys

import app.config  # noqa: F401  (loads .env)
from app.services import campuses as registry
from app.services.radar import scan, store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.scan", description="Scan campus sources on Apify.")
    parser.add_argument("campuses", nargs="+", choices=registry.feeds(), metavar="feed")
    parser.add_argument("--via-webhook", action="store_true",
                        help="start the run and let Apify call /webhooks/apify instead of waiting")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    campuses = list(dict.fromkeys(args.campuses))

    try:
        if args.via_webhook:
            base, secret = os.getenv("PUBLIC_API_URL"), os.getenv("APIFY_WEBHOOK_SECRET")
            if not base or not secret:
                print("--via-webhook needs PUBLIC_API_URL and APIFY_WEBHOOK_SECRET", file=sys.stderr)
                return 2
            run_id = scan.start_scan(campuses, f"{base.rstrip('/')}/webhooks/apify", secret)
            print(f"Started Apify run {run_id}; results arrive via /webhooks/apify.")
            return 0
        result = scan.run_scan(campuses)
    except (scan.ScanError, store.StoreError) as e:
        print(f"Scan failed: {e}", file=sys.stderr)
        return 1

    print(f"\nApify run {result.run_id}: stored {result.stored} opportunities")
    for source_id, count in sorted(result.per_source.items()):
        print(f"  {source_id:36} {count}")
    if result.skipped:
        print("Skipped: " + ", ".join(f"{k}={v}" for k, v in sorted(result.skipped.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
