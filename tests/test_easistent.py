from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from study.easistent import parse_timetable, sync_assessments
from study.mapping import choose_folder
from study.models import Assessment, Settings
from study.storage import Store


def timetable(day="2026-09-23", special="exam"):
    return {
        "school_hour_events": [
            {
                "event_id": 123,
                "subject": {"name": "Slovenščina"},
                "hour_special_type": special,
                "time": {"date": day, "from_id": 7, "to_id": 7},
                "classroom": {"name": "202"},
            }
        ],
        "time_table": [{"id": 7, "time": {"from": "13:25", "to": "14:10"}}],
    }


def test_only_explicit_tests_are_imported_with_real_times():
    found = parse_timetable(timetable())
    assert len(found) == 1
    assert found[0].date == date(2026, 9, 23)
    assert found[0].start_time == time(13, 25)
    assert found[0].end_time == time(14, 10)
    assert parse_timetable(timetable(special=None)) == []
    assert parse_timetable(timetable(special="substitution")) == []
    assert parse_timetable(timetable(day="2026-09-25"))[0].id == found[0].id


def test_malformed_test_does_not_disappear_silently():
    payload = timetable()
    del payload["school_hour_events"][0]["time"]["date"]
    with pytest.raises(ValueError):
        parse_timetable(payload)


def test_reschedule_idempotence_and_missing_records_are_preserved(tmp_path):
    store = Store(tmp_path)
    store.save_settings(Settings(easistent_enabled=True))
    payloads = [timetable()]
    factory = lambda _: SimpleNamespace(fetch_weeks=lambda **_: payloads)
    sync_assessments(store, client_factory=factory)
    first = store.settings().assessments[0]
    sync_assessments(store, client_factory=factory)
    assert store.settings().assessments[0].updated_at == first.updated_at
    payloads[0] = timetable(day="2026-09-25")
    sync_assessments(store, client_factory=factory)
    assert store.settings().assessments[0].id == first.id
    assert store.settings().assessments[0].date == date(2026, 9, 25)
    payloads.clear()
    sync_assessments(store, client_factory=factory)
    assert len(store.settings().assessments) == 1
    assert not store.settings().assessments[0].cancelled


def test_partial_fetch_does_not_replace_saved_tests(tmp_path):
    store = Store(tmp_path)
    existing = parse_timetable(timetable())[0]
    store.save_settings(Settings(easistent_enabled=True, assessments=[existing]))

    def failed(**_):
        raise RuntimeError("network unavailable")

    with pytest.raises(RuntimeError):
        sync_assessments(
            store, client_factory=lambda _: SimpleNamespace(fetch_weeks=failed)
        )
    assert store.settings().assessments == [existing]


def test_subject_aliases_and_ambiguous_test_folders():
    root = uuid4()
    a = Assessment(
        id=uuid4(),
        subject="SLO",
        title="Ocenjevanje znanja",
        date=date(2026, 9, 23),
        updated_at=datetime.now(UTC),
    )
    items = [
        SimpleNamespace(
            id=root, parent="", is_collection=True, visibleName="Slovenščina"
        )
    ]
    assert choose_folder(a, Settings(), items)[0] == root
    first, third = uuid4(), uuid4()
    items.extend(
        [
            SimpleNamespace(
                id=first, parent=str(root), is_collection=True, visibleName="Test 1"
            ),
            SimpleNamespace(
                id=third, parent=str(root), is_collection=True, visibleName="Test 3"
            ),
        ]
    )
    assert choose_folder(a, Settings(), items)[0] == first
    items[1].visibleName = "Test 2026-09-23"
    assert choose_folder(a, Settings(), items)[0] == first
    settings = Settings(assessment_folders={str(a.id): third})
    assert choose_folder(a, settings, items)[0] == third


def test_prefetched_neighbor_week_is_not_used_for_requested_week():
    from study.school_browser import select_week

    requested = {"day_table": [{"date": "2026-09-21"}]}
    neighbor = {"day_table": [{"date": "2026-09-28"}]}
    assert select_week([requested, neighbor], date(2026, 9, 21)) is requested
    assert select_week([neighbor], date(2026, 9, 21)) is None


def test_user_confirmed_calendar_event_keeps_id_after_automatic_discovery(tmp_path):
    store = Store(tmp_path)
    existing = parse_timetable(timetable())[0]
    existing.id = uuid4()
    existing.source = "manual"
    existing.source_id = "user-confirmed-timetable"
    store.save_settings(Settings(easistent_enabled=True, assessments=[existing]))
    payloads = [timetable()]
    factory = lambda _: SimpleNamespace(fetch_weeks=lambda **_: payloads)
    sync_assessments(store, client_factory=factory)
    saved = store.settings().assessments
    assert len(saved) == 1 and saved[0].id == existing.id
    assert saved[0].source == "easistent" and saved[0].source_id == "123"
    payloads[0] = timetable(day="2026-09-25")
    sync_assessments(store, client_factory=factory)
    saved = store.settings().assessments
    assert (
        len(saved) == 1
        and saved[0].id == existing.id
        and saved[0].date == date(2026, 9, 25)
    )


def test_first_school_week_starts_in_september():
    from study.school_browser import week_starts

    starts = week_starts(date(2026, 9, 12), 9)
    assert starts[:3] == [date(2026, 9, 1), date(2026, 9, 7), date(2026, 9, 14)]
    assert len(starts) == 10
    assert starts[-1] == date(2026, 11, 2)


def test_web_text_encoding_preserves_slovenian_subject_matching():
    from study.easistent import decode_school_text, parse_web_timetable

    broken = "Slovenščina".encode().decode("latin1")
    payload = {
        "events": [
            {
                "slug": "ocenjevanje$123",
                "evaluation": {
                    "evaluation_id": 123,
                    "title": "1. šolska naloga".encode().decode("latin1"),
                },
                "subject": {"title": broken},
                "date": "2026-09-23",
                "from": "13:25",
                "to": "14:10",
            }
        ]
    }
    found = parse_web_timetable(payload)[0]
    assert found.subject == "Slovenščina" and found.title == "1. šolska naloga"
    assert decode_school_text("Slovenščina") == "Slovenščina"
    assert decode_school_text("Åland") == "Åland"
