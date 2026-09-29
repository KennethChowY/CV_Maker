"""Finding a professor's research, the usage tracker, and automatic backups."""

import os
import time
import zipfile

import pytest

from cv_maker import scholar
from cv_maker.app import create_app
from cv_maker.backup import auto_backup, check_folder
from cv_maker.usage import UsageLog
from test_app import FakeAI

AUTHORS = {"results": [
    {"id": "https://openalex.org/A111", "display_name": "Jane Wong", "works_count": 40, "cited_by_count": 900,
     "last_known_institutions": [{"display_name": "Stanford University"}], "topics": [{"display_name": "Robotics"}]},
    {"id": "https://openalex.org/A222", "display_name": "Jane Wong", "works_count": 12, "cited_by_count": 300,
     "last_known_institutions": [{"display_name": "The Chinese University of Hong Kong"}],
     "topics": [{"display_name": "Exposome"}, {"display_name": "Environmental epidemiology"}]},
]}
WORKS_RECENT = {"results": [{"display_name": "Exposome-wide association of air pollution", "publication_year": 2025,
                             "primary_location": {"source": {"display_name": "Environment International"}},
                             "abstract_inverted_index": {"We": [0], "study": [1], "exposures.": [2]}, "cited_by_count": 3}]}
WORKS_CITED = {"results": [{"display_name": "A classic cohort", "publication_year": 2015, "cited_by_count": 500},
                           {"display_name": "Exposome-wide association of air pollution", "publication_year": 2025}]}


def fake_get(path, params):
    if path == "/authors":
        return AUTHORS
    if path.startswith("/authors/"):
        return next(a for a in AUTHORS["results"] if a["id"].endswith(path.rsplit("/", 1)[1]))
    return WORKS_CITED if params.get("sort", "").startswith("cited") else WORKS_RECENT


@pytest.fixture
def openalex(monkeypatch):
    monkeypatch.setattr(scholar, "_get", fake_get)


def test_find_authors_puts_the_right_university_first(openalex):
    people = scholar.find_authors("Prof. Jane Wong", "CUHK")
    assert [p["id"] for p in people] == ["A222", "A111"]
    assert people[0]["topics"] == ["Exposome", "Environmental epidemiology"]
    assert scholar.find_authors("Jane Wong")[0]["id"] == "A111"  # no university: most published first
    with pytest.raises(scholar.AIError):
        scholar.find_authors("J")


def test_research_profile_rebuilds_abstracts_and_skips_duplicates(openalex):
    p = scholar.research_profile("A222")
    assert p["recent"][0]["abstract"] == "We study exposures."
    assert p["recent"][0]["venue"] == "Environment International"
    assert [w["title"] for w in p["cited"]] == ["A classic cohort"]
    text = scholar.profile_text(p)
    assert "Exposome-wide association of air pollution (2025, Environment International)" in text
    with pytest.raises(scholar.AIError):
        scholar.research_profile("../../etc")


def test_professor_email_uses_their_papers(tmp_path, openalex):
    ai = FakeAI()
    c = create_app(tmp_path, ai=ai).test_client()
    vid = c.post("/api/versions", json={"company": "CUHK", "role": "PhD", "kind": "phd"}).get_json()["active"]["id"]
    people = c.post("/api/professor/search", json={"name": "Jane Wong", "institution": "CUHK"}).get_json()["people"]
    chosen = c.post(f"/api/versions/{vid}/professor", json={"id": people[0]["id"]}).get_json()["professor"]
    assert chosen["name"] == "Jane Wong"
    assert c.get(f"/api/versions/{vid}/professor").get_json()["professor"]["id"] == "A222"
    assert c.get("/api/state").get_json()["versions"][0]["supervisor"] == "Jane Wong"
    email = c.post(f"/api/versions/{vid}/supervisor-email", json={"interest": "Air pollution and health"}).get_json()
    about, university, programme, supervisor = ai.supervisor_args
    assert "Exposome-wide association of air pollution" in about and supervisor == "Jane Wong"
    assert email["fit"] == "partial" and email["paper"] == "A paper" and email["overlap"] == "Both use R"
    # What draws the student to them is remembered for rewrites, alongside a one-off instruction.
    c.post(f"/api/versions/{vid}/supervisor-email", json={"instruction": "Shorter"})
    assert ai.supervisor_extra == ("Air pollution and health", "Shorter")
    assert c.post("/api/versions/general/professor", json={"id": "A222"}).status_code == 404


def test_supervisor_prompt_is_honest_about_fit():
    from cv_maker.assistant import SupervisorEmail, supervisor_prompt
    system, user = supervisor_prompt("{}", "papers", "CUHK", "PhD", "Jane Wong", "air pollution", "shorter")
    assert "aligns with" in system and "Never use" in system  # banned stock phrases
    assert "air pollution" in user and "shorter" in system
    fields = list(SupervisorEmail.model_fields)
    assert fields.index("fit") < fields.index("body") and fields.index("paper") < fields.index("body")


def test_usage_is_summarised_with_costs(tmp_path):
    log = UsageLog(tmp_path / "usage.jsonl")
    log.record("anthropic", "claude-opus-5-5", "CVWording", 10_000, 2_000)
    log.record("openai", "gpt-x", "MemoryUpdate", 1_000, 100)
    log.record("ollama", "qwen3:4b", "MemoryUpdate", 5_000, 500)
    month = log.summary()["month"]
    assert month["requests"] == 3 and month["unpriced"] == 1 and month["local"] == 1
    assert month["cost"] == pytest.approx((10_000 * 4 + 2_000 * 20) / 1e6)
    assert month["by_purpose"][0]["purpose"] == "Writing the CV"


def test_backends_record_usage(tmp_path):
    from cv_maker.backend import ChatBackend
    from cv_maker.writing import BulletSuggestions

    class Tiny(ChatBackend):
        provider, model = "anthropic", "claude-haiku-4-5"

        def _chat(self, system, user, output):
            self._record(output, 100, 20)
            return BulletSuggestions(suggestions=["Built X"])

    ai = Tiny()
    ai.usage = UsageLog(tmp_path / "u.jsonl")
    ai.improve_bullet(__import__("cv_maker.schema", fromlist=["Memory"]).Memory(), "Did X", "stronger")
    assert ai.usage.entries()[0]["purpose"] == "BulletSuggestions"


def test_automatic_backups(tmp_path):
    data, folder = tmp_path / "data", tmp_path / "Backups"
    c = create_app(data, ai=FakeAI()).test_client()
    (data / "secrets.json").write_text("{}")
    assert c.post("/api/settings", json={"backup_dir": "relative/path"}).status_code == 400
    body = c.post("/api/settings", json={"backup_dir": str(folder)}).get_json()
    assert body["backup"]["folder"] == str(folder)
    zips = list(folder.glob("CV Maker backup *.zip"))
    assert len(zips) == 1  # the change itself triggered the first backup
    assert "data/secrets.json" not in zipfile.ZipFile(zips[0]).namelist()
    c.post("/api/ingest", data={"text": "Engineer"})
    assert len(list(folder.glob("*.zip"))) == 1  # at most hourly
    old = time.time() - 7200
    os.utime(zips[0], (old, old))
    c.post("/api/ingest", data={"text": "Analyst"})
    assert len(list(folder.glob("*.zip"))) == 2
    c.post("/api/backup/now")
    state = c.get("/api/state").get_json()
    assert state["backup"]["count"] == 3 and state["backup"]["last"]
    c.post("/api/settings", json={"backup_dir": ""})
    assert c.post("/api/backup/now").status_code == 400


def test_old_backups_are_pruned(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "memory.json").write_text("{}")
    for _ in range(33):
        auto_backup(tmp_path / "d", str(tmp_path / "b"), force=True)
    assert len(list((tmp_path / "b").glob("*.zip"))) == 30
    with pytest.raises(ValueError):
        check_folder("not/absolute")
