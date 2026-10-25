"""Label every stored listing with one of the ten opportunity categories (Opportunities feature).

    uv run python -m app.classify            # rules, then one cached Claude batch for leftovers
    uv run python -m app.classify --dry-run  # rules only; prints what Claude would be asked about

Needs SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY in the repo-root .env, and the
20261025_opportunities migration applied (opportunity_labels holds Claude's labels).
Listings that already have a stored label for their current title aren't asked about again.
"""

import argparse
import logging
import sys

import app.config  # noqa: F401  (loads .env)
from app.services.radar import classify, store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.classify", description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="rules only; no Claude call, nothing stored")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        rows = store.all_rows()
    except store.StoreError as e:
        print(f"Couldn't read opportunities: {e}", file=sys.stderr)
        return 1
    if args.dry_run:
        leftovers = [r for r in rows if classify.rule_label(r) is None]
        print(f"{len(rows)} listings: {len(rows) - len(leftovers)} placed by rules, {len(leftovers)} left for Claude")
        for r in leftovers:
            print(f"  {r.get('title')}  [{r.get('org')}]")
        return 0
    run = classify.label_leftovers(rows)
    print(f"{len(rows)} listings: {run.by_rule} by rule, {run.already_stored} already stored, "
          f"{run.by_claude} new from Claude, {run.unlabeled} by type")
    for category, count in (run.per_category or {}).most_common():
        print(f"  {category:14} {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
