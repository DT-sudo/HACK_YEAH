"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import type { AuditEntry, LlmCall } from "@/types/api";

/** Transparency view for the demo: audit trail (references only) and LLM gateway metadata (no content). */
export default function AuditPage() {
  const { t, ready, epoch } = useApp();
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [calls, setCalls] = useState<LlmCall[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    Promise.all([api.audit(), api.llmCalls()]).then(([a, c]) => { setAudit(a); setCalls(c); })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [ready, epoch]);

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", display: "grid", gap: 20 }}>
      <Link className="linkbtn" href="/doctor">← {t("audit.back")}</Link>
      {error && <p className="err">{error}</p>}
      <section className="panel">
        <h2 style={{ fontSize: 18 }}>{t("audit.llm")}</h2>
        <p className="small">{t("audit.llmNote")}</p>
        <div className="table-wrap">
          <table className="log">
            <thead><tr><th>{t("audit.time")}</th><th>{t("audit.task")}</th><th>{t("audit.provider")}</th><th>{t("audit.prompt")}</th><th>{t("audit.latency")}</th><th>{t("audit.tokens")}</th><th>{t("audit.validation")}</th></tr></thead>
            <tbody>
              {calls.map((c, i) => (
                <tr key={i}><td className="num">{c.timestamp.slice(11, 19)}</td><td className="mono">{c.task}</td><td>{c.provider}</td><td className="mono">{c.promptVersion}</td>
                  <td className="num">{c.latencyMs} ms</td><td className="num">{c.inputTokens ?? "–"} / {c.outputTokens ?? "–"}</td><td>{c.validation}</td></tr>
              ))}
              {!calls.length && <tr><td colSpan={7} className="small">{t("audit.empty")}</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel">
        <h2 style={{ fontSize: 18 }}>{t("audit.title")}</h2>
        <p className="small">{t("audit.note")}</p>
        <div className="table-wrap">
          <table className="log">
            <thead><tr><th>{t("audit.time")}</th><th>{t("audit.who")}</th><th>{t("audit.action")}</th><th>{t("audit.patient")}</th><th>{t("audit.resource")}</th><th>{t("audit.reason")}</th></tr></thead>
            <tbody>
              {audit.map((a, i) => (
                <tr key={i}><td className="num">{a.timestamp.slice(11, 19)}</td><td>{a.who} <span className="small">({a.role})</span></td><td className="mono">{a.action}</td>
                  <td className="mono">{a.patientId ?? "–"}</td><td className="mono">{a.resource ?? "–"}</td><td>{a.reason ?? ""}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
