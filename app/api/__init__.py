"""API package aggregating routers for FastAPI application."""

from fastapi import APIRouter, Depends

from app.core.guards import require_admin

# Import submodules before defining routers to avoid name clashes
from . import (
    oauth,
    admin as admin_module,
    hh_incoming,
    avito_incoming,
    amo_webhooks,
)  # noqa: E402

# Base routers for public and admin endpoints
router = APIRouter()
admin = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

router.include_router(oauth.router)
router.include_router(hh_incoming.router)
router.include_router(avito_incoming.router)
router.include_router(amo_webhooks.router)
router.include_router(admin_module.router)
admin.include_router(admin_module.admin)

__all__ = ["router", "admin"]

