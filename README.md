# VitalContext

**AI-assisted pre-visit intake and chart context for clinics.** HackYeah 2026, Sport & Healthcare.

The patient describes their complaint in an AI-guided chat, by typing, speaking or tapping. The backend
pulls the relevant records from the clinic's history, the patient's medicines and their lifestyle profile.
The doctor gets a structured brief in which every fact links to its source record. The patient gets a
plain-language summary to confirm. **No diagnoses, risk scores or suggested actions, anywhere.**

Product spec: [`VitalContext.md`](VitalContext.md) · Backend design: [`ARCHITECTURE.md`](ARCHITECTURE.md) ·
Original clickable prototype: [`vitalcontext/index.html`](vitalcontext/index.html).

All patients are synthetic. No real patient data is used.

## How to run

There are two ways to run the app: with Docker (Option A) or without Docker (Option B). Both
work on macOS, Linux and Windows and open the app at http://localhost:3000. You also need
Git (https://git-scm.com/downloads) to download the code.

### Option A: with Docker

1. Install Docker.
   - macOS / Windows: install Docker Desktop (https://www.docker.com/products/docker-desktop/) and
     start it.
   - Linux: install Docker Engine (https://docs.docker.com/engine/install/) with the Compose plugin.
2. Download the code and start the app. Open a terminal (on Windows: PowerShell) and run:

       git clone https://github.com/DT-sudo/HACK_YEAH.git
       cd HACK_YEAH
       docker compose up

   The first start needs internet and takes a few minutes. Later starts are fast and work offline.
3. Open http://localhost:3000 in a browser.
4. To stop, press Ctrl+C in the terminal.

### Option B: without Docker

1. Install Node.js 22 or newer from https://nodejs.org.
2. Install uv. It installs Python 3.13 for you.
   - macOS / Linux (Terminal):

         curl -LsSf https://astral.sh/uv/install.sh | sh

   - Windows (PowerShell):

         powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

   Then close the terminal and open a new one.
3. Download the code:

       git clone https://github.com/DT-sudo/HACK_YEAH.git
       cd HACK_YEAH

4. Start the API. In this terminal, run the commands below and leave it running:

       cd backend
       uv sync
       uv run uvicorn app.main:app --port 8000

5. Start the web app. Open a second terminal, go to the HACK_YEAH folder, and run:

       cd frontend
       npm install
       npm run dev

6. Open http://localhost:3000 in a browser.
7. To stop, press Ctrl+C in both terminals.

## Who it's for (MVP scope)

**Tech-literate adults aged 25–40 managing a newly diagnosed condition between visits.** The demo case is
ADHD medication titration, where the psychiatrist needs to know what happened day by day since the last
visit: focus, sleep, appetite, side effects, missed doses. Between visits the patient does a one-minute
daily check-in; before the visit, a short AI-guided chat. The doctor gets:

- **Since last visit:** daily trends around the dose change, from check-ins and wearable aggregates.
- **Public registry data:** medicine side effects from the Polish registry of medicinal products (URPL,
  a simulated snapshot for the demo), cited as a third source next to clinic and patient data.
- **Consistency check:** where the patient's chat answers differ from their check-ins, device data or
  clinic records (e.g. "none of these side effects" vs. racing heart on 3 days and a resting heart rate
  of 63 → 71 bpm). Computed by code, framed as a conversation prompt, never a verdict.

Starting with this group is a deliberate choice for safety and data integrity. Accessibility for older
patients, proxies and carers is on the roadmap, not in the MVP. The original general-practice flow
(Dr. Ewa Wiśniewska's day: cough, knee pain, safety-net case) is still included.

## Run it: one command

```bash
docker compose up
```

Then open **http://localhost:3000**. The API and its docs are at http://localhost:8000/docs.

This starts `web` (Next.js), `api` (FastAPI), PostgreSQL and Redis. Only `web` and `api` publish ports;
Postgres and Redis sit on an internal network. The API seeds the synthetic data set on start, and `web`
comes up once the API is healthy. FHIR resources live in the API's built-in FHIR store. Stop with
`Ctrl+C`, or `docker compose down` (add `-v` to also drop the Postgres volume).

**Reset demo** in the top bar (or `POST /demo/reset`) restores the seeded state at any time.

To run a separate **HAPI FHIR** server, the full `ARCHITECTURE.md` topology, add the override file:

```bash
docker compose -f docker-compose.yml -f docker-compose.hapi.yml up --build
```

HAPI is a large image (~450 MB) and needs 1–2 minutes to boot. The API waits for it, then seeds it.

**First run vs. later runs.** The first `docker compose up` builds the two app images. That needs internet
access to Docker Hub for the base images and to npm/PyPI for dependencies, and takes several minutes on a
slow connection. After that, `docker compose up` starts from the local images with no network needed.
Only use `docker compose up --build` after changing the code. `--build` re-checks the base images
on Docker Hub every time, so it fails when Docker Hub is unreachable.

**Troubleshooting**

- `failed to resolve source metadata ... TLS handshake timeout`: Docker couldn't reach Docker Hub.
  If the images were built before, run `docker compose up` without `--build`. Otherwise retry once the
  connection is stable, or configure a registry mirror in Docker Desktop (Settings → Docker Engine).
- `unknown flag: --build`: flags go after the subcommand: `docker compose up --build`, not
  `docker compose --build up`.
- Port 3000 or 8000 already in use: stop the other process, or a dev server started from `npm run dev` /
  `uvicorn`.

### Without Docker (two terminals)

```bash
# API → http://localhost:8000 (in-process FHIR store, SQLite, no containers)
cd backend && uv sync && uv run uvicorn app.main:app --port 8000

# Web → http://localhost:3000
cd frontend && npm install && npm run dev
```

### AI provider

| `VC_LLM_PROVIDER` | What runs |
|---|---|
| `auto` (default) | Claude (`claude-opus-5`) when `ANTHROPIC_API_KEY` is set, otherwise the offline engine |
| `mock` | Offline, deterministic rule engine: same JSON contracts and validation, no network |
| `anthropic` | Claude through the Anthropic SDK, structured JSON output, no tools |

The offline engine is also the **safe fallback**. If the model is unavailable or its output fails
validation twice, the intake continues with the framework questionnaire and the brief is built by rules.
The product degrades instead of breaking.

With Docker, put `ANTHROPIC_API_KEY=...` in a `.env` file next to `docker-compose.yml` (git-ignored).
Without Docker, copy `backend/.env.example` to `backend/.env`.

## Demo script (≈3 minutes, ADHD follow-up)

Defaults: patient **Natalia Zając** (28, methylphenidate ER, dose raised 18 → 27 mg on 17 Sep) and
doctor **Dr. Marta Kaczmarek** (psychiatrist).

1. **Patient app → Daily.** Do today's check-in: medicine, focus 0–10, when focus dropped, triggers,
   sleep, appetite, side effects, optional note. Fixed questions, no AI. "Your entries" shows the
   last four weeks.
2. **Patient app → Home.** The pre-visit chat opens with a follow-up question. Tap the demo shortcut,
   then answer, e.g. "Every day" for the medicine and "None of these" for side effects →
   **Review my summary** → confirm.
3. **Doctor dashboard** (Natalia shows *Brief updated just now*):
   - **Since last visit:** focus, sleep (reported vs. wearable) and resting heart rate, with the dose
     change marked. Hover for any day; "Show as table" gives the same data.
   - **Relevant history:** the methylphenidate statement cites the prescription, the **URPL registry**
     entry (diamond mark) and the check-ins.
   - **Consistency check:** "every day" vs. 2 missed doses; "none of these" vs. racing heart and the
     heart-rate rise; reported vs. wearable sleep; melatonin in the profile but not mentioned in the chat.
   - Every chip opens the original record.
4. **Safety net:** in Daily, write "chest pain" (or "ból w klatce") in the note. The patient gets the
   calm 112 screen and the case turns **Urgent** for the doctor. Kamila (09:00) is a pre-seeded case.
5. **Other states:** Bartosz (brief ready, with his own consistency findings) and Michał (no chat yet,
   but his check-in trends are already visible).
6. **Audit log:** every access, plus LLM gateway metadata with no content.

The GP flow still works: switch the doctor to Dr. Ewa Wiśniewska and the patient to Anna Kowalska
(cough, lisinopril) or Piotr Nowak (knee pain, running load).

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
| FHIR R4 store (built-in, or HAPI via `docker-compose.hapi.yml`) | `fhir/client.py`, `fhir/seed.py` |
| Daily check-ins (care-plan enabled, fixed questionnaire, safety-checked, one `QuestionnaireResponse` per day) | `config/checkins.yaml`, `services/checkins.py`, `frontend/app/patient/daily` |
| Since-last-visit trends and consistency check (code, not AI) | `services/trends.py`, `frontend/components/TrendChart.tsx` |
| Public registry side effects as a citable third source (simulated URPL snapshot) | `config/registry_snapshot.yaml`, `services/knowledge.py` |
| ADHD follow-up question bank (EN/PL) | `llm/framework.py` (`ADHD_FOLLOWUP`), `fhir/seed_adhd.py` |
| Eval set: golden, injection, red-flag, leakage, follow-up + API rules | `backend/tests/` → `uv run pytest` (57 tests) |

## Repository

```
backend/    FastAPI modular monolith (Python 3.13, uv)
frontend/   Next.js 16 + TypeScript + Tailwind v4 + lucide-react; PL/EN, light/dark
vitalcontext/  original single-file prototype and the front-end build prompt
docker-compose.yml        web + api + PostgreSQL + Redis (one-command start)
docker-compose.hapi.yml   optional override: separate HAPI FHIR server
```

## Known gaps (hackathon scope)

- The voice input uses the browser's Web Speech API. The server-side speech-to-text fallback (e.g.
  Whisper) is not built: when a browser has no speech support, the patient sees a clear message and types.
- The `anthropic` provider is wired and schema-checked, but this build was verified with the offline engine.
  Run one intake with a key before presenting with Claude.
- The URPL registry data is a **simulated snapshot** with the registry's structure (SmPC section 4.8
  frequency groups) and abridged values, not a live sync. Production would sync it from the public registry
  and keep the registry ID and version for every fact.
- Wearable data is seeded as daily aggregates. There is no live device integration.
- The frontend talks to the real API only. There is no separate mock-JSON mode.
- UI components are hand-written in the prototype's design language rather than generated with shadcn/ui.
  i18n is a small typed dictionary (`locales/en.json`, `locales/pl.json`) rather than next-intl.
- Mock login only. Production needs OIDC with 2FA / Profil Zaufany / mObywatel, a DPIA, and an MDR
  assessment of the differential-guided questioning.
