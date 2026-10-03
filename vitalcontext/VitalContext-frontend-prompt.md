# VitalContext front-end build prompt

Paste everything below the line into Claude Code, Cursor, v0 or similar. Attach `index.html` (the clickable prototype) as the visual and interaction reference if your tool accepts files.

---

You are building the front end for **VitalContext**, a HackYeah 2026 project (Sport & Healthcare, 24 hours). VitalContext is a clinic-operated system that prepares the patient and the GP before an appointment. Before the visit, the patient describes their complaint in an AI-guided chat. In parallel, the backend analyses the patient's history at this clinic, their medications and their lifestyle profile. The doctor gets a structured brief where every fact links to its source. The patient gets a plain-language summary and preparation tips. Target market: Polish primary-care clinics (POZ).

The attached `index.html` is a working prototype of both surfaces. Match its flow, information architecture and visual language (provenance colours, record-ID chips, source drawer). Rebuild it properly in the stack below.

## Non-negotiable product rules

Every screen, string and component must respect these. If a feature conflicts with them, drop the feature.

1. **No diagnosis, no treatment recommendations.** The UI collects, structures and surfaces information. No "possible causes", "differential", "risk score", "suggested action" or "recommended test" anywhere, for patient or doctor.
2. **Grounded output.** Every fact shown to the doctor carries at least one source record ID, rendered as a clickable chip that opens the original record in a side drawer.
3. **Source transparency.** Clinic data and patient-reported data are always visually distinct, and never by colour alone: clinic = cobalt + filled square mark; patient-reported = amber + ring mark + tinted row background. Facts that combine both sources show both marks. Every item shows its date.
4. **Patient control.** Patient-reported data (profile, external medications) can be viewed, edited and deleted at any time. Deleting an entry removes it from the doctor's brief.
5. **Clinic scope.** Clinical data comes only from this clinic. External medications appear only as patient-reported.
6. **Language rule.** Describe connections ("Lisinopril lists dry cough as a common side effect; cough began 3 weeks ago"), never conclusions ("likely ACE-inhibitor cough").
7. **Honest answers.** The patient is told that answers affect how urgently they're seen, that deliberately giving false information to get an earlier appointment is misuse of the service with consequences under the clinic's rules, and that honest mistakes are never penalised. The warning must never discourage reporting real symptoms: it never appears on or near the emergency screen or red-flag questions.
8. **AI disclosure (EU AI Act Art. 50).** The patient is told they are talking to an AI before the chat starts and the chat UI keeps an "AI assistant" label visible.

## Stack

- Next.js (App Router) + TypeScript, Tailwind CSS, shadcn/ui, lucide-react
- Backend is Python/FastAPI, built by teammates. Put all data access in `lib/api.ts` with typed functions. Start with a mock implementation that reads JSON from `mocks/`, switchable to real endpoints via `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_USE_MOCKS`.
- Data model is **HL7 FHIR R4**. Type the mocks with FHIR shapes (use `@types/fhir` or hand-written minimal types):
  - Diagnoses → `Condition`
  - Clinic prescriptions → `MedicationRequest`
  - Patient-reported medications → `MedicationStatement` (`informationSource` = the Patient)
  - Labs, lifestyle → `Observation` (lifestyle uses category `social-history`)
  - Allergies → `AllergyIntolerance`
  - Visit notes → `Encounter`, `DocumentReference`
  - Intake answers → `QuestionnaireResponse`
- The brief comes from the backend as a fixed JSON schema. Define it in `types/brief.ts`, for example:
  ```ts
  type Citation = { reference: string };            // "MedicationRequest/mr-4471"
  type Fact = { text: string; date?: string; citations: Citation[] };
  type Brief = {
    patientId: string;
    chiefComplaint: Fact;
    intakeAnswers: { label: string; answer: string }[];
    patientCorrection?: string;
    medications: { name: string; dose: string; dates: string; status: "current" | "past"; citation: Citation }[];
    relevantHistory: Fact[];
    lifestyle: (Fact & { updatedAt: string })[];
    openQuestions: string[];
  };
  ```
  Derive source (clinic vs patient) from the cited resource, not from a field the LLM writes. Hide any fact whose citation does not resolve to a loaded record (mirror of the backend validation).
- Demo data is synthetic (Synthea-style FHIR bundles). Never real patient data.

## Surface 1: Patient app (mobile-first, 375px and up)

Calm, plain-language, large tap targets. App structure:

- **The app opens straight into the intake chat.** No landing page or start button. The first AI question is already on screen.
- **Bottom tab bar** with three tabs, always visible except on the emergency screen: **Home** (the chat and visit flow), **My appointments**, **Profile**. A round avatar button with the patient's initials in the top-right header also opens the profile. Switching tabs mid-chat keeps the chat state.
- Routes: `/patient` (home = chat), `/patient/appointments`, `/patient/profile`.

Screens:

1. **Home = chat**. Pinned at the top of the conversation, a compact card: "You're chatting with the clinic's AI assistant. It asks questions and passes your answers to {doctor} before your visit on {date}. It doesn't diagnose or give medical advice." (EU AI Act Art. 50). Inside it, a collapsible "Please answer honestly" section with the misuse warning from rule 7 and the GDPR note (health data processed by the clinic to provide care, Art. 9(2)(h); not consent-based, so no consent checkbox).
   - **Two ways to answer, always available:** a text field and a microphone button side by side in the composer, plus quick-reply chips, multi-select chips or a 0–10 scale above it when the question has set options.
   - **Voice:** tapping the mic shows a "Listening…" panel with an animated waveform, "Speak in Polish or English" and a Stop button. The transcript lands in the text field for the patient to check and edit before sending ("Check what we heard, edit if needed, then send"). Voice answers are tagged "Voice" in the chat bubble. Use the Web Speech API (`pl-PL`, fallback `en-US`) with a server-side speech-to-text fallback (e.g. Whisper via the FastAPI backend); show a clear error if microphone access is denied and keep typing available.
   - Typed and spoken answers go through the same red-flag check as chips.
2. **My appointments**: the upcoming visit card (date and time, doctor, clinic address, type) with a "Visit preparation" status pill (Not started / In progress / Answers sent / Urgent) and a "Start in chat" or "Continue in chat" button that switches to Home. Below it, past visits (date, reason, doctor). Footer: the clinic's phone number for booking.
3. **Profile** (its own tab, filled once, reused every visit, never re-asked in chat):
   - Header: avatar with initials, name, date of birth, clinic. Note: "Your doctor sees your profile with every visit. Only you can change it."
   - **Lifestyle**, one row per item with its value, last-updated date and an Edit/Add link that opens an inline edit with Save, Cancel and Delete entry: smoking (status, pack-years, vaping), alcohol (frequency, units/week), physical activity (with a "Wearable" line when connected: resting HR, sleep), sleep, diet, work (sedentary/physical, shift work, stress), other substances (marked optional).
   - **Medicines from elsewhere**: prescriptions from other providers, OTC drugs and supplements. Fields: name, dose, frequency, start date, end date, reason (optional), prescriber (optional). Add and remove.
   - **Your data**: "Delete my profile data" with an inline confirmation step (no browser dialogs). Clinic records are not affected.
   - Every edit saves the date as today and updates the doctor's brief: a fresh "Work" entry removes the stale-data flag; a deleted medicine leaves the medication overview. Neutral, non-judgmental wording; the patient never sees stale-data warnings.

Chat behaviour:

- **Question flow**: Questions follow SOCRATES/OPQRST and arrive one at a time from `api.nextQuestion(sessionId, answer)`. Mock this with a scripted question tree. The backend's internal working list of conditions is **never** sent to or shown in the UI. Questions never name or hint at a disease. Show a typing indicator and progress bar.
- **Emergency safety net**: deterministic red-flag rules (e.g. chest pain, breathing difficulty at rest, fainting), checked on every typed message and on flagged options, in Polish and English keywords. On a hit: stop the chat immediately and show a calm, reassuring screen, not an alarming one: neutral background with a soft phone icon, heading "Let's get you checked now", a thank-you for telling us, one clear `tel:112` "Call 112" button (the only red element), a note that 112 is free and the operator will guide them, three short steps (call and repeat what you told us; stay where you are with your phone; ask someone nearby to stay with you), "Not sure it's serious? Call anyway", and a note that the clinic has been told. No warning icons, no big red blocks, no capitalised alarm text. Mark the case urgent in the doctor dashboard. This runs client-side as well as server-side so it works even if the API is slow.
- **Summary** (after the last question, still in Home): plain-language summary of what the patient said; a required checkbox "My answers are true to the best of my knowledge"; "Confirm and send to my doctor" (disabled until ticked) and "Something's not right" (free-text correction attached to the brief). Also "Please bring" (medicine packaging, external test results) and neutral questions the patient could ask. The doctor sees nothing until the patient confirms.
- **Sent** confirmation, with "In an emergency, call 112".

## Surface 2: Doctor dashboard (desktop-first, dense)

1. **Day view** (left column): today's appointments with time, name and a status pill: Urgent · safety net (red, pinned to the top), Brief ready, Intake in progress, Intake not started, Reviewed.
2. **Pre-visit brief** (main pane), readable in under a minute, sections in this order:
   - **Chief complaint**: one-line clinical summary with duration and severity
   - **Intake answers**: label/answer pairs from the chat, plus any patient correction
   - **Medication overview**: one table merging "Prescribed at this clinic" (`MedicationRequest`) and "Reported by the patient" (`MedicationStatement`), grouped current/past, with dose, dates, source and record chip. Note: "Reconcile with the patient."
   - **Relevant history**: clinic records connected to the complaint (similar episodes, abnormal past labs, medications listing the symptom as a side effect), each with record chips
   - **Relevant lifestyle**: profile facts connected to the complaint, with update date; data older than ~6 months is flagged ("Updated 10 months ago") for the doctor only
   - **Open questions**: what is unclear and worth clarifying in the visit
   - Footer: "Organises information only. No diagnoses, risk scores or suggested actions."
   - Actions: Mark as reviewed, Copy brief (plain text for pasting into the clinic EHR)
3. **Source drawer**: clicking any record chip opens a side panel with the record's human-readable fields, source, date, a "Citation verified" indicator and a collapsible raw FHIR JSON view. Esc closes it.
4. **Urgent case view**: for safety-net cases, show what triggered it and when, that the patient was told to call 112, and a "Mark as contacted" action. No brief.
5. **Empty states** for patients without intake: "The brief appears once the patient confirms their summary."

## Design direction

- Font: Atkinson Hyperlegible Next (fallback system-ui); one family for the UI, its mono companion only for record IDs and raw JSON.
- Palette tokens: background `#EDF1F0`, surface `#FFFFFF`, ink `#162B29`, muted `#556966`, line `#D2DBD9`, clinic `#2251A3`, patient `#94600C` (tint `#FAF0DC`), alert `#B3261E`, ok `#2C7652`. Provide a dark theme.
- Red is reserved for safety-net and stale-data flags. Patient app is spacious; doctor dashboard is dense with a two-column section layout (heading left, content right) that stacks on narrow screens.
- Accessibility: WCAG AA contrast, visible focus rings, keyboard navigation, labelled controls, `prefers-reduced-motion` respected.
- i18n: all strings in `locales/pl.json` and `locales/en.json` via next-intl. Polish is the default for the patient app; include a PL/EN toggle for the demo.

## Mock data

Use these two complete patients (match the prototype) plus 4 status-only entries:

- **Anna Kowalska, 52**: dry cough ~3 weeks, worse at night. Clinic: lisinopril 10 mg started 7 weeks ago for new hypertension (its product info lists dry cough), atorvastatin, past amoxicillin; cough after URTI in Feb 2025 that resolved; normal chest X-ray Feb 2025; dust-mite allergy. Patient-reported: OTC ibuprofen, vitamin D3, omeprazole from another provider. Lifestyle: former smoker 12 pack-years; sedentary office job (record 10+ months old → flagged); wearable steps/HR/sleep.
- **Piotr Nowak, 34**: right anterior knee pain ~2 weeks. Wearable: weekly running 14 → 38 km in 5 weeks (half-marathon training). Patient-reported: ibuprofen 400 mg TID for 10 days, creatine. Clinic: right ankle sprain 2024, normal creatinine 13 months ago. Occupation record 7 months old.
- **Marek Zieliński, 61**: flagged by the safety net (chest pain).
- Three more with "Intake not started" / "Intake in progress".

## Order of work

1. Scaffold, tokens, layout shell, routing (`/patient/[visitId]`, `/doctor`), i18n, FHIR + Brief types, mock API
2. Doctor brief with medication overview, record chips and source drawer (the core of the demo)
3. Day view, urgent and empty states
4. Patient app: opens in the chat (text + voice), three-tab bar, My appointments, Profile with inline editing, summary → sent, plus the emergency screen
5. Wire the demo loop: patient confirming, editing a profile entry or deleting a medicine updates the doctor's brief; a red flag marks the patient urgent
6. Polish: loading and error states, responsive check, dark mode, "Reset demo" button

Run the app after each step and fix all type and console errors before moving on. Keep components small: `PatientTabBar`, `ChatComposer` (text + mic), `VoiceListening`, `AppointmentCard`, `ProfileItem`, `Fact`, `SourceMark`, `CitationChip`, `SourceDrawer`, `MedicationTable`, `StatusPill`, `ChatBubble`, `QuickReplies`, `ScaleInput`, `EmergencyScreen`. Finish with a README covering how to run it, how to switch from mocks to the FastAPI backend, and the brief JSON schema.
