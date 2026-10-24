"""Runs untrusted extractors/<kind>.py in its own process (see extract.run_isolated).

Started by the API with an empty environment in isolated mode; reads one JSON job on
stdin and writes one JSON reply on stdout. Each kind gets KIND_TIMEOUT seconds.
"""

import json
import signal
import sys
from pathlib import Path

from app.services.radar import extract
from app.services.radar.sources import Source


class KindTimeout(BaseException):  # not an Exception, so an extractor's `except Exception` can't swallow it
    pass


def _alarm(signum, frame):
    raise KindTimeout()


def main() -> None:
    job = json.loads(sys.stdin.read())
    extract.EXTRACTORS_DIR = Path(job["dir"])
    signal.signal(signal.SIGALRM, _alarm)
    reply = {}
    for kind, items in job["batches"].items():
        batch = {kind: [(i["raw"], Source.model_validate(i["source"])) for i in items]}
        signal.alarm(int(job["kind_timeout"]))
        try:
            (results,) = extract.run_in_process(batch).values()
        except KindTimeout:
            results = [extract.ExtractorError(f"{kind}.py: did not finish within {job['kind_timeout']}s")] * len(items)
        finally:
            signal.alarm(0)
        reply[kind] = [{"error": str(r)} if isinstance(r, extract.ExtractorError)
                       else {"ok": [extract.parsed_to_json(p) for p in r]} for r in results]
    sys.stdout.write(json.dumps(reply))


if __name__ == "__main__":
    main()
