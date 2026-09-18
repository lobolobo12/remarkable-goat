from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from study.google_calendar import (
    connect_service_account,
    credential_present,
    ensure_calendar,
    service_for,
    upsert_event,
)
from study.models import Assessment, Settings
from study.storage import Store


def error(status):
    return HttpError(
        Response({"status": str(status)}), b'{"error":{"message":"fixture"}}'
    )


class Events:
    def __init__(self):
        self.rows = {}
        self.inserts = 0
        self.patches = 0
        self.fail_get = None
        self.lost_response = False

    def get(self, calendarId, eventId):
        def execute(**_):
            if self.fail_get:
                raise error(self.fail_get)
            if eventId not in self.rows:
                raise error(404)
            return self.rows[eventId]

        return SimpleNamespace(execute=execute)

    def insert(self, calendarId, body, sendUpdates):
        def execute(**_):
            self.inserts += 1
            self.rows[body["id"]] = body
            if self.lost_response:
                raise error(409)
            return body

        return SimpleNamespace(execute=execute)

    def patch(self, calendarId, eventId, body, sendUpdates):
        def execute(**_):
            self.patches += 1
            self.rows[eventId].update(body)
            return self.rows[eventId]

        return SimpleNamespace(execute=execute)


@pytest.fixture
def assessment():
    return Assessment(
        id=uuid4(),
        subject="Biologija",
        title="Test 1",
        date=date(2026, 10, 10),
        folder_id=uuid4(),
        updated_at=datetime.now(UTC),
    )


def test_google_creates_once_then_reschedules_same_event(assessment):
    events = Events()
    service = SimpleNamespace(events=lambda: events)
    assert upsert_event(service, "calendar", assessment, 7) == "created"
    assert upsert_event(service, "calendar", assessment, 7) == "unchanged"
    assessment.date += timedelta(days=2)
    assert upsert_event(service, "calendar", assessment, 7) == "updated"
    assert events.inserts == 1 and events.patches == 1
    assert len(events.rows) == 1
    assert events.rows[assessment.id.hex]["start"] == {"date": "2026-10-12"}
    assessment.cancelled = True
    assert upsert_event(service, "calendar", assessment, 7) == "updated"
    events.rows[assessment.id.hex] = {"status": "cancelled"}
    assert upsert_event(service, "calendar", assessment, 7) == "already_cancelled"


def test_google_recovers_ambiguous_insert_without_duplicate(assessment):
    events = Events()
    events.lost_response = True
    assert (
        upsert_event(SimpleNamespace(events=lambda: events), "calendar", assessment, 7)
        == "unchanged"
    )
    assert len(events.rows) == 1


def test_google_auth_failure_is_not_missing_event(assessment):
    events = Events()
    events.fail_get = 403
    with pytest.raises(HttpError):
        upsert_event(SimpleNamespace(events=lambda: events), "calendar", assessment, 7)
    assert events.inserts == 0


def test_google_does_not_overwrite_unowned_event(assessment):
    events = Events()
    events.rows[assessment.id.hex] = {"summary": "Someone else's event"}
    with pytest.raises(RuntimeError, match="ownership"):
        upsert_event(SimpleNamespace(events=lambda: events), "calendar", assessment, 7)
    assert events.patches == 0


def test_ambiguous_calendar_creation_is_not_retried(tmp_path):
    store = Store(tmp_path)
    settings = Settings()

    def execute(**_):
        raise TimeoutError("response lost")

    service = SimpleNamespace(
        calendars=lambda: SimpleNamespace(
            insert=lambda **_: SimpleNamespace(execute=execute)
        )
    )
    with pytest.raises(TimeoutError):
        ensure_calendar(store, settings, service)
    with pytest.raises(RuntimeError, match="previous calendar creation"):
        ensure_calendar(store, settings, service)


def test_service_account_never_falls_back_to_user_oauth(tmp_path):
    store = Store(tmp_path)
    store.save_settings(
        Settings(google_auth_mode="service_account", google_calendar_id="school")
    )
    (store.private / "google-token.json").write_text('{"fixture":"old user token"}')
    assert not credential_present(store)
    with pytest.raises(RuntimeError, match="google-service-account.json"):
        service_for(store)


def test_service_account_cannot_create_calendar(tmp_path):
    store = Store(tmp_path)
    settings = Settings(google_auth_mode="service_account")
    with pytest.raises(RuntimeError, match="existing shared school calendar"):
        ensure_calendar(store, settings, None)
    assert not (store.private / "google-calendar-creation-pending.json").exists()


def test_service_account_switch_requires_live_access(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.save_settings(Settings(google_calendar_id="school"))
    calls = []
    fail = True

    def list_events(**kwargs):
        calls.append(kwargs)

        def execute(**_):
            if fail:
                raise error(403)
            return {"kind": "calendar#events"}

        return SimpleNamespace(execute=execute)

    monkeypatch.setattr(
        "study.google_calendar.service_account_service",
        lambda _: SimpleNamespace(events=lambda: SimpleNamespace(list=list_events)),
    )
    with pytest.raises(HttpError):
        connect_service_account(store)
    assert store.settings().google_auth_mode == "oauth"
    fail = False
    connect_service_account(store)
    assert store.settings().google_auth_mode == "service_account"
    assert store.settings().google_calendar_id == "school"
    assert all(c["calendarId"] == "school" and c["fields"] == "kind" for c in calls)


def test_timed_unmapped_test_keeps_local_time_and_no_invalid_folder_link(assessment):
    from datetime import time

    from study.google_calendar import event_body

    assessment.folder_id = None
    assessment.start_time = time(13, 25)
    assessment.end_time = time(14, 10)
    body = event_body(assessment, 7)
    assert body["start"]["dateTime"] == "2026-10-10T13:25:00+02:00"
    assert body["end"]["dateTime"] == "2026-10-10T14:10:00+02:00"
    assert "/folder/None" not in body["description"]


def test_google_timezone_alias_does_not_cause_hourly_rewrites(assessment):
    from datetime import time

    events = Events()
    service = SimpleNamespace(events=lambda: events)
    assessment.start_time = time(13, 25)
    assessment.end_time = time(14, 10)
    assert upsert_event(service, "calendar", assessment, 7) == "created"
    for key in ("start", "end"):
        events.rows[assessment.id.hex][key]["timeZone"] = "Europe/Belgrade"
    assert upsert_event(service, "calendar", assessment, 7) == "unchanged"
    assert events.patches == 0
