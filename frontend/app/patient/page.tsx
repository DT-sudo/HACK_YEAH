"use client";

import { Chat } from "@/components/patient/Chat";
import { EmergencyScreen, SentView, SummaryView } from "@/components/patient/Screens";
import { useApp } from "@/lib/app-context";
import { usePatient } from "@/lib/patient-context";

/** Home = the intake chat. No landing page: the first AI question is already on screen. */
export default function PatientHome() {
  const { t } = useApp();
  const { intake, step, localEmergency, error } = usePatient();
  if (localEmergency || intake?.state === "EMERGENCY") return <EmergencyScreen />;
  if (!intake) return <div className="p-body"><p className={error ? "err" : "small"}>{error ?? t("common.loading")}</p></div>;
  if (intake.state === "SUBMITTED" || intake.state === "CONFIRMED_BY_PATIENT") return <SentView />;
  if (intake.state === "COMPLETED" && step === "summary") return <SummaryView />;
  return <Chat />;
}
