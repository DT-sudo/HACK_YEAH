// All data access goes through here. The FastAPI backend is the single source of truth.
import type {
  AuditEntry, CheckinState, Day, DayPatient, DemoUser, Intake, LlmCall, Me, Profile, Role, Summary, SystemInfo,
} from "@/types/api";
import type { Brief, Fact, FollowUp, SourceRecord } from "@/types/brief";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = (role: Role) => `vc2-token-${role}`; // v2: ADHD follow-up demo defaults
const USER_KEY = (role: Role) => `vc2-user-${role}`;

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
  }
}

function store(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function getToken(role: Role): string | null {
  try {
    return store()?.getItem(TOKEN_KEY(role)) ?? null;
  } catch {
    return null;
  }
}

export function getStoredUser(role: Role): DemoUser | null {
  try {
    const raw = store()?.getItem(USER_KEY(role));
    return raw ? (JSON.parse(raw) as DemoUser) : null;
  } catch {
    return null;
  }
}

function setSession(role: Role, token: string, user: DemoUser) {
  try {
    store()?.setItem(TOKEN_KEY(role), token);
    store()?.setItem(USER_KEY(role), JSON.stringify(user));
  } catch {
    /* storage unavailable: session lasts for this page only */
  }
}

const memoryTokens: Partial<Record<Role, string>> = {};

async function request<T>(path: string, init: RequestInit & { role?: Role } = {}): Promise<T> {
  const { role, ...rest } = init;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = role ? (getToken(role) ?? memoryTokens[role]) : null;
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...rest, headers: { ...headers, ...(rest.headers as Record<string, string>) } });
  } catch {
    throw new ApiError(0, `Can't reach the VitalContext API at ${API_URL}. Is the backend running?`);
  }
  if (res.status === 204) return undefined as T;
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const detail = isJson ? (body as { detail?: unknown }).detail : body;
    if (detail && typeof detail === "object" && "message" in detail) {
      const d = detail as { message: string; code?: string };
      throw new ApiError(res.status, d.message, d.code);
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : `Request failed (${res.status})`);
  }
  return body as T;
}

export async function login(username: string): Promise<DemoUser> {
  const r = await request<{ token: string; user: DemoUser }>("/auth/login", { method: "POST", body: JSON.stringify({ username }) });
  memoryTokens[r.user.role] = r.token;
  setSession(r.user.role, r.token, r.user);
  return r.user;
}

const P = "patient" as const;
const D = "doctor" as const;
const json = (b: unknown) => JSON.stringify(b);

export const api = {
  demoUsers: () => request<DemoUser[]>("/demo/users"),
  resetDemo: () => request<void>("/demo/reset", { method: "POST" }),
  system: () => request<SystemInfo>("/system"),

  // patient
  me: () => request<Me>("/me", { role: P }),
  profile: () => request<Profile>("/me/profile", { role: P }),
  putLifestyle: (key: string, value: string) => request<Profile>(`/me/profile/lifestyle/${key}`, { role: P, method: "PUT", body: json({ value }) }),
  deleteLifestyle: (key: string) => request<Profile>(`/me/profile/lifestyle/${key}`, { role: P, method: "DELETE" }),
  markLifestyleNotCurrent: (key: string) => request<Profile>(`/me/profile/lifestyle/${key}`, { role: P, method: "PATCH", body: json({ current: false }) }),
  addMedication: (m: { name: string; dose?: string; frequency?: string; start?: string | null; prescriber?: string | null; reason?: string | null }) =>
    request<Profile>("/me/profile/medications", { role: P, method: "POST", body: json(m) }),
  deleteMedication: (id: string) => request<Profile>(`/me/profile/medications/${id}`, { role: P, method: "DELETE" }),
  stopMedication: (id: string) => request<Profile>(`/me/profile/medications/${id}`, { role: P, method: "PATCH", body: json({ current: false }) }),
  wipeProfile: () => request<Profile>("/me/profile", { role: P, method: "DELETE" }),
  startIntake: (lang: "en" | "pl") => request<Intake>("/me/intakes", { role: P, method: "POST", body: json({ lang }) }),
  sendMessage: (id: string, text: string, mode: "text" | "voice" | "choice") =>
    request<Intake>(`/me/intakes/${id}/messages`, { role: P, method: "POST", body: json({ text, mode }) }),
  summary: (id: string) => request<Summary>(`/me/intakes/${id}/summary`, { role: P }),
  confirm: (id: string, truthful: boolean, correction: string | null) =>
    request<Intake>(`/me/intakes/${id}/confirm`, { role: P, method: "POST", body: json({ truthful, correction }) }),

  checkins: (lang: "en" | "pl") => request<CheckinState>(`/me/checkins?lang=${lang}`, { role: P }),
  submitCheckin: (answers: Record<string, number | string | string[]>, lang: "en" | "pl") =>
    request<CheckinState>("/me/checkins", { role: P, method: "POST", body: json({ answers, lang }) }),

  // doctor
  trends: (pid: string) => request<{ followUp: FollowUp | null; trends: Fact[] }>(`/doctor/patients/${pid}/trends`, { role: D }),
  day: () => request<Day>("/doctor/patients", { role: D }),
  brief: (pid: string, bid: string) => request<Brief>(`/doctor/patients/${pid}/briefs/${bid}`, { role: D }),
  briefText: (pid: string, bid: string) => request<string>(`/doctor/patients/${pid}/briefs/${bid}/text`, { role: D }),
  review: (pid: string, bid: string) => request<{ by: string; at: string }>(`/doctor/patients/${pid}/briefs/${bid}/review`, { role: D, method: "POST" }),
  source: (pid: string, ref: string) => request<SourceRecord>(`/doctor/patients/${pid}/sources/${ref}`, { role: D }),
  reconcile: (pid: string, ref: string) => request<{ by: string; at: string }>(`/doctor/patients/${pid}/medications/${ref}/reconcile`, { role: D, method: "POST" }),
  contacted: (pid: string) => request<unknown>(`/doctor/patients/${pid}/urgent/contacted`, { role: D, method: "POST" }),
  breakGlass: (pid: string, reason: string) => request<DayPatient>(`/doctor/break-glass/${pid}`, { role: D, method: "POST", body: json({ reason }) }),
  audit: () => request<AuditEntry[]>("/doctor/audit", { role: D }),
  llmCalls: () => request<LlmCall[]>("/doctor/llm-calls", { role: D }),
};
