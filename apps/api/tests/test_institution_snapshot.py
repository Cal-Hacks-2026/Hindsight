"""The committed institution snapshot the web app falls back to when ASSIST's live lists fail
(apps/web/src/lib/institutions.ts, built by scripts/snapshot_institutions.py)."""

import datetime
import json
from pathlib import Path

from app.config import ASSIST_YEAR_ID, CAMPUS_BY_ASSIST_ID
from app.models import AssistInstitution

SNAPSHOT = Path(__file__).resolve().parents[3] / "apps/web/src/data/institutions-snapshot.json"


def load() -> dict:
    return json.loads(SNAPSHOT.read_text())


def test_colleges_match_the_contract_and_are_sorted():
    snap = load()
    datetime.date.fromisoformat(snap["saved_on"])
    colleges = [AssistInstitution(**c) for c in snap["colleges"]]
    assert len(colleges) > 100
    assert all(c.term_system in ("quarter", "semester") for c in colleges)
    names = [c.name.casefold() for c in colleges]
    assert names == sorted(names)
    assert len({c.id for c in colleges}) == len(colleges)


def test_every_college_has_universities_that_resolve():
    snap = load()
    unis = snap["universities"]
    for c in snap["colleges"]:
        pairs = snap["agreements"][str(c["id"])]
        assert pairs, c["name"]
        for uid, year in pairs:
            u = unis[str(uid)]
            AssistInstitution(id=uid, name=u["name"], year_id=year, full_plan=u.get("full_plan"))
            assert 0 < year <= ASSIST_YEAR_ID


def test_only_curated_universities_are_full_plan():
    full = {int(uid) for uid, u in load()["universities"].items() if u.get("full_plan")}
    assert full and full <= set(CAMPUS_BY_ASSIST_ID)
