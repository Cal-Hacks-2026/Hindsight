"""What the routers call: majors for a school pair, and a transcript match.

Every input that becomes an outbound ASSIST request is validated first (real
institution ids, a real year range), and every in-memory cache is size-capped,
so callers can't grow memory or make us hammer the unofficial API.
"""

import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.config import ASSIST_YEAR_ID
from app.models import AssistMajor, Course, MatchResult

from .cache import ArticulationCache
from .client import AssistClient, AssistError, AssistNotFound
from .evaluator import academic_year_id_of, evaluate
from .parser import Agreement, parse_agreement

# Majors lists change rarely; agreements are cached indefinitely (keys are per-year).
MAJORS_TTL_SECONDS = 6 * 3600
MAX_CACHED_MAJOR_LISTS = 512
INSTITUTIONS_TTL_SECONDS = 24 * 3600
# Bound the extra ASSIST calls a long transcript can trigger (most recent years win).
MAX_PRIOR_YEARS = 6
# ASSIST's earliest academic year (1980–81); one year past ours once it's published.
MIN_YEAR_ID = 31
MAX_YEAR_ID = ASSIST_YEAR_ID + 1

log = logging.getLogger(__name__)


class AssistService:
    def __init__(self, client: AssistClient, cache: ArticulationCache):
        self.client = client
        self.cache = cache
        # Least recently used first.
        self._majors: OrderedDict[tuple[int, int, int], tuple[float, list[dict[str, Any]]]] = OrderedDict()
        self._institutions: tuple[float, dict[int, bool]] | None = None  # id → isCommunityCollege
        self._lock = threading.Lock()

    def _community_college_by_id(self) -> dict[int, bool]:
        with self._lock:
            hit = self._institutions
        if hit and time.monotonic() - hit[0] < INSTITUTIONS_TTL_SECONDS:
            return hit[1]
        ids = {i["id"]: bool(i.get("isCommunityCollege")) for i in self.client.institutions() if "id" in i}
        with self._lock:
            self._institutions = (time.monotonic(), ids)
        return ids

    def _validate(self, sending: int, receiving: int, year: int) -> None:
        """ASSIST agreements run community college → university."""
        if not MIN_YEAR_ID <= year <= MAX_YEAR_ID:
            raise AssistNotFound(f"ASSIST has no academic year {year}")
        cc = self._community_college_by_id()
        if cc.get(sending) is not True:
            raise AssistNotFound(f"{sending} is not an ASSIST community college")
        if cc.get(receiving) is not False:
            raise AssistNotFound(f"{receiving} is not an ASSIST university")

    def _reports(self, sending: int, receiving: int, year: int) -> list[dict[str, Any]]:
        k = (sending, receiving, year)
        with self._lock:
            hit = self._majors.get(k)
            if hit:
                self._majors.move_to_end(k)
        if hit and time.monotonic() - hit[0] < MAJORS_TTL_SECONDS:
            return hit[1]
        self._validate(sending, receiving, year)
        reports = self.client.majors(sending, receiving, year)
        with self._lock:
            self._majors[k] = (time.monotonic(), reports)
            self._majors.move_to_end(k)
            while len(self._majors) > MAX_CACHED_MAJOR_LISTS:
                self._majors.popitem(last=False)
        return reports

    def majors(self, sending: int, receiving: int, year: int) -> list[AssistMajor]:
        return [
            AssistMajor(label=r["label"], key=r["key"])
            for r in self._reports(sending, receiving, year)
            if r.get("label") and r.get("key")
        ]

    def agreement(self, sending: int, receiving: int, year: int, major_label: str) -> Agreement:
        """Exact label match → cached (or fetched) agreement → parsed."""
        report = next(
            (r for r in self._reports(sending, receiving, year) if r.get("label") == major_label),
            None,
        )
        if report is None:
            # Let the client raise the canonical not-found error (and re-check live).
            report = self.client.major(sending, receiving, year, major_label)
        key = report["key"]
        raw = self.cache.get(key)
        if raw is None:
            raw = self.client.agreement(key)
            self.cache.put(key, raw, sending_id=sending, receiving_id=receiving,
                           year_id=year, major_label=major_label)
        return parse_agreement(raw, key)

    def _prior_agreement(self, sending: int, receiving: int, year: int,
                         major_label: str) -> Agreement | None:
        """Best effort: a missing/renamed major or an ASSIST hiccup for an old year
        only costs confidence (renumbering fallback), never the whole match."""
        try:
            return self.agreement(sending, receiving, year, major_label)
        except AssistError as e:
            log.info("no %s agreement for year %s: %s", major_label, year, e)
            return None

    def match(self, sending: int, receiving: int, year: int, major_label: str,
              courses: list[Course]) -> MatchResult:
        current = self.agreement(sending, receiving, year, major_label)
        years = sorted({y for c in courses if (y := academic_year_id_of(c)) and MIN_YEAR_ID <= y < year})
        years = years[-MAX_PRIOR_YEARS:]
        with ThreadPoolExecutor(max_workers=4) as pool:
            prior = pool.map(lambda y: self._prior_agreement(sending, receiving, y, major_label), years)
            prior = [a for a in prior if a is not None]
        return evaluate(current, courses, prior)


_service: AssistService | None = None


def get_service() -> AssistService:
    global _service
    if _service is None:
        _service = AssistService(AssistClient(), ArticulationCache.from_env())
    return _service


def set_service(service: AssistService | None) -> None:
    """Swap the singleton (tests inject a fixture-backed transport)."""
    global _service
    _service = service
