import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.v1.auth import router as auth_router
from app.api.v1.channels import router as channels_router
from app.api.v1.comments import router as comments_router
from app.api.v1.feed import router as feed_router
from app.api.v1.history import router as history_router
from app.api.v1.playlists import router as playlists_router
from app.api.v1.reactions import router as reactions_router
from app.api.v1.search import router as search_router
from app.api.v1.subscriptions import router as subscriptions_router
from app.api.v1.videos import router as videos_router
from app.api.v1.views import router as views_router
from app.core.config import get_settings
from app.core.s3 import get_s3_client

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Buckets must exist before the first upload. MinIO is reached by the
    # Docker service name (minio:9000), not by localhost.
    await asyncio.to_thread(get_s3_client().ensure_buckets)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(auth_router)
# Before /videos/{video_id}, so /videos/search is not parsed as a video id.
app.include_router(search_router)
app.include_router(videos_router)
app.include_router(views_router)
app.include_router(comments_router)
app.include_router(reactions_router)
app.include_router(subscriptions_router)
app.include_router(feed_router)
app.include_router(history_router)
app.include_router(playlists_router)
app.include_router(channels_router)


@app.exception_handler(RequestValidationError)
async def hide_password_in_validation(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = jsonable_encoder(exc.errors())
    for error in errors:
        loc = error.get("loc") or []
        if any(part == "password" for part in loc):
            error.pop("input", None)
    return JSONResponse(status_code=422, content={"detail": errors})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
