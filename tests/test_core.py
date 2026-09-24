from unittest import SkipTest

from app.confidence.scoring import score_class
from app.database.catalog import Catalog, Subject
from app.parsers.grid import parse_grids
from app.parsers.text import parse_class_text, parse_time_range
from app.schemas.models import Grid, RawCell
from app.standardization.matcher import Match


def grid_from_values(values):
    return Grid(rows=[[RawCell(text=value, row=r, column=c, cell_ref=f"{r}:{c}")
                       for c, value in enumerate(row, 1)] for r, row in enumerate(values, 1)])


def test_time_range():
    assert parse_time_range("9:20 - 10:10") == ("09:20", "10:10")
    assert parse_time_range("9.20 AM – 10.10 AM") == ("09:20", "10:10")


def test_code_and_faculty_are_separate():
    assert parse_class_text("PCC-CS301 (MB2)")[:3] == ("", "PCC-CS301", "MB2")
    assert parse_class_text("OEC-CS701B (Multimedia Systems) (SC5)")[:3] == (
        "Multimedia Systems", "OEC-CS701B", "SC5")
    assert parse_class_text("PECCS701 E (Machine Learning) (ND)")[:3] == (
        "Machine Learning", "PECCS701 E", "ND")
    for code in ("ESCS201", "ESCS 201", "ESCS-201", "ESCS_201", "ESCS - _ 201"):
        assert parse_class_text(code)[1] == code


def test_grid_and_review_policy():
    grid = grid_from_values([
        ["Department: CSE", "Semester: 3", "Section: A"],
        ["Day", "09:20-10:10", "10:10-11:00"],
        ["Monday", "DSA (PCC-CS301)", "Break"],
        ["Tuesday", "Data Structure", ""],
    ])
    routine = parse_grids([grid])
    assert routine.department == "CSE"
    assert routine.semester == "3"
    assert len(routine.classes) == 2
    assert routine.classes[0].subject_raw == "DSA"
    assert routine.classes[0].subject_code_raw == "PCC-CS301"
    subject = Subject(name="Data Structures and Algorithms", code="PCC-CS301", aliases=["DSA"])
    score_class(routine.classes[0], Match(subject, 1, "code"))
    assert routine.classes[0].requires_review is False
    score_class(routine.classes[1], Match(None, 0, "no_match"))
    assert routine.classes[1].requires_review is True


def test_code_subject_conflict_requires_review():
    subject = Subject(name="Data Structures and Algorithms", code="PCC-CS301", aliases=["DSA"])
    item = grid_from_values([["DBMS"]]).rows[0][0]
    from app.schemas.models import ClassSession

    session = ClassSession(day="Monday", start_time="09:00", end_time="10:00",
                           subject_raw=item.text, subject_code_raw="PCC-CS301",
                           source="native", confidence=0)
    score_class(session, Match(subject, 1, "code"))
    assert session.requires_review
    assert any("conflicts" in reason for reason in session.review_reasons)


def test_context_filter():
    catalog = Catalog([
        Subject(name="Algorithms", code="A1", department="CSE", semester="3"),
        Subject(name="Algorithms", code="B1", department="ECE", semester="3"),
    ])
    result = catalog.candidates(college=None, department="CSE", year=None, semester="3rd")
    assert [item.code for item in result] == ["A1"]


def test_saved_tint_catalog_scopes_and_duplicate_code():
    from pathlib import Path

    root = Path(__file__).parents[1]
    catalog = Catalog.from_file(root / "samples/subjects.tint.json",
                                root / "samples/subjects.tint.aliases.json")
    assert len(catalog.subjects) == 1704
    cse = catalog.candidates(course="B.Tech", department="CSE", semester="3rd")
    assert next(subject for subject in cse if subject.subject_master_id == 927).code == "PCCCS301"
    from app.standardization.matcher import match_subject

    match = match_subject("DSE301B", "DSE301B", catalog, college=None,
                          department="BCA", year=None, semester="3rd", course="BCA")
    assert match.ambiguous and match.subject is None
    shared = match_subject("[Revision Class] TG", "ESCS - _ 201", catalog, college=None,
                           department="CSE(Data Science)", year="2nd", semester="3rd")
    assert shared.method == "shared_code" and shared.subject is None
    assert shared.common_subject.name == "Programming for Problem Solving"
    assert all(catalog.code_matches(code) == catalog.code_matches("ESCS201")
               for code in ("ESCS 201", "ESCS-201", "ESCS_201", "ESCS - _ 201"))


def test_tint_workbook_keeps_block_context_and_repairs_time():
    from pathlib import Path

    from app.extractors.excel import extract_excel

    root = Path(__file__).parents[1]
    if not (root / "Routines/TINT/Odd sem 2026-27.xlsx").exists():
        raise SkipTest("TINT workbook is not available in this checkout")
    grids = extract_excel((root / "Routines/TINT/Odd sem 2026-27.xlsx").read_bytes())
    routine = parse_grids(grids)
    assert routine.course is None  # The workbook mixes undergraduate and M.Tech blocks.
    first = next(item for item in routine.classes if item.cell_ref == "2nd year!B4")
    assert (first.department, first.semester, first.section) == ("CSE", "3rd", "1")
    assert (first.start_time, first.end_time, first.subject_code_raw, first.faculty_raw) == (
        "09:30", "10:25", "PCC-CS301", "MB2")
    corrected = next(item for item in routine.classes if item.cell_ref == "2nd year!C4")
    assert (corrected.start_time, corrected.end_time) == ("10:25", "11:20")
    assert "Time header required AM/PM correction" in corrected.review_reasons
    postgraduate = next(item for item in routine.classes if item.cell_ref == "M.tech!G16")
    assert (postgraduate.course, postgraduate.department, postgraduate.semester) == ("M.Tech", "CSE", "3rd")
    revision = next(item for item in routine.classes if item.cell_ref == "2nd year!J153")
    assert revision.subject_code_raw == "ESCS 201"


def test_code_lookup_precedes_context_and_name_guessing():
    from app.schemas.models import ClassSession
    from app.standardization.matcher import match_subject

    catalog = Catalog([
        Subject(name="Introduction to Data Science", code="PCCDS301", subject_master_id=1,
                course="B.Tech", department="DS", semester="3rd", subject_type="Theory"),
        Subject(name="Machine Learning", code="PECCS701E", subject_master_id=2,
                course="B.Tech", department="CSE", semester="7th"),
    ])
    match = match_subject("PCCDS 301", "PCCDS 301", catalog, college=None,
                          department="CSE(Data Science)", year="2nd", semester="3rd")
    assert match.subject is catalog.subjects[0]
    assert match.context_mismatch
    item = ClassSession(day="Monday", start_time="09:00", end_time="10:00",
                        subject_raw="PCCDS 301", subject_code_raw="PCCDS 301",
                        department="CSE(Data Science)", semester="3rd",
                        source="native", confidence=0)
    score_class(item, match)
    assert (item.subject_name, item.subject_code, item.subject_master_id) == (
        "Introduction to Data Science", "PCCDS301", 1)
    assert (item.catalog_course, item.catalog_stream, item.catalog_semester) == (
        "B.Tech", "DS", "3rd")
    assert item.requires_review

    unknown = match_subject("Machine Learning", "NOT-IN-CATALOG", catalog,
                            college=None, department="CSE", year="4th", semester="7th")
    assert unknown.subject is None and unknown.method == "unmatched_code"
    assert unknown.name_lookup_status == "exact_name_found"
    assert unknown.candidates[0][0].code == "PECCS701E"


def test_unknown_code_name_diagnostic_keeps_canonical_fields_empty():
    from app.schemas.models import ClassSession
    from app.standardization.matcher import match_subject

    class FakeIndex:
        def search(self, text, candidates, **kwargs):
            assert kwargs["course"] is None and kwargs["department"] is None
            assert len(candidates) == 1
            return [(candidates[0], 0.25)]

    catalog = Catalog([Subject(name="Machine Learning", code="ML701", department="CSE")])
    match = match_subject("Quantum Basket Weaving", "ZZ999", catalog, college=None,
                          department="Other Stream", year=None, semester="7th",
                          semantic=FakeIndex())
    assert match.subject is None and match.name_lookup_status == "no_strong_candidate"
    item = ClassSession(day="Monday", start_time="09:00", end_time="10:00",
                        subject_raw="Quantum Basket Weaving", subject_code_raw="ZZ999",
                        source="native", confidence=0)
    score_class(item, match)
    assert item.subject_name is None and item.subject_code is None
    assert item.subject_master_id is None and item.requires_review
    assert item.cosine_similarity == 0.25 and item.match_candidates[0].code == "ML701"

    code_only = match_subject("ZZ999", "ZZ999", catalog, college=None,
                              department=None, year=None, semester=None, semantic=FakeIndex())
    assert code_only.name_lookup_status == "name_unavailable"
    assert code_only.candidates is None

    unchecked = match_subject("Quantum Basket Weaving", "ZZ999", catalog, college=None,
                               department=None, year=None, semester=None)
    assert unchecked.name_lookup_status == "index_unavailable"

    contained = match_subject("PEC- (Cloud Computing", "ZZ999",
                              Catalog([Subject(name="Cloud Computing", code="CC301")]),
                              college=None, department=None, year=None, semester=None,
                              semantic=FakeIndex())
    assert contained.subject is None and contained.name_lookup_status == "exact_name_found"


def test_code_match_ignores_group_and_room_notes():
    from app.schemas.models import ClassSession
    from app.standardization.matcher import match_subject

    catalog = Catalog([Subject(name="Analog and Digital Electronics", code="ESC391",
                               subject_master_id=3, course="B.Tech", department="CSE",
                               semester="3rd", subject_type="Theory")])
    match = match_subject("Analog and digital lab (R-318) Gr-A", "ESC-391", catalog,
                          college=None, department="CSE", year="2nd", semester="3rd")
    item = ClassSession(day="Monday", start_time="09:00", end_time="10:00",
                        subject_raw="Analog and digital lab (R-318) Gr-A",
                        subject_code_raw="ESC-391", source="native", confidence=0)
    score_class(item, match)
    assert item.subject_name == "Analog and Digital Electronics"
    assert item.review_reasons == []


def test_duplicate_code_without_resolving_context_stays_ambiguous():
    from app.standardization.matcher import match_subject

    catalog = Catalog([
        Subject(name="Computational Statistics", code="BSC301", department="CSBS", semester="3rd"),
        Subject(name="Mathematics-III", code="BSC301", department="CSE", semester="3rd"),
    ])
    match = match_subject("BSC 301", "BSC 301", catalog, college=None,
                          department="CSE(Data Science)", year="2nd", semester="3rd")
    assert match.subject is None
    assert match.method == "duplicate_code"
    assert match.ambiguous


def test_duplicate_code_with_shared_name_returns_name_without_record_id():
    from app.schemas.models import ClassSession
    from app.standardization.matcher import match_subject

    catalog = Catalog([
        Subject(name="Programming for Problem Solving", code="ESCS201",
                subject_master_id=1, department="CSE", semester="2nd", subject_type="Theory"),
        Subject(name="Programming for Problem Solving", code="ESCS201",
                subject_master_id=2, department="IT", semester="2nd", subject_type="Theory"),
    ])
    match = match_subject("ESCS 201", "ESCS 201", catalog, college=None,
                          department="Unknown", year=None, semester="3rd")
    assert match.subject is None and match.common_subject is not None
    assert match.method == "shared_code" and not match.ambiguous
    item = ClassSession(day="Monday", start_time="09:00", end_time="10:00",
                        subject_raw="ESCS 201", subject_code_raw="ESCS 201",
                        source="native", confidence=0)
    score_class(item, match)
    assert (item.subject_name, item.subject_code, item.subject_type) == (
        "Programming for Problem Solving", "ESCS201", "Theory")
    assert item.subject_master_id is None and item.requires_review


def test_irregular_pdf_table_keeps_text_without_cell_bounds():
    from pathlib import Path

    from app.extractors.pdf import extract_pdf

    source = Path(__file__).parents[1] / "Routines/NSEC/ECE/ECE ROUTINE V-3.pdf"
    if not source.exists():
        raise SkipTest("NSEC PDF dataset is not available in this checkout")
    grids, _ = extract_pdf(source.read_bytes())
    assert grids
    assert any(cell.text for grid in grids for row in grid.rows for cell in row)
