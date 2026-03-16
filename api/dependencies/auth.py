import logging
import os

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import RoleEnum, User

logger = logging.getLogger(__name__)

_raw_iap = os.environ.get("IAP_AUDIENCE", "")
IAP_AUDIENCE = _raw_iap if _raw_iap not in ("", "disabled", "placeholder") else ""


def _validate_iap_jwt(iap_jwt: str, expected_audience: str) -> str:
    """Validate an IAP JWT and return the user's email."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        decoded = id_token.verify_token(
            iap_jwt,
            google_requests.Request(),
            audience=expected_audience,
            certs_url="https://www.gstatic.com/iap/verify/public_key",
        )
        email = decoded.get("email")
        if not email:
            raise ValueError("No email claim in IAP JWT")
        return email
    except Exception as e:
        logger.warning("IAP JWT validation failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid IAP JWT") from e


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    Authenticate the current user.

    Production (IAP_AUDIENCE set): validates the X-Goog-IAP-JWT-Assertion header
    signed by Cloud IAP and extracts the user email.

    Development (no IAP_AUDIENCE): reads identity from X-User-Email header.
    """
    if IAP_AUDIENCE:
        iap_jwt = request.headers.get("X-Goog-IAP-JWT-Assertion")
        if not iap_jwt:
            raise HTTPException(status_code=401, detail="Missing IAP JWT assertion header")
        email = _validate_iap_jwt(iap_jwt, IAP_AUDIENCE)
    else:
        email = request.headers.get("X-User-Email")
        if not email:
            raise HTTPException(status_code=401, detail="Missing X-User-Email header")

    user = db.query(User).filter(User.email == email, User.active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def require_role(*roles: RoleEnum):
    """FastAPI dependency that checks the current user has at least one of the given roles."""

    async def _check(user: User = Depends(get_current_user)) -> User:
        user_roles = {r.role for r in user.roles}
        if not user_roles.intersection(roles):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return _check
