// Fixed JSON schema of the doctor's pre-visit brief, as returned by
// GET /doctor/patients/{pid}/briefs/{bid}. Source (clinic vs patient) is derived by the backend
// from the cited FHIR resource, never from text an LLM wrote.

export type Source = "clinic" | "patient";

export type Citation = {
  reference: string; // "MedicationRequest/mr-4471"
  source: Source;
  label: string; // "mr-4471"
};

export type Fact = {
  text: string;
  date?: string | null;
  citations: Citation[];
  sources: Source[];
};

export type LifestyleFact = Fact & { updatedAt: string; monthsAgo: number; stale: boolean };

export type MedicationRow = {
  reference: string;
  name: string;
  dose: string;
  dates: string;
  note: string | null;
  status: "current" | "past";
  source: Source;
  reconciled: { by: string; at: string } | null;
};

export type Brief = {
  id: string;
  patientId: string;
  createdAt: string | null;
  category: string;
  chiefComplaint: Fact;
  patientWords: string[]; // copied verbatim by code, rendered as quotes
  intakeAnswers: { label: string; answer: string }[];
  patientCorrection: string | null;
  medications: MedicationRow[];
  relevantHistory: Fact[];
  lifestyle: LifestyleFact[];
  openQuestions: string[];
  reviewed: { by: string; at: string } | null;
  generation: {
    provider: string;
    prompt_version: string;
    dropped_statements: number;
    context_records: number;
    total_records: number;
    degraded: boolean;
    instruction_like_input: boolean;
    hidden_unresolved: number;
  };
};

export type SourceRecord = {
  reference: string;
  type: string;
  source: Source;
  title: string;
  date: string | null;
  fields: [string, string][];
  verified: boolean;
  version: string | null;
  raw: Record<string, unknown>;
};
