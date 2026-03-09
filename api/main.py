import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest

from api.dependencies.auth import get_current_user
from api.logging_config import setup_logging
from api.middleware import GlobalErrorHandler, RateLimiter, RequestLogger
from api.models import User
from api.routers import (
    admin,
    algolia,
    audit,
    dashboard,
    enrichment,
    export,
    ingestion,
    review,
    skus,
)

setup_logging()

app = FastAPI(title="Catalog Intelligence Engine")

# CORS — configurable origins (comma-separated)
_cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware (outermost first)
app.add_middleware(RequestLogger)
app.add_middleware(GlobalErrorHandler)
app.add_middleware(
    RateLimiter,
    limits={
        "/ingest/jobs": (30, 60),  # 30 requests per minute
        "/skus/": (60, 60),  # 60 enrichment requests per minute (covers /skus/*/enrich)
    },
)

# Routers
app.include_router(skus.router)
app.include_router(ingestion.router)
app.include_router(audit.router)
app.include_router(enrichment.router)
app.include_router(review.router)
app.include_router(export.router)
app.include_router(algolia.router)
app.include_router(dashboard.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return PlainTextResponse(generate_latest(), media_type="text/plain; version=0.0.4")


@app.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "name": current_user.name,
        "email": current_user.email,
        "roles": [{"role": r.role.value, "category": r.category} for r in current_user.roles],
    }
