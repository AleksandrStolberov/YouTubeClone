from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, unauthorized
from app.core.database import get_db
from app.core.security import InvalidTokenError
from app.models import User
from app.schemas.user import Token, TokenRefresh, UserCreate, UserLogin, UserRead
from app.services.auth import (
    InvalidCredentialsError,
    UserAlreadyExistsError,
    authenticate_user,
    issue_token_pair,
    refresh_access_token,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_DUPLICATE_DETAIL = {
    "email": "User with this email already exists",
    "username": "User with this username already exists",
    "email or username": "User with this email or username already exists",
}


def _login_openapi_extra() -> dict[str, object]:
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": UserLogin.model_json_schema()},
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "username": {
                                "type": "string",
                                "description": "Email or username",
                            },
                            "password": {
                                "type": "string",
                                "format": "password",
                            },
                        },
                        "required": ["username", "password"],
                    }
                },
            },
        }
    }


def _validate_login(data: object) -> UserLogin:
    try:
        return UserLogin.model_validate(data)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


async def _login_from_request(request: Request) -> UserLogin:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type == "application/json":
        try:
            payload = await request.json()
        except ValueError as exc:
            raise RequestValidationError(
                [
                    {
                        "type": "json_invalid",
                        "loc": ("body",),
                        "msg": "Invalid JSON body",
                        "input": None,
                    }
                ]
            ) from exc
        return _validate_login(payload)

    if media_type not in {"", "application/x-www-form-urlencoded", "multipart/form-data"}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Use JSON or form fields username and password",
        )

    form = await request.form()
    password = form.get("password")
    email = form.get("email")
    username = form.get("username")
    if password is None:
        raise RequestValidationError(
            [
                {
                    "type": "missing",
                    "loc": ("body", "password"),
                    "msg": "Field required",
                    "input": None,
                }
            ]
        )

    if email:
        data: dict[str, object] = {"email": str(email), "password": str(password)}
    elif username is not None and "@" in str(username):
        data = {"email": str(username), "password": str(password)}
    elif username:
        data = {"username": str(username), "password": str(password)}
    else:
        raise RequestValidationError(
            [
                {
                    "type": "missing",
                    "loc": ("body", "username"),
                    "msg": "Email or username is required",
                    "input": None,
                }
            ]
        )
    return _validate_login(data)


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(
    payload: UserCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    try:
        return await register_user(session, payload)
    except UserAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_DUPLICATE_DETAIL.get(exc.field, _DUPLICATE_DETAIL["email or username"]),
        ) from exc


@router.post(
    "/login",
    response_model=Token,
    summary="Issue access and refresh tokens",
    openapi_extra=_login_openapi_extra(),
)
async def login(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    credentials = await _login_from_request(request)
    try:
        user = await authenticate_user(session, credentials)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email, username or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return issue_token_pair(user.id)


@router.post(
    "/refresh",
    response_model=Token,
    summary="Issue a new token pair from a refresh token",
)
async def refresh(
    payload: TokenRefresh,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    try:
        return await refresh_access_token(session, payload.refresh_token)
    except InvalidTokenError as exc:
        raise unauthorized() from exc


@router.get(
    "/me",
    response_model=UserRead,
    summary="Current authenticated user",
)
async def read_me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user
