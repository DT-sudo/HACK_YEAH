"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Bot, Info, Mic } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { fmtWeekdayDate } from "@/lib/format";
import { usePatient } from "@/lib/patient-context";
import { isRedFlag } from "@/lib/redflags";
import { useSpeech } from "@/lib/use-speech";
import type { Question } from "@/types/api";

function AiDisclosure() {
  const { t, lang } = useApp();
  const { me } = usePatient();
  const appt = me?.upcoming;
  return (
    <div className="disclose">
      <div className="disclose-row">
        <Bot size={18} aria-hidden />
        <div>
          <b>{t("chat.disclose.title")}</b>{" "}
          {t("chat.disclose.body", { doctor: appt?.doctor ?? "", when: appt ? fmtWeekdayDate(appt.start, lang) : "" })}
        </div>
      </div>
      <details className="honest">
        <summary>{t("chat.honest.title")}</summary>
        <p>{t("chat.honest.body")}</p>
        <p>{t("chat.gdpr", { clinic: me?.clinic ?? "" })}</p>
      </details>
    </div>
  );
}

function Controls({ q, disabled, onAnswer, suggestion }: {
  q: Question; disabled: boolean; onAnswer: (v: string, mode: "choice") => void; suggestion: string | null;
}) {
  const { t } = useApp();
  const [multi, setMulti] = useState<string[]>([]);
  if (disabled) return null;
  const isNone = (o: string) => /^(none of these|nic z tych rzeczy|nothing in particular|nic szczególnego)$/i.test(o);

  if (q.answer_type === "single")
    return <div className="chips">{q.options.map((o) => <button key={o} className="chip" onClick={() => onAnswer(o, "choice")}>{o}</button>)}</div>;
  if (q.answer_type === "multi")
    return (
      <>
        <div className="chips" role="group" aria-label={t("chat.multi")}>
          {q.options.map((o) => (
            <button key={o} className="chip" aria-pressed={multi.includes(o)}
                    onClick={() => setMulti((m) => isNone(o) ? (m.includes(o) ? [] : [o])
                      : m.includes(o) ? m.filter((x) => x !== o) : [...m.filter((x) => !isNone(x)), o])}>
              {o}
            </button>
          ))}
        </div>
        <button className="btn secondary sm" style={{ justifySelf: "start", alignSelf: "flex-start" }} disabled={!multi.length}
                onClick={() => onAnswer(multi.join(", "), "choice")}>
          {t("chat.done")}
        </button>
      </>
    );
  if (q.answer_type === "scale")
    return (
      <div style={{ display: "grid", gap: 4 }}>
        <div className="scale">
          {Array.from({ length: 11 }, (_, i) => (
            <button key={i} onClick={() => onAnswer(String(i), "choice")} aria-label={t("chat.scale.aria", { n: i })}>{i}</button>
          ))}
        </div>
        <div className="scale-labels"><span>{t("chat.scale.low")}</span><span>{t("chat.scale.high")}</span></div>
      </div>
    );
  if (q.slot === "complaint" && suggestion)
    return (
      <div style={{ display: "grid", gap: 6 }}>
        <span className="small">{t("chat.demoSuggestion")}</span>
        <div className="chips"><button className="chip suggest" onClick={() => onAnswer(suggestion, "choice")}>{suggestion}</button></div>
      </div>
    );
  return null;
}

export function Chat() {
  const { t, lang } = useApp();
  const { me, intake, setIntake, setStep, setLocalEmergency } = usePatient();
  const [draft, setDraft] = useState("");
  const [fromVoice, setFromVoice] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const onFinal = useCallback((text: string) => {
    setDraft(text);
    setFromVoice(true);
    setTimeout(() => inputRef.current?.focus(), 0);
  }, []);
  const speech = useSpeech(lang, onFinal);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [intake?.messages.length, pending]);

  if (!intake) return <div className="p-body"><p className="small">{t("common.loading")}</p></div>;
  const q = intake.question;
  const done = intake.state === "COMPLETED";

  async function send(text: string, mode: "text" | "voice" | "choice") {
    if (!intake || !text.trim() || pending) return;
    setError(null);
    // Deterministic safety net runs here too, so the emergency screen appears instantly.
    if (isRedFlag(text, q?.text ?? "")) setLocalEmergency(true);
    setPending(text);
    setDraft("");
    setFromVoice(false);
    try {
      setIntake(await api.sendMessage(intake.id, text, mode));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("common.error"));
      if (mode !== "choice") setDraft(text);
    } finally {
      setPending(null);
    }
  }

  const voiceHint = speech.error === "unsupported" ? t("voice.unsupported") : speech.error === "denied" ? t("voice.denied")
    : speech.error === "failed" ? t("voice.failed") : null;

  return (
    <>
      <div className="p-body" ref={bodyRef}>
        <AiDisclosure />
        <div className="ai-label"><Bot size={14} aria-hidden /> {t("chat.aiLabel")}</div>
        <div className="msgs" aria-live="polite">
          {intake.messages.map((m, i) => (
            <div key={i} className={`msg ${m.from}`}>
              {m.mode === "voice" && <span className="vtag"><Mic size={13} aria-hidden /> {t("chat.voiceTag")}</span>}
              {m.text}
            </div>
          ))}
          {pending && <div className="msg me" style={{ opacity: .7 }}>{pending}</div>}
          {pending && <div className="msg ai typing">{t("chat.typing")}</div>}
        </div>
        {q && !done && !speech.listening && (
          <Controls key={q.slot} q={q} disabled={!!pending} onAnswer={(v, m) => void send(v, m)} suggestion={me?.demoSuggestion ?? null} />
        )}
        {intake.degraded && <p className="banner">{t("chat.degraded")}</p>}
        {error && <p className="err" role="alert">{error}</p>}
      </div>
      <div className="p-foot">
        <span className="small"><Info size={12} aria-hidden style={{ verticalAlign: "-1px" }} /> {t("common.not112")}</span>
        {done ? (
          <button className="btn" onClick={() => setStep("summary")}>{t("chat.review")}</button>
        ) : speech.listening ? (
          <div className="listening" role="status">
            <div className="bars" aria-hidden="true">{Array.from({ length: 9 }, (_, i) => <i key={i} />)}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <b>{t("voice.listening")}</b>
              <div className="small" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{speech.interim || t("voice.speak")}</div>
            </div>
            <button className="btn danger sm" onClick={speech.stop}>{t("voice.stop")}</button>
          </div>
        ) : (
          <>
            <form className="composer" onSubmit={(e) => { e.preventDefault(); void send(draft, fromVoice ? "voice" : "text"); }}>
              <button type="button" className="micbtn" onClick={() => { speech.clearError(); speech.start(); }} aria-label={t("voice.aria")} disabled={!!pending}>
                <Mic size={20} aria-hidden />
              </button>
              <input ref={inputRef} value={draft} onChange={(e) => { setDraft(e.target.value); if (!e.target.value) setFromVoice(false); }}
                     placeholder={q?.answer_type === "free" ? t("chat.placeholder.free") : t("chat.placeholder.options")}
                     aria-label={t("chat.inputAria")} disabled={!!pending} autoComplete="off" />
              <button type="submit" aria-label={t("chat.send")} disabled={!!pending || !draft.trim()}><ArrowRight size={18} aria-hidden /></button>
            </form>
            {(voiceHint || (draft && fromVoice)) && <span className="small" role="status">{voiceHint ?? t("voice.check")}</span>}
          </>
        )}
      </div>
    </>
  );
}
