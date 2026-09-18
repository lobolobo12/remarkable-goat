"""School-calendar sync via user OAuth or an explicitly shared service account."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .storage import write_json

SCOPES = ["https://www.googleapis.com/auth/calendar.app.created"]
SERVICE_ACCOUNT_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def credential_present(store):
    name = (
        "google-service-account.json"
        if store.settings().google_auth_mode == "service_account"
        else "google-token.json"
    )
    return (store.private / name).exists()


def service_account_service(store):
    # Calendar sharing supplies the resource boundary; no user impersonation,
    # domain-wide delegation, or project IAM roles are needed.
    path = store.private / "google-service-account.json"
    if not path.exists():
        raise RuntimeError("Missing .private/google-service-account.json")
    credentials = ServiceAccountCredentials.from_service_account_file(
        str(path), scopes=SERVICE_ACCOUNT_SCOPES
    )
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def connect_service_account(store):
    settings = store.settings()
    if not settings.google_calendar_id:
        raise RuntimeError("Set the existing shared school calendar ID first")
    service = service_account_service(store)
    # Check actual access before switching away from the working OAuth connection.
    # Do not create another calendar or expose the returned event contents.
    service.events().list(
        calendarId=settings.google_calendar_id, maxResults=1, fields="kind"
    ).execute(num_retries=3)
    settings.google_auth_mode = "service_account"
    store.save_settings(settings)


def connect(store):
    config = store.private / "google-client.json"
    if not config.exists():
        raise RuntimeError(
            "Google desktop OAuth client missing: save it to .private/google-client.json (see README)"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(config), SCOPES)
    # User completes Google sign-in/consent; no browser credentials are inspected.
    credentials = flow.run_local_server(port=0, open_browser=False, timeout_seconds=300)
    write_json(store.private / "google-token.json", json.loads(credentials.to_json()))
    settings = store.settings()
    settings.google_auth_mode = "oauth"
    store.save_settings(settings)
    ensure_calendar(store, store.settings(), service_for(store))


def service_for(store):
    settings = store.settings()
    if settings.google_auth_mode == "service_account":
        if not settings.google_calendar_id:
            raise RuntimeError("Set the existing shared school calendar ID first")
        return service_account_service(store)
    token = store.private / "google-token.json"
    if not token.exists():
        raise RuntimeError(
            "Google Calendar is not connected. Run: study connect-google"
        )
    credentials = Credentials.from_authorized_user_file(str(token), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        write_json(token, json.loads(credentials.to_json()))
    if not credentials.valid:
        raise RuntimeError("Google Calendar login expired. Run: study connect-google")
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def event_body(assessment, days_before):
    body = {
        "summary": f"{assessment.subject}: {assessment.title}",
        "description": "Učno gradivo temelji na tvojih zapiskih.\n"
        + (
            f"https://app.remarkable.com/folder/{assessment.folder_id}\n"
            if assessment.folder_id
            else (
                f"Izbrani zapiski in mape: {len(assessment.material_ids)}.\n"
                if assessment.material_ids
                else "Mapa zapiskov še ni povezana.\n"
            )
        )
        + (
            "Datum vnesen ročno."
            if assessment.source == "manual"
            else "Vir datuma: eAsistent."
        ),
        "start": {"date": assessment.date.isoformat()},
        "end": {"date": (assessment.date + timedelta(days=1)).isoformat()},
        "status": "cancelled" if assessment.cancelled else "confirmed",
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": min(40320, days_before * 1440)}
            ],
        },
        "extendedProperties": {"private": {"remarkableStudyId": str(assessment.id)}},
    }

    if assessment.start_time and assessment.end_time:
        zone = ZoneInfo("Europe/Ljubljana")
        body["start"] = {
            "dateTime": datetime.combine(
                assessment.date, assessment.start_time, zone
            ).isoformat(),
            "timeZone": "Europe/Ljubljana",
        }
        body["end"] = {
            "dateTime": datetime.combine(
                assessment.date, assessment.end_time, zone
            ).isoformat(),
            "timeZone": "Europe/Ljubljana",
        }
    if assessment.location:
        body["location"] = assessment.location
    return body


def event_matches(existing, desired):
    for key, value in desired.items():
        actual = existing.get(key)
        if (
            key in {"start", "end"}
            and value.get("dateTime")
            and isinstance(actual, dict)
        ):
            try:
                if datetime.fromisoformat(actual["dateTime"]) != datetime.fromisoformat(
                    value["dateTime"]
                ):
                    return False
            except (KeyError, ValueError):
                return False
        elif actual != value:
            return False
    return True


def upsert_event(service, calendar_id, assessment, days_before):
    event_id = (
        assessment.id.hex
    )  # Google accepts base32hex; UUID hex is a valid subset.
    events = service.events()
    desired = event_body(assessment, days_before)
    try:
        existing = events.get(calendarId=calendar_id, eventId=event_id).execute(
            num_retries=3
        )
    except HttpError as exc:
        if exc.resp.status not in {404, 410}:
            raise
        if assessment.cancelled:
            return "already_absent"
        try:
            events.insert(
                calendarId=calendar_id,
                body={"id": event_id, **desired},
                sendUpdates="none",
            ).execute(num_retries=3)
            return "created"
        except HttpError as conflict:
            # A timed-out insert may have succeeded; retry addresses the same ID.
            if conflict.resp.status != 409:
                raise
            existing = events.get(calendarId=calendar_id, eventId=event_id).execute(
                num_retries=3
            )
    if existing.get("status") == "cancelled" and assessment.cancelled:
        return "already_cancelled"
    if existing.get("extendedProperties", {}).get("private", {}).get(
        "remarkableStudyId"
    ) != str(assessment.id):
        raise RuntimeError(
            "Calendar event ownership marker is missing; refusing to overwrite"
        )
    if event_matches(existing, desired):
        return "unchanged"
    events.patch(
        calendarId=calendar_id, eventId=event_id, body=desired, sendUpdates="none"
    ).execute(num_retries=3)
    return "updated"


def ensure_calendar(store, settings, service):
    if settings.google_calendar_id:
        return
    if settings.google_auth_mode == "service_account":
        raise RuntimeError(
            "A service account must use the existing shared school calendar"
        )
    pending = store.private / "google-calendar-creation-pending.json"
    if pending.exists():
        raise RuntimeError(
            "A previous calendar creation was interrupted. Check Google Calendar for Šolski testi and set its ID in settings before retrying."
        )
    # CalendarList is deliberately not used: it requires broader OAuth scopes.
    # Do not blindly retry a calendar creation whose response may have been lost.
    write_json(pending, {"summary": "Šolski testi"})
    calendar = (
        service.calendars()
        .insert(
            body={
                "summary": "Šolski testi",
                "description": "remarkable-study-v1",
                "timeZone": settings.timezone,
            }
        )
        .execute(num_retries=0)
    )
    settings.google_calendar_id = calendar["id"]
    store.save_settings(settings)
    pending.unlink()


def sync_google(store, settings, service=None):
    if not settings.assessments:
        return {"status": "no_tests"}
    if service is None and not credential_present(store):
        return {"status": "not_connected"}
    service = service or service_for(store)
    ensure_calendar(store, settings, service)
    return {
        "status": "synced",
        "events": [
            {
                "id": str(a.id),
                "status": upsert_event(
                    service, settings.google_calendar_id, a, settings.days_before
                ),
            }
            for a in settings.assessments
        ],
    }
