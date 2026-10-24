"""Turn a raw ASSIST agreement into a typed, position-ordered structure.

Shape notes (PROJECT.md §8.1), all verified against saved agreements:
- `templateAssets` and `articulations` are JSON strings inside the JSON.
- Every array is unordered; sort by `position`.
- `templateAssets` interleaves RequirementTitle / RequirementGroup (area
  "Requirements") with GeneralTitle / GeneralText (area "General"). A group's
  title is the nearest RequirementTitle positioned before it.
- Each receiving-course cell has an `id`; `articulations[].templateCellId`
  joins the sending side onto it. A cell with no articulation record has no
  articulation at all.
"""

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SendingCourse:
    prefix: str
    number: str
    title: str
    units: float
    begin: str  # e.g. "F2024"; "" when unknown
    end: str  # "" when still active
    attributes: tuple[str, ...]
    cross_listed: tuple[tuple[str, str], ...] = ()

    @property
    def code(self) -> str:
        return f"{self.prefix} {self.number}"


@dataclass(frozen=True)
class CourseGroup:
    """Sending courses joined by `conjunction` (almost always "And")."""

    position: int
    conjunction: str
    courses: tuple[SendingCourse, ...]
    attributes: tuple[str, ...]


@dataclass(frozen=True)
class Articulation:
    no_articulation_reason: str | None
    groups: tuple[CourseGroup, ...]
    # (conjunction, begin position, end position) between course groups.
    group_conjunctions: tuple[tuple[str, int, int], ...]
    denied: tuple[SendingCourse, ...]
    attributes: tuple[str, ...]


@dataclass(frozen=True)
class ReceivingCourse:
    prefix: str
    number: str
    title: str
    units: float

    @property
    def label(self) -> str:
        return f"{self.prefix} {self.number} - {self.title}"


@dataclass(frozen=True)
class Cell:
    id: str  # = articulations[].templateCellId
    courses: tuple[ReceivingCourse, ...]  # >1 for a Series cell
    attributes: tuple[str, ...]
    articulation: Articulation | None

    @property
    def label(self) -> str:
        return " + ".join(c.label for c in self.courses)


@dataclass(frozen=True)
class Row:
    position: int
    cells: tuple[Cell, ...]
    attributes: tuple[str, ...]

    @property
    def label(self) -> str:
        return " + ".join(c.label for c in self.cells)


@dataclass(frozen=True)
class Section:
    position: int
    rows: tuple[Row, ...]
    attributes: tuple[str, ...]  # includes any preceding SectionHeader's attributes
    header: str | None
    # From an `NFollowing` advisement: complete `n_amount` of this section's rows.
    n_amount: float | None = None
    n_unit: str | None = None  # "Course" | "Sequence" | "Unit"


@dataclass(frozen=True)
class Instruction:
    type: str | None  # Following | NFromArea | NFromFollowing | Conjunction | None
    amount: float | None = None
    unit: str | None = None  # amountUnitType: Course | Unit | ...
    conjunction: str | None = None  # for type == Conjunction


@dataclass(frozen=True)
class RequirementGroup:
    id: str
    position: int
    title: str
    instruction: Instruction
    attributes: tuple[str, ...]
    sections: tuple[Section, ...]


@dataclass(frozen=True)
class Institution:
    id: int
    name: str


@dataclass(frozen=True)
class Agreement:
    key: str
    name: str  # major label, e.g. "Data Science, B.S."
    year_id: int
    year_code: str  # e.g. "2026-2027"
    sending: Institution
    receiving: Institution
    groups: tuple[RequirementGroup, ...]
    general_text: tuple[str, ...] = field(default=())  # raw HTML policy blocks


def _loads(value: Any) -> Any:
    """ASSIST double-encodes; tolerate already-decoded values and nulls."""
    if value is None:
        return None
    return json.loads(value) if isinstance(value, str) else value


def _by_position(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return sorted(items or [], key=lambda x: x.get("position") or 0)


def _attrs(*lists: list[dict[str, Any]] | None) -> tuple[str, ...]:
    out: list[str] = []
    for items in lists:
        for a in _by_position(items):
            if content := (a.get("content") or "").strip():
                out.append(content)
    return tuple(out)


def _institution(raw: Any, fallback_id: int) -> Institution:
    data = _loads(raw) or {}
    names = sorted(data.get("names") or [], key=lambda n: n.get("fromYear") or 0)
    name = names[-1]["name"] if names else f"Institution {fallback_id}"
    return Institution(id=data.get("id", fallback_id), name=name)


def _sending_course(c: dict[str, Any]) -> SendingCourse:
    return SendingCourse(
        prefix=(c.get("prefix") or "").strip(),
        number=(c.get("courseNumber") or "").strip(),
        title=(c.get("courseTitle") or "").strip(),
        units=float(c.get("maxUnits") or c.get("minUnits") or 0),
        begin=c.get("begin") or "",
        end=c.get("end") or "",
        attributes=_attrs(c.get("attributes")),
        cross_listed=tuple(
            ((x.get("prefix") or "").strip(), (x.get("courseNumber") or "").strip())
            for x in c.get("visibleCrossListedCourses") or []
        ),
    )


def _receiving_course(c: dict[str, Any]) -> ReceivingCourse:
    return ReceivingCourse(
        prefix=(c.get("prefix") or "").strip(),
        number=(c.get("courseNumber") or "").strip(),
        title=(c.get("courseTitle") or "").strip(),
        units=float(c.get("maxUnits") or c.get("minUnits") or 0),
    )


def _articulation(record: dict[str, Any]) -> Articulation:
    art = record.get("articulation") or {}
    sending = art.get("sendingArticulation") or {}
    groups: list[CourseGroup] = []
    for g in _by_position(sending.get("items")):
        # Only CourseGroups of Courses exist in practice; skip anything else
        # rather than guess at its meaning.
        if g.get("type") != "CourseGroup":
            continue
        courses = tuple(
            _sending_course(c) for c in _by_position(g.get("items")) if c.get("type") == "Course"
        )
        if courses:
            groups.append(
                CourseGroup(
                    position=g.get("position") or 0,
                    conjunction=g.get("courseConjunction") or "And",
                    courses=courses,
                    attributes=_attrs(g.get("attributes")),
                )
            )
    return Articulation(
        no_articulation_reason=sending.get("noArticulationReason"),
        groups=tuple(groups),
        group_conjunctions=tuple(
            (
                gc.get("groupConjunction") or "Or",
                gc.get("sendingCourseGroupBeginPosition") or 0,
                gc.get("sendingCourseGroupEndPosition") or 0,
            )
            for gc in sending.get("courseGroupConjunctions") or []
        ),
        denied=tuple(_sending_course(c) for c in sending.get("deniedCourses") or []),
        attributes=_attrs(
            sending.get("attributes"),
            art.get("attributes"),
            art.get("courseAttributes"),
            (record.get("receivingAttributes") or {}).get("attributes"),
            (record.get("receivingAttributes") or {}).get("courseAttributes"),
        ),
    )


def _cell(c: dict[str, Any], articulations: dict[str, Articulation]) -> Cell | None:
    if c.get("type") == "Course" and c.get("course"):
        courses = (_receiving_course(c["course"]),)
    elif c.get("type") == "Series" and c.get("series"):
        courses = tuple(_receiving_course(x) for x in _by_position(c["series"].get("courses")))
    else:
        return None
    return Cell(
        id=c["id"],
        courses=courses,
        attributes=_attrs(c.get("courseAttributes"), c.get("attributes")),
        articulation=articulations.get(c["id"]),
    )


def _instruction(raw: dict[str, Any] | None) -> Instruction:
    if not raw:
        return Instruction(type=None)
    return Instruction(
        type=raw.get("type"),
        amount=raw.get("amount"),
        unit=raw.get("amountUnitType"),
        conjunction=raw.get("conjunction"),
    )


def _sections(group: dict[str, Any], articulations: dict[str, Articulation]) -> tuple[Section, ...]:
    out: list[Section] = []
    header: str | None = None
    header_attrs: tuple[str, ...] = ()
    for s in _by_position(group.get("sections")):
        if s.get("type") == "SectionHeader":
            # Applies to the sections that follow it, until the next header.
            header = (s.get("content") or "").strip() or None
            header_attrs = _attrs(s.get("attributes"))
            continue
        rows = []
        for r in _by_position(s.get("rows")):
            cells = tuple(
                cell for c in _by_position(r.get("cells")) if (cell := _cell(c, articulations))
            )
            if cells:
                rows.append(Row(position=r.get("position") or 0, cells=cells,
                                attributes=_attrs(r.get("attributes"))))
        n_follow = next(
            (a for a in s.get("advisements") or [] if a.get("type") == "NFollowing"), None
        )
        out.append(
            Section(
                position=s.get("position") or 0,
                rows=tuple(rows),
                attributes=header_attrs + _attrs(s.get("attributes")),
                header=header,
                n_amount=n_follow.get("amount") if n_follow else None,
                n_unit=n_follow.get("amountUnitType") if n_follow else None,
            )
        )
    return tuple(out)


def parse_agreement(result: dict[str, Any], key: str) -> Agreement:
    """`result` is the `result` object from /api/articulation/Agreements."""
    assets = _loads(result.get("templateAssets")) or []
    articulations = {
        a["templateCellId"]: _articulation(a)
        for a in _loads(result.get("articulations")) or []
        if a.get("templateCellId")
    }
    year = _loads(result.get("academicYear")) or {}
    sending = _institution(result.get("sendingInstitution"), 0)
    receiving = _institution(result.get("receivingInstitution"), 0)

    # Positions are only unique within an area; General-area assets have their own sequence.
    requirement_assets = _by_position(
        [a for a in assets if a.get("area", "Requirements") == "Requirements"]
    )
    groups: list[RequirementGroup] = []
    title = ""
    for asset in requirement_assets:
        if asset.get("type") == "RequirementTitle":
            title = (asset.get("content") or "").strip()
        elif asset.get("type") == "RequirementGroup":
            groups.append(
                RequirementGroup(
                    id=asset.get("groupId") or f"group-{asset.get('position')}",
                    position=asset.get("position") or 0,
                    title=title or "Requirements",
                    instruction=_instruction(asset.get("instruction")),
                    attributes=_attrs(asset.get("attributes")),
                    sections=_sections(asset, articulations),
                )
            )
    general = tuple(
        a.get("content") or ""
        for a in _by_position(assets)
        if a.get("type") == "GeneralText" and a.get("content")
    )
    return Agreement(
        key=key,
        name=(result.get("name") or "").strip(),
        year_id=year.get("id") or int(key.split("/")[0]),
        year_code=year.get("code") or "",
        sending=sending,
        receiving=receiving,
        groups=tuple(groups),
        general_text=general,
    )
