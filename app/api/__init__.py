from fastapi import APIRouter, Depends
from app.core.guards import require_admin

__all__ = ["build_routers"]


def build_routers():
    from . import oauth, admin as admin_module, hh_incoming, avito_incoming, amo_webhooks

    router = APIRouter()
    admin = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

    router.include_router(oauth.router)
    router.include_router(hh_incoming.router)
    router.include_router(avito_incoming.router)
    router.include_router(amo_webhooks.router)
    router.include_router(admin_module.router)
    admin.include_router(admin_module.admin)
    return router, admin
