"""FHIR R4 data access. One interface, two implementations:

* LocalFhirStore - in-process store with native-style versioning, seeded with synthetic data.
  Default for the hackathon demo (no containers needed).
* HapiFhirStore - talks to a HAPI FHIR server on the internal network (docker-compose).

Callers only ever pass ids that the API layer derived from the auth token or a care assignment.
"""
from __future__ import annotations

import copy
import itertools
import logging
import threading
import time
from typing import Any, Protocol

import httpx

from app.settings import get_settings, iso_now

Resource = dict[str, Any]
log = logging.getLogger("vitalcontext.fhir")

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
    """REST client for HAPI FHIR (R4). Used when VC_FHIR_BACKEND=hapi (docker compose)."""

    SEARCH_PARAM = {"AllergyIntolerance": "patient", "Appointment": "patient"}
    # Everything the demo creates; wiped on reset so the demo always starts from the same state.
    DEMO_TYPES = ["Provenance", "Composition", "QuestionnaireResponse", "Appointment", "MedicationStatement",
                  "MedicationRequest", "Observation", "AllergyIntolerance", "DocumentReference", "Encounter",
                  "Condition", "Patient", "Practitioner", "Organization"]

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")
        self._http = httpx.Client(base_url=self._base, timeout=30.0,
                                  headers={"Accept": "application/fhir+json", "Content-Type": "application/fhir+json"})

    def wait_until_ready(self, timeout_s: float = 300) -> None:
        """HAPI needs a minute or two to boot; the API waits instead of crashing."""
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                if self._http.get("/metadata", timeout=5).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError(f"FHIR server at {self._base} not ready after {timeout_s:.0f}s")
            log.info("waiting for FHIR server at %s ...", self._base)
            time.sleep(3)

    def read(self, rtype: str, rid: str) -> Resource | None:
        r = self._http.get(f"/{rtype}/{rid}")
        if r.status_code in (404, 410):
            return None
        r.raise_for_status()
        return r.json()

    def _search_all(self, rtype: str, params: dict[str, str]) -> list[Resource]:
        out: list[Resource] = []
        r = self._http.get(f"/{rtype}", params={"_count": "200", **params})
        while True:
            r.raise_for_status()
            bundle = r.json()
            out += [e["resource"] for e in bundle.get("entry", []) if e.get("resource", {}).get("resourceType") == rtype]
            nxt = next((l["url"] for l in bundle.get("link", []) if l.get("relation") == "next"), None)
            if not nxt:
                return out
            r = self._http.get(nxt)

    def search(self, rtype: str, patient: str | None = None) -> list[Resource]:
        params = {self.SEARCH_PARAM.get(rtype, "subject"): patient} if patient else {}
        return self._search_all(rtype, params)

    def create(self, resource: Resource) -> Resource:
        if resource.get("id"):  # client-assigned ids keep seeds stable
            return self.update(resource)
        r = self._http.post(f"/{resource['resourceType']}", json=resource)
        self._raise(r)
        return r.json()

    def update(self, resource: Resource) -> Resource:
        r = self._http.put(f"/{resource['resourceType']}/{resource['id']}", json=resource)
        self._raise(r)
        return r.json()

    def delete(self, rtype: str, rid: str) -> None:
        r = self._http.delete(f"/{rtype}/{rid}")
        if r.status_code not in (200, 204, 404, 410):
            self._raise(r)

    def history(self, rtype: str, rid: str) -> list[Resource]:
        r = self._http.get(f"/{rtype}/{rid}/_history")
        r.raise_for_status()
        return [e["resource"] for e in r.json().get("entry", [])][::-1]

    def reset(self) -> None:
        for rtype in self.DEMO_TYPES:
            for res in self._search_all(rtype, {"_elements": "id"}):
                self.delete(rtype, res["id"])

    @staticmethod
    def _raise(r: httpx.Response) -> None:
        if r.is_error:
            detail = ""
            try:
                detail = "; ".join(i.get("diagnostics", "") for i in r.json().get("issue", []))
            except ValueError:
                pass
            raise RuntimeError(f"FHIR {r.request.method} {r.request.url.path} -> {r.status_code}: {detail[:300]}")


_store: FhirStore | None = None


def get_fhir() -> FhirStore:
    global _store
    if _store is None:
        s = get_settings()
        _store = HapiFhirStore(s.fhir_base_url) if s.fhir_backend == "hapi" else LocalFhirStore()
    return _store
