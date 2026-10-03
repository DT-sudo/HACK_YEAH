"use client";

import { useEffect, useState } from "react";
import { Info, ShieldAlert } from "lucide-react";
import { TrendChart } from "@/components/TrendChart";
import { CitationChip, Fact, SourceMark, StatusPill } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { fmtDate } from "@/lib/format";
import type { DayPatient } from "@/types/api";
import type { Brief, MedicationRow } from "@/types/brief";

function MedicationTable({ rows, pid, onOpen, onReconciled }: {
  rows: MedicationRow[]; pid: string; onOpen: (ref: string) => void; onReconciled: () => void;
}) {
  const { t, lang, toast } = useApp();
  const current = rows.filter((r) => r.status === "current");
  const past = rows.filter((r) => r.status === "past");
  const row = (m: MedicationRow) => (
    <tr key={m.reference} className={`${m.source}${m.status === "past" ? " past" : ""}`}>
      <td><b>{m.name}</b>{m.note && <div className="small">{m.note}</div>}</td>
      <td>{m.dose}</td>
      <td className="num">{m.dates}</td>
      <td><span className="src"><SourceMark source={m.source} /> {m.source === "clinic" ? t("med.thisClinic") : t("med.patient")}</span></td>
      <td><CitationChip c={{ reference: m.reference, source: m.source, label: m.reference.split("/")[1] }} onOpen={onOpen} /></td>
      <td>
        {m.reconciled ? <span className="small">{t("med.confirmed", { by: m.reconciled.by, date: fmtDate(m.reconciled.at, lang) })}</span>
          : m.status === "current" && (
            <button className="linkbtn" onClick={async () => { await api.reconcile(pid, m.reference); toast(t("med.reconciledToast", { name: m.name })); onReconciled(); }}>
              {t("med.confirm")}
            </button>
          )}
      </td>
    </tr>
  );
  return (
    <div className="table-wrap">
      <table className="meds">
        <thead><tr><th>{t("med.medicine")}</th><th>{t("med.dose")}</th><th>{t("med.dates")}</th><th>{t("med.source")}</th><th>{t("med.record")}</th><th>{t("med.reconcile")}</th></tr></thead>
        <tbody>
          <tr className="grp"><td colSpan={6}>{t("med.current")}</td></tr>
          {current.length ? current.map(row) : <tr><td colSpan={6} className="small">{t("med.noneCurrent")}</td></tr>}
          {past.length > 0 && <tr className="grp"><td colSpan={6}>{t("med.past")}</td></tr>}
          {past.map(row)}
        </tbody>
      </table>
    </div>
  );
}

export function BriefView({ p, onOpen, onChanged, fresh }: { p: DayPatient; onOpen: (ref: string) => void; onChanged: () => void; fresh: boolean }) {
  const { t, lang, toast, epoch } = useApp();
  const [b, setB] = useState<Brief | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!p.briefId) return;
    let cancelled = false;
    api.brief(p.patientId, p.briefId).then((x) => { if (!cancelled) { setB(x); setError(null); } })
      .catch((e) => !cancelled && setError(String(e.message ?? e)));
    return () => { cancelled = true; };
    // p.briefCreatedAt changes when a new brief arrives; tick after reconcile/review; epoch after resets
  }, [p.patientId, p.briefId, tick, epoch]);

  // Profile edits flow into the brief live: re-read it every few seconds while it's open.
  useEffect(() => {
    const id = setInterval(() => setTick((x) => x + 1), 5000);
    return () => clearInterval(id);
  }, []);

  if (error) return <section className="brief"><div className="empty"><p className="err">{error}</p></div></section>;
  if (!b) return <section className="brief"><div className="empty"><p>{t("common.loading")}</p></div></section>;

  const g = b.generation;
  async function copy() {
    try {
      const text = await api.briefText(p.patientId, b!.id);
      await navigator.clipboard.writeText(text);
      toast(t("brief.copied"));
    } catch {
      toast(t("brief.copyBlocked"));
    }
  }

  return (
    <section className="brief" aria-label={t("brief.aria")}>
      <div className="brief-head">
        <div>
          <h1>{p.name}</h1>
          <div className="sub num">{p.age} · {p.sex === "female" ? t("sex.f") : t("sex.m")} · {p.time} · {p.visit} · {t("brief.confirmed")}</div>
        </div>
        <div className="actions">
          <StatusPill status={b.reviewed ? "reviewed" : "ready"} fresh={fresh} />
          <button className="btn secondary sm" onClick={() => void copy()}>{t("brief.copy")}</button>
          <button className="btn sm" disabled={!!b.reviewed} onClick={async () => { await api.review(p.patientId, b.id); toast(t("brief.reviewedToast")); setTick((x) => x + 1); onChanged(); }}>
            {b.reviewed ? t("brief.reviewed") : t("brief.markReviewed")}
          </button>
        </div>
      </div>
      <div className="legend">
        <span><SourceMark source="clinic" /> {t("source.clinic")}</span>
        <span><SourceMark source="patient" /> {t("source.patient")}</span>
        <span><SourceMark source="registry" /> {t("source.registry")}</span>
        <span>{t("brief.legendHint")}</span>
      </div>

      <div className="sec"><h2>{t("brief.cc")}</h2>
        <div className="body">
          <div className="cc">{b.chiefComplaint.text}</div>
          <div className="actions">{b.chiefComplaint.citations.map((c) => <CitationChip key={c.reference} c={c} onOpen={onOpen} />)}</div>
          {b.patientWords.map((w, i) => (
            <blockquote key={i} className="quote" style={{ margin: 0 }}>
              <span className="small" style={{ display: "block" }}>{t("brief.patientWords")}</span>“{w}”
            </blockquote>
          ))}
        </div>
      </div>

      <div className="sec"><h2>{t("brief.answers")}</h2>
        <div className="body">
          <dl className="qa">{b.intakeAnswers.map((a) => <div key={a.label} style={{ display: "contents" }}><dt>{a.label}</dt><dd>{a.answer}</dd></div>)}</dl>
          {b.patientCorrection && <div className="quote"><b>{t("brief.correction")}</b> {b.patientCorrection}</div>}
        </div>
      </div>

      {b.followUp && (
        <div className="sec"><h2>{t("brief.since")}</h2>
          <div className="body">
            <TrendChart data={b.followUp} />
            {b.trends.map((f, i) => <Fact key={i} fact={f} onOpen={onOpen} />)}
          </div>
        </div>
      )}

      <div className="sec"><h2>{t("brief.meds")}</h2>
        <div className="body">
          <MedicationTable rows={b.medications} pid={p.patientId} onOpen={onOpen} onReconciled={() => setTick((x) => x + 1)} />
          <span className="small">{t("brief.medsNote")}</span>
        </div>
      </div>

      <div className="sec"><h2>{t("brief.history")}</h2>
        <div className="body">
          {b.relevantHistory.length ? b.relevantHistory.map((f, i) => <Fact key={i} fact={f} onOpen={onOpen} when={f.date ? fmtDate(f.date, lang) : null} />)
            : <span className="small">{t("brief.noHistory")}</span>}
        </div>
      </div>

      {(b.consistency.length > 0 || b.followUp) && (
        <div className="sec"><h2>{t("brief.consistency")}</h2>
          <div className="body">
            <span className="small">{t("brief.consistencyNote")}</span>
            {b.consistency.length ? b.consistency.map((f, i) => <Fact key={i} fact={f} onOpen={onOpen} />)
              : <span className="small">{t("brief.consistencyNone")}</span>}
          </div>
        </div>
      )}

      <div className="sec"><h2>{t("brief.lifestyle")}</h2>
        <div className="body">
          {b.lifestyle.length ? b.lifestyle.map((f, i) => (
            <Fact key={i} fact={f} onOpen={onOpen}
                  when={f.stale ? <span className="stale">{t("brief.staleAgo", { n: f.monthsAgo })}</span> : t("brief.updated", { date: fmtDate(f.updatedAt, lang) })} />
          )) : <span className="small">{t("brief.noLifestyle")}</span>}
        </div>
      </div>

      <div className="sec"><h2>{t("brief.open")}</h2>
        <div className="body"><ul className="ul">{b.openQuestions.map((q) => <li key={q}>{q}</li>)}</ul></div>
      </div>

      <div className="brief-foot">
        <div className="row"><Info size={16} aria-hidden style={{ flex: "none", marginTop: 2 }} /><span>{t("brief.footer")}</span></div>
        <div className="row small">
          <ShieldAlert size={16} aria-hidden style={{ flex: "none", marginTop: 2 }} />
          <span>
            {t("brief.transparency", { n: g.context_records, total: g.total_records, provider: g.provider === "mock" ? t("brief.rules") : g.provider, prompt: g.prompt_version, dropped: g.dropped_statements })}
            {g.degraded ? ` ${t("brief.degraded")}` : ""}
            {g.instruction_like_input ? ` ${t("brief.injection")}` : ""}
          </span>
        </div>
      </div>
    </section>
  );
}
