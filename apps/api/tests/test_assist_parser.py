from app.services.assist import parse_agreement
from tests.assist_fake import BERKELEY_ECON_KEY, DS_KEY, ECON_BS_KEY, agreement_result


def test_parses_metadata():
    a = parse_agreement(agreement_result(DS_KEY), DS_KEY)
    assert a.name == "Data Science, B.S."
    assert (a.year_id, a.year_code) == (77, "2026-2027")
    assert (a.sending.id, a.sending.name) == (113, "De Anza College")
    assert (a.receiving.id, a.receiving.name) == (39, "San Jose State University")
    assert a.general_text  # policy HTML kept for the counselor


def test_groups_sorted_by_position_with_titles():
    a = parse_agreement(agreement_result(DS_KEY), DS_KEY)
    assert [g.position for g in a.groups] == sorted(g.position for g in a.groups)
    assert [g.title for g in a.groups] == [
        "SECOND COURSE IN ENGLISH COMPOSITION",
        "PREPARATION FOR THE MAJOR",
        "LOWER DIVISION CORE REQUIREMENTS OF THE MAJOR",
        "MAJOR ELECTIVES",
    ]
    assert [g.instruction.type for g in a.groups] == ["NFromArea", "Following", "Following", None]
    assert a.groups[0].instruction.amount == 1
    assert a.groups[1].attributes == ("Minimum grade required: C- or better",)
    rows = a.groups[1].sections[0].rows
    assert [r.label for r in rows] == [
        "MATH 30 - Calculus I",
        "MATH 31 - Calculus II",
        "MATH 39 - Linear Algebra I",
        "MATH 42 - Discrete Mathematics",
    ]


def test_cells_joined_to_articulations_by_template_cell_id():
    a = parse_agreement(agreement_result(DS_KEY), DS_KEY)
    cs46a = a.groups[2].sections[0].rows[0].cells[0]
    art = cs46a.articulation
    assert art is not None and art.no_articulation_reason is None
    # Or between course groups, And within: CIS 35A | CIS 22A+22B | CIS 22A+22BH | CIS 36A+36B | CIS 27
    assert [[c.code for c in g.courses] for g in art.groups] == [
        ["CIS 35A"], ["CIS 22A", "CIS 22B"], ["CIS 22A", "CIS 22BH"], ["CIS 36A", "CIS 36B"], ["CIS 27"],
    ]
    assert all(g.conjunction == "And" for g in art.groups)
    assert {c for c, _, _ in art.group_conjunctions} == {"Or"}
    assert "Complete entire sequence at same institution prior to transfer" in art.groups[1].courses[1].attributes
    assert art.groups[4].courses[0].end == "F2026"


def test_cell_without_articulation_record():
    a = parse_agreement(agreement_result(DS_KEY), DS_KEY)
    electives = {r.cells[0].courses[0].number: r.cells[0] for r in a.groups[3].sections[0].rows}
    assert electives["48"].articulation is None
    assert electives["47"].articulation is not None


def test_group_without_title_and_section_attributes():
    a = parse_agreement(agreement_result(ECON_BS_KEY), ECON_BS_KEY)
    assert a.groups[0].title == "Requirements"
    assert a.groups[1].sections[0].attributes == ("Minimum grade required: C or better",)


def test_berkeley_conjunction_and_nfollowing_sections():
    a = parse_agreement(agreement_result(BERKELEY_ECON_KEY), BERKELEY_ECON_KEY)
    req, rec = a.groups
    assert (req.instruction.type, req.instruction.conjunction) == ("Conjunction", "And")
    assert [(s.n_amount, s.n_unit) for s in req.sections] == [(None, None), (1.0, "Sequence")]
    assert rec.instruction.type == "NFromFollowing"
    stat20 = rec.sections[0].rows[0].cells[0]
    assert stat20.articulation.no_articulation_reason == "No Course Articulated"
