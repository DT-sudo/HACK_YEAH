"use client";

import Link from "next/link";
import { useApp } from "@/lib/app-context";
import { fmtDate, fmtWeekdayDate } from "@/lib/format";
import { usePatient } from "@/lib/patient-context";

export default function Appointments() {
  const { t, lang } = useApp();
  const { me, intake } = usePatient();
  if (!me) return <div className="p-body"><p className="small">{t("common.loading")}</p></div>;
  const a = me.upcoming;
  const prep = a?.preparation ?? "not_started";
  const pill = { urgent: ["urgent", t("appt.prep.urgent")], sent: ["ready", t("appt.prep.sent")],
                 in_progress: ["progress", t("appt.prep.progress")], not_started: ["none", t("appt.prep.none")] }[prep];
  const canChat = intake && ["STARTED", "COLLECTING", "COMPLETED"].includes(intake.state);
  return (
    <div className="p-body">
      <div className="group-title">{t("appt.upcoming")}</div>
      {a ? (
        <div className="apptcard">
          <div className="when-big num">{fmtWeekdayDate(a.start, lang)}</div>
          <div><b>{a.doctor}</b><div className="small">{a.service}</div></div>
          <div className="small">{a.clinic}<br />{a.address}</div>
          <div className="prep"><span className="small">{t("appt.prep")}</span><span className={`pill ${pill[0]}`}>{pill[1]}</span></div>
          {canChat && (
            <Link className="btn" href="/patient" style={{ fontSize: 15, padding: "11px 16px" }}>
              {prep === "in_progress" ? t("appt.continue") : t("appt.start")}
            </Link>
          )}
        </div>
      ) : <p className="small">{t("appt.none")}</p>}
      <div className="group-title">{t("appt.past")}</div>
      <div className="plist">
        {me.pastVisits.length ? me.pastVisits.map((v) => (
          <div className="pitem" key={v.date + v.reason}>
            <div><div className="v">{v.reason}</div><div className="k num">{fmtDate(v.date, lang)} · {v.doctor}</div></div>
          </div>
        )) : <div className="pitem"><span className="k">{t("appt.noPast")}</span></div>}
      </div>
      <p className="small">{t("appt.call")} <b className="num">{a?.phone ?? "+48 12 000 00 00"}</b>.</p>
    </div>
  );
}
