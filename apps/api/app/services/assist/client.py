"""HTTP client for assist.org's (unofficial) JSON API — PROJECT.md §8.1.

ASSIST rejects API calls with 400 unless they carry the anti-forgery token:
GET https://assist.org/ first, read the `X-XSRF-TOKEN` cookie, and echo it
back as the `X-XSRF-TOKEN` header. Tokens rotate, so a 400 triggers one
fresh handshake and a retry.
"""

import json
import threading
from typing import Any

import httpx

BASE_URL = "https://assist.org"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
XSRF_COOKIE = "X-XSRF-TOKEN"
XSRF_HEADER = "X-XSRF-TOKEN"


class AssistError(Exception):
    """ASSIST was unreachable or returned something we can't use."""


class AssistNotFound(AssistError):
    """The institution / major / agreement asked for doesn't exist."""


def _validation_failure(res: httpx.Response) -> dict[str, Any] | None:
    try:
        body = res.json()
    except ValueError:
        return None
    return body.get("validationFailure") if isinstance(body, dict) else None


class AssistClient:
    def __init__(self, transport: httpx.BaseTransport | None = None, timeout: float = 20.0):
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*"},
            follow_redirects=True,
            timeout=timeout,
            transport=transport,
        )
        self._token: str | None = None
        self._lock = threading.Lock()

    # ---- handshake ----

    def _handshake(self) -> str:
        try:
            res = self._http.get("/", headers={"Accept": "text/html"})
        except httpx.HTTPError as e:
            raise AssistError(f"ASSIST handshake failed: {e}") from e
        token = self._http.cookies.get(XSRF_COOKIE) or res.cookies.get(XSRF_COOKIE)
        if not token:
            raise AssistError("ASSIST handshake returned no X-XSRF-TOKEN cookie")
        self._token = token
        return token

    def _ensure_token(self, stale: str | None = None) -> str:
        with self._lock:
            # Another thread may already have refreshed past the stale token.
            if self._token is None or self._token == stale:
                return self._handshake()
            return self._token

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        token = self._ensure_token()
        for attempt in range(2):
            try:
                res = self._http.get(path, params=params, headers={XSRF_HEADER: token})
            except httpx.HTTPError as e:
                raise AssistError(f"ASSIST request failed: {path}: {e}") from e
            if res.status_code == 400 and (failure := _validation_failure(res)):
                # A real validation error (e.g. unknown key), not a stale token.
                errors = "; ".join(e.get("errorMessage", "") for e in failure.get("errors") or [])
                cls = AssistNotFound if "not found" in errors.lower() else AssistError
                raise cls(f"ASSIST rejected {path}: {errors or 'validation failed'}")
            if res.status_code in (400, 401, 403) and attempt == 0:
                token = self._ensure_token(stale=token)
                continue
            if res.status_code == 404:
                raise AssistNotFound(f"ASSIST 404: {path}")
            if res.status_code != 200:
                raise AssistError(f"ASSIST {res.status_code}: {path}")
            try:
                return res.json()
            except json.JSONDecodeError as e:
                raise AssistError(f"ASSIST returned non-JSON for {path}") from e
        raise AssistError(f"ASSIST rejected the XSRF token twice: {path}")

    # ---- endpoints ----

    def institutions(self) -> list[dict[str, Any]]:
        return self._get_json("/api/institutions")

    def institution_id(self, name: str) -> int:
        """Exact (case-insensitive) match on any of an institution's names."""
        want = name.strip().casefold()
        for inst in self.institutions():
            if any(n.get("name", "").strip().casefold() == want for n in inst.get("names", [])):
                return inst["id"]
        raise AssistNotFound(f"No ASSIST institution named {name!r}")

    def partners(self, sending_id: int) -> list[dict[str, Any]]:
        """Institutions with agreements from `sending_id`: {institutionParentId, sendingYearIds,
        receivingYearIds}. An institution can appear more than once."""
        data = self._get_json(f"/api/institutions/{sending_id}/agreements")
        return [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []

    def partner_year_ids(self, sending_id: int, receiving_id: int) -> list[int]:
        """Academic year ids with published agreements between the two schools."""
        years: set[int] = set()
        for p in self.partners(sending_id):
            if p.get("institutionParentId") == receiving_id:
                years.update(p.get("sendingYearIds", []) + p.get("receivingYearIds", []))
        return sorted(years)

    def majors(self, sending_id: int, receiving_id: int, year_id: int) -> list[dict[str, Any]]:
        """`reports[]` ({label, key, ...}) for major agreements, in ASSIST's order."""
        data = self._get_json(
            "/api/agreements",
            params={
                "receivingInstitutionId": receiving_id,
                "sendingInstitutionId": sending_id,
                "academicYearId": year_id,
                "categoryCode": "major",
            },
        )
        return data.get("reports", [])

    def major(self, sending_id: int, receiving_id: int, year_id: int, label: str) -> dict[str, Any]:
        """Exact label match — "Data Science, B.S." must not hit "Population Data Science"."""
        for report in self.majors(sending_id, receiving_id, year_id):
            if report.get("label") == label:
                return report
        raise AssistNotFound(
            f"No ASSIST major {label!r} for {sending_id} → {receiving_id} in year {year_id}"
        )

    def transferability_courses(self, institution_id: int, year_id: int, list_type: str) -> dict[str, Any]:
        """A college's transferability list for a year (listType "CALGETC", "IGETC", …):
        `courseInformationList[]`, each course with its `transferAreas`. Empty when unpublished."""
        return self._get_json(
            "/api/transferability/courses",
            params={"institutionId": institution_id, "academicYearId": year_id, "listType": list_type},
        )

    def agreement(self, key: str) -> dict[str, Any]:
        """Raw `result` object of a full agreement (templateAssets etc. still JSON strings)."""
        data = self._get_json("/api/articulation/Agreements", params={"Key": key})
        if not data.get("isSuccessful", True) or not data.get("result"):
            raise AssistNotFound(f"ASSIST has no agreement {key!r}: {data.get('validationFailure')}")
        return data["result"]
