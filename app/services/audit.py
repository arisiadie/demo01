from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import AuditLog


def write_audit_log(
    db: Session,
    *,
    actor_external_id: str,
    actor_role: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    risk_level: str = "low",
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    log = AuditLog(
        actor_external_id=actor_external_id,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        risk_level=risk_level,
        detail_json=json.dumps(detail or {}, ensure_ascii=False),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log

