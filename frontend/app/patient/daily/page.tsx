"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Check, ClipboardCheck } from "lucide-react";
import { TrendChart } from "@/components/TrendChart";
import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { fmtDate } from "@/lib/format";
import { usePatient } from "@/lib/patient-context";
import { isRedFlag } from "@/lib/redflags";
import type { CheckinItem, CheckinState } from "@/types/api";

type Answers = Record<string, number | string | string[]>;

/** Daily check-in: a fixed, chat-style questionnaire (no AI). One per day; answers feed the doctor's trends. */
export default function DailyPage() {
  const { t, lang, epoch, users, ready } = useApp();
  const { setLocalEmergency } = usePatient();
  const router = useRouter();
  const [state, setState] = useState<CheckinState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState(-1); // -1 = not started
  const [answers, setAnswers] = useState<Answers>({});
  const [multi, setMulti] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!ready) return; // wait for the demo login, otherwise the first request has no token
    let cancelled = false;
    api.checkins(lang).then((s) => !cancelled && setState(s)).catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => { cancelled = true; };
  }, [ready, lang, epoch, users.patient?.id]);

  if (!state) return <div className="p-body"><p className={error ? "err" : "small"}>{error ?? t("common.loading")}</p></div>;
  if (!state.enabled || !state.questionnaire)
    return <div className="p-body"><h1 className="p-title">{t("daily.title")}</h1><p className="small">{t("daily.notEnabled")}</p></div>;

  const items = state.questionnaire.items;
  const q: CheckinItem | undefined = items[step];
  const labelOf = (it: CheckinItem, v: number | string | string[]) =>
    Array.isArray(v) ? v.map((x) => it.options.find((o) => o.value === x)?.label ?? x).join(", ")
      : it.type === "scale" ? `${v}/10` : it.options.find((o) => o.value === v)?.label ?? String(v);

  function answer(v: number | string | string[]) {
    if (!q) return;
    setAnswers((a) => ({ ...a, [q.id]: v }));
    setMulti([]);
    setStep((s) => s + 1);
  }

  async function save() {
    setBusy(true);
    setError(null);
    const all: Answers = { ...answers, ...(note.trim() ? { note: note.trim() } : {}) };
    if (note.trim() && isRedFlag(note)) setLocalEmergency(true); // instant, before the API answers
    try {
      const s = await api.submitCheckin(all, lang);
      setState(s);
      setStep(-1);
      setAnswers({});
      setNote("");
      if (s.emergency) {
        setLocalEmergency(true);
        router.push("/patient");
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("common.error"));
    } finally {
      setBusy(false);
    }
  }

  const done = step >= items.length;
  return (
    <>
      <div className="p-body">
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <ClipboardCheck size={22} aria-hidden style={{ color: "var(--clinic)" }} />
          <h1 className="p-title" style={{ fontSize: 21 }}>{state.questionnaire.title}</h1>
        </div>
        <p className="small">{state.questionnaire.intro}</p>

        {step === -1 && state.todayDone && (
          <div className="chk-done"><b><Check size={16} aria-hidden style={{ verticalAlign: "-3px" }} /> {t("daily.doneToday")}</b>
            <span className="small">{t("daily.doneNote")}</span></div>
        )}

        {step >= 0 && (
          <div className="msgs" aria-live="polite">
            {items.slice(0, Math.min(step + 1, items.length)).map((it, i) => (
              <div key={it.id} style={{ display: "contents" }}>
                <div className="msg ai">{it.text}</div>
                {i < step && answers[it.id] !== undefined && <div className="msg me">{labelOf(it, answers[it.id])}</div>}
                {i < step && answers[it.id] === undefined && it.optional && <div className="msg me" style={{ opacity: .7 }}>{t("daily.skipped")}</div>}
              </div>
            ))}
          </div>
        )}

        {q && q.type === "single" && (
          <div className="chips">{q.options.map((o) => <button key={o.value} className="chip" onClick={() => answer(o.value)}>{o.label}</button>)}</div>
        )}
        {q && q.type === "multi" && (
          <>
            <div className="chips" role="group" aria-label={t("chat.multi")}>
              {q.options.map((o) => (
                <button key={o.value} className="chip" aria-pressed={multi.includes(o.value)}
                        onClick={() => setMulti((m) => o.exclusive ? (m.includes(o.value) ? [] : [o.value])
                          : m.includes(o.value) ? m.filter((x) => x !== o.value)
                            : [...m.filter((x) => !q.options.find((oo) => oo.value === x)?.exclusive), o.value])}>
                  {o.label}
                </button>
              ))}
            </div>
            <button className="btn secondary sm" style={{ alignSelf: "flex-start" }} disabled={!multi.length} onClick={() => answer(multi)}>{t("chat.done")}</button>
          </>
        )}
        {q && q.type === "scale" && (
          <div style={{ display: "grid", gap: 4 }}>
            <div className="scale">{Array.from({ length: 11 }, (_, i) => (
              <button key={i} onClick={() => answer(i)} aria-label={t("chat.scale.aria", { n: i })}>{i}</button>))}</div>
            <div className="scale-labels"><span>{q.low}</span><span>{q.high}</span></div>
          </div>
        )}
        {q && q.type === "free" && (
          <div style={{ display: "grid", gap: 8 }}>
            <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("daily.notePh")} aria-label={q.text} />
          </div>
        )}
        {error && <p className="err" role="alert">{error}</p>}

        {step === -1 && state.followUp && state.followUp.series.some((s) => s.ref) && (
          <>
            <div className="group-title">{t("daily.yourWeeks")}</div>
            <p className="small">{t("daily.yourWeeksNote", { date: fmtDate(state.followUp.since, lang) })}</p>
            <TrendChart data={state.followUp} compact />
          </>
        )}
      </div>
      <div className="p-foot">
        <span className="small">{t("common.not112")}</span>
        {step === -1 ? (
          <button className="btn" onClick={() => setStep(0)}>{state.todayDone ? t("daily.update") : t("daily.start")}</button>
        ) : q?.type === "free" || done ? (
          <button className="btn" disabled={busy} onClick={() => void save()}>{busy ? t("common.sending") : t("daily.save")}</button>
        ) : (
          <button className="linkbtn" style={{ justifySelf: "center" }} onClick={() => { setStep(-1); setAnswers({}); }}>{t("common.cancel")}</button>
        )}
      </div>
    </>
  );
}
