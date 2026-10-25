"""Save ASSIST's institution lists for the web app's fallback (apps/web/src/lib/institutions.ts).

The browser uses the snapshot only when the live /assist/colleges or /assist/universities call
fails. It's built by the same route code, so it matches what the API serves. About one ASSIST
request per community college, paced; re-run when the lists change (a new academic year):

    cd apps/api && uv run python scripts/snapshot_institutions.py
"""

import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers.assist import colleges, universities  # noqa: E402

OUT = Path(__file__).resolve().parents[3] / "apps/web/src/data/institutions-snapshot.json"
PAUSE_SECONDS = 0.5  # between ASSIST requests


def main() -> None:
    found = colleges().institutions
    # Each university once (name, and full_plan when true); per college, [university id, year id].
    unis: dict[str, dict] = {}
    pairs: dict[str, list[list[int]]] = {}
    for i, college in enumerate(found, 1):
        partners = universities(college.id).institutions
        for u in partners:
            unis[str(u.id)] = {"name": u.name, **({"full_plan": True} if u.full_plan else {})}
        pairs[str(college.id)] = [[u.id, u.year_id] for u in partners]
        print(f"{i}/{len(found)} {college.name}: {len(partners)} universities", file=sys.stderr)
        time.sleep(PAUSE_SECONDS)
    snapshot = {
        "saved_on": datetime.date.today().isoformat(),
        "source": "https://assist.org",
        "colleges": [c.model_dump(exclude_none=True) for c in found],
        "universities": unis,
        "agreements": pairs,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)", file=sys.stderr)

if __name__ == "__main__":
    main()
