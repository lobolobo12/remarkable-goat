from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class Assessment(BaseModel):
    id: UUID
    subject: str = Field(min_length=1)
    title: str = Field(min_length=1)
    date: date
    folder_id: UUID | None = None
    material_ids: list[UUID] = Field(default_factory=list, max_length=500)
    start_time: time | None = None
    end_time: time | None = None
    location: str | None = None
    source: Literal["manual", "easistent"] = "manual"
    source_id: str | None = None
    cancelled: bool = False
    updated_at: datetime
    study_hours: float = Field(default=3, ge=0.25, le=100)
    knowledge_level: int = Field(default=2, ge=0, le=4)
    target_grade: int = Field(default=4, ge=2, le=5)
    school_scope: str = ""
    scope_notes: str = Field(default="", max_length=12000)
    diagnostic_result: dict | None = None

    @model_validator(mode="after")
    def valid_times(self):
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError("Provide both start and end times")
        if self.start_time is not None and self.end_time <= self.start_time:
            raise ValueError("Test end time must be after its start")
        return self


class Settings(BaseModel):
    timezone: str = "Europe/Ljubljana"
    model: str = "gpt-5.6-luna"
    reading_model: str | None = "gpt-5.6-sol"
    days_before: int = Field(default=7, ge=1, le=60)
    max_pages_per_test: int = Field(default=100, ge=1, le=500)
    max_packs_per_run: int = Field(default=2, ge=1, le=20)
    google_calendar_id: str | None = None
    google_auth_mode: Literal["oauth", "service_account"] = "oauth"
    easistent_enabled: bool = False
    easistent_weeks: int = Field(default=9, ge=2, le=40)
    subject_folders: dict[str, UUID] = Field(default_factory=dict)
    assessment_folders: dict[str, UUID] = Field(default_factory=dict)
    tablet_delivery: bool = True
    assessments: list[Assessment] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [item.id for item in self.assessments]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate assessment IDs")
        return self


class Source(BaseModel):
    id: UUID
    name: str
    hash: str
    pdf: str


class Page(BaseModel):
    number: int = Field(ge=1)
    blank: bool
    text: str
    uncertainties: list[str]


class Extraction(BaseModel):
    pages: list[Page]


class Reference(BaseModel):
    source_id: str
    page: int = Field(ge=1)


class Section(BaseModel):
    title: str
    explanation: str
    references: list[Reference]


class Question(BaseModel):
    question: str
    points: int = Field(ge=1, le=20)
    answer: str
    marking: str
    references: list[Reference]


class StudyDay(BaseModel):
    day: int = Field(ge=1, le=7)
    task: str
    minutes: int = Field(default=0, ge=0, le=6000)


class Pack(BaseModel):
    title: str
    sections: list[Section]
    questions: list[Question]
    schedule: list[StudyDay]
    warnings: list[str]


def validate_pack(pack: Pack, sources: dict[str, Extraction]) -> None:
    valid = {
        (sid, page.number)
        for sid, doc in sources.items()
        for page in doc.pages
        if not page.blank
    }
    if not pack.sections or not pack.questions:
        raise ValueError("Study pack must contain notes and questions")
    for item in [*pack.sections, *pack.questions]:
        if not item.references:
            raise ValueError("Every section/question must cite a source page")
        if any((ref.source_id, ref.page) not in valid for ref in item.references):
            raise ValueError("Study pack cites a missing or blank source page")


class DiagnosticQuestion(BaseModel):
    topic: str
    question: str
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    explanation: str
    references: list[Reference] = Field(min_length=1)


class Diagnostic(BaseModel):
    title: str
    questions: list[DiagnosticQuestion] = Field(min_length=6, max_length=12)
    warnings: list[str]
