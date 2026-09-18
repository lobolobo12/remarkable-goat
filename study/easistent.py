"""Normalize timetable assessments and preserve stable IDs across updates."""

from datetime import date


class ConnectionRequired(RuntimeError):
    pass


def parse_timetable(payload, *, timezone="Europe/Ljubljana"):
    from datetime import datetime, time
    from uuid import NAMESPACE_URL, uuid5
    from zoneinfo import ZoneInfo

    from .models import Assessment

    if (
        isinstance(payload, dict)
        and isinstance(payload.get("events"), list)
        and isinstance(payload.get("schedule"), list)
    ):
        return parse_web_timetable(payload, timezone=timezone)
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("school_hour_events"), list)
        or not isinstance(payload.get("time_table"), list)
    ):
        raise TypeError("Unsupported eAsistent timetable schema")
    times = {str(row["id"]): row for row in payload["time_table"]}
    result = []
    for row in payload["school_hour_events"]:
        special = row.get("hour_special_type")
        if special != "exam":
            continue
        try:
            binding = row["time"]
            day = date.fromisoformat(binding["date"])
            source_id = str(row["event_id"])
            subject = row["subject"]["name"].strip()
            if not subject or source_id in ("None", ""):
                raise ValueError()
            start = times[str(binding["from_id"])]["time"]["from"]
            end = times[str(binding["to_id"])]["time"]["to"]
            result.append(
                Assessment(
                    id=uuid5(
                        NAMESPACE_URL,
                        "https://www.easistent.com/m/timetable/event/" + source_id,
                    ),
                    source="easistent",
                    source_id=source_id,
                    subject=subject,
                    title="Ocenjevanje znanja",
                    date=day,
                    start_time=time.fromisoformat(start),
                    end_time=time.fromisoformat(end),
                    location=(row.get("classroom") or {}).get("name"),
                    updated_at=datetime.now(ZoneInfo(timezone)),
                )
            )
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                "An eAsistent test has incomplete date, subject or time; previous tests preserved."
            ) from None
    return result


def sync_assessments(store, *, client_factory=None, today=None):
    if client_factory is None:
        from .school_browser import BrowserTimetable

        client_factory = BrowserTimetable
    settings = store.settings()
    if not settings.easistent_enabled:
        return {"status": "not_connected"}
    payloads = client_factory(store).fetch_weeks(
        today=today, weeks=settings.easistent_weeks
    )
    discovered = {}
    for payload in payloads:
        for assessment in parse_timetable(payload, timezone=settings.timezone):
            if assessment.id in discovered:
                prior = discovered[assessment.id]
                if prior.model_dump(exclude={"updated_at"}) != assessment.model_dump(
                    exclude={"updated_at"}
                ):
                    raise ValueError(
                        "eAsistent returned conflicting versions of one test; previous tests preserved."
                    )
            discovered[assessment.id] = assessment
    previous = {a.id: a for a in settings.assessments}
    changed = 0
    for identifier, assessment in discovered.items():
        old = previous.get(identifier)
        if old is None:
            from .mapping import subject_key

            matches = [
                a
                for a in previous.values()
                if (a.source == "easistent" and a.source_id == assessment.source_id)
                or (
                    a.source == "manual"
                    and a.source_id == "user-confirmed-timetable"
                    and a.date == assessment.date
                    and a.start_time == assessment.start_time
                    and subject_key(a.subject) == subject_key(assessment.subject)
                )
            ]
            if len(matches) > 1:
                raise ValueError(
                    "Ambiguous existing timetable event; previous tests preserved"
                )
            if matches:
                old = matches[0]
                identifier = old.id
                assessment.id = old.id
        if old:
            assessment.folder_id = old.folder_id
            assessment.cancelled = old.cancelled
            for field in (
                "material_ids",
                "study_hours",
                "knowledge_level",
                "target_grade",
                "scope_notes",
                "diagnostic_result",
            ):
                setattr(assessment, field, getattr(old, field))
            if old.model_dump(exclude={"updated_at"}) == assessment.model_dump(
                exclude={"updated_at"}
            ):
                assessment.updated_at = old.updated_at
            else:
                changed += 1
        else:
            changed += 1
        previous[identifier] = assessment
    # Disappearance is not proof of cancellation (window/plan/teacher changes).
    settings.assessments = list(previous.values())
    store.save_settings(settings)
    return {
        "status": "synced",
        "found": len(discovered),
        "changed": changed,
        "weeks": len(payloads),
    }


def parse_web_timetable(payload, *, timezone="Europe/Ljubljana"):
    from datetime import datetime, time
    from uuid import NAMESPACE_URL, uuid5
    from zoneinfo import ZoneInfo

    from .models import Assessment

    found = []
    for event in payload["events"]:
        evaluation = event.get("evaluation")
        if not evaluation:
            if str(event.get("slug", "")).startswith("ocenjevanje$"):
                raise ValueError("Assessment details missing; previous tests preserved")
            continue
        try:
            identifier = str(evaluation["evaluation_id"])
            if not identifier.isdigit():
                raise ValueError("Invalid assessment ID")
            found.append(
                Assessment(
                    id=uuid5(
                        NAMESPACE_URL,
                        "https://moj.easistent.com/evaluation/" + identifier,
                    ),
                    source="easistent",
                    source_id="evaluation:" + identifier,
                    subject=decode_school_text(event["subject"]["title"]),
                    title=decode_school_text(evaluation["title"]),
                    school_scope=decode_school_text(evaluation.get("summary") or ""),
                    date=date.fromisoformat(event["date"]),
                    start_time=time.fromisoformat(event["from"]),
                    end_time=time.fromisoformat(event["to"]),
                    location=event.get("classroom"),
                    updated_at=datetime.now(ZoneInfo(timezone)),
                )
            )
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                "Incomplete assessment; previous tests preserved"
            ) from None
    return found


def decode_school_text(text):
    """Repair the web response's UTF-8 text exposed as Latin-1, when reversible."""
    if not any(marker in text for marker in ("Ã", "Â", "Ä", "Å", "â")):
        return text
    try:
        return text.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
