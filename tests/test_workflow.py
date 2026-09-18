import io
import zipfile
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from icalendar import Calendar

from study.calendar import calendar_bytes
from study.cloud import check_bundle, descendants
from study.models import (
    Assessment,
    Extraction,
    Pack,
    Page,
    Question,
    Reference,
    Section,
    Settings,
    Source,
    validate_pack,
)
from study.runner import due, fingerprint, publish
from study.storage import Store


@pytest.fixture
def assessment():
    return Assessment(
        id=uuid4(),
        subject="Matematika",
        title="Test 1",
        date=date(2026, 10, 10),
        folder_id=uuid4(),
        updated_at=datetime(2026, 9, 11, tzinfo=UTC),
    )


def test_seven_day_window_catches_missed_runs_and_ignores_past(assessment):
    assert not due(assessment, date(2026, 10, 2))
    assert due(assessment, date(2026, 10, 3))
    assert due(assessment, date(2026, 10, 8))
    assert due(assessment, date(2026, 10, 10))
    assert not due(assessment, date(2026, 10, 11))
    assessment.cancelled = True
    assert not due(assessment, date(2026, 10, 9))


def test_calendar_reschedule_preserves_uid_and_advances_sequence(assessment):
    settings = Settings(assessments=[assessment])
    first = Calendar.from_ical(calendar_bytes(settings)).walk("VEVENT")[0]
    assessment.date += timedelta(days=3)
    assessment.updated_at += timedelta(hours=1)
    second = Calendar.from_ical(calendar_bytes(settings)).walk("VEVENT")[0]
    assert first["UID"] == second["UID"]
    assert second["SEQUENCE"] > first["SEQUENCE"]
    assert second.decoded("DTSTART") == date(2026, 10, 13)
    assert second.decoded("DTEND") == date(2026, 10, 14)
    assert second.walk("VALARM")[0].decoded("TRIGGER") == timedelta(days=-7)
    assessment.cancelled = True
    assert (
        Calendar.from_ical(calendar_bytes(settings)).walk("VEVENT")[0]["STATUS"]
        == "CANCELLED"
    )


def item(id, parent, folder=False):
    return SimpleNamespace(
        id=id, parent=parent, is_collection=folder, visibleName=id, hash="a" * 64
    )


def test_only_selected_folder_and_nested_notebooks_are_included():
    items = [
        item("test1", "", True),
        item("nested", "test1", True),
        item("a", "test1"),
        item("b", "nested"),
        item("test3", "", True),
        item("c", "test3"),
        item("d", ""),
    ]
    assert [i.id for i in descendants(items, "test1")] == ["a", "b"]
    with pytest.raises(ValueError):
        descendants(items, "missing")
    items[0].parent = "trash"
    with pytest.raises(ValueError, match="Trash"):
        descendants(items, "test1")


def test_folder_cycles_are_not_followed():
    with pytest.raises(ValueError, match="cycle"):
        descendants([item("a", "b", True), item("b", "a", True)], "a")


@pytest.mark.parametrize(
    "filename", ["../escape", "/absolute", "a/../../escape", "..\\escape"]
)
def test_archive_traversal_is_rejected(filename):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(filename, "bad")
    with pytest.raises(ValueError, match="Unsafe"):
        check_bundle(data.getvalue())


def test_every_claim_needs_a_real_nonblank_page():
    ref = Reference(source_id="source", page=1)
    pack = Pack(
        title="Preizkus",
        sections=[Section(title="Tema", explanation="Razlaga", references=[ref])],
        questions=[
            Question(
                question="Vprašanje",
                points=2,
                answer="Odgovor",
                marking="2 točki",
                references=[ref],
            )
        ],
        schedule=[],
        warnings=[],
    )
    docs = {
        "source": Extraction(
            pages=[Page(number=1, blank=False, text="Zapiski", uncertainties=[])]
        )
    }
    validate_pack(pack, docs)
    docs["source"].pages[0].blank = True
    with pytest.raises(ValueError, match="blank"):
        validate_pack(pack, docs)
    pack.sections[0].references = []
    with pytest.raises(ValueError, match="cite"):
        validate_pack(pack, docs)


def test_new_notes_or_date_generate_new_version_not_timestamp(assessment):
    source = Source(id=uuid4(), name="Zapiski", hash="one", pdf="notes.pdf")
    settings = Settings()
    original = fingerprint(assessment, [source], settings)
    assessment.updated_at += timedelta(days=1)
    assert fingerprint(assessment, [source], settings) == original
    source.hash = "two"
    assert fingerprint(assessment, [source], settings) != original
    source.hash = "one"
    assessment.date += timedelta(days=1)
    assert fingerprint(assessment, [source], settings) != original


def test_failed_publication_can_retry_and_success_is_idempotent(tmp_path, assessment):
    store = Store(tmp_path)
    settings = Settings()
    source = Source(id=uuid4(), name="Zapiski", hash="one", pdf="notes.pdf")
    ai = SimpleNamespace(generate=lambda *_: "pack")

    def broken(*_):
        raise RuntimeError("disk problem")

    with pytest.raises(RuntimeError):
        publish(store, assessment, [source], settings, date(2026, 10, 3), ai, broken)
    assert not list(store.output.rglob("complete.json"))

    def successful(pack, sources, destination):
        destination.mkdir()
        (destination / "zapiski.pdf").write_text("fixture")

    assert (
        publish(
            store, assessment, [source], settings, date(2026, 10, 3), ai, successful
        )
        == "generated"
    )
    ai.generate = lambda *_: pytest.fail("Unchanged source must not call the API")
    assert (
        publish(
            store, assessment, [source], settings, date(2026, 10, 4), ai, successful
        )
        == "unchanged"
    )


def test_duplicate_assessment_ids_rejected(assessment):
    with pytest.raises(ValueError, match="Duplicate"):
        Settings(assessments=[assessment, assessment])


def test_cloud_login_failure_is_recorded_and_does_not_use_old_notes(
    tmp_path, assessment, monkeypatch
):
    from study.runner import run_once

    store = Store(tmp_path)
    assessment.date = datetime.now(UTC).date() + timedelta(days=1)
    store.save_settings(Settings(assessments=[assessment]))
    monkeypatch.setattr(
        "study.runner.sync_google", lambda *_: {"status": "not_connected"}
    )

    def fail(_):
        raise RuntimeError("login expired")

    report = run_once(store, client_factory=fail)
    assert report["tests"][0]["status"] == "sync_failed"
    assert "sync_failed" in (store.private / "last-run.json").read_text()
    assert not list(store.output.rglob("complete.json"))


def test_reading_model_changes_invalidate_pack_cache(assessment):
    source = Source(id=uuid4(), name="Zapiski", hash="one", pdf="notes.pdf")
    settings = Settings(model="gpt-5.6-luna", reading_model="gpt-5.6-luna")
    before = fingerprint(assessment, [source], settings)
    settings.reading_model = "gpt-5.6-sol"
    assert fingerprint(assessment, [source], settings) != before


def test_page_omission_retries_individually_and_uses_reader_model(
    tmp_path, monkeypatch
):
    from pypdf import PdfWriter

    from study.ai import StudyAI

    store = Store(tmp_path)
    pdf = tmp_path / "notes.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    writer.write(pdf)
    monkeypatch.setattr("study.ai.blank_pages", lambda _: set())
    source = Source(id=uuid4(), name="Notes", hash="one", pdf="notes.pdf")
    settings = Settings(model="gpt-5.6-luna", reading_model="gpt-5.6-sol")
    ai = StudyAI(store, settings, client=object())
    calls = []

    def parse(schema, instructions, content, *, model):
        calls.append(model)
        return Extraction(pages=[Page(number=1, blank=True, text="", uncertainties=[])])

    ai.parse = parse
    result = ai.extract(source)
    assert [page.number for page in result.pages] == [1, 2]
    assert calls == ["gpt-5.6-sol"] * 3
    ai.extract(source)
    assert len(calls) == 3
