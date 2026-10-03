from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import AuditLog
from app.settings import now


def record(db: Session, who: str, role: str, action: str, patient_id: str | None = None,
           resource: str | None = None, reason: str | None = None) -> None:
    """Append-only audit entry: who, role, patient, action, resource reference. No medical content."""
    db.add(AuditLog(who=who, role=role, patient_id=patient_id, action=action, resource=resource,
                    reason=reason, timestamp=now()))
    db.commit()
