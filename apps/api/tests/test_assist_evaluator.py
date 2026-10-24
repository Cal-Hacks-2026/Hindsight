"""And/Or evaluator against saved real agreements (De Anza → SJSU / UC Berkeley)."""

import json

import pytest

from app.models import Course, MatchResult, Requirement
from app.services.assist import evaluate, parse_agreement
from tests.assist_fake import BERKELEY_ECON_KEY, DS_KEY, ECON_BS_KEY, agreement_result


def c(code: str, grade: str = "A", term: str = "Fall 2025") -> Course:
    prefix, number = code.split()
    return Course(prefix=prefix, number=number, title="", units=5, grade=grade, term=term,
                  confirmed=True)


def match(key: str, *courses: Course) -> MatchResult:
    return evaluate(parse_agreement(agreement_result(key), key), list(courses))


def req(result: MatchResult, receiving: str) -> Requirement:
    hits = [r for r in result.requirements if r.receiving_course.startswith(receiving)]
    assert len(hits) == 1, [r.receiving_course for r in result.requirements]
    return hits[0]


def test_empty_transcript_satisfies_nothing():
    r = match(DS_KEY)
    assert r.major_label == "Data Science, B.S." and r.agreement_key == DS_KEY
    assert r.summary.satisfied == 0
    s = r.summary
    assert s.satisfied + s.partial + s.missing + s.at_university == len(r.requirements) == 8


def test_or_between_course_groups():
    assert req(match(DS_KEY, c("MATH 1A")), "MATH 30").status == "satisfied"
    hit = req(match(DS_KEY, c("MATH 1AH")), "MATH 30")
    assert (hit.status, hit.satisfied_by, hit.confidence) == ("satisfied", ["MATH 1AH"], "high")


def test_and_within_course_group_and_sequence_rule():
    half = req(match(DS_KEY, c("MATH 1B")), "MATH 31")
    assert half.status == "partial"
    assert half.satisfied_by == ["MATH 1B"]
    assert "sequence_rule" in half.flags

    full = req(match(DS_KEY, c("MATH 1B"), c("MATH 1C")), "MATH 31")
    assert (full.status, full.satisfied_by) == ("satisfied", ["MATH 1B", "MATH 1C"])
    assert "sequence_rule" not in full.flags

    mixed = req(match(DS_KEY, c("MATH 1BH"), c("MATH 1C")), "MATH 31")
    assert mixed.status == "satisfied"


def test_partial_sequence_earns_nothing_but_alternative_path_works():
    cs46a = req(match(DS_KEY, c("CIS 22A")), "CS 46A")
    assert cs46a.status == "partial" and "sequence_rule" in cs46a.flags
    assert req(match(DS_KEY, c("CIS 22A"), c("CIS 35A")), "CS 46A").status == "satisfied"


def test_group_level_minimum_grade():
    below = req(match(DS_KEY, c("MATH 1A", "D+")), "MATH 30")
    assert below.status == "missing"
    assert {"min_grade_C-", "below_min_grade"} <= set(below.flags)
    ok = req(match(DS_KEY, c("MATH 1A", "C-")), "MATH 30")
    assert ok.status == "satisfied" and "below_min_grade" not in ok.flags


def test_section_level_minimum_grade():
    # SJSU Econ B.S. puts "C or better" on the section (and each course), not the group.
    stats = req(match(ECON_BS_KEY, c("STAT C1000", "C-")), "STAT 95")
    assert stats.status == "missing" and {"min_grade_C", "below_min_grade"} <= set(stats.flags)
    assert req(match(ECON_BS_KEY, c("STAT C1000", "C")), "STAT 95").status == "satisfied"


def test_pass_grade_under_a_grade_rule_counts_with_low_confidence():
    hit = req(match(DS_KEY, c("MATH 1A", "P")), "MATH 30")
    assert (hit.status, hit.confidence) == ("satisfied", "low")
    assert "pass_no_pass" in hit.flags


@pytest.mark.parametrize("grade", ["F", "W", "NP", "I", ""])
def test_non_completing_grades_do_not_count(grade):
    assert req(match(DS_KEY, c("MATH 1A", grade)), "MATH 30").status == "missing"


def test_in_progress_grade_does_not_count_yet():
    hit = req(match(DS_KEY, c("MATH 1A", "IP")), "MATH 30")
    assert (hit.status, hit.satisfied_by) == ("in_progress", ["MATH 1A"])


def test_retake_best_attempt_wins():
    hit = req(match(DS_KEY, c("MATH 1A", "F", "Fall 2024"), c("MATH 1A", "B", "Winter 2025")), "MATH 30")
    assert hit.status == "satisfied"


def test_n_from_area_collapses_to_one_requirement():
    r = match(DS_KEY, c("ENGL C1001"))
    engl = req(r, "ENGL 1B")
    assert (engl.rule, engl.n, engl.status) == ("n_of", 1, "satisfied")
    assert engl.receiving_course == "ENGL 1B - Argument and Analysis or ENGL 2 - Critical Thinking and Writing"
    assert engl.satisfied_by == ["ENGL C1001"]
    assert req(match(DS_KEY), "ENGL 1B").status == "missing"


def test_no_articulation_reason_means_at_university():
    stat = req(match(BERKELEY_ECON_KEY, c("STAT C1000")), "STAT 20")
    assert (stat.status, stat.rule, stat.n) == ("at_university", "n_of", 1)
    assert stat.flags == ["no_current_articulation"]


def test_conjunction_and_sections_and_sequence_advisement():
    r = match(BERKELEY_ECON_KEY, c("MATH 1A"), c("MATH 1B"), c("MATH 1C"))
    calc = req(r, "MATH 51")
    assert (calc.status, calc.rule, calc.n) == ("satisfied", "n_of", 1)
    assert "sequence_grouping_inferred" in calc.flags and calc.confidence == "medium"
    assert calc.receiving_course.startswith("MATH 51 - Calculus I + MATH 52 - Calculus II or MATH 16A")

    one = req(match(BERKELEY_ECON_KEY, c("MATH 1A")), "MATH 51")
    assert one.status == "partial"

    econ = req(match(BERKELEY_ECON_KEY, c("ECON 1", term="Fall 2024")), "ECON 1")
    assert (econ.rule, econ.status, econ.satisfied_by) == ("all", "partial", ["ECON 1"])


def test_regular_and_honors_may_be_combined_when_attribute_says_so():
    hit = req(match(BERKELEY_ECON_KEY, c("ECON 1", term="Fall 2024"), c("ECON 2H", term="Fall 2024")), "ECON 1")
    assert hit.status == "satisfied"


def test_course_taken_outside_agreement_dates_is_flagged():
    # De Anza's current MATH 1A record begins F2024; an older MATH 1A may be a different course.
    old = req(match(DS_KEY, c("MATH 1A", term="Fall 2023")), "MATH 30")
    assert (old.status, old.confidence) == ("satisfied", "medium")
    assert "course_year_mismatch" in old.flags
    by_year = Course(prefix="MATH", number="1A", title="", units=5, grade="A", term="",
                     academic_year_id=74, confirmed=True)
    assert "course_year_mismatch" in req(match(DS_KEY, by_year), "MATH 30").flags


def test_unspecified_instruction_is_low_confidence_choose_from():
    r = match(DS_KEY, c("CIS 40"))
    elect = req(r, "Choose from:")
    assert (elect.rule, elect.status, elect.confidence) == ("n_of", "satisfied", "low")
    assert "unspecified_rule" in elect.flags
    body = r.model_dump(exclude_none=True)
    elect_json = next(x for x in body["requirements"] if x["id"] == elect.id)
    assert "n" not in elect_json


def test_and_between_course_groups():
    raw = agreement_result(DS_KEY)
    arts = json.loads(raw["articulations"])
    math30 = next(a for a in arts if a["articulation"]["course"]["courseNumber"] == "30")
    for gc in math30["articulation"]["sendingArticulation"]["courseGroupConjunctions"]:
        gc["groupConjunction"] = "And"
    raw["articulations"] = json.dumps(arts)
    agreement = parse_agreement(raw, DS_KEY)
    assert req(evaluate(agreement, [c("MATH 1A")]), "MATH 30").status == "partial"
    assert req(evaluate(agreement, [c("MATH 1A"), c("MATH 1AH")]), "MATH 30").status == "satisfied"


def test_citation_points_at_the_agreement():
    hit = req(match(DS_KEY, c("MATH 1A")), "MATH 30")
    cit = hit.citation
    assert cit.source == "assist"
    assert cit.label == "De Anza College → San Jose State University · Data Science, B.S. (2026–2027)"
    assert "viewByKey=77%2F113%2Fto%2F39%2FMajor%2F0739dd42" in cit.url
    assert cit.ref == "PREPARATION FOR THE MAJOR › MATH 30 - Calculus I"
    assert hit.id.startswith("523a4697")  # templateCellId


def test_all_rule_requirements_omit_n_when_serialized():
    body = match(DS_KEY, c("MATH 1A")).model_dump(exclude_none=True)
    assert all("n" not in r for r in body["requirements"] if r["rule"] == "all")
    MatchResult.model_validate(body)


def test_unsatisfied_rows_list_what_to_take_at_the_college():
    empty = match(DS_KEY)
    assert req(empty, "MATH 30").options == ["MATH 1A or MATH 1AH"]
    assert req(empty, "MATH 31").options == ["MATH 1B + MATH 1C (or honors)"]
    assert req(empty, "CS 46A").options == ["CIS 35A", "CIS 22A + CIS 22B (or honors)", "CIS 36A + CIS 36B", "CIS 27"]
    # "One of" rows pool their children's alternatives, without repeats.
    stats = req(match(ECON_BS_KEY), "STAT 95")
    assert stats.options == ["PSYC 15", "SOC 15", "STAT C1000 or STAT C1000H", "POLI 20"]

    partial = req(match(DS_KEY, c("CIS 22A")), "CS 46A")
    assert partial.status == "partial" and partial.options and "CIS 35A" in partial.options
    done = req(match(DS_KEY, c("MATH 1A")), "MATH 30")
    assert done.status == "satisfied" and done.options is None


def test_requirement_whose_only_gap_is_in_progress():
    ip = req(match(DS_KEY, c("MATH 1B"), c("MATH 1C", "IP", "Fall 2026")), "MATH 31")
    assert (ip.status, ip.satisfied_by, ip.options) == ("in_progress", ["MATH 1B", "MATH 1C"], None)
    assert "sequence_rule" not in ip.flags and "pass_no_pass" not in ip.flags

    # Still short even once the IP course passes (MATH 1B): not "in progress".
    short = req(match(DS_KEY, c("MATH 1C", "IP", "Fall 2026")), "MATH 31")
    assert short.status == "missing" and short.options == ["MATH 1B + MATH 1C (or honors)"]
    r = match(DS_KEY, c("MATH 1B"), c("MATH 1C", "IP", "Fall 2026"))
    assert r.summary.in_progress == 1
    assert sum(r.summary.model_dump().values()) == len(r.requirements)
