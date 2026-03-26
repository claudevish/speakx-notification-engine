"""FastAPI application factory — configures logging, middleware, and lifespan events."""

import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)

from app.api.router import api_router
from app.api.tracking import tracking_router
from app.config.settings import settings
from app.portal.api import portal_api_router
from app.portal.router import portal_router

LOG_LEVEL_MAP: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def configure_structlog() -> None:
    """Set up structlog with environment-appropriate processors and log level."""
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.CallsiteParameterAdder(
            [
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            ]
        ),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.environment == "development":
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    log_level = LOG_LEVEL_MAP.get(settings.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger = structlog.get_logger()
    await logger.ainfo(
        "Application starting",
        environment=settings.environment,
    )

    from app.config.manager import ConfigManager
    from app.models.base import AsyncSessionLocal

    async with AsyncSessionLocal() as db_session:
        config_manager = ConfigManager(db_session)
        await config_manager.seed_defaults()

    # Ensure generated image directories exist
    generated_dir = Path(__file__).resolve().parent / "static" / "generated" / "notifications"
    generated_dir.mkdir(parents=True, exist_ok=True)

    yield
    await logger.ainfo("Application shutting down")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject a unique request ID into structlog context and response headers."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def create_app() -> FastAPI:
    """Build and return the fully configured FastAPI application."""
    configure_structlog()

    application = FastAPI(
        title="SpeakX Notification Engine",
        description="AI-powered journey notification engine",
        version="1.0.0",
        lifespan=lifespan,
    )

    application.add_middleware(RequestIDMiddleware)
    application.include_router(api_router)

    # Portal: admin web interface
    application.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
        name="static",
    )
    application.include_router(portal_router)
    application.include_router(portal_api_router)
    application.include_router(tracking_router)

    return application


app = create_app()
