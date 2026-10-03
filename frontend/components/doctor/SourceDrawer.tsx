"use client";

import { useEffect, useRef, useState } from "react";
import { Check, X } from "lucide-react";
import { SourceMark } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { fmtDate } from "@/lib/format";
import type { SourceRecord } from "@/types/brief";

/** One-click verification: the original FHIR record behind a citation. Esc closes. */
export function SourceDrawer({ pid, reference, onClose }: { pid: string; reference: string; onClose: () => void }) {
  const { t, lang } = useApp();
  const [rec, setRec] = useState<SourceRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let cancelled = false;
    api.source(pid, reference).then((r) => !cancelled && setRec(r)).catch((e) => !cancelled && setError(String(e.message ?? e)));
    return () => { cancelled = true; };
  }, [pid, reference]);
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="dr-t">
        <div className="drawer-head">
          <div style={{ display: "grid", gap: 4 }}>
            {rec && <span className="src"><SourceMark source={rec.source} /> {rec.source === "clinic" ? t("source.clinic") : t("source.patient")} · {rec.type}</span>}
            <h2 id="dr-t">{rec?.title ?? reference}</h2>
            {rec?.date && <span className="small num">{fmtDate(rec.date, lang)}{rec.version ? ` · ${t("drawer.version", { v: rec.version })}` : ""}</span>}
          </div>
          <button ref={closeRef} className="x" onClick={onClose} aria-label={t("drawer.close")}><X size={20} aria-hidden /></button>
        </div>
        <div className="drawer-body">
          {error && <p className="err">{error}</p>}
          {!rec && !error && <p className="small">{t("common.loading")}</p>}
          {rec && (
            <>
              {rec.verified && <div className="verified"><Check size={16} aria-hidden /> {t("drawer.verified")}</div>}
              <dl className="kv">{rec.fields.map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
              <details>
                <summary>{t("drawer.raw", { ref: rec.reference })}</summary>
                <pre>{JSON.stringify(rec.raw, null, 2)}</pre>
              </details>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
