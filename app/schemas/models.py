from __future__ import annotations

from datetime import date as CalendarDate
from typing import Literal

from pydantic import BaseModel, Field, field_validator


Day = Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
Source = Literal["native", "printed", "handwritten", "unknown"]


class MatchSuggestion(BaseModel):
    subject_master_id: int | None = None
    name: str
    code: str
    subject_type: str | None = None
    score: float = Field(ge=-1, le=1)


class ClassSession(BaseModel):
    day: Day
    start_time: str
    end_time: str
    subject_raw: str
    college: str | None = None
    course: str | None = None
    department: str | None = None
    year: str | None = None
    semester: str | None = None
    section: str | None = None
    subject_name: str | None = None
    subject_type: str | None = None
    catalog_course: str | None = None
    catalog_stream: str | None = None
    catalog_semester: str | None = None
    subject_code: str | None = None
    subject_master_id: int | None = None
    match_method: str | None = None
    name_lookup_status: Literal["name_unavailable", "index_unavailable", "exact_name_found",
                                "similar_name_found", "no_strong_candidate"] | None = None
    cosine_similarity: float | None = Field(default=None, ge=-1, le=1)
    match_margin: float | None = None
    match_candidates: list[MatchSuggestion] = Field(default_factory=list)
    faculty_raw: str | None = None
    room: str | None = None
    source: Source = "unknown"
    confidence: float = Field(ge=0, le=1)
    requires_review: bool = True
    review_reasons: list[str] = Field(default_factory=list)
    page: int | None = None
    cell_ref: str | None = None
    bbox: tuple[float, float, float, float] | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def valid_time(cls, value: str) -> str:
        from datetime import datetime

        datetime.strptime(value, "%H:%M")
        return value


class ReviewItem(BaseModel):
    reason: str
    raw_text: str | None = None
    page: int | None = None
    cell_ref: str | None = None
    bbox: tuple[float, float, float, float] | None = None


class Routine(BaseModel):
    college: str | None = None
    course: str | None = None
    department: str | None = None
    year: str | None = None
    semester: str | None = None
    section: str | None = None
    room: str | None = None
    version: str | None = None
    date: CalendarDate | None = None
    classes: list[ClassSession] = Field(default_factory=list)
    review_items: list[ReviewItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RawCell(BaseModel):
    text: str
    row: int
    column: int
    page: int | None = None
    cell_ref: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    source: Source = "native"
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)
    alternatives: list[str] = Field(default_factory=list)


class Grid(BaseModel):
    rows: list[list[RawCell]]
    page: int | None = None
    context_text: str = ""
    source_name: str | None = None
