"use client";

import { useCallback, useEffect, useState } from "react";
import { Watch } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { fmtDate } from "@/lib/format";
import { usePatient } from "@/lib/patient-context";
import type { LifestyleItem, MedicationItem, Profile } from "@/types/api";

type Pending = { kind: "life"; key: string; label: string } | { kind: "med"; id: string; name: string };

export default function ProfilePage() {
  const { t, lang, toast, epoch } = useApp();
  const { me } = usePatient();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [adding, setAdding] = useState(false);
  const [wiping, setWiping] = useState(false);
  const [documented, setDocumented] = useState<Pending | null>(null); // 409: part of the medical record
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.profile().then(setProfile).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [epoch, me?.id]);

  const run = useCallback(async (fn: () => Promise<Profile>, ok: string, pending?: Pending) => {
    setError(null);
    try {
      setProfile(await fn());
      setEditing(null);
      setDocumented(null);
      toast(ok);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && pending) setDocumented(pending);
      else setError(e instanceof Error ? e.message : String(e));
    }
  }, [toast]);

  if (!me || !profile) return <div className="p-body"><p className={error ? "err" : "small"}>{error ?? t("common.loading")}</p></div>;

  const label = (l: LifestyleItem) => (lang === "pl" ? l.labelPl : l.label);
  const wear = profile.wearable;
  const current = profile.medications.filter((m) => m.current);
  const past = profile.medications.filter((m) => !m.current);

  return (
    <div className="p-body">
      <div className="prof-id">
        <div className="avatar" aria-hidden="true">{me.initials}</div>
        <div>
          <h1 className="p-title" style={{ fontSize: 21 }}>{me.name}</h1>
          <div className="small num">{t("prof.born", { date: fmtDate(me.birthDate, lang), clinic: me.clinic })}</div>
        </div>
      </div>
      <p className="small">{t("prof.note", { doctor: me.upcoming?.doctor ?? "" })}</p>

      {documented && (
        <div className="notice" role="status">
          <b>{t("prof.doc.title")}</b>
          <span>{t("prof.doc.body")}</span>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="btn sm" onClick={() => void (documented.kind === "med"
              ? run(() => api.stopMedication(documented.id), t("prof.toast.stopped", { name: documented.name }))
              : run(() => api.markLifestyleNotCurrent(documented.key), t("prof.toast.notCurrent", { name: documented.label })))}>
              {documented.kind === "med" ? t("prof.doc.stop") : t("prof.doc.notCurrent")}
            </button>
            <button className="btn secondary sm" onClick={() => setDocumented(null)}>{t("common.cancel")}</button>
          </div>
        </div>
      )}

      <div className="group-title">{t("prof.lifestyle")}</div>
      <div className="plist">
        {profile.lifestyle.map((l) => editing === l.key ? (
          <div className="pitem editing" key={l.key}>
            <form style={{ display: "grid", gap: 8, width: "100%" }}
                  onSubmit={(e) => { e.preventDefault(); void run(() => api.putLifestyle(l.key, value), value.trim() ? t("prof.toast.saved", { name: label(l).toLowerCase() }) : t("prof.toast.deleted", { name: label(l).toLowerCase() }), { kind: "life", key: l.key, label: label(l) }); }}>
              <label className="k" htmlFor={`life-${l.key}`}>{label(l)}</label>
              <input id={`life-${l.key}`} value={value} onChange={(e) => setValue(e.target.value)} placeholder={l.hint} autoFocus />
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button className="btn sm" type="submit">{t("common.save")}</button>
                <button className="btn secondary sm" type="button" onClick={() => setEditing(null)}>{t("common.cancel")}</button>
                {l.value && (
                  <button className="linkbtn danger" type="button" style={{ marginLeft: "auto" }}
                          onClick={() => void run(() => api.deleteLifestyle(l.key), t("prof.toast.deleted", { name: label(l).toLowerCase() }), { kind: "life", key: l.key, label: label(l) })}>
                    {t("prof.deleteEntry")}
                  </button>
                )}
              </div>
            </form>
          </div>
        ) : (
          <div className="pitem" key={l.key}>
            <div style={{ minWidth: 0 }}>
              <div className="k">{label(l)}{l.optional && <span className="opt">{t("prof.optional")}</span>}</div>
              <div className="v">{l.value || <span className="k">{t("prof.notProvided")}</span>}</div>
              {l.key === "activity" && wear && (
                <div className="wear"><Watch size={14} aria-hidden /> {t("prof.wearable")} · {wear.metrics.map((m) => `${m.label.split(" (")[0]} ${m.value} ${m.unit}`).join(" · ")}</div>
              )}
              {l.value && l.updatedAt && <div className="meta num">{t("prof.updated", { date: fmtDate(l.updatedAt, lang) })}</div>}
            </div>
            <button className="linkbtn" onClick={() => { setEditing(l.key); setValue(l.value); setDocumented(null); }}
                    aria-label={`${l.value ? t("common.edit") : t("common.add")} ${label(l)}`}>
              {l.value ? t("common.edit") : t("common.add")}
            </button>
          </div>
        ))}
      </div>

      <div className="group-title">{t("prof.meds")} <span className="small">{t("prof.meds.count", { n: current.length })}</span></div>
      <p className="small">{t("prof.meds.note")}</p>
      <div className="plist">
        {current.length ? current.map((m) => <MedRow key={m.id} m={m} onRemove={() =>
          void run(() => api.deleteMedication(m.id), t("prof.toast.removed", { name: m.name }), { kind: "med", id: m.id, name: m.name })} />)
          : <div className="pitem"><span className="k">{t("prof.meds.none")}</span></div>}
      </div>
      {past.length > 0 && (
        <details>
          <summary>{t("prof.meds.past", { n: past.length })}</summary>
          <div className="plist" style={{ marginTop: 8 }}>{past.map((m) => <MedRow key={m.id} m={m} />)}</div>
        </details>
      )}
      {adding ? <AddMedication onCancel={() => setAdding(false)} onSubmit={(m) => { void run(() => api.addMedication(m), t("prof.toast.added", { name: m.name })); setAdding(false); }} />
        : <button className="btn secondary sm" style={{ alignSelf: "flex-start" }} onClick={() => setAdding(true)}>{t("prof.meds.add")}</button>}

      <div className="group-title">{t("prof.data")}</div>
      <p className="small">{t("prof.data.note")}</p>
      {wiping ? (
        <div className="wipe">
          <b>{t("prof.wipe.title")}</b>
          <span className="small">{t("prof.wipe.body")}</span>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="btn danger sm" onClick={() => { void run(() => api.wipeProfile(), t("prof.toast.wiped")); setWiping(false); }}>{t("prof.wipe.confirm")}</button>
            <button className="btn secondary sm" onClick={() => setWiping(false)}>{t("prof.wipe.keep")}</button>
          </div>
        </div>
      ) : <button className="linkbtn danger" style={{ alignSelf: "flex-start" }} onClick={() => setWiping(true)}>{t("prof.wipe.link")}</button>}
      {error && <p className="err" role="alert">{error}</p>}
    </div>
  );
}

function MedRow({ m, onRemove }: { m: MedicationItem; onRemove?: () => void }) {
  const { t, lang } = useApp();
  const detail = [[m.dose, m.frequency].filter(Boolean).join(", "), m.prescriber, m.note].filter(Boolean).join(" · ");
  return (
    <div className="pitem">
      <div style={{ minWidth: 0 }}>
        <div className="v">{m.name}</div>
        <div className="k">{detail || t("prof.meds.noDose")}</div>
        {!m.current && m.end && <div className="meta">{t("prof.meds.stopped", { date: fmtDate(m.end, lang) })}</div>}
      </div>
      {onRemove && <button className="linkbtn danger" onClick={onRemove} aria-label={`${t("common.remove")} ${m.name}`}>{t("common.remove")}</button>}
    </div>
  );
}

function AddMedication({ onSubmit, onCancel }: {
  onSubmit: (m: { name: string; dose: string; frequency: string; start: string | null; prescriber: string | null }) => void;
  onCancel: () => void;
}) {
  const { t } = useApp();
  const [f, setF] = useState({ name: "", dose: "", frequency: "", start: "", prescriber: "" });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="addform" onSubmit={(e) => { e.preventDefault(); if (f.name.trim()) onSubmit({ name: f.name.trim(), dose: f.dose, frequency: f.frequency, start: f.start || null, prescriber: f.prescriber || null }); }}>
      <label className="small" htmlFor="m-name">{t("prof.add.name")}</label>
      <input className="field" id="m-name" required value={f.name} onChange={set("name")} placeholder={t("prof.add.namePh")} autoFocus />
      <div className="row">
        <div><label className="small" htmlFor="m-dose">{t("prof.add.dose")}</label><input className="field" id="m-dose" value={f.dose} onChange={set("dose")} placeholder="250 mg" /></div>
        <div><label className="small" htmlFor="m-freq">{t("prof.add.freq")}</label><input className="field" id="m-freq" value={f.frequency} onChange={set("frequency")} placeholder={t("prof.add.freqPh")} /></div>
      </div>
      <div className="row">
        <div><label className="small" htmlFor="m-start">{t("prof.add.start")}</label><input className="field" id="m-start" type="month" value={f.start} onChange={set("start")} /></div>
        <div><label className="small" htmlFor="m-who">{t("prof.add.who")}</label><input className="field" id="m-who" value={f.prescriber} onChange={set("prescriber")} placeholder={t("prof.optional")} /></div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn sm" type="submit">{t("prof.add.submit")}</button>
        <button className="btn secondary sm" type="button" onClick={onCancel}>{t("common.cancel")}</button>
      </div>
    </form>
  );
}
