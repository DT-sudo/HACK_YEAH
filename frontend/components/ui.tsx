"use client";

import { useApp } from "@/lib/app-context";
import type { DayStatus } from "@/types/api";
import type { Citation, Fact as FactT, Source } from "@/types/brief";
import { Check } from "lucide-react";

export function BrandMark() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
      <rect x="1" y="1" width="11" height="11" rx="2" fill="var(--clinic)" />
      <circle cx="19" cy="19" r="5.2" fill="none" stroke="var(--patient)" strokeWidth="2.6" />
      <path d="M12 6.5h4.5a3 3 0 0 1 3 3V13" fill="none" stroke="var(--ink)" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** Provenance is never shown by colour alone: clinic = filled square, patient = ring. */
export function SourceMark({ source }: { source: Source }) {
  return <span className={`mark ${source}`} aria-hidden="true" />;
}

export function CitationChip({ c, onOpen }: { c: Citation; onOpen: (ref: string) => void }) {
  const { t } = useApp();
  const label = c.source === "clinic" ? t("source.clinic") : t("source.patient");
  return (
    <button className={`cite ${c.source}`} onClick={() => onOpen(c.reference)} title={c.reference}
            aria-label={t("brief.cite.aria", { source: label, ref: c.reference })}>
      {c.label}
    </button>
  );
}

export function Fact({ fact, onOpen, when }: { fact: FactT; onOpen: (ref: string) => void; when?: React.ReactNode }) {
  const mixed = fact.sources.length > 1;
  const cls = mixed ? "mixed" : fact.sources[0] ?? "clinic";
  return (
    <div className={`fact ${cls}`}>
      {mixed ? (
        <span style={{ display: "inline-flex", gap: 3 }}><SourceMark source="clinic" /><SourceMark source="patient" /></span>
      ) : <SourceMark source={(fact.sources[0] ?? "clinic") as Source} />}
      <div>{fact.text}</div>
      <span className="when">{when}</span>
      <div className="cites">{fact.citations.map((c) => <CitationChip key={c.reference} c={c} onOpen={onOpen} />)}</div>
    </div>
  );
}

export function StatusPill({ status, fresh }: { status: DayStatus; fresh?: boolean }) {
  const { t } = useApp();
  if (status === "urgent") return <span className="pill urgent">{t("pill.urgent")}</span>;
  if (status === "reviewed") return <span className="pill reviewed"><Check size={14} aria-hidden /> {t("pill.reviewed")}</span>;
  if (status === "ready") return fresh ? <span className="pill new">{t("pill.updated")}</span> : <span className="pill ready">{t("pill.ready")}</span>;
  if (status === "progress") return <span className="pill progress">{t("pill.progress")}</span>;
  return <span className="pill none">{t("pill.none")}</span>;
}
