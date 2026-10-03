"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CalendarDays, House, User } from "lucide-react";
import { useApp } from "@/lib/app-context";
import { PatientProvider, usePatient } from "@/lib/patient-context";

function PhoneFrame({ children }: { children: React.ReactNode }) {
  const { t } = useApp();
  const { me, intake, step, localEmergency } = usePatient();
  const path = usePathname();
  const tab = path.startsWith("/patient/profile") ? "profile" : path.startsWith("/patient/appointments") ? "appts" : "home";
  const emergency = localEmergency || intake?.state === "EMERGENCY";
  const inChat = intake && ["STARTED", "COLLECTING", "COMPLETED"].includes(intake.state) && step === "chat";
  const title = tab === "profile" ? t("p.title.profile") : tab === "appts" ? t("p.title.appts") : inChat ? t("p.title.chat") : t("p.title.visit");
  const progress = emergency || intake?.state === "SUBMITTED" ? 1 : step === "summary" ? 0.9 : intake?.progress ?? 0.05;

  return (
    <section className="phone" aria-label={t("p.aria")}>
      <div className="p-head">
        <div style={{ flex: 1, minWidth: 0 }}>
          <span className="clinic">{me?.clinic ?? "…"}</span>
          <strong>{title}</strong>
        </div>
        {tab !== "profile" && me && (
          <Link className="avatar-btn" href="/patient/profile" aria-label={t("p.openProfile")}>{me.initials}</Link>
        )}
      </div>
      {tab === "home" && <div className="p-progress" aria-hidden="true"><span style={{ width: `${Math.round(progress * 100)}%` }} /></div>}
      {children}
      {!(emergency && tab === "home") && (
        <nav className="ptabs" aria-label={t("p.sections")}>
          <Link href="/patient" aria-current={tab === "home" ? "page" : undefined}><House size={22} aria-hidden /><span>{t("p.tab.home")}</span></Link>
          <Link href="/patient/appointments" aria-current={tab === "appts" ? "page" : undefined}><CalendarDays size={22} aria-hidden /><span>{t("p.tab.appts")}</span></Link>
          <Link href="/patient/profile" aria-current={tab === "profile" ? "page" : undefined}><User size={22} aria-hidden /><span>{t("p.tab.profile")}</span></Link>
        </nav>
      )}
    </section>
  );
}

function SideNotes() {
  const { t } = useApp();
  return (
    <aside className="side-notes">
      <h3>{t("notes.title")}</h3>
      <ol>
        <li>{t("notes.1")}</li>
        <li>{t("notes.2")}</li>
        <li>{t("notes.3")}</li>
        <li>{t("notes.4")}</li>
        <li>{t("notes.5")}</li>
      </ol>
      <p>{t("notes.tail")}</p>
    </aside>
  );
}

export default function PatientLayout({ children }: { children: React.ReactNode }) {
  return (
    <PatientProvider>
      <div className="patient-wrap">
        <PhoneFrame>{children}</PhoneFrame>
        <SideNotes />
      </div>
    </PatientProvider>
  );
}
