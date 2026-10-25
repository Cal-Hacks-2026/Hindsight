"""`class_schedule` in Supabase (migrations/20261025_class_schedule.sql).

Only confirmed rows are stored; an upload's unconfirmed rows live in the browser until the
student confirms them, as with transcripts.
"""

import uuid

import httpx

from app.models import ScheduledClass
from app.services.profile_store import _call

COLUMNS = ("term,course,title,crn,section,professor,units,location,mode,days,"
           "start_time,end_time,start_date,end_date")


def _to_row(profile_id: str, position: int, row: ScheduledClass) -> dict:
    return {"id": str(uuid.uuid4()), "profile_id": profile_id, "position": position,
            **row.model_dump(exclude={"flags", "confirmed"})}


def _from_row(row: dict) -> ScheduledClass:
    # Postgres `time` comes back as "09:30:00".
    for field in ("start_time", "end_time"):
        if row.get(field):
            row[field] = row[field][:5]
    if row.get("units") is not None:
        row["units"] = float(row["units"])
    return ScheduledClass(**row, confirmed=True)


def replace_schedule(profile_id: str, rows: list[ScheduledClass],
                     transport: httpx.BaseTransport | None = None) -> None:
    """Insert the new set, then delete the profile's other rows, so a failed write never
    leaves the student with no schedule."""
    new = [_to_row(profile_id, i, r) for i, r in enumerate(rows)]
    if new:
        _call(transport, "POST", "/class_schedule", json=new, headers={"Prefer": "return=minimal"})
    stale = {"profile_id": f"eq.{profile_id}"}
    if new:
        stale["id"] = f"not.in.({','.join(r['id'] for r in new)})"
    _call(transport, "DELETE", "/class_schedule", params=stale, headers={"Prefer": "return=minimal"})


def schedule(profile_id: str, transport: httpx.BaseTransport | None = None) -> list[ScheduledClass]:
    res = _call(transport, "GET", "/class_schedule", params={
        "select": COLUMNS, "profile_id": f"eq.{profile_id}", "order": "position"})
    return [_from_row(r) for r in res.json()]
