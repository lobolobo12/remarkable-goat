"""JSON-over-stdio bridge for the native Mac app. No web server or open port."""

import contextlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from .ai import StudyAI
from .cloud import client_for, sync_folder, sync_selection
from .delivery import deliver
from .explorer import library_tree
from .mapping import choose_folder, test_number
from .models import Assessment, Diagnostic
from .personal import (
    attachment_sources,
    create_diagnostic,
    import_attachment,
    score_diagnostic,
)
from .runner import fingerprint, publish, run_once
from .storage import Store, write_json


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def diagnostic_file(store, identifier):
    return store.private / "diagnostics" / f"{UUID(str(identifier))}.json"


def state(store):
    settings = store.settings()
    tests = []
    for a in sorted(settings.assessments, key=lambda a: (a.date, a.subject)):
        if a.cancelled:
            continue
        row = a.model_dump(mode="json")
        row["folder_selection"] = str(settings.assessment_folders.get(str(a.id), ""))
        row["test_number"] = test_number(a, settings)
        row["attachments"] = [
            s.model_dump(mode="json") for s in attachment_sources(store, a.id)
        ]
        latest = read_json(store.output / str(a.id) / "latest.json", {})
        row["output_path"] = str(store.root / latest["path"]) if latest else None
        saved = read_json(diagnostic_file(store, a.id), {})
        row["diagnostic"] = (
            {
                "title": saved["quiz"]["title"],
                "warnings": saved["quiz"]["warnings"],
                "questions": [
                    {
                        k: v
                        for k, v in q.items()
                        if k not in {"correct_index", "explanation"}
                    }
                    for q in saved["quiz"]["questions"]
                ],
            }
            if saved
            else None
        )
        tests.append(row)
    report = read_json(store.private / "last-run.json", {})
    needs_school = (
        not settings.easistent_enabled
        or report.get("easistent", {}).get("status") == "fetch_failed"
    )
    attention = (
        "Za samodejni uvoz testov se prijavi v eAsistent."
        if needs_school
        else (
            "Zadnji samodejni pregled potrebuje pozornost. Odpri poročilo."
            if report.get("needs_attention")
            else ""
        )
    )
    return {
        "attention": attention,
        "report_path": str(store.output / "index.html"),
        "tests": tests,
        "folders": read_json(store.private / "desktop-folders.json", []),
        "library": read_json(store.private / "desktop-library.json", []),
        "last_run": read_json(store.private / "last-run.json", {}),
        "models": {
            "reading": settings.reading_model or settings.model,
            "generation": settings.model,
        },
        "geography_path": str(store.output / "pdf" / "geografija"),
        "easistent_connected": settings.easistent_enabled,
        "calendar_connected": bool(settings.google_calendar_id),
    }


def get_assessment(settings, identifier):
    return next(
        a for a in settings.assessments if str(a.id) == str(UUID(str(identifier)))
    )


def cache_folders(store, items):
    write_json(store.private / "desktop-library.json", library_tree(store, items))
    by_id = {str(i.id): i for i in items}
    folders = []
    for item in items:
        if not item.is_collection:
            continue
        names, current, seen = [], item, set()
        while current is not None and str(current.id) not in seen:
            seen.add(str(current.id))
            names.insert(0, current.visibleName)
            if str(current.parent) == "trash":
                names = []
                break
            current = by_id.get(str(current.parent))
        if names and names[0] != "Učna priprava":
            folders.append({"id": str(item.id), "name": " / ".join(names)})
    write_json(
        store.private / "desktop-folders.json", sorted(folders, key=lambda f: f["name"])
    )


def sources_for(store, assessment, settings, client):
    items = client.list_items(refresh=True)
    cache_folders(store, items)
    if assessment.material_ids:
        sources = sync_selection(store, client, assessment.material_ids, items)
    else:
        assessment.folder_id, _ = choose_folder(assessment, settings, items)
        store.save_settings(settings)
        sources = (
            sync_folder(store, client, str(assessment.folder_id), items)
            if assessment.folder_id
            else []
        )
    sources += attachment_sources(store, assessment.id)
    if not sources:
        raise ValueError("Poveži mapo reMarkable ali dodaj slike/PDF.")
    return sources


def dispatch(store, request):
    action = request.get("action", "state")
    if action == "state":
        return state(store)
    if action == "connect_school":
        from .school_browser import connect_browser

        connect_browser(store)
        return state(store)
    with store.lock():
        settings = store.settings()
        if action == "refresh":
            run_once(store)
            with client_for(store) as client:
                cache_folders(store, client.list_items(refresh=True))
        elif action == "refresh_files":
            with client_for(store) as client:
                cache_folders(store, client.list_items(refresh=True))
        elif action == "add_test":
            now = datetime.now(ZoneInfo(settings.timezone))
            assessment = Assessment(
                id=uuid4(),
                subject=request["subject"].strip(),
                title=request.get("title") or "Ocenjevanje znanja",
                date=request["date"],
                updated_at=now,
            )
            settings.assessments.append(assessment)
            store.save_settings(settings)
        else:
            assessment = get_assessment(settings, request["id"])
            if action == "save":
                fields = {
                    k: request[k]
                    for k in (
                        "study_hours",
                        "knowledge_level",
                        "target_grade",
                        "scope_notes",
                        "folder_id",
                        "material_ids",
                    )
                    if k in request
                }
                if "material_ids" in fields:
                    fields["material_ids"] = sorted(
                        {str(UUID(value)) for value in fields["material_ids"]}
                    )
                materials_changed = "material_ids" in fields and fields[
                    "material_ids"
                ] != sorted(str(value) for value in assessment.material_ids)
                selection = request.get("folder_id")
                old_selection = str(
                    settings.assessment_folders.get(str(assessment.id), "")
                )
                selection_changed = (
                    selection is not None and str(selection or "") != old_selection
                )
                changed_source = (
                    materials_changed
                    or selection_changed
                    or (
                        "scope_notes" in fields
                        and fields["scope_notes"] != assessment.scope_notes
                    )
                )
                if "folder_id" in fields:
                    fields["folder_id"] = selection or (
                        None if selection_changed else assessment.folder_id
                    )
                assessment = Assessment.model_validate(
                    {
                        **assessment.model_dump(),
                        **fields,
                        "updated_at": datetime.now(ZoneInfo(settings.timezone)),
                    }
                )
                if assessment.material_ids:
                    assessment.folder_id = None
                if changed_source:
                    assessment.diagnostic_result = None
                    diagnostic_file(store, assessment.id).unlink(missing_ok=True)
                elif assessment.diagnostic_result and "target_grade" in fields:
                    saved = read_json(diagnostic_file(store, assessment.id), {})
                    if "answers" in saved:
                        assessment.diagnostic_result = score_diagnostic(
                            Diagnostic.model_validate(saved["quiz"]),
                            saved["answers"],
                            assessment.target_grade,
                        )
                settings.assessments = [
                    assessment if a.id == assessment.id else a
                    for a in settings.assessments
                ]
                if selection is not None:
                    if selection:
                        settings.assessment_folders[str(assessment.id)] = UUID(
                            selection
                        )
                    else:
                        settings.assessment_folders.pop(str(assessment.id), None)
                store.save_settings(settings)
            elif action == "attach":
                for path in request["paths"]:
                    import_attachment(store, assessment.id, path)
                assessment.diagnostic_result = None
                diagnostic_file(store, assessment.id).unlink(missing_ok=True)
                store.save_settings(settings)
            elif action == "remove_attachment":
                remaining = [
                    s
                    for s in attachment_sources(store, assessment.id)
                    if str(s.id) != str(UUID(request["attachment_id"]))
                ]
                write_json(
                    store.private / "attachments" / str(assessment.id) / "sources.json",
                    [s.model_dump(mode="json") for s in remaining],
                )
                assessment.diagnostic_result = None
                diagnostic_file(store, assessment.id).unlink(missing_ok=True)
                store.save_settings(settings)
            elif action in {"prepare", "diagnostic"}:
                with client_for(store) as client:
                    sources = sources_for(store, assessment, settings, client)
                    ai = StudyAI(store, settings)
                    if action == "prepare":
                        publish(
                            store,
                            assessment,
                            sources,
                            settings,
                            datetime.now(ZoneInfo(settings.timezone)).date(),
                            ai,
                        )
                        if settings.tablet_delivery:
                            deliver(store, client, assessment)
                    else:
                        quiz = create_diagnostic(ai, assessment, sources)
                        write_json(
                            diagnostic_file(store, assessment.id),
                            {
                                "quiz": quiz.model_dump(mode="json"),
                                "fingerprint": fingerprint(
                                    assessment, sources, settings
                                ),
                            },
                        )
                        assessment.diagnostic_result = None
                        store.save_settings(settings)
            elif action == "score":
                saved = read_json(diagnostic_file(store, assessment.id), None)
                if not saved:
                    raise ValueError("Najprej ustvari predtest.")
                diagnostic = Diagnostic.model_validate(saved["quiz"])
                assessment.diagnostic_result = score_diagnostic(
                    diagnostic, request["answers"], assessment.target_grade
                )
                saved["answers"] = request["answers"]
                write_json(diagnostic_file(store, assessment.id), saved)
                store.save_settings(settings)
            else:
                raise ValueError("Neznano dejanje.")
    return state(store)


def main():
    os.umask(0o077)
    store = Store(Path(sys.argv[1]))
    try:
        request = json.loads(sys.stdin.read(2_000_000))
        with contextlib.redirect_stdout(sys.stderr):
            result = dispatch(store, request)
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False))
    except Exception as exc:
        # Third-party errors can contain request headers; show only controlled errors.
        message = (
            str(exc)
            if isinstance(exc, (ValueError, RuntimeError))
            and not any(
                t in str(exc).lower()
                for t in ("token", "api_key", "authorization", "sk-")
            )
            else type(exc).__name__
        )
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))


if __name__ == "__main__":
    main()
