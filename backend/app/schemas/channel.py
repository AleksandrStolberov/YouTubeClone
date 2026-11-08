import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChannelProfileRead(BaseModel):
    """Public counters for a channel.

    ``total_views`` sums views of public videos only.
    ``videos_count`` counts every video the user owns, including private ones.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    username: str
    created_at: datetime
    subscribers_count: int
    total_views: int
    videos_count: int
