"""A college's Cal-GETC and IGETC course lists from ASSIST, cached per college, list and year.

ASSIST publishes these as transferability lists: `GET /api/transferability/courses?institutionId=…
&academicYearId=…&listType=CALGETC|IGETC` (behind the same XSRF handshake as agreements). Each
course lists the areas it is approved for, each with the term the approval begins and ends, so a
course counts in an area only if it was taken inside that window.

Cached like agreements (assist/cache.py): process memory always, Supabase `ge_list_cache` too when
configured. Past years never change; the current and later years are refetched after a week. A
year with no published list comes back empty from ASSIST and is kept in memory only, briefly.
"""

import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import ASSIST_YEAR_ID, supabase_rest_url
from app.services.assist import AssistClient, AssistError

from .rules import code_ord

log = logging.getLogger(__name__)

LIST_TYPE_IDS = {"CALGETC": 8, "IGETC": 3}  # ASSIST answers an unknown listType with list 0 (CSU)
MAX_IN_MEMORY = 64
EMPTY_TTL_SECONDS = 6 * 3600
CURRENT_TTL = timedelta(days=7)


@dataclass(frozen=True)
class ListArea:
    code: str  # ASSIST's area code, e.g. "3B" or "2A"
    begin: int | None  # rules.code_ord; None = no lower bound
    end: int | None  # exclusive; None = still approved

    def covers(self, ord_: int | None) -> bool:
        if ord_ is None:
            return self.end is None
        return (self.begin is None or self.begin <= ord_) and (self.end is None or ord_ < self.end)


@dataclass(frozen=True)
class ListCourse:
    code: str  # "PHIL 20A"
    title: str
    units: float
    areas: tuple[ListArea, ...]


@dataclass(frozen=True)
class GeList:
    list_type: str
    institution_id: int
    year_id: int
    institution_name: str
    year_code: str  # "2026-2027"
    courses: dict[str, ListCourse]  # by norm_code

    def url(self) -> str:
        """The list's public page on ASSIST."""
        return (f"https://assist.org/transfer/results?year={self.year_id}&institution={self.institution_id}"
                f"&type={self.list_type}&view=transferability")


def norm_code(prefix: str, number: str = "") -> str:
    return "".join(f"{prefix}{number}".split()).replace("-", "").replace(".", "").upper()


def trim(raw: dict[str, Any]) -> dict[str, Any]:
    """Only the fields we read (a full list is up to 1 MB; this is about a fifth)."""
    year = raw.get("academicYear") or {}
    return {
        "listType": raw.get("listType"),
        "institutionName": raw.get("institutionName"),
        "academicYear": {"id": year.get("id"), "code": year.get("code")},
        "courseInformationList": [
            {
                "prefixCode": c.get("prefixCode"), "courseNumber": c.get("courseNumber"),
                "courseTitle": c.get("courseTitle"), "minUnits": c.get("minUnits"),
                "transferAreas": [{"code": a.get("code"), "beginTermCode": a.get("beginTermCode"),
                                   "endTermCode": a.get("endTermCode")}
                                  for a in c.get("transferAreas") or []],
            }
            for c in raw.get("courseInformationList") or []
        ],
    }


def parse(raw: dict[str, Any], list_type: str, institution_id: int, year_id: int) -> GeList:
    if raw.get("listType") != LIST_TYPE_IDS[list_type]:
        raise AssistError(f"ASSIST returned list {raw.get('listType')!r} instead of {list_type}")
    courses: dict[str, ListCourse] = {}
    for c in raw.get("courseInformationList") or []:
        prefix, number = (c.get("prefixCode") or "").strip(), (c.get("courseNumber") or "").strip()
        if not prefix or not number:
            continue
        areas = tuple(ListArea((a.get("code") or "").strip(), code_ord(a.get("beginTermCode") or ""),
                               code_ord(a.get("endTermCode") or ""))
                      for a in c.get("transferAreas") or [] if (a.get("code") or "").strip())
        course = ListCourse(f"{prefix} {number}", (c.get("courseTitle") or "").strip(),
                            float(c.get("minUnits") or 0), areas)
        key = norm_code(prefix, number)
        if key in courses:  # listed twice: keep every area window
            course = ListCourse(course.code, course.title, course.units, courses[key].areas + areas)
        courses[key] = course
    year = raw.get("academicYear") or {}
    return GeList(list_type, institution_id, year_id, (raw.get("institutionName") or "").strip(),
                  year.get("code") or "", courses)


class GeListStore:
    """Fetches lists through AssistClient and caches them."""

    def __init__(self, client: AssistClient, rest_url: str | None = None, service_key: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.client = client
        self._mem: OrderedDict[tuple[str, int, int], tuple[float, GeList]] = OrderedDict()
        self._lock = threading.Lock()
        self._db: httpx.Client | None = None
        if rest_url and service_key:
            self._db = httpx.Client(
                base_url=rest_url,
                headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
                timeout=10.0,
                transport=transport,
            )

    @classmethod
    def from_env(cls, client: AssistClient) -> "GeListStore":
        return cls(client, supabase_rest_url(), os.getenv("SUPABASE_SERVICE_ROLE_KEY") or None)

    def get(self, list_type: str, institution_id: int, year_id: int) -> GeList:
        k = (list_type, institution_id, year_id)
        with self._lock:
            hit = self._mem.get(k)
            if hit:
                self._mem.move_to_end(k)
        if hit and (hit[1].courses or time.monotonic() - hit[0] < EMPTY_TTL_SECONDS):
            return hit[1]
        stored, fresh = self._db_get(k)
        if stored is not None and fresh:
            self._remember(k, stored)
            return stored
        try:
            raw = self.client.transferability_courses(institution_id, year_id, list_type)
            found = parse(raw, list_type, institution_id, year_id)
        except AssistError:
            if stored is not None:
                return stored  # stale beats nothing
            raise
        self._remember(k, found)
        if found.courses:
            self._db_put(k, trim(raw))
        return found

    def _remember(self, k: tuple[str, int, int], found: GeList) -> None:
        with self._lock:
            self._mem[k] = (time.monotonic(), found)
            self._mem.move_to_end(k)
            while len(self._mem) > MAX_IN_MEMORY:
                self._mem.popitem(last=False)

    @staticmethod
    def _key(k: tuple[str, int, int]) -> str:
        return f"{k[0]}/{k[1]}/{k[2]}"

    def _db_get(self, k: tuple[str, int, int]) -> tuple[GeList | None, bool]:
        """(stored list, still fresh). A Supabase failure only costs a refetch."""
        if self._db is None:
            return None, False
        try:
            res = self._db.get("/ge_list_cache", params={"key": f"eq.{self._key(k)}",
                                                         "select": "payload,fetched_at"})
            res.raise_for_status()
            rows = res.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("ge_list_cache read failed for %s: %s", self._key(k), e)
            return None, False
        if not rows or not rows[0].get("payload"):
            return None, False
        try:
            found = parse(rows[0]["payload"], *k)
        except AssistError as e:
            log.warning("ge_list_cache row %s is unusable: %s", self._key(k), e)
            return None, False
        fresh = k[2] < ASSIST_YEAR_ID or _age(rows[0].get("fetched_at")) < CURRENT_TTL
        return found, fresh

    def _db_put(self, k: tuple[str, int, int], payload: dict[str, Any]) -> None:
        if self._db is None:
            return
        row = {"key": self._key(k), "list_type": k[0], "institution_id": k[1], "year_id": k[2],
               "payload": payload, "fetched_at": datetime.now(timezone.utc).isoformat()}
        try:
            self._db.post("/ge_list_cache", json=row,
                          headers={"Prefer": "resolution=merge-duplicates,return=minimal"}).raise_for_status()
        except httpx.HTTPError as e:
            log.warning("ge_list_cache write failed for %s: %s", self._key(k), e)


def _age(fetched_at: str | None) -> timedelta:
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at or "")
    except ValueError:
        return CURRENT_TTL
