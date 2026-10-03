# VitalContext

**AI-assisted pre-visit intake and chart context for clinics.** HackYeah 2026, Sport & Healthcare.

The patient describes their complaint in an AI-guided chat, by typing, speaking or tapping. The backend
pulls the relevant records from the clinic's history, the patient's medicines and their lifestyle profile.
The doctor gets a structured brief in which every fact links to its source record. The patient gets a
plain-language summary to confirm. **No diagnoses, risk scores or suggested actions, anywhere.**

Product spec: [`VitalContext.md`](VitalContext.md) · Backend design: [`ARCHITECTURE.md`](ARCHITECTURE.md) ·
Original clickable prototype: [`vitalcontext/index.html`](vitalcontext/index.html).

All patients are synthetic. No real patient data is used.

## Run it (two terminals, no Docker needed)

```bash
# 1. API  → http://localhost:8000  (OpenAPI docs at /docs)
cd backend
uv sync
uv run uvicorn app.main:app --port 8000

# 2. Web  → http://localhost:3000
cd frontend
npm install
npm run dev
```

The API seeds the synthetic data set on every start. **Reset demo** in the top bar (or `POST /demo/reset`)
restores it at any time.

### AI provider

| `VC_LLM_PROVIDER` | What runs |
|---|---|
| `auto` (default) | Claude (`claude-opus-5`) when `ANTHROPIC_API_KEY` is set, otherwise the offline engine |
| `mock` | Offline, deterministic rule engine: same JSON contracts and validation, no network |
| `anthropic` | Claude through the Anthropic SDK, structured JSON output, no tools |

The offline engine is also the **safe fallback**. If the model is unavailable or its output fails
validation twice, the intake continues with the framework questionnaire and the brief is built by rules.
The product degrades instead of breaking. Copy `backend/.env.example` to `backend/.env` to configure it.

### Production-like topology

`docker compose up --build` starts `api`, `web`, PostgreSQL, HAPI FHIR and Redis, with only `api` and
`web` exposed (see [`docker-compose.yml`](docker-compose.yml)). Untested here: Docker wasn't running on
the build machine. HAPI keeps resources created during a demo; run `docker compose down -v` for a clean
slate.

## Demo script (≈3 minutes)

1. **Patient app** (Anna Kowalska, 52). The app opens straight into the chat, with the AI disclosure
   pinned at the top. Tap the demo shortcut, or say *"I've had a dry cough for about three weeks and it's
   worse at night"* with the mic (Chrome / Edge / Safari, PL or EN). Onset, character and timing are
   extracted from that one answer, so the assistant skips those questions.
2. Answer the remaining 3 questions → **Review my summary** → tick *"true to the best of my knowledge"* → **Confirm**.
3. **Doctor dashboard**: Anna now shows *Brief updated just now*. Look at:
   - the lisinopril → dry cough connection, citing both the prescription and the intake;
   - the medication table that merges clinic prescriptions with patient-reported medicines;
   - the stale *Work* record flag;
   - any record chip, which opens the original FHIR resource ("Citation verified").
4. Back in **Profile**: update *Work* and the stale flag disappears from the brief within seconds. Remove
   *Omeprazole* and you get a 409, because it is now part of the medical record. *Mark as no longer taking*
   moves it to "Past" in the brief.
5. **Safety net**: switch to another patient (e.g. Tomasz) and type *"ból w klatce"* or *"chest pain"*.
   The chat stops, a calm 112 screen appears and the patient is pinned as **Urgent** for the doctor.
   Marek (08:00) shows a pre-seeded case.
6. **Break-glass**: in the day list, open patient `jan-k` (Dr. Mazur's patient) with a written reason.
   **Audit log** shows every access, plus the LLM gateway metadata, which contains no content.

Other seeded states: Piotr (knee pain, brief ready from a voice intake; wearable running load
14 → 38 km/week), Zofia (intake in progress), Halina and Tomasz (not started).

## How the spec maps to code

| Requirement | Where |
|---|---|
| Deterministic red-flag rules (PL/EN, before any LLM call) | `backend/app/config/red_flags.yaml`, `services/safety.py`, mirrored client-side in `frontend/lib/redflags.ts` |
| Differential-guided questioning; working list never shown or stored | `llm/framework.py`, `llm/mock_provider.py` (T1), `services/session_cache.py` (TTL memory / Redis only) |
| Context pack: deterministic retrieval, relevance filter, pseudonymisation, `R1…` refs | `services/context.py`, `config/relevance.yaml` |
| Three narrow LLM tasks, fixed JSON schemas, versioned prompts, retry → fallback, metadata-only logs | `llm/gateway.py`, `llm/schemas.py`, `llm/prompts/*.md`, `llm/anthropic_provider.py` |
| Citation validation, language filter, patient words copied by code | `services/brief.py`, `llm/validation.py` |
| Medication overview built by code; reconciliation as `Provenance` | `services/brief.py`, `api/doctor.py` |
| Profile in FHIR; deletable until documented, then `409` + "mark not current" | `services/profile.py` |
| `patient_id` only from the token; doctor access via care assignment; audited break-glass | `api/deps.py`, `api/doctor.py` |
| Explicit response models (nothing internal can leak) | `api/models.py` |
| FHIR R4 store (local in-process or HAPI) | `fhir/client.py`, `fhir/seed.py` |
| Eval set: golden, injection, red-flag, leakage + API rules | `backend/tests/` → `uv run pytest` (52 tests) |

## Repository

```
backend/    FastAPI modular monolith (Python 3.13, uv)
frontend/   Next.js 16 + TypeScript + Tailwind v4 + lucide-react; PL/EN, light/dark
vitalcontext/  original single-file prototype and the front-end build prompt
docker-compose.yml
```

## Known gaps (hackathon scope)

- The voice input uses the browser's Web Speech API. The server-side speech-to-text fallback (e.g.
  Whisper) is not built: when a browser has no speech support, the patient sees a clear message and types.
- The `anthropic` provider is wired and schema-checked, but this build was verified with the offline engine.
  Run one intake with a key before presenting with Claude.
- The frontend talks to the real API only. There is no separate mock-JSON mode.
- UI components are hand-written in the prototype's design language rather than generated with shadcn/ui.
  i18n is a small typed dictionary (`locales/en.json`, `locales/pl.json`) rather than next-intl.
- Mock login only. Production needs OIDC with 2FA / Profil Zaufany / mObywatel, a DPIA, and an MDR
  assessment of the differential-guided questioning.
