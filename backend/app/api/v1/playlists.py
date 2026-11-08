import uuid
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_user, unauthorized
from app.core.database import get_db
from app.models import User
from app.schemas.playlist import (
    PlaylistCreate,
    PlaylistDetailRead,
    PlaylistRead,
    PlaylistUpdate,
)
from app.services.playlist import (
    PlaylistForbiddenError,
    PlaylistNotFoundError,
    PlaylistVideoExistsError,
    PlaylistVideoMissingError,
    UserNotFoundError,
    add_video_to_playlist,
    create_playlist,
    delete_playlist,
    get_playlist_detail,
    list_user_playlists,
    remove_video_from_playlist,
    update_playlist,
)
from app.services.video import VideoForbiddenError, VideoNotFoundError

router = APIRouter(tags=["playlists"])


def _raise_forbidden(exc: Exception, viewer: User | None) -> NoReturn:
    if viewer is None:
        raise unauthorized() from exc
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not enough permissions",
    ) from exc


@router.post("/playlists", response_model=PlaylistRead, status_code=status.HTTP_201_CREATED)
async def create_playlist_endpoint(
    payload: PlaylistCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PlaylistRead:
    """Create a playlist for the signed-in user."""
    return await create_playlist(session, current_user, payload)


@router.get("/playlists/{playlist_id}", response_model=PlaylistDetailRead)
async def read_playlist(
    playlist_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    viewer: Annotated[User | None, Depends(get_optional_user)],
) -> PlaylistDetailRead:
    """Return one playlist and its videos in position order.

    Public playlists are visible without a token. A private playlist is
    visible only to its author.
    """
    try:
        return await get_playlist_detail(session, playlist_id, viewer)
    except PlaylistNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        ) from exc
    except PlaylistForbiddenError as exc:
        _raise_forbidden(exc, viewer)


@router.put("/playlists/{playlist_id}", response_model=PlaylistRead)
async def update_playlist_endpoint(
    playlist_id: uuid.UUID,
    payload: PlaylistUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PlaylistRead:
    """Edit playlist fields. Only the author can do this."""
    try:
        return await update_playlist(session, playlist_id, current_user, payload)
    except PlaylistNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        ) from exc
    except PlaylistForbiddenError as exc:
        _raise_forbidden(exc, current_user)


@router.delete("/playlists/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_playlist_endpoint(
    playlist_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Delete a playlist. Allowed for the author and for an admin."""
    try:
        await delete_playlist(session, playlist_id, current_user)
    except PlaylistNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        ) from exc
    except PlaylistForbiddenError as exc:
        _raise_forbidden(exc, current_user)


@router.post(
    "/playlists/{playlist_id}/videos/{video_id}",
    response_model=PlaylistDetailRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_playlist_video(
    playlist_id: uuid.UUID,
    video_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PlaylistDetailRead:
    """Append a video to the author's playlist."""
    try:
        return await add_video_to_playlist(session, playlist_id, video_id, current_user)
    except PlaylistNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        ) from exc
    except PlaylistForbiddenError as exc:
        _raise_forbidden(exc, current_user)
    except VideoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found") from exc
    except VideoForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        ) from exc
    except PlaylistVideoExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Video is already in the playlist",
        ) from exc


@router.delete(
    "/playlists/{playlist_id}/videos/{video_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_playlist_video(
    playlist_id: uuid.UUID,
    video_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Remove a video from the author's playlist."""
    try:
        await remove_video_from_playlist(session, playlist_id, video_id, current_user)
    except PlaylistNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        ) from exc
    except PlaylistForbiddenError as exc:
        _raise_forbidden(exc, current_user)
    except PlaylistVideoMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video is not in the playlist",
        ) from exc


@router.get("/users/{user_id}/playlists", response_model=list[PlaylistRead])
async def list_playlists(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    viewer: Annotated[User | None, Depends(get_optional_user)],
) -> list[PlaylistRead]:
    """List playlists of one user.

    The author sees private playlists too. Everyone else sees public ones only.
    """
    try:
        return await list_user_playlists(session, user_id, viewer)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
