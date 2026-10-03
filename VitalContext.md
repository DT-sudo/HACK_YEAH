# VitalContext
**AI-assisted pre-visit intake and chart context for clinics**

HackYeah 2026 · Sport & Healthcare (open task)

Technical implementation: see `ARCHITECTURE.md`.

---

## 1. Overview
VitalContext is a clinic-operated system that prepares both the patient and the doctor before an appointment.

- **Before the visit:** the patient describes their complaint in an AI-guided chat.
- **In parallel:** the system analyzes the patient's history at this clinic, their medications and their lifestyle profile.
- **The doctor receives** a short structured brief with every fact linked to its source.
- **The patient receives** a plain-language summary and preparation tips.

**Goal:** shorter, more precise appointments where neither side misses important details.

## 2. Problem
- **Short visits.** GP appointments last 10–15 minutes. Part of that time goes to reading the record and re-collecting the patient's story. This is a hypothesis; back it with a source before using it in the pitch.
- **Lost details.** Patients forget symptoms, timelines and medications. Relevant facts get buried in long records.
- **Fragmented medication info.** Prescriptions from other clinics are invisible to the current doctor.
- **Untrustworthy medical AI.** Symptom-checker bots that diagnose create liability and are not trusted by clinicians.

## 3. Core Principles
Every feature must follow these rules.

1. **No diagnosis, no treatment recommendations, no risk scores, no suggested actions.** The system collects, structures and surfaces information. All clinical decisions stay with the doctor.
2. **Grounded output.** Every fact shown to the doctor links to its source: a clinic record or a patient-reported entry.
3. **Source transparency.** Clinic data and patient-reported data are always visually distinguished. Each item carries its date.
4. **Data minimization.** The AI receives only the data relevant to the current complaint, pseudonymized.
5. **Patient control.** Profile data is optional. The patient can view and edit it at any time and delete entries that are not yet part of medical documentation (see 4.1).
6. **Clinic scope.** Clinical data comes only from this clinic. External information enters only through the patient's own profile.
7. **Not an emergency service.** This is stated to the patient at all times, and the product never implies that someone is monitoring the chat.

## 4. Components

### 4.1 Patient Profile
Filled in once and updated when something changes. It is automatically included in every analysis, so it is not re-asked during intake.

**Lifestyle**
- Smoking (status, pack-years, vaping).
- Alcohol (frequency, units per week).
- Physical activity (type, frequency, intensity). Optional wearable import: only aggregates (weekly activity, resting heart rate, sleep), never location or raw history.
- Sleep (duration, regularity).
- Diet (pattern, restrictions).
- Occupation and workload (sedentary or physical, shift work, stress level).
- Other substances (optional).

**Medications from other providers**
- Current and past medications prescribed outside this clinic, including over-the-counter drugs and supplements.
- Fields: name, dose, frequency, start date, end date (if stopped), reason (optional), prescriber or clinic (optional).

**Rules**
- Each field stores its last update date. Data older than ~6 months is flagged to the doctor; the patient is not re-asked.
- An entry can be deleted until it is used in a confirmed intake. After that it is part of medical documentation and can only be marked as no longer current.
- Neutral, non-judgmental wording.

### 4.2 Intake Chat (differential-guided)
The patient describes the complaint in free text or voice. The patient is clearly informed they are talking to an AI.

**Questioning logic**
- The model keeps an **internal working list** of conditions that could plausibly explain the symptoms, based on the complaint, the clinic history, medications and the lifestyle profile.
- Each next question is chosen by its value for confirming or ruling out conditions on that list (character of pain, timing, triggers, accompanying symptoms).
- Conditions that the answers clearly contradict are dropped from the list.
- Questions follow standard history-taking frameworks (SOCRATES / OPQRST, review of systems).
- The chat ends when further questions would not meaningfully change the picture, or when the question limit is reached.

**Rules**
- **The working list is never shown** to the patient or the doctor and **never persisted**. It exists only during the session to select questions.
- Dropping a condition is not ruling it out. Only the doctor excludes diagnoses.
- Questions are neutral, in plain language, and never hint at a specific disease.
- No medical advice.

### 4.3 Context Engine
- Retrieves the records relevant to the complaint from the clinic history (diagnoses, prescriptions, labs, visit notes, allergies) and the patient profile. Retrieval is done by the backend; the AI never queries data itself.
- Finds factual connections, for example:
  - a medication that lists the symptom as a known side effect;
  - a similar earlier episode;
  - an abnormal past lab result;
  - a relevant lifestyle factor.

### 4.4 Doctor's Pre-Visit Brief
A structured view that can be read in under a minute.

| Section | Content |
|---|---|
| **Chief complaint** | Clinical summary with duration and severity |
| **Intake answers** | Structured answers. The patient's own words are shown as quotes, visually separated from system-generated content. |
| **Medication overview** | All current and past medications from two sources, each with dose, dates and source |
| **Relevant history** | Clinic records connected to the complaint, each linked to the original |
| **Relevant lifestyle factors** | Profile facts connected to the complaint, with their update date |
| **Open questions** | What remains unclear and is worth clarifying in the visit |

The medication overview combines:
- **Prescribed at this clinic:** from the clinic's records.
- **Reported by the patient:** prescriptions from other providers, OTC drugs and supplements.

The doctor reconciles the list with the patient during the visit; the system records who confirmed each entry and when.

The brief contains no diagnoses, risk scores or suggested actions.

### 4.5 Patient Summary
- A plain-language summary of what the patient reported. The patient confirms or corrects it before it reaches the doctor.
- The confirmed intake becomes medical documentation.
- What to bring (e.g. medication packaging, external test results) and suggested questions for the doctor.

### 4.6 Emergency Safety Net
- Rule-based red-flag detection (e.g. chest pain, breathing difficulty). Deterministic, not AI-based, and run before every AI call.
- On a match: intake stops, the patient is advised to call 112, and the case is marked urgent for the clinic.
- The notice "This is not an emergency service. If your condition worsens, call 112." is always visible.

## 5. AI Reliability
- **Narrow tasks:** the AI runs three tasks (intake turn, patient summary, doctor brief), each with a fixed JSON schema. It has no tools, no data access and cannot trigger actions.
- **Citations required:** every fact in the brief carries a source reference, checked against the real data. Facts without a valid source are discarded.
- **Language rule:** describe connections ("medication X lists symptom Y as a side effect"), never conclusions ("risk of disease Z").
- **Patient words are never rewritten** by the AI; they are copied into the brief by code.
- **One-click verification:** the doctor can open the original record of any fact.
- **Graceful degradation:** if the AI fails, intake continues with a static framework-based questionnaire.
- **Medication overview** is built by code, not by the AI.

## 6. Integration (Poland)
The data already exists and is structured. The barrier is interoperability, not missing data.

- **National system:** the P1 platform (e-Zdrowie). Every patient has an Internet Patient Account (IKP) with e-prescriptions (e-recepta), e-referrals (e-skierowanie) and medical events.
- **Hospital systems (HIS):** Asseco (AMMS), Kamsoft, Comarch.
- **Approach:** VitalContext connects to the HIS through HL7 FHIR, in line with the EU push toward standardized exchange through the European Health Data Space (EHDS). P1 already uses FHIR for parts of its data exchange. Real FHIR coverage varies by vendor and must be verified per deployment.
- **Demo data:** synthetic patients generated with Synthea. No real patient data is used.

## 7. Compliance

**GDPR**
- All data, including lifestyle and medications, is health data (Art. 9), processed under Art. 9(2)(h) by the clinic as data controller.
- AI processing uses pseudonymized data. Pseudonymized data is **still personal data** (Recital 26).
- Confirmed intakes and briefs are medical documentation: retained per Polish law (20 years) and covered by the Art. 17(3)(c) exception to erasure. Drafts and unused profile entries remain deletable.
- Access is role-based and logged; break-glass access for substitutions and emergencies requires a reason and is audited.
- A DPIA (Art. 35) is required before production.

**AI hosting**
- Production default: an EU-hosted LLM (e.g. Azure OpenAI in an EU region / EU data zone) under a DPA (Art. 28 GDPR), with no training on customer data and modified abuse monitoring.
- Alternative for hospitals with GPU capacity: a self-hosted open-weights model. The model is replaceable.
- Demo: external API on synthetic data only.

**EU AI Act**
- Patients are always told they are interacting with AI (Art. 50).
- If the product ever qualifies as a medical device, it becomes a high-risk AI system with the corresponding obligations.

**EU MDR**
- Software that diagnoses or recommends treatment is a medical device (Rule 11, class IIa or higher).
- The core product organizes and surfaces information only.
- **Gray area:** differential-guided questioning uses internal diagnostic reasoning. Its classification depends on the declared intended purpose (MDCG 2019-11) and needs a formal regulatory assessment before production.

**NIS2**
- Hospitals are essential entities; production deployment must meet NIS2 security requirements (encryption, incident management).

**Authentication**
- Production: clinic login with 2FA or national ID (Profil Zaufany / mObywatel). Demo: mock login.

## 8. Scope

**In scope (hackathon)**
- Patient profile (lifestyle and external medications).
- Differential-guided intake chat.
- Context engine with citation validation.
- Doctor brief with medication overview.
- Patient summary.
- Red-flag safety net.

**Future extensions**
- Showing the differential diagnosis to the doctor (requires MDR certification).
- Automatic import of prescriptions from national systems (IKP) instead of manual entry.
- Proxy access for legal representatives and carers (children, elderly patients).
- Pharmacogenetic data for clinics that perform such testing.

**Out of scope**
- Diagnosis, treatment recommendations, risk scores, suggested actions.
- Data from other providers beyond what the patient reports.

## 9. Judging Alignment
| Criterion | How we address it |
|---|---|
| Idea & Innovation (30%) | Differential-guided intake + clinic history + patient profile, with every AI statement grounded in a source |
| Relation to Category (20%) | Appointment preparation and doctor–patient communication; lifestyle and activity included in the clinical picture |
| Practical Applicability (20%) | Clinic-operated, FHIR-based, regulatory path designed in from the start |
| Design (20%) | Two purpose-built interfaces: calm patient app, efficient clinical dashboard |
| Completeness (10%) | End-to-end flow on synthetic data; disclosed use of AI and external resources |
