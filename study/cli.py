import argparse
import getpass
import importlib.util
import json
import os
import secrets
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from .calendar import make_server
from .cloud import client_for, renderer_command, renderer_environment, sync_folder
from .models import Assessment
from .runner import run_once
from .storage import Store


def doctor(store):
    import subprocess

    from .google_calendar import credential_present

    renderer = renderer_command()
    renderer_ok = False
    if renderer:
        try:
            renderer_ok = (
                subprocess.run(
                    [renderer, "--help"],
                    capture_output=True,
                    timeout=20,
                    check=False,
                    env=renderer_environment(),
                ).returncode
                == 0
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    status = {
        "remarkable_browser": "Browser sign-in is separate from background pairing",
        "remarkable_paired": store.token_file.exists()
        and store.token_file.stat().st_size > 0,
        "remarkable_client_installed": importlib.util.find_spec("remarkapy")
        is not None,
        "notebook_renderer_ready": renderer_ok,
        "openai_key_present": bool(os.environ.get("OPENAI_API_KEY"))
        or (store.key_file.exists() and bool(store.key_file.read_text().strip())),
        "model": store.settings().model,
        "reading_model": store.settings().reading_model or store.settings().model,
        "mapped_tests": sum(
            a.folder_id is not None for a in store.settings().assessments
        ),
        "discovered_tests": len(store.settings().assessments),
        "easistent": "browser_connected"
        if (store.private / "easistent-browser-check.json").exists()
        else "connection_required",
        "easistent_enabled": store.settings().easistent_enabled,
        "tablet_delivery": store.settings().tablet_delivery,
        "google_calendar_connected": credential_present(store),
        "google_auth_mode": store.settings().google_auth_mode,
        "google_calendar_id": store.settings().google_calendar_id,
    }
    print(json.dumps(status, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Study packs from your own reMarkable test folders"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    for name in [
        "doctor",
        "pair",
        "set-key",
        "folders",
        "run",
        "list-tests",
        "connect-google",
        "connect-google-service-account",
        "connect-easistent",
        "install-scheduler",
        "scheduler-status",
        "sync-dates",
        "watch",
    ]:
        sub.add_parser(name)
    mapping = sub.add_parser("map-folder")
    mapping.add_argument("--subject", required=True)
    mapping.add_argument("--folder", required=True, type=UUID)
    test_mapping = sub.add_parser("map-test")
    test_mapping.add_argument("--id", required=True, type=UUID)
    test_mapping.add_argument("--folder", required=True, type=UUID)
    prepare = sub.add_parser(
        "prepare-test", help="Prepare one real test now to verify the full workflow"
    )
    prepare.add_argument("id", type=UUID)
    add = sub.add_parser("add-test")
    add.add_argument("--subject", required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--date", required=True, type=date.fromisoformat)
    add.add_argument(
        "--folder",
        required=True,
        type=UUID,
        help="reMarkable folder UUID, from study folders",
    )
    add.add_argument(
        "--id",
        type=UUID,
        help="Existing test ID to update without duplicating calendar events",
    )
    cancel = sub.add_parser("cancel-test")
    cancel.add_argument("id", type=UUID)
    export = sub.add_parser(
        "export-folder", help="Fetch and render a test folder without calling AI"
    )
    export.add_argument("--folder", required=True, type=UUID)
    service = sub.add_parser(
        "serve", help="Serve a local calendar feed and run the workflow daily"
    )
    service.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    os.umask(0o077)
    store = Store(args.root)
    try:
        if args.command == "install-scheduler":
            from .scheduler import install

            print("Hourly scheduler installed:", install(store))
        elif args.command == "scheduler-status":
            from .scheduler import status

            print(json.dumps(status()))
        elif args.command == "sync-dates":
            from .easistent import sync_assessments

            with store.lock():
                print(json.dumps(sync_assessments(store)))
        elif args.command in {"map-folder", "map-test"}:
            from .cloud import descendants
            from .mapping import subject_key

            with store.lock(), client_for(store) as client:
                descendants(client.list_items(refresh=True), str(args.folder))
                settings = store.settings()
                if args.command == "map-folder":
                    settings.subject_folders[subject_key(args.subject)] = args.folder
                else:
                    if not any(a.id == args.id for a in settings.assessments):
                        raise ValueError("Test ID not found")
                    settings.assessment_folders[str(args.id)] = args.folder
                store.save_settings(settings)
            print("Folder mapping saved.")
        elif args.command == "prepare-test":
            from .ai import StudyAI
            from .delivery import deliver
            from .mapping import choose_folder
            from .runner import publish

            with store.lock(), client_for(store) as client:
                settings = store.settings()
                assessment = next(
                    (a for a in settings.assessments if a.id == args.id), None
                )
                if assessment is None or assessment.cancelled:
                    raise ValueError("Active test ID not found")
                items = client.list_items(refresh=True)
                if not assessment.material_ids:
                    assessment.folder_id, _ = choose_folder(assessment, settings, items)
                from .personal import attachment_sources

                if (
                    not assessment.material_ids
                    and assessment.folder_id is None
                    and not attachment_sources(store, assessment.id)
                ):
                    raise ValueError("Map a test folder or add attachments first")
                store.save_settings(settings)
                from .cloud import sync_selection

                sources = (
                    sync_selection(store, client, assessment.material_ids, items)
                    if assessment.material_ids
                    else (
                        sync_folder(store, client, str(assessment.folder_id), items)
                        if assessment.folder_id
                        else []
                    )
                )
                print(
                    publish(
                        store,
                        assessment,
                        sources,
                        settings,
                        datetime.now(ZoneInfo(settings.timezone)).date(),
                        StudyAI(store, settings),
                    ),
                    flush=True,
                )
                if settings.tablet_delivery:
                    print(json.dumps(deliver(store, client, assessment)), flush=True)
        elif args.command == "connect-easistent":
            from .school_browser import connect_browser

            connect_browser(store)
        elif args.command == "connect-google":
            from .google_calendar import connect

            connect(store)
            print("Google Calendar connected. study run will sync mapped tests.")
        elif args.command == "connect-google-service-account":
            from .google_calendar import connect_service_account

            connect_service_account(store)
            print("Service-account Calendar access verified and selected.")
        elif args.command == "doctor":
            doctor(store)
        elif args.command == "set-key":
            value = getpass.getpass(
                "OpenAI API key (hidden; saved only in .private/openai-key): "
            ).strip()
            if not value:
                raise ValueError("No key entered")
            store.key_file.write_text(value)
            os.chmod(store.key_file, 0o600)
            print("API key saved locally. No API request made.")
        elif args.command == "pair":
            from remarkapy import Client

            if store.token_file.exists():
                print("Pairing file exists. Use study folders to check the connection.")
                return 0
            print("Get your pairing code at https://my.remarkable.com/pair/app")
            code = getpass.getpass("reMarkable pairing code (hidden): ").strip()
            if len(code) != 8:
                raise ValueError("Expected an eight-character pairing code")
            with Client(
                configfile=store.token_file, interactive=False, persist_config=True
            ) as client:
                client.register_device(code)
                client.refresh_user_token()
            os.chmod(store.token_file, 0o600)
            print("Background sync paired. Notebook contents have not been downloaded.")
        elif args.command == "export-folder":
            with store.lock(), client_for(store) as client:
                sources = sync_folder(
                    store, client, str(args.folder), client.list_items(refresh=True)
                )
            print(
                json.dumps(
                    [source.model_dump(mode="json") for source in sources],
                    indent=2,
                    ensure_ascii=False,
                )
            )
        elif args.command == "folders":
            with client_for(store) as client:
                items = client.list_items(refresh=True)
                by_id = {str(item.id): item for item in items}
                for item in items:
                    if not item.is_collection:
                        continue
                    names, parent, seen = (
                        [item.visibleName],
                        str(item.parent),
                        {str(item.id)},
                    )
                    while parent in by_id:
                        if parent in seen:
                            raise ValueError("Folder cycle")
                        seen.add(parent)
                        ancestor = by_id[parent]
                        names.insert(0, ancestor.visibleName)
                        parent = str(ancestor.parent)
                    if parent != "trash":
                        print(f"{item.id}  {' / '.join(names)}")
        elif args.command in {"add-test", "cancel-test"}:
            with store.lock():
                settings = store.settings()
                now = datetime.now(ZoneInfo(settings.timezone))
                if args.command == "cancel-test":
                    match = next(
                        (a for a in settings.assessments if a.id == args.id), None
                    )
                    if match is None:
                        raise ValueError("Test ID not found")
                    match.cancelled, match.updated_at = True, now
                else:
                    test_id = args.id or uuid4()
                    if args.id and not any(
                        a.id == args.id for a in settings.assessments
                    ):
                        raise ValueError(
                            "Test ID not found; omit --id to create a new test"
                        )
                    assessment = Assessment(
                        id=test_id,
                        subject=args.subject,
                        title=args.title,
                        date=args.date,
                        folder_id=args.folder,
                        updated_at=now,
                    )
                    settings.assessments = [
                        a for a in settings.assessments if a.id != test_id
                    ] + [assessment]
                    print(f"Test ID: {test_id}")
                store.save_settings(settings)
        elif args.command == "list-tests":
            print(store.settings().model_dump_json(indent=2))
        elif args.command == "run":
            with store.lock():
                report = run_once(store)
            print(json.dumps(report, indent=2))
            return int(report["needs_attention"])
        elif args.command == "watch":
            print(
                "Runs now, then every 24 hours while the Mac and process are running.",
                flush=True,
            )
            while True:
                try:
                    with store.lock():
                        print(json.dumps(run_once(store)), flush=True)
                except Exception as exc:
                    print(
                        f"Run failed: {type(exc).__name__}; check study doctor",
                        file=sys.stderr,
                        flush=True,
                    )
                time.sleep(86400)
        elif args.command == "serve":
            token_file = store.private / "calendar-token"
            if not token_file.exists():
                token_file.write_text(secrets.token_urlsafe(24))
            token = token_file.read_text().strip()
            server = make_server(store.output / "tests.ics", token, args.port)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            print(
                f"Apple Calendar subscription URL (this Mac only): http://127.0.0.1:{args.port}/{token}/tests.ics",
                flush=True,
            )
            print(
                "Runs now, then every 24 hours while this process and Mac are running.",
                flush=True,
            )
            try:
                while True:
                    try:
                        with store.lock():
                            print(json.dumps(run_once(store)), flush=True)
                    except Exception as exc:
                        print(
                            f"Run failed: {type(exc).__name__}; check study doctor",
                            file=sys.stderr,
                            flush=True,
                        )
                    time.sleep(86400)
            finally:
                server.shutdown()
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        # Third-party exceptions can contain server bodies. Do not print auth responses.
        if isinstance(exc, (ValueError, RuntimeError, FileNotFoundError)):
            print(str(exc), file=sys.stderr)
        else:
            print(
                f"{type(exc).__name__}: command failed; check study doctor",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
