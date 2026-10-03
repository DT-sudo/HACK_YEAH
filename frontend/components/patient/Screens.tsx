"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Check, Phone } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { fmtWeekdayDate } from "@/lib/format";
import { usePatient } from "@/lib/patient-context";
import type { Summary } from "@/types/api";

export function SummaryView() {
  const { t } = useApp();
  const { me, intake, setIntake, setStep, refreshMe } = usePatient();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [truthful, setTruthful] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const [correction, setCorrection] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!intake) return;
    api.summary(intake.id).then(setSummary).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [intake?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function confirm() {
    if (!intake) return;
    setBusy(true);
    setError(null);
    try {
      setIntake(await api.confirm(intake.id, truthful, correction.trim() || null));
      setStep("chat");
      await refreshMe();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("common.error"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="p-body">
        <h1 className="p-title">{t("sum.title")}</h1>
        <p className="small">{t("sum.sub", { doctor: me?.upcoming?.doctor ?? "" })}</p>
        {!summary ? <p className="small">{error ?? t("common.loading")}</p> : (
          <>
            <div className="sumcard">
              <div className="quote">“{summary.patientWords}”</div>
              {summary.paragraphs.map((p, i) => <p key={i}>{p}</p>)}
              {correction.trim() && !correcting && <p><b>{t("sum.yourCorrection")}</b> {correction}</p>}
            </div>
            {correcting && (
              <div style={{ display: "grid", gap: 8 }}>
                <label className="small" htmlFor="corr">{t("sum.correctLabel")}</label>
                <textarea id="corr" value={correction} onChange={(e) => setCorrection(e.target.value)} placeholder={t("sum.correctPh")} autoFocus />
                <button className="btn secondary sm" style={{ justifySelf: "start" }} onClick={() => setCorrecting(false)}>{t("sum.saveCorrection")}</button>
              </div>
            )}
            <div className="group-title">{t("sum.bring")}</div>
            <ul className="ul">{summary.bring.map((b) => <li key={b}>{b}</li>)}</ul>
            <div className="group-title">{t("sum.questions")}</div>
            <ul className="ul">{summary.questions.map((b) => <li key={b}>{b}</li>)}</ul>
          </>
        )}
        {error && summary && <p className="err" role="alert">{error}</p>}
      </div>
      <div className="p-foot">
        <label className="check"><input type="checkbox" checked={truthful} onChange={(e) => setTruthful(e.target.checked)} /> {t("sum.truthful")}</label>
        <button className="btn" disabled={!truthful || busy || !summary} onClick={() => void confirm()}>{busy ? t("common.sending") : t("sum.confirm")}</button>
        {!correcting && <button className="btn secondary" onClick={() => setCorrecting(true)}>{t("sum.notRight")}</button>}
        <button className="linkbtn" style={{ justifySelf: "center" }} onClick={() => setStep("chat")}>{t("sum.backToChat")}</button>
      </div>
    </>
  );
}

export function SentView() {
  const { t, lang } = useApp();
  const { me } = usePatient();
  const appt = me?.upcoming;
  return (
    <>
      <div className="p-body">
        <div style={{ display: "grid", gap: 14, paddingTop: 24 }}>
          <div className="ok-icon"><Check size={28} aria-hidden /></div>
          <h1 className="p-title">{t("sent.title", { doctor: appt?.doctor ?? "" })}</h1>
          <p className="lead">{t("sent.lead", { when: appt ? fmtWeekdayDate(appt.start, lang) : "" })}</p>
          <p className="small">{t("sent.small")}</p>
        </div>
      </div>
      <div className="p-foot">
        <Link className="btn secondary" href="/doctor">{t("sent.doctorView")}</Link>
      </div>
    </>
  );
}

/** Calm, not alarming: neutral background, soft icon, one red element (the call button). */
export function EmergencyScreen() {
  const { t } = useApp();
  const { me } = usePatient();
  return (
    <>
      <div className="p-body">
        <div className="calm" role="alert">
          <div className="calm-icon" aria-hidden="true"><Phone size={24} /></div>
          <h2>{t("em.title")}</h2>
          <p>{t("em.body")}</p>
          <a className="btn call" href="tel:112">{t("em.call")}</a>
          <p className="small">{t("em.free")}</p>
        </div>
        <div className="group-title">{t("em.what")}</div>
        <ol className="ul">
          <li>{t("em.step1")}</li>
          <li>{t("em.step2")}</li>
          <li>{t("em.step3")}</li>
        </ol>
        <p className="small">{t("em.notSure", { clinic: me?.clinic ?? "" })}</p>
      </div>
      <div className="p-foot">
        <Link className="btn secondary" href="/doctor">{t("em.clinicView")}</Link>
      </div>
    </>
  );
}
