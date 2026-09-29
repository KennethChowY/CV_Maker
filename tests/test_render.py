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
    assert "window.CVLayout" in doc and "CVLayout.tighten(cv)" in doc and "CVLayout.paginate(cv" in doc
    assert "width: 210mm" in doc
    letter = page_document("<p>x</p>", title="t", template="classic", accent="#1f4e79", page_size="letter",
                           scale=1.0, paginate=False)
    assert "CVLayout.paginate(cv" not in letter and "width: 215.9mm" in letter


def test_academic_cv_places_thesis_research_projects_and_service():
    from cv_maker.render import assemble_cv
    from cv_maker.schema import Achievement, Education, Experience, Memory, Project

    m = Memory(
        experience=[Experience(id="a", role="Research Assistant", organization="C-FIST Lab", start="2025")],
        education=[Education(id="e", institution="UCLA", qualification="BS", field="Data Theory",
                             thesis="Air pollution ExWAS (Supervisor: Prof. X)", highlights=["Coursework: ML"])],
        projects=[Project(id="bot", name="Showdown bot"), Project(id="r", kind="research", name="Carbon study")],
        achievements=[Achievement(id="s", kind="service", title="Organiser, data seminar")])
    sections = {s.heading: s for s in assemble_cv(m, academic=True).sections}
    assert sections["Education"].entries[0].bullets[0] == "Final-year project: Air pollution ExWAS (Supervisor: Prof. X)"
    assert [e.title for e in sections["Research Experience"].entries] == ["Research Assistant", "Carbon study"]
    assert [e.title for e in sections["Other Projects"].entries] == ["Showdown bot"]
    assert sections["Professional Service"].items == ["Organiser, data seminar"]
    order = list(sections)
    assert order.index("Professional Service") < order.index("Other Projects")
    # Job CVs keep projects together and call service "Leadership & Service".
    job = [s.heading for s in assemble_cv(m).sections]
    assert "Projects" in job and "Leadership & Service" in job and "Research Experience" not in job
    # A thesis already labelled isn't labelled twice.
    m.education[0].thesis = "Honours thesis: Air pollution"
    assert assemble_cv(m).sections[1].entries[0].bullets[0] == "Honours thesis: Air pollution"


def test_phd_cv_has_research_interests_pi_citations_and_references():
    from cv_maker.render import assemble_cv, citation, render_cv
    from cv_maker.schema import Achievement, Experience, Memory, Referee

    m = Memory(
        profile={"name": "Kenneth Chow"},
        research_interests=["Exposome data science", "Environmental epidemiology"],
        experience=[Experience(id="a", role="Research Assistant", organization="C-FIST Lab, CUHK", kind="research",
                               supervisor="Prof. Jane Wong", start="2025-07", end="Present")],
        achievements=[
            Achievement(id="p", kind="publication", title="Exposome-wide association of X", issuer="Environ Int",
                        date="2025", authors="Wong J, Chow K, Lee A", status="published"),
            Achievement(id="q", kind="publication", title="Carbon fingerprints", authors="K. Chow and J. Wong",
                        status="in preparation"),
            Achievement(id="t", kind="talk", title="Poster: ExWAS in R Shiny", issuer="ISEE 2025", date="2025-08",
                        authors="Chow K")],
        referees=[Referee(id="r", name="Prof. Jane Wong", title="Associate Professor", organization="CUHK",
                          email="jane@cuhk.edu.hk", relationship="Supervisor, C-FIST Lab")])
    cv = assemble_cv(m, academic=True)
    assert cv.summary_title == "Research Interests"
    assert cv.summary == "Exposome data science · Environmental epidemiology"
    research = next(s for s in cv.sections if s.heading == "Research Experience")
    assert research.entries[0].subtitle == "C-FIST Lab, CUHK · PI: Prof. Jane Wong"
    pubs = next(s for s in cv.sections if s.heading.startswith("Publications")).items
    assert "Wong J, **Chow K**, Lee A (2025). Exposome-wide association of X. Environ Int." in pubs
    assert "**K. Chow** and J. Wong (in preparation). Carbon fingerprints." in pubs
    assert "**Chow K** (2025). ExWAS in R Shiny. Poster at ISEE 2025." in pubs
    assert cv.sections[-1].heading == "References"
    assert cv.sections[-1].items == ["Prof. Jane Wong, Associate Professor, CUHK — jane@cuhk.edu.hk — Supervisor, C-FIST Lab"]
    html = render_cv(cv)
    assert "<h2>Research Interests</h2>" in html and "<strong>Chow K</strong>" in html
    # No references when asked (US), and job CVs are unchanged.
    assert "References" not in [s.heading for s in assemble_cv(m, academic=True, references=False).sections]
    job = assemble_cv(m)
    assert job.summary_title == "" and "References" not in [s.heading for s in job.sections]
    assert job.sections[0].entries[0].subtitle == "C-FIST Lab, CUHK"
    # Without authors, papers keep the simple format.
    assert citation(m.achievements[0], "") .startswith("Wong J, Chow K")


def test_small_academic_fixes():
    from cv_maker.render import assemble_cv, citation, pretty_date
    from cv_maker.schema import Achievement, Education, Memory

    assert pretty_date("currently") == "Present" and pretty_date("Currently.") == "Present"
    paper = Achievement(title="X", authors="Chow K", date="2025", status="under review")
    assert citation(paper, "Kenneth Chow") == "**Chow K** (under review). X."
    m = Memory(education=[Education(id="e", institution="UCLA", qualification="BS", thesis="Exposome pipeline",
                                    highlights=["Capstone: exposome data pipeline", "Dean's list"])])
    assert assemble_cv(m, academic=True).sections[0].entries[0].bullets == \
        ["Final-year project: Exposome pipeline", "Dean's list"]


def test_own_name_is_bold_but_not_a_coauthor_with_the_same_surname():
    from cv_maker.render import _own_name
    assert _own_name("Kenneth CHOW (presenter), Xiaohan MO, and Alex CHOW", "Kenneth Chow") == \
        "**Kenneth CHOW (presenter)**, Xiaohan MO, and Alex CHOW"
    assert _own_name("Chow K, Chow A, Wong J", "Kenneth Chow") == "**Chow K**, Chow A, Wong J"
    assert _own_name("K. Chow and A. Chow", "Kenneth Chow") == "**K. Chow** and A. Chow"


def test_academic_cv_has_no_job_title_and_no_repeated_location():
    from cv_maker.render import assemble_cv, render_cv
    from cv_maker.schema import Experience, Memory
    m = Memory(profile={"name": "K", "headline": "Data Scientist"},
               experience=[Experience(id="a", role="RA", organization="School of Public Health, CUHK",
                                      location="School of Public Health, CUHK")])
    assert assemble_cv(m, academic=True).headline == ""
    assert assemble_cv(m).headline == "Data Scientist"
    assert "cv-entry-loc" not in render_cv(assemble_cv(m))
