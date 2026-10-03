from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import doctor, patient, system
from app.db.session import SessionLocal, create_schema, reset_schema
from app.fhir.client import HapiFhirStore, get_fhir
from app.fhir.seed import seed
from app.services import session_cache
from app.settings import get_settings

# Never log request bodies: they can contain health data.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def reset_demo() -> None:
    reset_schema()
    session_cache.clear_all()
    with SessionLocal() as db:
        seed(db, get_fhir())


@asynccontextmanager
async def lifespan(app: FastAPI):
    fhir = get_fhir()
    if isinstance(fhir, HapiFhirStore):
        fhir.wait_until_ready()
    if get_settings().seed_on_startup:
        reset_demo()
    else:
        create_schema()
    yield


app = FastAPI(title="VitalContext API", version="0.1.0", lifespan=lifespan,
              description="Pre-visit intake and chart context. Organises information only: no diagnoses, "
                          "risk scores or suggested actions. Synthetic data only.")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins.split(","), allow_credentials=False,
                   allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def no_store(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


app.include_router(system.router)
app.include_router(patient.router)
app.include_router(doctor.router)


@app.get("/health")
def health():
    return {"ok": True}
