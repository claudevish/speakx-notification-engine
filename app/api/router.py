"""Top-level API router — aggregates health and admin sub-routers."""

from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(admin_router)
