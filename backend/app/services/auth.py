import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    dummy_password_hash,
    hash_password,
    verify_password,
)
from app.models import User, UserRole
from app.schemas.user import Token, UserCreate, UserLogin


class UserAlreadyExistsError(Exception):
    """Raised when email or username is already taken."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(field)


class InvalidCredentialsError(Exception):
    """Raised when the login identifier or password does not match."""


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def register_user(session: AsyncSession, data: UserCreate) -> User:
    if await get_user_by_email(session, data.email):
        raise UserAlreadyExistsError("email")
    if await get_user_by_username(session, data.username):
        raise UserAlreadyExistsError("username")

    user = User(
        email=data.email,
        username=data.username,
        hashed_password=hash_password(data.password),
        role=UserRole.USER,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise UserAlreadyExistsError("email or username") from exc
    await session.refresh(user)
    return user


async def authenticate_user(session: AsyncSession, data: UserLogin) -> User:
    if data.email is not None:
        user = await get_user_by_email(session, data.email)
    else:
        user = await get_user_by_username(session, data.username or "")

    if user is None:
        verify_password(data.password, dummy_password_hash())
        raise InvalidCredentialsError

    if not verify_password(data.password, user.hashed_password):
        raise InvalidCredentialsError
    return user


def issue_token_pair(user_id: uuid.UUID) -> Token:
    subject = str(user_id)
    return Token(
        access_token=create_access_token(subject),
        refresh_token=create_refresh_token(subject),
    )


async def refresh_access_token(session: AsyncSession, refresh_token: str) -> Token:
    payload = decode_token(refresh_token)
    if payload.token_type != "refresh":
        raise InvalidTokenError("Refresh token is required")
    try:
        user_id = uuid.UUID(payload.sub)
    except ValueError as exc:
        raise InvalidTokenError("Invalid subject") from exc

    user = await get_user_by_id(session, user_id)
    if user is None:
        raise InvalidTokenError("User not found")
    return issue_token_pair(user.id)
