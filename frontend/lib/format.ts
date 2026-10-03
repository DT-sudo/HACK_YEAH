import type { Lang } from "@/lib/app-context";

const loc = (lang: Lang) => (lang === "pl" ? "pl-PL" : "en-GB");

/** Formats FHIR dates, including partial ones ("2025", "2026-07"). */
export function fmtDate(d: string | null | undefined, lang: Lang = "en"): string {
  if (!d) return "";
  const parts = d.slice(0, 10).split("-");
  if (parts.length === 1) return parts[0];
  const date = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2] ?? 1));
  if (parts.length === 2) return date.toLocaleDateString(loc(lang), { month: "short", year: "numeric" });
  return date.toLocaleDateString(loc(lang), { day: "numeric", month: "short", year: "numeric" });
}

export function fmtTime(iso: string, lang: Lang = "en"): string {
  return new Date(iso).toLocaleTimeString(loc(lang), { hour: "2-digit", minute: "2-digit" });
}

export function fmtWeekdayDate(iso: string, lang: Lang = "en"): string {
  const d = new Date(iso);
  const day = d.toLocaleDateString(loc(lang), { weekday: "short", day: "numeric", month: "short" });
  return `${day} · ${iso.slice(11, 16)}`;
}

export function fmtLongDay(isoDate: string, lang: Lang = "en"): string {
  const [y, m, dd] = isoDate.split("-").map(Number);
  return new Date(y, m - 1, dd).toLocaleDateString(loc(lang), { weekday: "long", day: "numeric", month: "long" });
}
