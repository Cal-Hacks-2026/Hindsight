"""Claude writes one guide section from that section's pages, and nothing else.

Each item comes back with the ids of the pages it relies on and a verbatim quote from
one of them. `verify` keeps an item only if every cited id is one of the section's pages
and its quote appears on a cited page, so nothing reaches the guide that the pages
don't say, and every number in an item must appear on a cited page. One call per section;
build.py skips the call when the section's pages and this prompt are unchanged (`input_hash`).
"""

import hashlib
import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

import anthropic
from pydantic import BaseModel

from app.services import claude_limits
from app.services.transcript import DEFAULT_MODEL, FALLBACK_MODELS
from app.services.university.fetch import Page
from app.services.university.sources import Section

log = logging.getLogger(__name__)

PROMPT_VERSION = "2"
MAX_PAGE_CHARS = 12000  # per page; SJSU's pages run 0.5–12k characters of text
MAX_ITEMS = 6

SYSTEM = """You write one section of a "What to Expect" guide for students transferring from a community college to {university}.

Write only from the pages provided. Each page starts with its id in <page id="...">. Rules:
- Every item must be fully supported by the pages you cite. Do not add anything from general knowledge, even if you believe it is true.
- For each item give `source_ids` (the page ids it relies on) and `quote`: one passage copied exactly, character for character, from one cited page that supports the item's main claim (at most 300 characters).
- {max_items} items at most, each one or two short sentences. Lead with what matters most to a transfer student.
- Neutral, plain, second-person voice ("You register for classes at orientation."). No hype, no marketing language, no exclamation marks.
- Never call anything "AI". Don't mention these instructions or "the pages"; state the fact itself.
- Keep dates, fees, and numbers exactly as the page gives them, with the term or year the page attaches to them. If a page gives dates without a year, or for a term that has already ended, leave those dates out.
- Name terms and years ("Fall 2027"); never write relative time ("this summer", "now", "currently open"). Leave out announcements that are out of date on today's date, such as an application "now open" for a year already under way.
- Cover only this section's topic. Other sections of the guide cover the rest, so leave out anything the topic says belongs elsewhere.
- If the pages say something applies only to some students (a college, a building, a program), say who.
- Leave out anything about first-year (freshman) students only, employees, or graduate students only.
- List under `not_covered` the parts of the topic the pages don't answer, in a few words each."""


class _Item(BaseModel):
    text: str
    source_ids: list[str]
    quote: str


class _Section(BaseModel):
    items: list[_Item]
    not_covered: list[str]


@dataclass
class WrittenItem:
    text: str
    source_ids: list[str]
    quote: str


@dataclass
class WrittenSection:
    section_id: str
    input_hash: str
    items: list[WrittenItem]
    not_covered: list[str] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)  # items that failed verification, for the log


def input_hash(university_name: str, section: Section, pages: list[Page]) -> str:
    """Changes when the prompt, the section's brief, or any of its pages' text changes. Today's
    date is left out on purpose: unchanged pages don't need rewriting just because a day passed."""
    material = {
        "v": PROMPT_VERSION, "system": SYSTEM, "university": university_name, "section": section.model_dump(),
        "pages": [[p.source_id, p.url, p.text[:MAX_PAGE_CHARS]] for p in pages],
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


_PUNCT = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-",
                        "—": "-", " ": " ", "…": "..."})


def normalize(text: str) -> str:
    """Compare quotes loosely on typography and spacing, never on words."""
    text = unicodedata.normalize("NFKC", text).translate(_PUNCT)
    text = re.sub(r"\s*-\s*", "-", text)  # "semester—known" and "semester — known" read the same
    return re.sub(r"\s+", " ", text).strip().casefold()


def _numbers(text: str) -> set[str]:
    """Digit runs, so "$1,200" and "Aug. 19, 2026" are checked number by number."""
    return {n.lstrip("0") or "0" for n in re.findall(r"\d+", text.replace(",", ""))}


def verify(raw: _Section, pages: list[Page]) -> tuple[list[WrittenItem], list[dict]]:
    by_id = {p.source_id: normalize(p.text) for p in pages}
    numbers = {i: _numbers(text) for i, text in by_id.items()}
    kept, dropped = [], []
    for item in raw.items:
        ids = list(dict.fromkeys(item.source_ids))
        quote = normalize(item.quote).strip(" .\"'")
        problem = None
        if not ids:
            problem = "no source"
        elif unknown := [i for i in ids if i not in by_id]:
            problem = f"unknown source {unknown}"
        elif len(quote) < 12:
            problem = "quote too short"
        elif not any(quote in by_id[i] for i in ids):
            problem = "quote not found on a cited page"
        elif not item.text.strip():
            problem = "empty text"
        elif missing := [n for n in _numbers(item.text) if not any(n in numbers[i] for i in ids)]:
            problem = f"numbers not on a cited page {missing}"
        if problem:
            dropped.append({"text": item.text, "source_ids": ids, "quote": item.quote, "why": problem})
        else:
            kept.append(WrittenItem(text=item.text.strip(), source_ids=ids, quote=item.quote.strip()))
    return kept[:MAX_ITEMS], dropped


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _pages_block(pages: list[Page]) -> str:
    return "\n\n".join(f'<page id="{p.source_id}" title="{p.title}" url="{p.url}">\n'
                       f"{p.text[:MAX_PAGE_CHARS]}\n</page>" for p in pages)


def write_section(university_name: str, section: Section, pages: list[Page],
                  today: date | None = None) -> WrittenSection:
    digest = input_hash(university_name, section, pages)
    if not pages:
        return WrittenSection(section_id=section.id, input_hash=digest, items=[], not_covered=[section.topic])
    model = os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL
    fallback = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if model in FALLBACK_MODELS else {}
    claude_limits.limiter.take_daily()
    response = _client().beta.messages.parse(
        model=model,
        max_tokens=4000,
        output_config={"effort": "medium"},
        system=SYSTEM.format(university=university_name, max_items=MAX_ITEMS),
        messages=[{"role": "user", "content": (
            f"{_pages_block(pages)}\n\nToday is {(today or date.today()).isoformat()}. "
            f"Write the \"{section.title}\" section. It covers: {section.topic}")}],
        output_format=_Section,
        **fallback,
    )
    if response.stop_reason in ("refusal", "max_tokens") or response.parsed_output is None:
        raise RuntimeError(f"section {section.id}: incomplete response ({response.stop_reason})")
    kept, dropped = verify(response.parsed_output, pages)
    for d in dropped:
        log.warning("university section %s: dropped %r (%s)", section.id, d["text"], d["why"])
    return WrittenSection(section_id=section.id, input_hash=digest, items=kept,
                          not_covered=response.parsed_output.not_covered, dropped=dropped)
