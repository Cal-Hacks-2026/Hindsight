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
from typing import Any, Literal

from app.config import ASSIST_YEAR_ID
from app.models import AssistInstitution, AssistMajor, Course, MatchResult

from .cache import ArticulationCache
from .client import AssistClient, AssistError, AssistNotFound
from .evaluator import academic_year_id_of, evaluate
from .parser import Agreement, parse_agreement

# Majors lists change rarely; agreements are cached indefinitely (keys are per-year).
MAJORS_TTL_SECONDS = 6 * 3600
MAX_CACHED_MAJOR_LISTS = 512
INSTITUTIONS_TTL_SECONDS = 24 * 3600
# After a failed institutions fetch, fail fast for a while: profile routes look up names on every
# request and shouldn't each wait out an ASSIST timeout.
INSTITUTIONS_RETRY_SECONDS = 60
# Which universities a college has agreements with, and for which years.
PARTNERS_TTL_SECONDS = 24 * 3600
MAX_CACHED_PARTNER_LISTS = 256
# Quarter-system colleges, for when ASSIST's institution data can't be read.
QUARTER_COLLEGES = {113, 51}  # De Anza, Foothill
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
        self._institutions: tuple[float, dict[int, dict[str, Any]]] | None = None  # id → institution
        # sending id → (fetched at, receiving id → year ids with agreements); least recently used first
        self._partners: OrderedDict[int, tuple[float, dict[int, list[int]]]] = OrderedDict()
        self._institutions_failed: float | None = None
        self._lock = threading.Lock()

    def _institutions_by_id(self) -> dict[int, dict[str, Any]]:
        with self._lock:
            hit = self._institutions
        if hit and time.monotonic() - hit[0] < INSTITUTIONS_TTL_SECONDS:
            return hit[1]
        failed = self._institutions_failed
        if failed is not None and time.monotonic() - failed < INSTITUTIONS_RETRY_SECONDS:
            if hit:
                return hit[1]  # stale beats nothing
            raise AssistError("ASSIST institutions unavailable (recent failure)")
        try:
            ids = {i["id"]: i for i in self.client.institutions() if "id" in i}
        except AssistError:
            self._institutions_failed = time.monotonic()
            if hit:
                return hit[1]
            raise
        with self._lock:
            self._institutions = (time.monotonic(), ids)
            self._institutions_failed = None
        return ids

    def _community_college_by_id(self) -> dict[int, bool]:
        return {i: bool(inst.get("isCommunityCollege")) for i, inst in self._institutions_by_id().items()}

    def institution_name(self, institution_id: int) -> str | None:
        """ASSIST's current name for an institution; None when unknown or ASSIST is down."""
        try:
            inst = self._institutions_by_id().get(institution_id)
        except AssistError as e:
            log.info("institutions unavailable for a name: %s", e)
            return None
        return _current_name(inst) if inst else None

    def colleges(self) -> list[AssistInstitution]:
        """Every community college ASSIST lists, by name."""
        out = [AssistInstitution(id=i, name=name, term_system=self.term_system(i))
               for i, inst in self._institutions_by_id().items()
               if inst.get("isCommunityCollege") and (name := _current_name(inst))]
        return sorted(out, key=lambda x: x.name.casefold())

    def _partner_years(self, sending: int) -> dict[int, list[int]]:
        """Universities with agreements from `sending`, and the years they cover. One ASSIST call
        per college a day."""
        with self._lock:
            hit = self._partners.get(sending)
            if hit:
                self._partners.move_to_end(sending)
        if hit and time.monotonic() - hit[0] < PARTNERS_TTL_SECONDS:
            return hit[1]
        cc = self._community_college_by_id()
        if cc.get(sending) is not True:
            raise AssistNotFound(f"{sending} is not an ASSIST community college")
        years: dict[int, set[int]] = {}
        for p in self.client.partners(sending):
            rid = p.get("institutionParentId")
            if cc.get(rid) is False:
                years.setdefault(rid, set()).update(p.get("sendingYearIds") or [], p.get("receivingYearIds") or [])
        found = {rid: sorted(ys) for rid, ys in years.items() if ys}
        with self._lock:
            self._partners[sending] = (time.monotonic(), found)
            self._partners.move_to_end(sending)
            while len(self._partners) > MAX_CACHED_PARTNER_LISTS:
                self._partners.popitem(last=False)
        return found

    def universities(self, sending: int) -> list[tuple[int, str, int]]:
        """(id, name, year id) for every university with agreements from `sending`, by name. The
        year is ours (ASSIST_YEAR_ID) when published for the pair, else the latest one before it."""
        by_id = self._institutions_by_id()
        out = []
        for rid, years in self._partner_years(sending).items():
            usable = [y for y in years if MIN_YEAR_ID <= y <= ASSIST_YEAR_ID]
            if usable and rid in by_id and (name := _current_name(by_id[rid])):
                out.append((rid, name, usable[-1]))
        return sorted(out, key=lambda u: u[1].casefold())

    def year_for(self, sending: int, receiving: int) -> int:
        """The ASSIST year to read a pair's agreements from (I-17): ours when the pair has it,
        else the latest year that has agreements (UCLA had none for 2026–27 at first). ASSIST_YEAR_ID
        when that can't be told."""
        try:
            years = self._partner_years(sending).get(receiving, [])
        except AssistError as e:
            log.info("partner years unavailable for %s → %s: %s", sending, receiving, e)
            return ASSIST_YEAR_ID
        usable = [y for y in years if MIN_YEAR_ID <= y <= ASSIST_YEAR_ID]
        return usable[-1] if usable else ASSIST_YEAR_ID

    def term_system(self, institution_id: int) -> Literal["quarter", "semester"]:
        """From ASSIST's `termType` (1 = quarter, 0 = semester); the known quarter colleges otherwise."""
        try:
            term_type = self._institutions_by_id().get(institution_id, {}).get("termType")
        except AssistError as e:
            log.info("institutions unavailable for term system: %s", e)
            term_type = None
        if term_type in (0, 1):
            return "quarter" if term_type == 1 else "semester"
        return "quarter" if institution_id in QUARTER_COLLEGES else "semester"

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


def _current_name(inst: dict[str, Any]) -> str | None:
    """An institution's latest name (ASSIST keeps old ones, each from a `fromYear`)."""
    names = [n for n in inst.get("names") or [] if (n.get("name") or "").strip() and not n.get("hideInList")]
    if not names:
        return None
    return max(names, key=lambda n: n.get("fromYear") or 0)["name"].strip()


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
