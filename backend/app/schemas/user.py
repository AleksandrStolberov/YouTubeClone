import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    model_validator,
)

from app.models.user import UserRole

USERNAME_PATTERN = r"^[A-Za-z0-9_-]+$"
TokenType = Literal["access", "refresh"]


def _strip_lower(value: object) -> object:
    if isinstance(value, str):
        return value.strip().lower()
    return value


def _strip(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


def _validate_password(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Password contains invalid characters")
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes")
    return value


NormalizedEmail = Annotated[
    EmailStr,
    BeforeValidator(_strip_lower),
    Field(max_length=320),
]
Username = Annotated[
    str,
    BeforeValidator(_strip),
    Field(min_length=3, max_length=50, pattern=USERNAME_PATTERN),
]
Password = Annotated[
    str,
    Field(min_length=8, max_length=72),
    AfterValidator(_validate_password),
]


class UserCreate(BaseModel):
    """Registration payload. The role is assigned by the server."""

    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    username: Username
    password: Password


class UserLogin(BaseModel):
    """Credentials for login by email or by username."""

    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail | None = Field(
        default=None,
        description="Email address. Provide this or username, not both.",
    )
    username: Username | None = Field(
        default=None,
        description="Username. Provide this or email, not both.",
    )
    password: Password

    @model_validator(mode="after")
    def require_email_or_username(self) -> Self:
        if (self.email is None) == (self.username is None):
            raise ValueError("Provide exactly one of email or username")
        return self


class UserRead(BaseModel):
    """Public user profile. Password hashes are never included."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    username: str
    role: UserRole
    created_at: datetime


class Token(BaseModel):
    """Access and refresh token pair returned to the client."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """Claims stored inside an access or refresh JWT."""

    model_config = ConfigDict(extra="ignore")

    sub: str = Field(min_length=1)
    token_type: TokenType
    exp: int | None = None


class TokenRefresh(BaseModel):
    """Refresh token sent by the client to obtain a new access token."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1)
