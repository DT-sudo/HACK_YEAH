"""Auth and access control.

* Mock login issues a JWT (demo). Production: OIDC with 2FA / Profil Zaufany / mObywatel.
* Patient endpoints take patient_id ONLY from the token, never from request parameters.
* Doctor endpoints require a care assignment (or an audited break-glass grant).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import CareAssignment, User
from app.db.session import get_db
from app.fhir.client import FhirStore, get_fhir
from app.services import audit
from app.settings import get_settings, now

bearer = HTTPBearer(auto_error=False)


def issue_token(user: User) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=s.jwt_ttl_minutes)
    return jwt.encode({"sub": user.id, "role": user.role, "exp": exp}, s.jwt_secret, algorithm="HS256")


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not cred:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    try:
        claims = jwt.decode(cred.credentials, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    user = db.get(User, claims["sub"])
    if not user or user.role != claims.get("role"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


def patient_user(user: User = Depends(current_user)) -> User:
    if user.role != "patient":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Patients only")
    return user


def doctor_user(user: User = Depends(current_user)) -> User:
    if user.role != "doctor":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Doctors only")
    return user


def patient_id_of(user: User) -> str:
    return user.fhir_ref.split("/", 1)[1]


def has_access(db: Session, doctor_id: str, patient_id: str) -> CareAssignment | None:
    return db.scalars(select(CareAssignment).where(
        CareAssignment.doctor_id == doctor_id, CareAssignment.patient_id == patient_id,
        or_(CareAssignment.expires_at.is_(None), CareAssignment.expires_at > now()))).first()


def assigned_patient(pid: str, user: User = Depends(doctor_user), db: Session = Depends(get_db)) -> str:
    """Path dependency: the doctor may access {pid} only through a care assignment."""
    if not has_access(db, user.id, pid):
        audit.record(db, user.id, "doctor", "access.denied", pid)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No care assignment for this patient. Use break-glass access if needed.")
    return pid


def fhir_dep() -> FhirStore:
    return get_fhir()
