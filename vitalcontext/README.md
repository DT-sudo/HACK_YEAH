# VitalContext

**AI-assisted pre-visit intake and chart context for clinics** · HackYeah 2026, Sport & Healthcare

VitalContext prepares both the patient and the GP before an appointment. The patient describes their complaint in an AI-guided chat (typing or speaking). The system pulls the relevant records from the clinic's history, the patient's medications and their lifestyle profile. The doctor gets a short structured brief where every fact links to its source record. The patient gets a plain-language summary and preparation tips.

**Goal:** shorter, more precise appointments where neither side misses important details.

## Live prototype

Open `index.html` in a browser, or via GitHub Pages once it's enabled for this repository.

The prototype has two views, switched from the top bar:

- **Patient app**: opens straight into the intake chat (text or voice), with tabs for Home, My appointments and Profile. The profile holds lifestyle data and medicines from other providers; every entry can be edited or deleted.
- **Doctor dashboard**: today's appointments and the pre-visit brief: chief complaint, intake answers, medication overview from two sources, relevant history, relevant lifestyle, open questions. Click any record ID to open the original FHIR record.

Try it:
1. Answer the chat questions by tapping, typing or using the mic (voice is simulated in the prototype).
2. Confirm the summary, then switch to **Doctor dashboard** to see the brief update.
3. In **Profile**, update "Work" or remove a medicine and watch the brief change.
4. Type "chest pain" in the chat to see the emergency safety net.

All patients are synthetic. No real patient data is used.

## Core principles

1. **No diagnosis, no treatment recommendations.** The system collects, structures and surfaces information. Clinical decisions stay with the doctor.
2. **Grounded output.** Every fact in the brief links to a clinic record or a patient-reported entry.
3. **Source transparency.** Clinic data and patient-reported data are always visually distinct and dated.
4. **Data minimization.** The LLM only receives data relevant to the current complaint.
5. **Patient control.** Patient-reported data can be viewed, edited or deleted at any time.
6. **Clinic scope.** Clinical data comes only from this clinic.

Red flags (e.g. chest pain, breathing difficulty) are detected by deterministic rules, not the LLM. The chat stops, the patient is calmly directed to call 112, and the case is marked urgent for the clinic.

## Tech stack (target build)

- **Frontend:** Next.js, TypeScript, Tailwind, shadcn/ui. Mobile-first patient app, dense desktop doctor dashboard.
- **Backend:** Python, FastAPI.
- **AI:** LLM with JSON schema output, relevance-based retrieval of FHIR resources, citation validation layer.
- **Data:** HL7 FHIR R4, synthetic patients (Synthea).

`VitalContext-frontend-prompt.md` contains the full specification for building the production front end with an AI coding tool.

## Compliance notes

- **GDPR:** health data processed under Art. 9(2)(h) by the clinic as data controller; role-based access; DPIA required before production.
- **EU AI Act:** patients are always told they're talking to an AI (Art. 50).
- **EU MDR:** the product organises and surfaces information only; the differential-guided questioning needs a formal regulatory assessment before production.
- **LLM hosting:** demo uses an external API on synthetic data; production requires an EU-hosted model with zero retention or an open-weights model on clinic infrastructure.

## Repository contents

| File | What it is |
| --- | --- |
| `index.html` | Clickable prototype of the patient app and doctor dashboard, no dependencies |
| `VitalContext-frontend-prompt.md` | Build specification / prompt for the Next.js front end |
| `README.md` | This file |
