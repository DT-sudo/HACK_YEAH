export type Role = "patient" | "doctor";

export type DemoUser = { id: string; role: Role; displayName: string; detail?: string | null };

export type Appointment = {
  id: string;
  start: string;
  doctor: string;
  service: string;
  clinic: string;
  address: string;
  phone: string;
  preparation: "not_started" | "in_progress" | "sent" | "urgent";
};

export type Me = {
  id: string;
  name: string;
  initials: string;
  birthDate: string;
  clinic: string;
  demoSuggestion: string | null;
  upcoming: Appointment | null;
  pastVisits: { date: string; reason: string; doctor: string }[];
};

export type LifestyleItem = {
  key: string;
  label: string;
  labelPl: string;
  hint: string;
  optional: boolean;
  value: string;
  updatedAt: string | null;
  documented: boolean;
};

export type MedicationItem = {
  id: string;
  name: string;
  dose: string;
  frequency: string;
  start: string | null;
  end: string | null;
  reason: string | null;
  prescriber: string | null;
  note: string | null;
  current: boolean;
  updatedAt: string;
  documented: boolean;
};

export type Profile = {
  lifestyle: LifestyleItem[];
  medications: MedicationItem[];
  wearable: { updatedAt: string; metrics: { label: string; value: number | null; unit: string }[] } | null;
};

export type AnswerType = "free" | "single" | "multi" | "scale";

export type Question = { slot: string; text: string; answer_type: AnswerType; options: string[] };

export type ChatMessage = { from: "ai" | "me"; text: string; mode?: string | null };

export type IntakeState = "STARTED" | "COLLECTING" | "EMERGENCY" | "COMPLETED" | "CONFIRMED_BY_PATIENT" | "SUBMITTED";

export type Intake = {
  id: string;
  state: IntakeState;
  lang: "en" | "pl";
  messages: ChatMessage[];
  question: Question | null;
  progress: number;
  emergency: { message: string; ruleId: string } | null;
  degraded: boolean;
};

export type Summary = {
  patientWords: string;
  paragraphs: string[];
  bring: string[];
  questions: string[];
  correction: string | null;
};

export type DayStatus = "urgent" | "reviewed" | "ready" | "progress" | "none";

export type Urgent = { ruleId: string; trigger: string; at: string; contactedBy: string | null; contactedAt: string | null };

export type DayPatient = {
  patientId: string;
  name: string;
  age: number | null;
  sex: string;
  time: string;
  status: DayStatus;
  briefId: string | null;
  briefCreatedAt: string | null;
  briefFresh: boolean;
  urgent: Urgent | null;
  breakGlass: boolean;
};

export type Day = { date: string; doctor: string; patients: DayPatient[] };

export type AuditEntry = {
  who: string;
  role: string;
  patientId: string | null;
  action: string;
  resource: string | null;
  reason: string | null;
  timestamp: string;
};

export type LlmCall = {
  task: string;
  provider: string;
  promptVersion: string;
  latencyMs: number;
  inputTokens: number | null;
  outputTokens: number | null;
  validation: string;
  timestamp: string;
};

export type SystemInfo = { llmProvider: string; model: string; fhirBackend: string; redFlagRulesVersion: string; demoToday: string };
