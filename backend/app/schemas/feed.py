from pydantic import BaseModel

from app.schemas.video import VideoRead


class PaginatedFeedResponse(BaseModel):
    """One page of published videos from channels the user follows."""

    items: list[VideoRead]
    total: int
    limit: int
    offset: int
