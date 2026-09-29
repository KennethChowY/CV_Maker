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


def test_publications_are_not_listed_as_awards():
    from cv_maker.schema import Achievement
    memory = Memory(achievements=[
        Achievement(id="p", kind="publication", title="Wildfire impacts on organic matter", date="2025-03"),
        Achievement(id="c", kind="certification", title="AWS Cloud Practitioner"),
        Achievement(id="a", kind="award", title="Dean's List"),
    ])
    headings = {s.heading: s.items for s in assemble_cv(memory).sections}
    assert headings["Publications & Presentations"] == ["Wildfire impacts on organic matter — Mar 2025"]
    assert headings["Certifications"] == ["AWS Cloud Practitioner"]
    assert headings["Awards"] == ["Dean's List"]


def test_degree_filed_as_a_highlight_becomes_the_title():
    memory = Memory(education=[Education(
        id="e", institution="UCLA", grade="3.6/4.0",
        highlights=["Bachelor of Science in Data Theory", "Coursework: Machine Learning"],
    )])
    entry = assemble_cv(memory).sections[0].entries[0]
    assert entry.title == "Bachelor of Science in Data Theory" and entry.subtitle == "UCLA"
    assert entry.bullets == ["Coursework: Machine Learning"] and entry.description == "GPA 3.6/4.0"


def test_placeholders_are_flagged_but_labels_are_not():
    cv = tidy_cv(CVDocument(name="K", sections=[CVSection(heading="Projects", entries=[
        CVEntry(title="Bot", dates="[month year]", bullets=["Peak rating of [rating] on [N replays]"]),
        CVEntry(title="Courses", bullets=["[Programming]: Python"]),
    ])]))
    assert "[month year]" in cv.advice[0] and "[rating]" in cv.advice[0] and "[N replays]" in cv.advice[0]
    assert "[Programming]" not in cv.advice[0]
    html = render_cv(cv)
    assert '<mark class="placeholder">[rating]</mark>' in html and "<mark class=\"placeholder\">[Programming]" not in html


def test_render_applies_order_and_hidden_sections():
    cv = CVDocument(name="K", summary="Hi", sections=[
        CVSection(heading="Experience", items=["a"]), CVSection(heading="Education", items=["b"]),
        CVSection(heading="Skills", items=["c"]),
    ])
    html = render_cv(cv, order=["skills", "education"], hidden=["experience", "summary"])
    assert html.index('data-section="skills"') < html.index('data-section="education"') < html.index('data-section="experience"')
    assert 'data-section="experience" hidden' in html and 'data-section="summary" hidden' in html


def test_page_break_hints_in_the_html():
    cv = CVDocument(name="K", sections=[
        CVSection(heading="Experience", entries=[
            CVEntry(title="Long job", bullets=[f"Did thing {i}" for i in range(6)]),
            CVEntry(title="Short job", bullets=["One", "Two"]),
        ]),
        CVSection(heading="Skills", items=["Python"]),
    ])
    html = render_cv(cv)
    assert html.count('class="cv-entry long"') == 1 and html.count('class="cv-entry"') == 1
    assert 'class="cv-section cv-list" data-section="skills"' in html


def test_pdf_page_runs_the_same_line_tightening():
    from cv_maker.export import page_document
    doc = page_document("<p>x</p>", title="t", template="classic", accent="#1f4e79", page_size="A4", scale=1.0)
    assert "window.CVLayout" in doc and "CVLayout.tighten(document.querySelector('.cv'))" in doc
