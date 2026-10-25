"""The campus registry: data/campuses/<assist_id>.json, one file per school we hold extra data for.

Application code knows no school by name, id or key. Everything school-specific (names, term
system, degree requirements, opportunity sources, programs, University-guide sources) is read
from here by the ASSIST id on the student's profile, and every school goes through the same code
path. A school with no file is still fully supported: ASSIST gives its name and agreements, and
it simply has no curated requirements, opportunities or guide (data/campuses/README.md).
"""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CAMPUSES_DIR = Path(
    os.getenv("CAMPUSES_DIR") or Path(__file__).resolve().parents[4] / "data" / "campuses"
)

TermSystem = Literal["quarter", "semester"]
# When neither ASSIST nor the registry says: most California colleges and universities use semesters.
DEFAULT_TERM_SYSTEM: TermSystem = "semester"


class FeedVocabulary(BaseModel):
    """Words a school's own feeds use that ranking and sorting need to recognize."""

    staff_audience_tags: list[str] = []  # calendar audience tags meaning "not for students"
    wellness_tags: list[str] = []  # event tags that mean Growth › Wellness & Community
    faculty_prefixes: list[str] = []  # "for <prefix> faculty" means a faculty-only listing


class Opportunities(BaseModel):
    # The `campus` value on this school's stored listings, Radar runs and agent jobs. It's an opaque
    # key from the data, kept so rows stored before the registry still match.
    feed: str = Field(min_length=1, pattern=r"^[a-z0-9-]+$")
    sources: str  # Radar sources file, relative to the campuses directory
    programs: str | None = None  # recurring programs file, relative to the campuses directory
    vocabulary: FeedVocabulary = FeedVocabulary()


class UniversityGuide(BaseModel):
    sources: str  # guide source pages, relative to the campuses directory
    guide: str  # the checked-in guide, relative to the campuses directory


class Campus(BaseModel):
    assist_id: int
    name: str  # display name
    short_name: str  # for running text: "<short>'s advisors"
    term_system: TermSystem | None = None  # used only when ASSIST's institution data can't say
    requirements: list[str] = []  # curated degree-requirements files: the "Full Plan"
    opportunities: Opportunities | None = None
    university_guide: UniversityGuide | None = None

    def path(self, relative: str) -> Path:
        return CAMPUSES_DIR / relative


class Registry(BaseModel):
    campuses: dict[int, Campus]

    @model_validator(mode="after")
    def _unique_feeds(self) -> "Registry":
        feeds = [c.opportunities.feed for c in self.campuses.values() if c.opportunities]
        if len(feeds) != len(set(feeds)):
            raise ValueError(f"two campuses share an opportunities feed: {sorted(feeds)}")
        return self


@lru_cache(maxsize=4)
def load(directory: Path | None = None) -> Registry:
    directory = directory or CAMPUSES_DIR
    campuses: dict[int, Campus] = {}
    for path in sorted(directory.glob("*.json")):
        campus = Campus.model_validate(json.loads(path.read_text()))
        if path.stem != str(campus.assist_id):
            raise ValueError(f"{path.name}: assist_id {campus.assist_id} doesn't match the file name")
        campuses[campus.assist_id] = campus
    return Registry(campuses=campuses)


def get(assist_id: int | None) -> Campus | None:
    return load().campuses.get(assist_id) if assist_id is not None else None


def all_campuses() -> list[Campus]:
    return list(load().campuses.values())


def by_feed(feed: str) -> Campus | None:
    return next((c for c in all_campuses() if c.opportunities and c.opportunities.feed == feed), None)


def feeds() -> list[str]:
    """Every opportunities feed, in registry order."""
    return [c.opportunities.feed for c in all_campuses() if c.opportunities]


def feed_of(assist_id: int | None) -> str | None:
    campus = get(assist_id)
    return campus.opportunities.feed if campus and campus.opportunities else None


def short_name(assist_id: int | None, fallback: str) -> str:
    campus = get(assist_id)
    return campus.short_name if campus else fallback


def has_requirements(assist_id: int | None) -> bool:
    campus = get(assist_id)
    return bool(campus and campus.requirements)


def term_system(assist_id: int | None) -> TermSystem | None:
    campus = get(assist_id)
    return campus.term_system if campus else None


def vocabulary() -> FeedVocabulary:
    """Every feed's vocabulary together: the words are specific enough that one campus's never
    misfire on another's listings."""
    vocab = [c.opportunities.vocabulary for c in all_campuses() if c.opportunities]
    return FeedVocabulary(**{field: sorted({w.casefold() for v in vocab for w in getattr(v, field)})
                             for field in FeedVocabulary.model_fields})


PROFILE_FEED_NONE = "other"


def profile_feed(receiving_institution_id: int) -> str:
    """The value stored in a profile's legacy `campus` column: the target university's feed, or
    "other". Kept for older rows and clients; nothing looks a school up by it."""
    return feed_of(receiving_institution_id) or PROFILE_FEED_NONE
