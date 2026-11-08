import uuid
from typing import Annotated, Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import User, Video
from app.schemas.moderation import ReportCreate, ReportRead, VideoBanRequest
from app.schemas.video import VideoRead
from app.services.moderation import (
    ModerationForbiddenError,
    ReportNotFoundError,
    ban_video,
    create_report,
    list_reports,
    reject_report,
    unban_video,
)
from app.services.video import VideoForbiddenError, VideoNotFoundError

router = APIRouter(tags=["moderation"])


def _raise_video_access(exc: Exception) -> NoReturn:
    if isinstance(exc, VideoNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found") from exc
    if isinstance(exc, VideoForbiddenError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        ) from exc
    raise exc


@router.post(
    "/videos/{video_id}/report",
    response_model=ReportRead,
    status_code=status.HTTP_201_CREATED,
)
async def report_video(
    video_id: uuid.UUID,
    payload: ReportCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ReportRead:
    """File a complaint about a video the caller is allowed to open."""
    try:
        return await create_report(session, video_id, current_user, payload)
    except (VideoNotFoundError, VideoForbiddenError) as exc:
        _raise_video_access(exc)


@router.get("/moderation/reports", response_model=list[ReportRead])
async def read_reports(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    report_status: Annotated[
        Literal["pending", "resolved", "rejected"] | None,
        Query(alias="status"),
    ] = None,
) -> list[ReportRead]:
    """List complaints. Allowed for moderators and admins, newest first."""
    try:
        return await list_reports(session, current_user, status=report_status)
    except ModerationForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        ) from exc


@router.post("/moderation/reports/{report_id}/reject", response_model=ReportRead)
async def dismiss_report(
    report_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ReportRead:
    """Mark a complaint as rejected. The video stays visible."""
    try:
        return await reject_report(session, report_id, current_user)
    except ReportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found") from exc
    except ModerationForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        ) from exc


@router.post("/moderation/videos/{video_id}/ban", response_model=VideoRead)
async def hide_video(
    video_id: uuid.UUID,
    payload: VideoBanRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Video:
    """Hide a video from the public catalog. Allowed for moderators and admins."""
    try:
        return await ban_video(session, video_id, current_user, payload.reason)
    except VideoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found") from exc
    except ModerationForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        ) from exc


@router.post("/moderation/videos/{video_id}/unban", response_model=VideoRead)
async def restore_video(
    video_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Video:
    """Clear a ban so the video can appear in the public catalog again."""
    try:
        return await unban_video(session, video_id, current_user)
    except VideoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found") from exc
    except ModerationForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        ) from exc
