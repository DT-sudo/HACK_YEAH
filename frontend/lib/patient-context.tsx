"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import type { Intake, Me } from "@/types/api";

type PatientCtx = {
  me: Me | null;
  intake: Intake | null;
  setIntake: (i: Intake) => void;
  refreshMe: () => Promise<void>;
  step: "chat" | "summary";
  setStep: (s: "chat" | "summary") => void;
  localEmergency: boolean;
  setLocalEmergency: (b: boolean) => void;
  error: string | null;
};

const Ctx = createContext<PatientCtx | null>(null);

/** Chat state lives here (in the patient layout), so switching tabs keeps it. */
export function PatientProvider({ children }: { children: React.ReactNode }) {
  const { ready, epoch, lang, users } = useApp();
  const [me, setMe] = useState<Me | null>(null);
  const [intake, setIntake] = useState<Intake | null>(null);
  const [step, setStep] = useState<"chat" | "summary">("chat");
  const [localEmergency, setLocalEmergency] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const userId = users.patient?.id;

  const refreshMe = useCallback(async () => {
    try {
      setMe(await api.me());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (!ready || !userId) return;
    let cancelled = false;
    // Reset per-user view state when the demo user changes or the demo is reset.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStep("chat");
    setLocalEmergency(false);
    Promise.all([api.me(), api.startIntake(lang)])
      .then(([m, i]) => { if (!cancelled) { setMe(m); setIntake(i); setError(null); } })
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => { cancelled = true; };
    // lang is handled below without resetting the step
  }, [ready, epoch, userId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    // Language switch: the backend resumes the same session and asks next questions in the new language.
    if (!ready || !intake || intake.lang === lang || !["STARTED", "COLLECTING"].includes(intake.state)) return;
    api.startIntake(lang).then(setIntake).catch(() => {});
  }, [lang]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Ctx.Provider value={{ me, intake, setIntake, refreshMe, step, setStep, localEmergency, setLocalEmergency, error }}>
      {children}
    </Ctx.Provider>
  );
}

export function usePatient(): PatientCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("usePatient outside PatientProvider");
  return c;
}
