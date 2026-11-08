import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserRole, Video, VideoReport
from app.schemas.moderation import ReportCreate, ReportRead
from app.services.video import VideoNotFoundError, get_video

_STAFF_ROLES = {UserRole.MODERATOR.value, UserRole.ADMIN.value}


class ModerationForbiddenError(Exception):
    """Raised when the caller is not a moderator or an admin."""


def _role_name(user: User) -> str:
    role = user.role
    return role.value if isinstance(role, UserRole) else str(role)


def _ensure_staff(user: User) -> None:
    if _role_name(user) not in _STAFF_ROLES:
        raise ModerationForbiddenError


def _report_read(report: VideoReport, ban_reason: str | None) -> ReportRead:
    return ReportRead(
        id=report.id,
        video_id=report.video_id,
        reporter_id=report.reporter_id,
        reason=report.reason,
        status=report.status,
        created_at=report.created_at,
        ban_reason=ban_reason,
    )


async def create_report(
    session: AsyncSession,
    video_id: uuid.UUID,
    reporter: User,
    data: ReportCreate,
) -> ReportRead:
    """Store a complaint for a video the reporter is allowed to open."""
    video = await get_video(session, video_id, reporter)
    report = VideoReport(
        video_id=video.id,
        reporter_id=reporter.id,
        reason=data.reason,
        status="pending",
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return _report_read(report, video.ban_reason)


async def list_reports(
    session: AsyncSession,
    actor: User,
    *,
    status: str | None,
) -> list[ReportRead]:
    """Return complaints, newest first. Optional status filter is exact."""
    _ensure_staff(actor)
    stmt = (
        select(VideoReport, Video.ban_reason)
        .join(Video, Video.id == VideoReport.video_id)
        .order_by(VideoReport.created_at.desc(), VideoReport.id.desc())
    )
    if status is not None:
        stmt = stmt.where(VideoReport.status == status)
    rows = await session.execute(stmt)
    return [_report_read(report, ban_reason) for report, ban_reason in rows.all()]


async def ban_video(
    session: AsyncSession,
    video_id: uuid.UUID,
    actor: User,
    reason: str,
) -> Video:
    """Hide a video from public surfaces and from viewers who are not staff."""
    _ensure_staff(actor)
    video = await session.get(Video, video_id)
    if video is None:
        raise VideoNotFoundError
    video.is_banned = True
    video.ban_reason = reason
    await session.commit()
    await session.refresh(video)
    return video


async def unban_video(
    session: AsyncSession,
    video_id: uuid.UUID,
    actor: User,
) -> Video:
    """Make a banned video public again and clear the ban note."""
    _ensure_staff(actor)
    video = await session.get(Video, video_id)
    if video is None:
        raise VideoNotFoundError
    video.is_banned = False
    video.ban_reason = None
    await session.commit()
    await session.refresh(video)
    return video
