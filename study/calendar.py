from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Alarm, Calendar, Event

from .models import Settings


def calendar_bytes(settings: Settings) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", "-//reMarkable Study//SL")
    calendar.add("version", "2.0")
    calendar.add("x-wr-calname", "Šolski testi")
    calendar.add("x-wr-timezone", settings.timezone)
    for assessment in settings.assessments:
        event = Event()
        event.add("uid", f"{assessment.id}@remarkable-study.local")
        event.add("dtstamp", assessment.updated_at.astimezone(UTC))
        event.add("last-modified", assessment.updated_at.astimezone(UTC))
        event.add("sequence", int(assessment.updated_at.timestamp()))
        if assessment.start_time and assessment.end_time:
            zone = ZoneInfo(settings.timezone)
            event.add(
                "dtstart",
                datetime.combine(assessment.date, assessment.start_time, zone),
            )
            event.add(
                "dtend", datetime.combine(assessment.date, assessment.end_time, zone)
            )
        else:
            event.add("dtstart", assessment.date)
            event.add("dtend", assessment.date + timedelta(days=1))
        event.add("summary", f"{assessment.subject}: {assessment.title}")
        event.add("status", "CANCELLED" if assessment.cancelled else "CONFIRMED")
        event.add(
            "description",
            "Učno gradivo temelji na zapiskih v povezani mapi reMarkable. "
            + (
                "Datum vnesen ročno."
                if assessment.source == "manual"
                else "Vir datuma: eAsistent."
            ),
        )
        if assessment.folder_id:
            event.add(
                "url", f"https://app.remarkable.com/folder/{assessment.folder_id}"
            )
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", "Čez en teden je test - čas za pripravo.")
        alarm.add("trigger", timedelta(days=-settings.days_before))
        event.add_component(alarm)
        calendar.add_component(event)
    return calendar.to_ical()


def make_server(path: Path, token: str, port: int = 8765):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != f"/{token}/tests.ics":
                self.send_error(404)
                return
            if not path.exists():
                self.send_error(503, "Calendar has not been generated")
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/calendar; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass  # Do not log subscription tokens.

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
