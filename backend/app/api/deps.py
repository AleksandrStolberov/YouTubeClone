import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import InvalidTokenError, decode_token
from app.models import User, UserRole
from app.services.auth import get_user_by_id

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    try:
        payload = decode_token(token)
    except InvalidTokenError as exc:
        raise unauthorized() from exc
    if payload.token_type != "access":
        raise unauthorized()
    try:
        user_id = uuid.UUID(payload.sub)
    except ValueError as exc:
        raise unauthorized() from exc

    user = await get_user_by_id(session, user_id)
    if user is None:
        raise unauthorized()
    return user


class RoleChecker:
    """Allow the request only when the current user's role is in the list."""

    def __init__(self, roles: list[str]) -> None:
        self.roles = list(roles)

    async def __call__(
        self,
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        role = current_user.role
        role_name = role.value if isinstance(role, UserRole) else str(role)
        if role_name not in self.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions",
            )
        return current_user


def require_role(roles: list[str]) -> RoleChecker:
    return RoleChecker(roles)
