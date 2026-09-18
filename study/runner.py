import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .ai import EXTRACT, GENERATE, StudyAI
from .calendar import calendar_bytes
from .cloud import client_for, sync_folder, sync_selection
from .delivery import deliver
from .easistent import sync_assessments
from .google_calendar import sync_google
from .mapping import choose_folder
from .models import Assessment, Settings, Source
from .output import render_pack
from .personal import attachment_sources
from .storage import Store, digest, write_json


def due(assessment: Assessment, today: date, days_before: int = 7):
    return (
        not assessment.cancelled and 0 <= (assessment.date - today).days <= days_before
    )


def fingerprint(assessment: Assessment, sources: list[Source], settings: Settings):
    payload = {
        "test": assessment.model_dump(mode="json", exclude={"updated_at"}),
        "sources": sorted((str(s.id), s.name, s.hash) for s in sources),
        "model": settings.model,
        "reading_model": settings.reading_model or settings.model,
        "days_before": settings.days_before,
        "prompts": [EXTRACT, GENERATE],
    }
    return digest(json.dumps(payload, sort_keys=True).encode())


def publish(store, assessment, sources, settings, today, ai, render=render_pack):
    sources = sources + [
        s
        for s in attachment_sources(store, assessment.id)
        if s.id not in {x.id for x in sources}
    ]
    version = fingerprint(assessment, sources, settings)
    output = store.output / str(assessment.id) / version
    if (output / "complete.json").exists():
        write_json(
            output.parent / "latest.json", {"path": str(output.relative_to(store.root))}
        )
        return "unchanged"
    # Cache a completed paid generation separately from PDF rendering/publication.
    cached = store.private / "generated" / f"{version}.json"
    from .models import Pack

    if cached.exists():
        pack = Pack.model_validate_json(cached.read_text())
    else:
        pack = ai.generate(assessment, sources, max(1, (assessment.date - today).days))
        if isinstance(pack, Pack):
            write_json(cached, pack.model_dump())
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        stage = Path(tmp) / "pack"
        render(pack, sources, stage)
        write_json(
            stage / "complete.json", {"version": version, "generated_on": str(today)}
        )
        os.replace(stage, output)
    write_json(
        output.parent / "latest.json", {"path": str(output.relative_to(store.root))}
    )
    return "generated"


def run_once(store: Store, *, client_factory=client_for, ai_factory=StudyAI):
    settings = store.settings()
    now = datetime.now(ZoneInfo(settings.timezone))
    report = {"at": now.isoformat(), "tests": []}
    try:
        report["easistent"] = sync_assessments(store, today=now.date())
    except Exception as exc:
        report["easistent"] = {"status": "fetch_failed", "error": type(exc).__name__}
    settings = store.settings()
    active = [
        a for a in settings.assessments if not a.cancelled and a.date >= now.date()
    ]
    client = None
    items = []
    try:
        if active:
            client = client_factory(store)
            client.__enter__()
            items = client.list_items(refresh=True)
            for assessment in active:
                if not assessment.material_ids and (
                    assessment.source == "easistent"
                    or assessment.folder_id is None
                    or str(assessment.id) not in settings.assessment_folders
                ):
                    try:
                        folder, _reason = choose_folder(assessment, settings, items)
                        assessment.folder_id = folder
                    except ValueError:
                        assessment.folder_id = None
            store.save_settings(settings)
    except Exception as exc:
        report["remarkable"] = {"status": "sync_failed", "error": type(exc).__name__}
    store.output.mkdir(parents=True, exist_ok=True)
    calendar = store.output / "tests.ics"
    tmp = calendar.with_suffix(".tmp")
    tmp.write_bytes(calendar_bytes(settings))
    os.replace(tmp, calendar)
    try:
        report["google_calendar"] = sync_google(store, settings)
    except Exception as exc:
        report["google_calendar"] = {"status": "failed", "error": type(exc).__name__}
    try:
        synced, failures = {}, {}
        ai, generated = None, 0
        for assessment in sorted(active, key=lambda item: item.date):
            entry = {
                "id": str(assessment.id),
                "title": assessment.title,
                "subject": assessment.subject,
                "date": str(assessment.date),
            }
            try:
                if report.get("remarkable", {}).get("status") == "sync_failed":
                    entry.update(
                        status="sync_failed", error=report["remarkable"]["error"]
                    )
                elif (
                    assessment.source == "easistent"
                    and report["easistent"]["status"] != "synced"
                ):
                    entry["status"] = "source_unavailable"
                elif (
                    not assessment.material_ids
                    and assessment.folder_id is None
                    and not attachment_sources(store, assessment.id)
                ):
                    entry["status"] = "folder_mapping_required"
                elif not due(assessment, now.date(), settings.days_before):
                    entry["status"] = "waiting_for_study_window"
                else:
                    folder = (
                        "selection:"
                        + ",".join(sorted(str(i) for i in assessment.material_ids))
                        if assessment.material_ids
                        else str(assessment.folder_id)
                    )
                    if assessment.folder_id is None and not assessment.material_ids:
                        synced[folder] = []
                    if folder not in synced and folder not in failures:
                        try:
                            synced[folder] = (
                                sync_selection(
                                    store, client, assessment.material_ids, items
                                )
                                if assessment.material_ids
                                else sync_folder(store, client, folder, items)
                            )
                        except Exception as exc:
                            failures[folder] = type(exc).__name__
                    if folder in failures:
                        entry.update(status="sync_failed", error=failures[folder])
                    else:
                        version = fingerprint(
                            assessment,
                            synced[folder] + attachment_sources(store, assessment.id),
                            settings,
                        )
                        complete = (
                            store.output
                            / str(assessment.id)
                            / version
                            / "complete.json"
                        )
                        if (
                            generated >= settings.max_packs_per_run
                            and not complete.exists()
                        ):
                            entry["status"] = "deferred_run_limit"
                        else:
                            if ai is None:
                                ai = ai_factory(store, settings)
                            entry["status"] = publish(
                                store,
                                assessment,
                                synced[folder],
                                settings,
                                now.date(),
                                ai,
                            )
                            generated += entry["status"] == "generated"
                            if settings.tablet_delivery:
                                try:
                                    entry["delivery"] = deliver(
                                        store, client, assessment
                                    )
                                except Exception as exc:
                                    entry["delivery"] = {
                                        "status": "delivery_failed",
                                        "error": type(exc).__name__,
                                    }
            except Exception as exc:
                entry.update(status="generation_failed", error=type(exc).__name__)
            report["tests"].append(entry)
    finally:
        if client is not None:
            try:
                client.__exit__(None, None, None)
            except Exception as exc:
                report["remarkable_close"] = {
                    "status": "failed",
                    "error": type(exc).__name__,
                }
    report["needs_attention"] = (
        report["easistent"]["status"] != "synced"
        or report["google_calendar"]["status"] in {"failed", "not_connected"}
        or any(
            item["status"].endswith("failed")
            or item["status"] in {"folder_mapping_required", "source_unavailable"}
            or item.get("delivery", {}).get("status") == "delivery_failed"
            for item in report["tests"]
        )
    )
    write_json(store.private / "last-run.json", report)
    write_status(store, report)
    return report


def write_status(store, report):
    from html import escape

    labels = {
        "generated": "Pripravljeno",
        "unchanged": "Gradivo je posodobljeno",
        "waiting_for_study_window": "Priprava se začne 7 dni pred testom",
        "folder_mapping_required": "Poveži mapo zapiskov",
        "source_unavailable": "Ponovno poveži eAsistent",
        "sync_failed": "Zapiskov ni bilo mogoče prenesti",
        "generation_failed": "Priprava ni uspela; program bo poskusil znova",
        "deferred_run_limit": "Priprava pri naslednjem pregledu",
        "synced": "Povezano",
        "not_connected": "Povezava še ni končana",
        "fetch_failed": "Preveri prijavo v eAsistent",
        "failed": "Povezava ni uspela",
        "no_tests": "Ni vpisanih testov",
    }
    rows = []
    settings = store.settings()
    for item in report["tests"]:
        latest = store.output / item["id"] / "latest.json"
        links = ""
        if latest.exists():
            directory = store.root / json.loads(latest.read_text())["path"]
            relative = directory.relative_to(store.output)
            links = " · ".join(
                f'<a href="{escape(str(relative / name), quote=True)}">{label}</a>'
                for name, label in [
                    ("zapiski.pdf", "Zapiski"),
                    ("vaje.pdf", "Vaje"),
                    ("resitve.pdf", "Rešitve"),
                ]
            )
        rows.append(
            f"<tr><td>{escape(item['date'])}</td><td>{escape(item['subject'])}</td><td>{escape(labels.get(item['status'], item['status']))}</td><td>{links}</td></tr>"
        )
    body = f"""<!doctype html><html lang="sl"><meta charset="utf-8"><title>Učna priprava</title><style>body{{font:17px system-ui;max-width:1100px;margin:50px auto;padding:24px;background:#f3f5f2;color:#18362b}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:16px;border-bottom:1px solid #ccd4cf}}a{{color:#185c42}}p{{line-height:1.6}}</style><h1>Učna priprava</h1><p>Zadnji pregled: {escape(report["at"])}<br>eAsistent: {escape(labels.get(report["easistent"]["status"], report["easistent"]["status"]))}<br>Google Calendar: {escape(labels.get(report["google_calendar"]["status"], report["google_calendar"]["status"]))}</p><p>Priprava {settings.days_before} dni pred testom. Gradivo temelji na zapiskih iz povezanih map reMarkable.</p><table><tr><th>Datum</th><th>Predmet</th><th>Stanje</th><th>Gradivo</th></tr>{"".join(rows)}</table><p>Na tablici: Učna priprava → datum in predmet → različica. Rešitve so v ločenem dokumentu.</p></html>"""
    (store.output / "index.html").write_text(body, encoding="utf-8")
