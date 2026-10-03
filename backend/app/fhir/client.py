"""FHIR R4 data access. One interface, two implementations:

* LocalFhirStore - in-process store with native-style versioning, seeded with synthetic data.
  Default for the hackathon demo (no containers needed).
* HapiFhirStore - talks to a HAPI FHIR server on the internal network (docker-compose).

Callers only ever pass ids that the API layer derived from the auth token or a care assignment.
"""
from __future__ import annotations

import copy
import itertools
import threading
from typing import Any, Protocol

import httpx

from app.settings import get_settings, iso_now

Resource = dict[str, Any]

PATIENT_REF_PATHS = ("subject", "patient", "beneficiary")
DOCUMENTED_TAG = {"system": "https://vitalcontext.example/tags", "code": "documented"}


def ref_of(resource: Resource) -> str:
    return f"{resource['resourceType']}/{resource['id']}"


def patient_ref_of(resource: Resource) -> str | None:
    if resource.get("resourceType") == "Patient":
        return ref_of(resource)
    for key in PATIENT_REF_PATHS:
        v = resource.get(key)
        if isinstance(v, dict) and v.get("reference"):
            return v["reference"]
    for p in resource.get("participant", []) or []:
        r = (p.get("actor") or {}).get("reference", "")
        if r.startswith("Patient/"):
            return r
    return None


def is_documented(resource: Resource) -> bool:
    return any(t.get("code") == DOCUMENTED_TAG["code"] for t in (resource.get("meta") or {}).get("tag", []))


class FhirStore(Protocol):
    def read(self, rtype: str, rid: str) -> Resource | None: ...
    def search(self, rtype: str, patient: str | None = None) -> list[Resource]: ...
    def create(self, resource: Resource) -> Resource: ...
    def update(self, resource: Resource) -> Resource: ...
    def delete(self, rtype: str, rid: str) -> None: ...
    def history(self, rtype: str, rid: str) -> list[Resource]: ...
    def reset(self) -> None: ...


class LocalFhirStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._current: dict[str, Resource] = {}
        self._history: dict[str, list[Resource]] = {}
        self._ids = itertools.count(1000)

    def reset(self) -> None:
        with self._lock:
            self._current.clear()
            self._history.clear()

    def _stamp(self, resource: Resource, version: int) -> Resource:
        meta = resource.setdefault("meta", {})
        meta["versionId"] = str(version)
        meta["lastUpdated"] = iso_now()
        return resource

    def read(self, rtype: str, rid: str) -> Resource | None:
        with self._lock:
            r = self._current.get(f"{rtype}/{rid}")
            return copy.deepcopy(r) if r else None

    def search(self, rtype: str, patient: str | None = None) -> list[Resource]:
        with self._lock:
            out = []
            for key, r in self._current.items():
                if not key.startswith(rtype + "/"):
                    continue
                if patient and patient_ref_of(r) != patient:
                    continue
                out.append(copy.deepcopy(r))
            return out

    def create(self, resource: Resource) -> Resource:
        with self._lock:
            resource = copy.deepcopy(resource)
            if not resource.get("id"):
                prefix = {"QuestionnaireResponse": "qr", "Composition": "brief", "Provenance": "prov", "Observation": "obs",
                          "MedicationStatement": "ms"}.get(resource["resourceType"], resource["resourceType"].lower())
                resource["id"] = f"{prefix}-{next(self._ids)}"
            key = ref_of(resource)
            self._stamp(resource, 1)
            self._current[key] = resource
            self._history[key] = [copy.deepcopy(resource)]
            return copy.deepcopy(resource)

    def update(self, resource: Resource) -> Resource:
        with self._lock:
            key = ref_of(resource)
            if key not in self._current:
                return self.create(resource)
            resource = copy.deepcopy(resource)
            self._stamp(resource, len(self._history[key]) + 1)
            self._current[key] = resource
            self._history[key].append(copy.deepcopy(resource))
            return copy.deepcopy(resource)

    def delete(self, rtype: str, rid: str) -> None:
        with self._lock:
            self._current.pop(f"{rtype}/{rid}", None)

    def history(self, rtype: str, rid: str) -> list[Resource]:
        with self._lock:
            return copy.deepcopy(self._history.get(f"{rtype}/{rid}", []))


class HapiFhirStore:
    """Minimal REST client for HAPI FHIR (R4). Used when VC_FHIR_BACKEND=hapi."""

    SEARCH_PARAM = {"AllergyIntolerance": "patient", "Appointment": "patient"}

    def __init__(self, base_url: str) -> None:
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=15.0,
                                  headers={"Accept": "application/fhir+json", "Content-Type": "application/fhir+json"})

    def read(self, rtype: str, rid: str) -> Resource | None:
        r = self._http.get(f"/{rtype}/{rid}")
        if r.status_code in (404, 410):
            return None
        r.raise_for_status()
        return r.json()

    def search(self, rtype: str, patient: str | None = None) -> list[Resource]:
        params: dict[str, str] = {"_count": "500"}
        if patient:
            params[self.SEARCH_PARAM.get(rtype, "subject")] = patient
        r = self._http.get(f"/{rtype}", params=params)
        r.raise_for_status()
        return [e["resource"] for e in r.json().get("entry", [])]

    def create(self, resource: Resource) -> Resource:
        if resource.get("id"):  # client-assigned ids keep seeds stable
            return self.update(resource)
        r = self._http.post(f"/{resource['resourceType']}", json=resource)
        r.raise_for_status()
        return r.json()

    def update(self, resource: Resource) -> Resource:
        r = self._http.put(f"/{resource['resourceType']}/{resource['id']}", json=resource)
        r.raise_for_status()
        return r.json()

    def delete(self, rtype: str, rid: str) -> None:
        self._http.delete(f"/{rtype}/{rid}").raise_for_status()

    def history(self, rtype: str, rid: str) -> list[Resource]:
        r = self._http.get(f"/{rtype}/{rid}/_history")
        r.raise_for_status()
        return [e["resource"] for e in r.json().get("entry", [])][::-1]

    def reset(self) -> None:
        # Seed data uses fixed ids, so re-seeding overwrites it. Resources created during a demo stay
        # in HAPI; for a clean slate recreate its volume (`docker compose down -v`).
        pass


_store: FhirStore | None = None


def get_fhir() -> FhirStore:
    global _store
    if _store is None:
        s = get_settings()
        _store = HapiFhirStore(s.fhir_base_url) if s.fhir_backend == "hapi" else LocalFhirStore()
    return _store
