from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import User


ALLOWED_ROLES = {"patient", "doctor", "admin"}


@dataclass(frozen=True)
class CurrentUser:
    id: int
    external_id: str
    role: str
    display_name: str


def get_or_create_user(db: Session, external_id: str, role: str) -> CurrentUser:
    user = db.query(User).filter(User.external_id == external_id).first()
    if user is None:
        user = User(external_id=external_id, role=role, display_name=_display_name(external_id, role), active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    elif user.role != role:
        user.role = role
        db.commit()
        db.refresh(user)
    return CurrentUser(id=user.id, external_id=user.external_id, role=user.role, display_name=user.display_name)


def authenticate_user(db: Session, external_id: str, password: str) -> CurrentUser:
    user = db.query(User).filter(User.external_id == external_id).first()
    if user is None or not user.active or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return CurrentUser(id=user.id, external_id=user.external_id, role=user.role, display_name=user.display_name)


def current_user_from_token(db: Session, token: str) -> CurrentUser:
    payload = parse_access_token(token)
    external_id = str(payload.get("sub") or "")
    user = db.query(User).filter(User.external_id == external_id).first()
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive token user")
    return CurrentUser(id=user.id, external_id=user.external_id, role=user.role, display_name=user.display_name)


def parse_user_headers(
    x_user_id: str = Header(default="patient-demo"),
    x_role: str = Header(default="patient"),
) -> tuple[str, str]:
    role = x_role.lower().strip()
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="Unsupported role")
    external_id = x_user_id.strip() or f"{role}-demo"
    return external_id, role


def hash_password(password: str, iterations: int = 120_000) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, raw_iterations, salt, expected = stored_hash.split("$", 3)
        iterations = int(raw_iterations)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations).hex()
    return hmac.compare_digest(digest, expected)


def create_access_token(user: CurrentUser) -> str:
    payload = {
        "sub": user.external_id,
        "role": user.role,
        "name": user.display_name,
        "exp": int(time.time()) + settings.auth_token_ttl_seconds,
    }
    body = _b64_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signature = _sign(body)
    return f"{body}.{signature}"


def parse_access_token(token: str) -> dict[str, Any]:
    try:
        body, signature = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    if not hmac.compare_digest(_sign(body), signature):
        raise HTTPException(status_code=401, detail="Invalid token signature")
    try:
        payload = json.loads(_b64_decode(body).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid token payload") from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise HTTPException(status_code=401, detail="Token expired")
    return payload


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def require_role(user: CurrentUser, allowed_roles: set[str]) -> None:
    if user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Insufficient role permission")


def _display_name(external_id: str, role: str) -> str:
    label = {"patient": "患者", "doctor": "医生", "admin": "管理员"}.get(role, "用户")
    return f"{label}-{external_id}"


def _sign(body: str) -> str:
    digest = hmac.new(settings.auth_secret_key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return _b64_encode(digest)


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
