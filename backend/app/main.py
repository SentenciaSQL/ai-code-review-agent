from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.core.middleware import RequestSizeLimitMiddleware
from app.repositories.review_repository import ReviewRepository

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    repository = ReviewRepository(settings.resolved_database_path)
    repository.initialize()
    interrupted = repository.mark_interrupted()
    if interrupted:
        logger.info("Marked %s interrupted review(s) as failed", interrupted)
    logger.info(
        "Patchline started database=%s llm_configured=%s github_token_configured=%s",
        settings.resolved_database_path,
        settings.llm_configured,
        settings.github_token_configured,
    )
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    summary="Local AI code review for Git diffs and GitHub pull requests.",
    description=(
        "Patchline reviews a unified diff or a GitHub pull request and stores the result locally. "
        "It is an MVP for a local or controlled development environment, not a multi-user production service. "
        "Submitted code is untrusted data and is never executed."
    ),
    lifespan=lifespan,
)

app.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.max_request_bytes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
    max_age=600,
)
app.include_router(api_router, prefix="/api")


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "health": "/api/health",
        "docs": "/docs",
    }


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    body: dict[str, str] = {"detail": exc.message, "code": exc.code}
    if exc.review_id:
        body["review_id"] = exc.review_id
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", []) if part != "body")
        message = str(error.get("msg", "Invalid value"))
        messages.append(f"{location}: {message}" if location else message)
    return JSONResponse(
        status_code=422,
        content={"detail": "; ".join(messages) or "Invalid request.", "code": "validation_error"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment != "production",
    )
