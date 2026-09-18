import json
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from study.desktop import diagnostic_file, dispatch
from study.easistent import sync_assessments
from study.mapping import choose_folder
from study.models import Assessment, Diagnostic, DiagnosticQuestion, Reference, Settings
from study.personal import attachment_sources, import_attachment, score_diagnostic
from study.runner import fingerprint
from study.storage import Store, write_json


def assessment(**changes):
    return Assessment(
        id=uuid4(),
        subject="GEO",
        title="Test",
        date=date(2026, 9, 23),
        updated_at=datetime.now(UTC),
        **changes,
    )


def quiz():
    return Diagnostic(
        title="Predtest",
        warnings=[],
        questions=[
            DiagnosticQuestion(
                topic="Podnebje" if i < 3 else "Prst",
                question=f"Vprašanje {i}",
                options=["a", "b", "c", "d"],
                correct_index=i % 4,
                explanation="Razlaga",
                references=[Reference(source_id=str(uuid4()), page=1)],
            )
            for i in range(6)
        ],
    )


def test_diagnostic_scores_unknowns_and_recommends_by_gaps_and_goal():
    q = quiz()
    correct = [x.correct_index for x in q.questions]
    good = score_diagnostic(q, correct, 4)
    weak = score_diagnostic(q, [-1] * 6, 4)
    assert good["score_percent"] == 100 and good["weak_topics"] == []
    assert weak["score_percent"] == 0 and set(weak["weak_topics"]) == {
        "Podnebje",
        "Prst",
    }
    assert weak["recommended_minutes"] > good["recommended_minutes"]
    assert (
        score_diagnostic(q, [-1] * 6, 5)["recommended_minutes"]
        > score_diagnostic(q, [-1] * 6, 2)["recommended_minutes"]
    )
    with pytest.raises(ValueError):
        score_diagnostic(q, [-2] * 6, 4)


def test_app_saves_goals_and_invalidates_diagnostic_when_scope_changes(tmp_path):
    store = Store(tmp_path)
    a = assessment()
    store.save_settings(Settings(assessments=[a]))
    original = fingerprint(a, [], store.settings())
    dispatch(
        store,
        {
            "action": "save",
            "id": str(a.id),
            "target_grade": 5,
            "knowledge_level": 0,
            "study_hours": 1.5,
        },
    )
    updated = store.settings().assessments[0]
    assert (
        updated.target_grade == 5
        and updated.study_hours == 1.5
        and updated.knowledge_level == 0
    )
    assert fingerprint(updated, [], store.settings()) != original
    write_json(
        diagnostic_file(store, a.id), {"quiz": quiz().model_dump(), "answers": [-1] * 6}
    )
    result = dispatch(store, {"action": "score", "id": str(a.id), "answers": [-1] * 6})
    assert result["tests"][0]["diagnostic_result"]["score_percent"] == 0
    assert "correct_index" not in result["tests"][0]["diagnostic"]["questions"][0]
    dispatch(store, {"action": "save", "id": str(a.id), "scope_notes": "Samo rastje"})
    assert store.settings().assessments[0].diagnostic_result is None
    assert not diagnostic_file(store, a.id).exists()


def test_image_import_is_repeatable_and_part_of_generation_fingerprint(tmp_path):
    store = Store(tmp_path)
    a = assessment()
    image = tmp_path / "zapiske.png"
    Image.new("RGB", (100, 100), "white").save(image)
    source = import_attachment(store, a.id, image)
    import_attachment(store, a.id, image)
    assert len(attachment_sources(store, a.id)) == 1
    assert len(PdfReader(store.root / source.pdf).pages) == 1
    assert fingerprint(a, [source], Settings()) != fingerprint(a, [], Settings())
    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    with pytest.raises(UnidentifiedImageError):
        import_attachment(store, a.id, bad)


def test_numbering_is_per_subject_school_year_and_manual_choice_wins():
    one = assessment()
    two = assessment()
    two.date = date(2026, 10, 1)
    unrelated = assessment()
    unrelated.subject = "SLO"
    unrelated.date = date(2026, 9, 1)
    previous_year = assessment()
    previous_year.date = date(2026, 5, 1)
    root, first, second = uuid4(), uuid4(), uuid4()
    items = [
        SimpleNamespace(
            id=root, parent="", visibleName="Geografija", is_collection=True
        ),
        SimpleNamespace(
            id=first, parent=str(root), visibleName="Test 1", is_collection=True
        ),
        SimpleNamespace(
            id=second, parent=str(root), visibleName="Test 2", is_collection=True
        ),
    ]
    settings = Settings(assessments=[two, unrelated, previous_year, one])
    assert choose_folder(one, settings, items)[0] == first
    assert choose_folder(two, settings, items)[0] == second
    settings.assessment_folders[str(one.id)] = second
    assert choose_folder(one, settings, items)[0] == second


def test_web_assessment_and_sync_preserve_personal_choices(tmp_path):
    from study.easistent import parse_timetable
    from study.school_browser import flight_timetables

    event = {
        "slug": "ocenjevanje$123",
        "evaluation": {
            "evaluation_id": 123,
            "title": "1. šolska naloga",
            "summary": "Tvorba besedila",
        },
        "subject": {"title": "Slovenščina"},
        "date": "2026-09-23",
        "from": "13:25",
        "to": "14:10",
    }
    raw = "1:" + json.dumps({"ok": True, "value": {"schedule": [], "events": [event]}})
    payload = flight_timetables(raw)[0]
    a = parse_timetable(payload)[0]
    assert a.subject == "Slovenščina" and a.school_scope == "Tvorba besedila"
    a.study_hours = 8
    a.target_grade = 5
    a.knowledge_level = 1
    a.scope_notes = "Moja snov"
    store = Store(tmp_path)
    store.save_settings(Settings(easistent_enabled=True, assessments=[a]))
    event["date"] = "2026-09-24"
    sync_assessments(
        store,
        client_factory=lambda _: SimpleNamespace(fetch_weeks=lambda **_: [payload]),
    )
    saved = store.settings().assessments[0]
    assert saved.id == a.id and saved.study_hours == 8 and saved.target_grade == 5
    assert saved.knowledge_level == 1 and saved.scope_notes == "Moja snov"


def test_saving_automatic_folder_keeps_diagnostic_and_does_not_pin_folder(tmp_path):
    store = Store(tmp_path)
    a = assessment(folder_id=uuid4(), diagnostic_result={"score_percent": 50})
    store.save_settings(Settings(assessments=[a]))
    dispatch(
        store, {"action": "save", "id": str(a.id), "folder_id": "", "study_hours": 2}
    )
    saved = store.settings()
    assert saved.assessments[0].diagnostic_result == {"score_percent": 50}
    assert saved.assessments[0].folder_id == a.folder_id
    assert str(a.id) not in saved.assessment_folders


def test_multiple_sources_save_clear_old_diagnostic_and_survive_date_sync(tmp_path):
    from study.easistent import parse_web_timetable

    payload = {
        "events": [
            {
                "evaluation": {"evaluation_id": 777, "title": "Test"},
                "subject": {"title": "GEO"},
                "date": "2026-09-23",
                "from": "08:00",
                "to": "08:45",
            }
        ],
        "schedule": [],
    }
    a = parse_web_timetable(payload)[0]
    a.diagnostic_result = {"score_percent": 70}
    store = Store(tmp_path)
    store.save_settings(Settings(easistent_enabled=True, assessments=[a]))
    ids = [str(uuid4()), str(uuid4())]
    dispatch(
        store,
        {
            "action": "save",
            "id": str(a.id),
            "material_ids": ids + ids[:1],
            "folder_id": "",
        },
    )
    saved = store.settings().assessments[0]
    assert {str(i) for i in saved.material_ids} == set(ids)
    assert saved.folder_id is None and saved.diagnostic_result is None
    payload["events"][0]["date"] = "2026-09-25"
    sync_assessments(
        store,
        client_factory=lambda _: SimpleNamespace(fetch_weeks=lambda **_: [payload]),
    )
    assert {str(i) for i in store.settings().assessments[0].material_ids} == set(ids)
    assert store.settings().assessments[0].date == date(2026, 9, 25)
