"""Persistent browser used only for the user's eAsistent timetable workflow."""

import json
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import Error as BrowserError
from playwright.sync_api import sync_playwright

from .easistent import ConnectionRequired
from .storage import write_json

URL = "https://moj.easistent.com/timetable"


def is_timetable(data):
    return (
        isinstance(data, dict)
        and isinstance(data.get("school_hour_events"), list)
        and isinstance(data.get("time_table"), list)
    )


def select_week(payloads, monday):
    for payload in reversed(payloads):
        days = payload.get("day_table", [])
        if any(
            isinstance(day, dict) and day.get("date") == str(monday) for day in days
        ):
            return payload
    return None


def flight_timetables(text):
    """Parse only JSON Flight records. Never evaluate page scripts."""
    found = []

    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("schedule"), list) and isinstance(
                value.get("events"), list
            ):
                found.append(value)
            else:
                for child in value.values():
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for line in text.splitlines():
        _, separator, value = line.partition(":")
        if separator:
            try:
                walk(json.loads(value))
            except ValueError:
                continue
    return found


def listen(page, captured, store=None):
    def response_received(response):
        parsed = urlsplit(response.url)
        if (
            parsed.hostname != "moj.easistent.com"
            or parsed.path != "/timetable"
            or response.status != 200
        ):
            return
        try:
            if "text/x-component" not in response.headers.get("content-type", ""):
                return
            arguments = json.loads(response.request.post_data or "null")
            if not isinstance(arguments, list) or len(arguments) != 1:
                return
            from datetime import date

            week = date.fromisoformat(arguments[0])
            payloads = flight_timetables(response.body().decode("utf-8"))
            for payload in payloads:
                payload["day_table"] = [{"date": str(week)}]
                captured.append(payload)
        except (ValueError, TypeError, BrowserError):
            return

    page.on("response", response_received)


def connect_browser(store):
    profile = store.private / "easistent-browser"
    profile.mkdir(mode=0o700, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile), headless=False, viewport={"width": 1200, "height": 900}
        )
        page = context.pages[0] if context.pages else context.new_page()
        captured = []
        listen(page, captured, store)
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        print(
            "Official eAsistent browser opened. Sign in there and open Urnik. Waiting up to 20 minutes.",
            flush=True,
        )
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            if (
                urlsplit(page.url).hostname == "moj.easistent.com"
                and urlsplit(page.url).path == "/timetable"
            ):
                context.storage_state(
                    path=str(store.private / "easistent-browser-state.json")
                )
            if captured:
                write_json(
                    store.private / "easistent-browser-check.json",
                    {
                        "status": "connected",
                        "at": datetime.now(ZoneInfo("Europe/Ljubljana")).isoformat(),
                    },
                )
                write_json(store.private / "easistent-timetables.json", captured)
                with store.lock():
                    settings = store.settings()
                    settings.easistent_enabled = True
                    store.save_settings(settings)
                print(
                    "Official browser timetable access verified; session saved.",
                    flush=True,
                )
                context.storage_state(
                    path=str(store.private / "easistent-browser-state.json")
                )
                context.close()
                return
            page.wait_for_timeout(1000)
        context.close()
        raise ConnectionRequired(
            "eAsistent connection timed out; run study connect-easistent again."
        )


class BrowserTimetable:
    def __init__(self, store):
        self.store = store

    def fetch_weeks(self, today=None, weeks=9):
        if not (self.store.private / "easistent-browser-state.json").exists():
            raise ConnectionRequired(
                "Run study connect-easistent to sign in on the official website."
            )
        today = today or datetime.now(ZoneInfo("Europe/Ljubljana")).date()
        starts = week_starts(today, weeks)
        payloads = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            state = self.store.private / "easistent-browser-state.json"
            context = browser.new_context(storage_state=str(state))
            try:
                page = context.pages[0] if context.pages else context.new_page()
                captured = []
                listen(page, captured)
                for start in starts:
                    captured.clear()
                    page.goto(
                        URL + "?date=" + str(start),
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                    for _ in range(60):
                        if select_week(captured, start) is not None:
                            break
                        page.wait_for_timeout(500)
                    selected = select_week(captured, start)
                    if selected is None:
                        raise ConnectionRequired(
                            "eAsistent session expired or timetable unavailable; run study connect-easistent. Previous tests preserved."
                        )
                    payloads.append(selected)
                    context.storage_state(path=str(state))
            finally:
                context.close()
                browser.close()
        write_json(self.store.private / "easistent-timetables.json", payloads)
        return payloads


def week_starts(today, weeks):
    """eAsistent starts the first school week on 1 September, not in August."""
    from datetime import date

    current = today - timedelta(days=today.weekday())
    year = today.year - (today.month < 9)
    school_start = date(year, 9, 1)
    first = school_start - timedelta(days=school_start.weekday())
    count = weeks + (current - first).days // 7
    return [max(school_start, first + timedelta(weeks=i)) for i in range(count)]
