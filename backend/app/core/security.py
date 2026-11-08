from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import ValidationError

from app.core.config import get_settings
from app.schemas.user import TokenPayload, TokenType

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_dummy_password_hash: str | None = None


class InvalidTokenError(Exception):
    """Raised when a JWT is missing, expired, malformed, or has the wrong type."""


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except (ValueError, TypeError):
        return False


def dummy_password_hash() -> str:
    """Hash used to keep login timing similar when the user does not exist."""

    global _dummy_password_hash
    if _dummy_password_hash is None:
        _dummy_password_hash = hash_password("dummy-password")
    return _dummy_password_hash


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    lifetime = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    return _encode_token(subject, "access", lifetime)


def create_refresh_token(subject: str, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    lifetime = expires_delta or timedelta(days=settings.refresh_token_expire_days)
    return _encode_token(subject, "refresh", lifetime)


def decode_token(token: str) -> TokenPayload:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            options={"require_sub": True, "require_exp": True},
        )
        return TokenPayload.model_validate(payload)
    except (JWTError, ValidationError) as exc:
        raise InvalidTokenError("Could not validate token") from exc


def _encode_token(subject: str, token_type: TokenType, expires_delta: timedelta) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": subject,
        "token_type": token_type,
        "exp": expire,
    }
    encoded = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    if isinstance(encoded, bytes):
        return encoded.decode()
    return encoded
