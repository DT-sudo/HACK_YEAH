"""Auth (mock login) and demo utilities."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import models as M
from app.api.deps import issue_token
from app.db.models import User
from app.db.session import get_db
from app.llm.gateway import get_gateway
from app.services import safety
from app.settings import get_settings

router = APIRouter(tags=["system"])

DETAIL = {"natalia": "28 · ADHD follow-up (live demo patient)", "bartosz": "34 · ADHD follow-up, brief ready",
          "kamila": "26 · ADHD, safety-net case", "michal": "31 · ADHD follow-up, not started",
          "marta": "Psychiatrist, ADHD follow-ups today",
          "anna": "52 · dry cough (GP)", "piotr": "34 · knee pain, brief ready", "marek": "61 · safety-net case",
          "halina": "74 · intake not started", "zofia": "29 · intake in progress", "tomasz": "45 · intake not started",
          "jan": "68 · Dr. Mazur's patient", "ewa": "GP, 6 visits today", "adam": "GP, 1 visit today"}


@router.post("/auth/login", response_model=M.LoginOut)
def login(body: M.LoginIn, db: Session = Depends(get_db)):
    """Demo mock login (synthetic users only). Production: OIDC + 2FA or Profil Zaufany / mObywatel."""
    if not get_settings().demo_mode:
        raise HTTPException(404)
    user = db.get(User, body.username.lower())
    if not user:
        raise HTTPException(401, "Unknown demo user")
    return M.LoginOut(token=issue_token(user), user=M.DemoUser(id=user.id, role=user.role, displayName=user.display_name,
                                                               detail=DETAIL.get(user.id)))


@router.get("/demo/users", response_model=list[M.DemoUser])
def demo_users(db: Session = Depends(get_db)):
    if not get_settings().demo_mode:
        raise HTTPException(404)
    return [M.DemoUser(id=u.id, role=u.role, displayName=u.display_name, detail=DETAIL.get(u.id))
            for u in db.scalars(select(User)).all()]


@router.post("/demo/reset", status_code=204)
def reset():
    if not get_settings().demo_mode:
        raise HTTPException(404)
    from app.main import reset_demo
    reset_demo()


@router.get("/system", response_model=M.SystemOut)
def system():
    s = get_settings()
    gw = get_gateway()
    return M.SystemOut(llmProvider=gw.provider_name, model=getattr(gw.provider, "model", ""), fhirBackend=s.fhir_backend,
                       redFlagRulesVersion=safety.rules_version(), demoToday=s.demo_today)
