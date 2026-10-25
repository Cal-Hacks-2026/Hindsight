"""A fake assist.org served from saved real responses (tests/fixtures/assist/).

Enforces the XSRF handshake like the real site: API calls without the current
token get a bare 400.
"""

import json
from pathlib import Path
from typing import Any

import httpx

from app.services.assist import ArticulationCache, AssistClient, AssistService

FIXTURES = Path(__file__).parent / "fixtures" / "assist"

DS_KEY = "77/113/to/39/Major/0739dd42-491e-45c4-3e82-08dec89fcc4a"
ECON_BS_KEY = "77/113/to/39/Major/18619712-eec7-4023-3ef3-08dec89fcc4a"
BERKELEY_ECON_KEY = "76/113/to/79/Major/a7e5abb1-a30f-46eb-acf1-08ddbf3f4ee7"
DS_2023_KEY = "74/113/to/39/Major/351029ac-76f7-44c8-99b2-f1b56d2b5224"
ECON_BS_2023_KEY = "74/113/to/39/Major/2767db96-1510-485f-0091-08dc647f2147"

AGREEMENT_FILES = {
    DS_KEY: "agreement-113-39-77-data-science-bs.json",
    ECON_BS_KEY: "agreement-113-39-77-economics-bs.json",
    BERKELEY_ECON_KEY: "agreement-113-79-76-economics-ba.json",
    DS_2023_KEY: "agreement-113-39-74-data-science-bs.json",
    ECON_BS_2023_KEY: "agreement-113-39-74-economics-bs.json",
}

INSTITUTIONS = [
    {"id": 39, "names": [{"name": "San Jose State University"}], "isCommunityCollege": False},
    {"id": 51, "names": [{"name": "Foothill College"}], "isCommunityCollege": True, "termType": 1},
    {"id": 58, "names": [{"name": "Berkeley City College"}], "isCommunityCollege": True},
    {"id": 79, "names": [{"name": "University of California, Berkeley"}], "isCommunityCollege": False},
    {"id": 113, "names": [{"name": "De Anza College"}], "isCommunityCollege": True},
    {"id": 117, "names": [{"name": "UCLA", "hideInList": True}, {"name": "University of California, Los Angeles"}],
     "isCommunityCollege": False},
]


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def agreement_result(key: str) -> dict[str, Any]:
    return load(AGREEMENT_FILES[key])["result"]


class FakeAssist:
    def __init__(self) -> None:
        self.token_n = 0
        self.requests: list[httpx.Request] = []

    @property
    def token(self) -> str:
        return f"tok-{self.token_n}"

    def rotate(self) -> None:
        """Simulate the site expiring the token we hold."""
        self.token_n += 1

    def count(self, path: str) -> int:
        return sum(r.url.path == path for r in self.requests)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, q = request.url.path, request.url.params
        if path == "/":
            self.token_n += 1
            return httpx.Response(
                200,
                text="<html></html>",
                headers=[
                    ("set-cookie", f"X-XSRF-TOKEN={self.token}; path=/"),
                    ("set-cookie", f"XSRF-TOKEN=cookie-{self.token}; path=/; httponly"),
                ],
            )
        if request.headers.get("X-XSRF-TOKEN") != self.token:
            return httpx.Response(400, json={"title": "Bad Request", "code": 400})
        if path == "/api/institutions":
            return httpx.Response(200, json=INSTITUTIONS)
        if path == "/api/institutions/113/agreements":
            return httpx.Response(200, json=[
                {"institutionParentId": 39, "sendingYearIds": [], "receivingYearIds": [75, 76, 77]},
                {"institutionParentId": 79, "sendingYearIds": [], "receivingYearIds": [74, 76]},
                # UCLA: nothing published for 2026–27 yet (I-17); listed twice, as ASSIST does.
                {"institutionParentId": 117, "sendingYearIds": [], "receivingYearIds": [74, 75]},
                {"institutionParentId": 117, "sendingYearIds": [], "receivingYearIds": [76]},
                {"institutionParentId": 58, "sendingYearIds": [76, 77], "receivingYearIds": []},  # CC → CC
            ])
        if path == "/api/agreements":
            pair = (q.get("sendingInstitutionId"), q.get("receivingInstitutionId"), q.get("academicYearId"))
            if pair in (("113", "39", "77"), ("113", "39", "74")):
                return httpx.Response(200, json=load(f"majors-113-39-{pair[2]}.json"))
            if pair == ("113", "79", "76"):
                return httpx.Response(200, json={"reports": [
                    {"label": "Economics, B.A.", "key": BERKELEY_ECON_KEY, "ownerInstitutionId": 79},
                ], "allReports": []})
            return httpx.Response(200, json={"reports": [], "allReports": []})
        if path == "/api/articulation/Agreements":
            key = q.get("Key")
            if key in AGREEMENT_FILES:
                return httpx.Response(200, json=load(AGREEMENT_FILES[key]))
            return httpx.Response(400, json={"result": None, "isSuccessful": False, "validationFailure": {
                "isValid": False, "errors": [{"propertyName": "Key", "errorMessage": "Agreement was not found"}],
            }})
        return httpx.Response(404)


def fake_service(fake: FakeAssist | None = None) -> tuple[AssistService, FakeAssist]:
    fake = fake or FakeAssist()
    client = AssistClient(transport=httpx.MockTransport(fake))
    return AssistService(client, ArticulationCache()), fake
