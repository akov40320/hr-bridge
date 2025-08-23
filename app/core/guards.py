from fastapi import Header, HTTPException, status
from .config import get_settings


settings = get_settings()


async def require_admin(authorization: str | None = Header(None), x_admin_token: str | None = Header(None)):
    token = settings.ADMIN_TOKEN
    if not token:
        raise RuntimeError("ADMIN_TOKEN must be set")
    # допускаем либо Authorization: Bearer <token>, либо X-Admin-Token: <token>
    if authorization and authorization.startswith("Bearer "):
        if authorization.removeprefix("Bearer ").strip() == token:
            return
    if x_admin_token and x_admin_token.strip() == token:
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
