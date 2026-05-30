import logging
import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from middleware.logging import StructuredLoggingMiddleware
from routers import (
    backtest,
    execution,
    health,
    internal,
    keys,
    orders,
    portfolio,
    positions,
    signals,
    usage,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            integrations=[StarletteIntegration(), FastApiIntegration()],
            traces_sample_rate=0.2,
        )

    yield

    from cache.redis import _pool
    if _pool is not None:
        await _pool.aclose()

    from ml.langfuse_tracing import flush as _flush_langfuse, is_enabled as _langfuse_enabled
    if _langfuse_enabled():
        _flush_langfuse()


def create_app() -> FastAPI:
    app = FastAPI(
        title="SIGMA API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(StructuredLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(signals.router)
    app.include_router(keys.router)
    app.include_router(usage.router)
    app.include_router(portfolio.router)
    app.include_router(backtest.router)
    app.include_router(internal.router)
    app.include_router(positions.router)
    app.include_router(orders.router)
    app.include_router(execution.router)

    return app


app = create_app()
