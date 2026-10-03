"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// Minimal typing for the Web Speech API (not in TypeScript's DOM lib).
type Recognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
};

function getRecognition(): (new () => Recognition) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/** Browser speech-to-text (pl-PL / en-US). The transcript is handed back for the patient to check before sending. */
export function useSpeech(lang: "en" | "pl", onFinal: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<"unsupported" | "denied" | "failed" | null>(null);
  const [interim, setInterim] = useState("");
  const rec = useRef<Recognition | null>(null);
  const text = useRef("");

  useEffect(() => () => rec.current?.stop(), []);

  const start = useCallback(() => {
    const R = getRecognition();
    if (!R) {
      setError("unsupported");
      return;
    }
    setError(null);
    text.current = "";
    setInterim("");
    const r = new R();
    r.lang = lang === "pl" ? "pl-PL" : "en-US";
    r.interimResults = true;
    r.continuous = false;
    r.onresult = (e) => {
      const t = Array.from(e.results).map((res) => res[0].transcript).join(" ");
      text.current = t;
      setInterim(t);
    };
    r.onerror = (e) => setError(e.error === "not-allowed" || e.error === "service-not-allowed" ? "denied" : e.error === "no-speech" ? null : "failed");
    r.onend = () => {
      setListening(false);
      if (text.current.trim()) onFinal(text.current.trim());
    };
    rec.current = r;
    try {
      r.start();
      setListening(true);
    } catch {
      setError("failed");
    }
  }, [lang, onFinal]);

  const stop = useCallback(() => rec.current?.stop(), []);

  return { listening, error, interim, start, stop, clearError: () => setError(null) };
}
