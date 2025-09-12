"""API‑роутеры приложения."""

from fastapi import APIRouter, Depends

from app.core.guards import require_admin
from . import admin as admin_module
from . import amo_webhooks, avito_incoming, hh_incoming, oauth

__all__ = ["build_routers"]


def build_routers() -> tuple[APIRouter, APIRouter]:
    """Построить и вернуть публичный и административный роутеры API."""

    router = APIRouter()
    admin = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

    router.include_router(oauth.router)
    router.include_router(hh_incoming.router)
    router.include_router(avito_incoming.router)
    router.include_router(amo_webhooks.router)
    router.include_router(admin_module.router)
    admin.include_router(admin_module.admin)
    return router, admin
