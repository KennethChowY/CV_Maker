"""Reviewing the memory on request, and keeping emails good with small models."""

import pytest

from cv_maker.app import create_app
from cv_maker.quality import EmailPieces, assemble_email, check_email, intro_sentence, surname
from cv_maker.review import apply_suggestions, rule_suggestions, tidy_date
from cv_maker.schema import Achievement, Education, Experience, Memory, Project, SkillGroup
from test_app import FakeAI


def kenneth() -> Memory:
    return Memory(
        profile={"name": "Kenneth Chow"},
        experience=[
            Experience(id="a", role="Research Assistant", organization="C-FIST Lab, CUHK", kind="work",
                       start="Jul 2025", end="currently", highlights=["• Built the data system", "Built the data system", ""]),
            Experience(id="b", role="Teaching Assistant", organization="UCLA", start="2024/1", end="06/2024"),
            Experience(id="a2", role="research assistant", organization="C-FIST Lab, CUHK",
                       highlights=["Trained 3 students"], location="Hong Kong")],
        education=[Education(id="e", institution="UCLA", qualification="BS", field="Data Theory", start="2021",
                             end="2025-06", highlights=["Capstone: Air pollution ExWAS", "Dean's list"])],
        projects=[Project(id="p", name="Exposome research pipeline"), Project(id="q", name="Showdown bot")],
        achievements=[Achievement(id="s", title="Organiser, CUHK data seminar", kind="other")],
        skills=[SkillGroup(category="Programming", skills=["Python", "R"]), SkillGroup(category="Tools", skills=["r", "Git"])])


def test_tidy_date():
    assert [tidy_date(x) for x in ("Jan 2024", "2024/1", "01/2024", "currently", "2024", "Spring 2024")] == \
        ["2024-01", "2024-01", "2024-01", "Present", "2024", "Spring 2024"]


def test_rules_find_the_usual_problems():
    s = rule_suggestions(kenneth())
    summaries = {(x["item_id"], x["summary"]) for x in s}
    assert ("a", "Tidy the dates") in summaries and ("b", "Tidy the dates") in summaries
    assert ("a", "Mark as research experience") in summaries and ("b", "Mark as teaching experience") in summaries
    assert ("e", "Move the final-year project to its own line") in summaries
    assert ("p", "Mark as a research project") in summaries and ("q", "Mark as a research project") not in summaries
    assert ("s", "Mark as service") in summaries
    assert ("a", "Clean up the highlights") in summaries
    merge = next(x for x in s if x["summary"] == "Merge a duplicate")
    assert merge["item_id"] == "a" and merge["remove_ids"] == ["a2"] and merge["changes"]["location"] == "Hong Kong"
    assert any(x["section"] == "skills" for x in s)


def test_accepted_suggestions_combine_on_one_item():
    memory = kenneth()
    s = {x["summary"] + x["item_id"]: x for x in rule_suggestions(memory)}
    picked = [s["Tidy the datesa"], s["Mark as research experiencea"], s["Clean up the highlightsa"],
              s["Merge a duplicatea"], s["Move the final-year project to its own linee"]]
    updated, done = apply_suggestions(memory, picked)
    a = updated.experience[0]
    assert (a.start, a.end, a.kind) == ("2025-07", "Present", "research")
    assert [x.id for x in updated.experience] == ["a", "b"]  # the duplicate is gone
    assert updated.education[0].thesis == "Capstone: Air pollution ExWAS"
    assert updated.education[0].highlights == ["Dean's list"]
    assert len(done) == 5
    assert memory.experience[0].kind == "work"  # the original is untouched


def test_review_only_changes_memory_when_accepted(tmp_path):
    ai = FakeAI()
    c = create_app(tmp_path, ai=ai).test_client()
    c.put("/api/memory?rebuild=0", json=kenneth().model_dump())
    before = c.get("/api/state").get_json()["memory"]
    res = c.post("/api/memory/review").get_json()
    assert res["ai"] and c.get("/api/state").get_json()["memory"] == before  # reviewing changes nothing
    ai_one = next(x for x in res["suggestions"] if x["source"] == "ai")
    assert set(ai_one["changes"]) == {"highlights", "location"}  # unknown items and the id are ignored
    assert "40" in ai_one["warnings"][0]  # a number that isn't in the memory is flagged
    body = c.post("/api/memory/revise", json={"suggestions": [ai_one]}).get_json()
    assert body["memory"]["experience"][0]["highlights"] == ["Built a data system used by 40 researchers"]
    assert body["history"][0]["source"] == "review" and "Rebuild CV" in body["notice"]
    assert c.post("/api/undo").status_code == 200
    assert c.get("/api/state").get_json()["memory"] == before
    assert c.post("/api/memory/revise", json={"suggestions": []}).status_code == 400
    # Without AI (or when asked), only the rule-based fixes.
    assert c.post("/api/memory/review", json={"ai": False}).get_json()["ai"] is False


def test_email_checks():
    good = ("Dear Professor Wong,\n\n" + "I graduated from UCLA in 2025 with a BS in Data Theory. " * 12
            + "Your cohort exposures paper was great.\n\nBest regards,\nKenneth Chow")
    assert check_email("Subject", good, name="Kenneth Chow", paper_title="Cohort exposures in Hong Kong",
                       context="UCLA 2025") == []
    bad = "Hi,\n\nMy work aligns with yours. I helped 500 people. I am passionate."
    problems = " ".join(check_email("", bad, name="Kenneth Chow", paper_title="Cohort exposures", context=""))
    for expected in ("aligns with", "passionate", "Too short", "greeting", "signed", "chosen paper", "500", "subject"):
        assert expected in problems


def test_guided_email_writes_the_facts_itself():
    m = kenneth()
    assert intro_sentence(m) == ("I graduated from UCLA in 2025 with a BS in Data Theory and now work as "
                                 "a Research Assistant at C-FIST Lab, CUHK.")
    assert surname("Prof. Jane Wong") == "Wong"
    subject, body = assemble_email(m, "Prof. Jane Wong", EmailPieces(paper_sentences="P.", link_sentences="L.",
                                                                     subject="S"))
    assert body.startswith("Dear Professor Wong,") and body.endswith("Best regards,\nKenneth Chow") and subject == "S"


def test_local_models_get_the_guided_email_and_one_repair_round(tmp_path, monkeypatch):
    import cv_maker.scholar as scholar
    from test_scholar_usage_backup import fake_get
    monkeypatch.setattr(scholar, "_get", fake_get)
    ai = FakeAI()
    ai.local = True
    app = create_app(tmp_path, ai=ai)
    app.config["READ_PAPER"] = lambda w: {}
    c = app.test_client()
    c.put("/api/memory?rebuild=0", json=kenneth().model_dump())
    vid = c.post("/api/versions", json={"company": "CUHK", "role": "PhD", "kind": "phd"}).get_json()["active"]["id"]
    c.post(f"/api/versions/{vid}/professor", json={"id": "A222"})
    email = c.post(f"/api/versions/{vid}/supervisor-email", json={"paper_id": "W1"}).get_json()
    assert email["style"] == "guided"
    assert "I graduated from UCLA in 2025" in email["body"] and email["body"].startswith("Dear Professor Wong,")
    # The stand-in's pieces are short, so the draft was sent back once with its problems, and the rest shown.
    assert len(ai.pieces_calls) == 2 and "problems" in ai.pieces_calls[1]
    assert any("Too short" in p for p in email["checks"])
    free = c.post(f"/api/versions/{vid}/supervisor-email", json={"paper_id": "W1", "style": "free"}).get_json()
    assert free["style"] == "free"
