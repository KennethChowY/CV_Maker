from cv_maker.render import assemble_cv, date_key, pretty_date, render_cv, tidy_cv
from cv_maker.schema import CVDocument, CVEntry, CVSection, Education, Experience, Memory, Profile


def test_dates_are_understood_in_common_formats():
    assert date_key("2021-03") == (2021, 3)
    assert date_key("Mar 2021") == (2021, 3)
    assert date_key("03/2021") == (2021, 3)
    assert date_key("2021") == (2021, 0)
    assert date_key("Present") > date_key("2030")
    assert date_key("") == (0, 0)
    assert pretty_date("2021-03") == "Mar 2021"
    assert pretty_date("present") == "Present"
    assert pretty_date("Summer 2020") == "Summer 2020"


def test_layout_is_newest_first_and_leads_with_experience_when_employed():
    memory = Memory(
        profile=Profile(name="Kim"),
        experience=[
            Experience(id="a", role="Intern", organization="Old", start="2019-06", end="2019-09"),
            Experience(id="b", role="Analyst", organization="Now", start="2023-01", end="Present"),
            Experience(id="c", role="Helper", organization="Charity", start="2022", kind="volunteering"),
        ],
        education=[Education(id="e", institution="CUHK", qualification="BSc", field="Data Science", end="2022")],
    )
    cv = assemble_cv(memory)
    assert [s.heading for s in cv.sections] == ["Experience", "Education", "Volunteering"]
    assert [e.title for e in cv.sections[0].entries] == ["Analyst", "Intern"]
    assert cv.sections[0].entries[0].dates == "Jan 2023 – Present"


def test_students_lead_with_education():
    memory = Memory(
        experience=[Experience(id="a", role="Research Assistant", organization="Lab", kind="internship")],
        education=[Education(id="e", institution="CUHK")],
    )
    assert [s.heading for s in assemble_cv(memory).sections] == ["Education", "Experience"]


def test_tidy_removes_empty_duplicate_and_redundant_sections():
    cv = CVDocument(
        name=" ",
        summary="Hi",
        sections=[
            CVSection(heading="Summary", items=["Hi again"]),
            CVSection(heading="Experience", entries=[
                CVEntry(title="Dev", bullets=["• Built it", "  ", "- Shipped it"]),
                CVEntry(title="", subtitle=""),
            ]),
            CVSection(heading="experience", items=["dupe"]),
            CVSection(heading="Awards"),
        ],
    )
    cv = tidy_cv(cv)
    assert cv.name == "Your Name"
    assert [s.heading for s in cv.sections] == ["Experience"]
    assert cv.sections[0].entries[0].bullets == ["Built it", "Shipped it"]
    assert "Built it" in render_cv(cv)
