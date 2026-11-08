from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.video import VideoRead

UploadDate = Literal["all", "today", "this_week", "this_month", "this_year"]
SortBy = Literal["date", "views", "rating", "likes"]
SortOrder = Literal["asc", "desc"]


class VideoSearchParams(BaseModel):
    """Query filters for public video search.

    ``upload_date`` uses UTC calendar boundaries: today, the current week
    (Monday), the current month, or the current year. ``all`` applies no
    date filter. ``rating`` and ``likes`` both sort by the number of likes.
    """

    query: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=50)
    tag: str | None = Field(default=None, max_length=50)
    upload_date: UploadDate | None = None
    sort_by: SortBy = "date"
    order: SortOrder = "desc"
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0)

    @field_validator("query", "category", "tag", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("upload_date", mode="before")
    @classmethod
    def _normalize_upload_date(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip().lower()
        return stripped or None

    @field_validator("sort_by", mode="before")
    @classmethod
    def _normalize_sort_by(cls, value: object) -> object:
        if value is None:
            return "date"
        if not isinstance(value, str):
            return value
        stripped = value.strip().lower()
        return stripped or "date"

    @field_validator("order", mode="before")
    @classmethod
    def _normalize_order(cls, value: object) -> object:
        if value is None:
            return "desc"
        if not isinstance(value, str):
            return value
        stripped = value.strip().lower()
        return stripped or "desc"


class PaginatedSearchResult(BaseModel):
    """One page of public videos that match the search filters."""

    items: list[VideoRead]
    total: int
    limit: int
    offset: int


class TrendingTag(BaseModel):
    """A tag and how many public videos use it."""

    tag: str
    count: int
