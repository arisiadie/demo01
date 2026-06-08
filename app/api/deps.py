from __future__ import annotations

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.auth import CurrentUser, bearer_token, current_user_from_token, get_or_create_user, parse_user_headers


def get_current_user(
    authorization: str | None = Header(default=None),
    user_headers: tuple[str, str] = Depends(parse_user_headers),
    db: Session = Depends(get_db),
) -> CurrentUser:
    token = bearer_token(authorization)
    if token:
        return current_user_from_token(db, token)
    external_id, role = user_headers
    return get_or_create_user(db, external_id, role)
