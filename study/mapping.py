"""Explicit selection, dated folders, then Test N in subject/calendar order."""

import re
import unicodedata
from uuid import UUID

from .cloud import descendants

ALIASES = {
    "slo": "slovenscina",
    "slovenscina": "slovenscina",
    "geo": "geografija",
    "geografija": "geografija",
    "bio": "biologija",
    "biologija": "biologija",
    "kem": "kemija",
    "kemija": "kemija",
    "fiz": "fizika",
    "fizika": "fizika",
    "nem": "nemscina",
    "nemscina": "nemscina",
    "ang": "anglescina",
    "anglescina": "anglescina",
    "mat": "matematika",
    "matematika": "matematika",
    "zgo": "zgodovina",
    "zgodovina": "zgodovina",
}


def normalize(text):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        "".join(
            c
            for c in unicodedata.normalize("NFKD", text.lower())
            if not unicodedata.combining(c)
        ),
    ).strip()


def subject_key(text):
    name = normalize(text)
    return ALIASES.get(name, name)


def choose_folder(assessment, settings, items):
    explicit = settings.assessment_folders.get(str(assessment.id))
    if explicit:
        descendants(items, str(explicit))
        return explicit, "explicit_test_folder"
    root = next(
        (
            folder
            for name, folder in settings.subject_folders.items()
            if subject_key(name) == subject_key(assessment.subject)
        ),
        None,
    )
    if root is None:
        matches = [
            item
            for item in items
            if item.is_collection
            and subject_key(item.visibleName) == subject_key(assessment.subject)
            and str(item.parent) != "trash"
        ]
        matches = [item for item in matches if valid_folder(items, str(item.id))]
        if len(matches) != 1:
            return None, "subject_folder_missing_or_ambiguous"
        root = UUID(str(matches[0].id))
    descendants(items, str(root))
    tests = [
        item
        for item in items
        if item.is_collection
        and str(item.parent) == str(root)
        and re.search(r"\b(test|preizkus|ocenjevanje)\b", normalize(item.visibleName))
    ]
    # Date-labelled folders or a matching explicit Test N title are deterministic.
    exact = [
        item
        for item in tests
        if assessment.date.isoformat() in item.visibleName
        or normalize(item.visibleName) == normalize(assessment.title)
    ]
    if len(exact) == 1:
        return UUID(str(exact[0].id)), "matching_test_folder"
    number = test_number(assessment, settings)
    numbered = [
        item
        for item in tests
        if normalize(item.visibleName)
        in {f"test {number}", f"preizkus {number}", f"ocenjevanje {number}"}
    ]
    if len(numbered) == 1:
        return UUID(str(numbered[0].id)), "calendar_order_test_folder"
    if tests:
        return None, "test_folder_needs_mapping"
    return root, "whole_subject_folder"


def valid_folder(items, folder):
    try:
        descendants(items, folder)
        return True
    except ValueError:
        return False


def test_number(assessment, settings):
    from datetime import date, time

    year = assessment.date.year - (assessment.date.month < 9)
    start, end = date(year, 9, 1), date(year + 1, 9, 1)
    tests = {
        a.id: a
        for a in settings.assessments
        if not a.cancelled
        and subject_key(a.subject) == subject_key(assessment.subject)
        and start <= a.date < end
    }
    tests[assessment.id] = assessment
    ordered = sorted(
        tests.values(), key=lambda a: (a.date, a.start_time or time.min, str(a.id))
    )
    return next(i + 1 for i, a in enumerate(ordered) if a.id == assessment.id)
