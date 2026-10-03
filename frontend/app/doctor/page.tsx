"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { BriefView } from "@/components/doctor/BriefView";
import { SourceDrawer } from "@/components/doctor/SourceDrawer";
import { TrendChart } from "@/components/TrendChart";
import { Fact, StatusPill } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { fmtLongDay, fmtTime } from "@/lib/format";
import type { Day, DayPatient } from "@/types/api";
import type { Fact as FactT, FollowUp } from "@/types/brief";

function BreakGlass({ onGranted }: { onGranted: (p: DayPatient) => void }) {
  const { t, toast } = useApp();
  const [open, setOpen] = useState(false);
  const [pid, setPid] = useState("jan-k");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  if (!open) return <button className="linkbtn" style={{ justifySelf: "start" }} onClick={() => setOpen(true)}>{t("bg.open")}</button>;
  return (
    <form style={{ display: "grid", gap: 6 }} onSubmit={async (e) => {
      e.preventDefault();
      setError(null);
      try {
        const p = await api.breakGlass(pid.trim(), reason.trim());
        toast(t("bg.granted"));
        setOpen(false);
        setReason("");
        onGranted(p);
      } catch (err) {
        setError(err instanceof ApiError ? (err.status === 422 ? t("bg.reasonShort") : err.message) : String(err));
      }
    }}>
      <b style={{ fontSize: 14 }}>{t("bg.title")}</b>
      <span className="small">{t("bg.note")}</span>
      <label className="small" htmlFor="bg-pid">{t("bg.pid")}</label>
      <input id="bg-pid" className="field" value={pid} onChange={(e) => setPid(e.target.value)} />
      <label className="small" htmlFor="bg-reason">{t("bg.reason")}</label>
      <textarea id="bg-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("bg.reasonPh")} style={{ minHeight: 60 }} />
      {error && <span className="err">{error}</span>}
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn danger sm" type="submit">{t("bg.submit")}</button>
        <button className="btn secondary sm" type="button" onClick={() => setOpen(false)}>{t("common.cancel")}</button>
      </div>
    </form>
  );
}

function UrgentView({ p, onChanged }: { p: DayPatient; onChanged: () => void }) {
  const { t, lang, toast } = useApp();
  const u = p.urgent!;
  return (
    <section className="brief" aria-label={t("urgent.aria")}>
      <div className="brief-head">
        <div><h1>{p.name}</h1><div className="sub num">{p.age} · {p.sex === "female" ? t("sex.f") : t("sex.m")} · {p.time}</div></div>
        <StatusPill status="urgent" />
      </div>
      <div className="urgent-card">
        <h2>{t("urgent.title")}</h2>
        <p>{u.trigger}</p>
        <p className="small num">{t("urgent.when", { time: fmtTime(u.at, lang) })}</p>
        <p className="small">{t("urgent.rules")}</p>
        {u.contactedAt ? (
          <p className="pill reviewed" style={{ justifySelf: "start" }}>{t("urgent.contacted", { by: u.contactedBy ?? "", time: fmtTime(u.contactedAt, lang) })}</p>
        ) : (
          <div className="actions">
            <button className="btn danger sm" onClick={async () => { await api.contacted(p.patientId); toast(t("urgent.contactedToast")); onChanged(); }}>
              {t("urgent.markContacted")}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

function EmptyView({ p, onOpen }: { p: DayPatient; onOpen: (ref: string) => void }) {
  const { t, epoch } = useApp();
  const [tr, setTr] = useState<{ followUp: FollowUp | null; trends: FactT[] } | null>(null);
  useEffect(() => {
    if (!p.checkinDays) return;
    let cancelled = false;
    api.trends(p.patientId).then((x) => !cancelled && setTr(x)).catch(() => {});
    return () => { cancelled = true; };
  }, [p.patientId, p.checkinDays, epoch]);
  return (
    <section className="brief" aria-label={t("brief.aria")}>
      <div className="brief-head">
        <div><h1>{p.name}</h1><div className="sub num">{p.age} · {p.sex === "female" ? t("sex.f") : t("sex.m")} · {p.time} · {p.visit}</div></div>
        <StatusPill status={p.status} />
      </div>
      <div className="empty">
        <h2>{p.status === "progress" ? t("empty.progress") : t("empty.none")}</h2>
        <p>{t("empty.body")} {p.status === "none" ? t("empty.reminder") : ""}</p>
      </div>
      {tr?.followUp && (
        <div className="sec"><h2>{t("brief.since")}</h2>
          <div className="body">
            <span className="small">{t("empty.trendsNote")}</span>
            <TrendChart data={tr.followUp} />
            {tr.trends.map((f, i) => <Fact key={i} fact={f} onOpen={onOpen} />)}
          </div>
        </div>
      )}
    </section>
  );
}

function Dashboard() {
  const { t, lang, ready, epoch, users } = useApp();
  const router = useRouter();
  const search = useSearchParams();
  const [day, setDay] = useState<Day | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<string | null>(null);
  const selected = search.get("p");

  const load = useCallback(async () => {
    try {
      setDay(await api.day());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (!ready) return;
    const first = setTimeout(load, 0);
    const id = setInterval(load, 4000); // picks up patient confirmations and safety-net flags live
    return () => { clearTimeout(first); clearInterval(id); };
  }, [ready, epoch, users.doctor?.id, load]);

  const patients = day?.patients ?? [];
  const p = patients.find((x) => x.patientId === selected) ?? patients.find((x) => x.status === "urgent") ?? patients[0];
  const select = (pid: string) => router.replace(`/doctor?p=${pid}`, { scroll: false });
  const fresh = (x: DayPatient) => x.status === "ready" && x.briefFresh;

  if (!day) return <p className={error ? "err" : "small"} style={{ textAlign: "center" }}>{error ?? t("common.loading")}</p>;

  return (
    <div className="desk">
      <nav className="day" aria-label={t("day.aria")}>
        <div className="day-head">
          <h2>{fmtLongDay(day.date, lang)}</h2>
          <span className="small">{t("day.sub", { doctor: day.doctor, n: patients.length })}</span>
        </div>
        <ul className="appts">
          {patients.map((x) => (
            <li key={x.patientId}>
              <button onClick={() => select(x.patientId)} aria-current={x.patientId === p?.patientId} className={x.status === "urgent" ? "urgent" : ""}>
                <span className="t">{x.time}</span>
                <span className="n">{x.name}</span>
                <span className="s"><StatusPill status={x.status} fresh={fresh(x)} />{x.breakGlass && <span className="pill bg">{t("bg.pill")}</span>}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="day-foot">
          <BreakGlass onGranted={(g) => { void load().then(() => select(g.patientId)); }} />
          <Link className="linkbtn" href="/doctor/audit" style={{ justifySelf: "start" }}>{t("day.audit")}</Link>
        </div>
      </nav>
      {p && (p.status === "urgent" && p.urgent ? <UrgentView p={p} onChanged={load} />
        : p.briefId ? <BriefView p={p} onOpen={setDrawer} onChanged={load} fresh={fresh(p)} />
          : <EmptyView p={p} onOpen={setDrawer} />)}
      {drawer && p && <SourceDrawer pid={p.patientId} reference={drawer} onClose={() => setDrawer(null)} />}
    </div>
  );
}

export default function DoctorPage() {
  return <Suspense><Dashboard /></Suspense>;
}
