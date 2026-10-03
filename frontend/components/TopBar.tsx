"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Moon, RotateCcw, Sun, SunMoon } from "lucide-react";
import { BrandMark } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import type { DemoUser, SystemInfo } from "@/types/api";

export function TopBar() {
  const { t, lang, setLang, theme, setTheme, users, switchUser, resetDemo, ready, epoch } = useApp();
  const path = usePathname();
  const [all, setAll] = useState<DemoUser[]>([]);
  const [sys, setSys] = useState<SystemInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const onDoctor = path.startsWith("/doctor");

  useEffect(() => {
    if (!ready) return;
    api.demoUsers().then(setAll).catch(() => {});
    api.system().then(setSys).catch(() => {});
  }, [ready, epoch]);

  const role = onDoctor ? "doctor" : "patient";
  const current = users[role]?.id ?? "";
  const nextTheme = theme === "system" ? "light" : theme === "light" ? "dark" : "system";
  const ThemeIcon = theme === "system" ? SunMoon : theme === "light" ? Sun : Moon;

  return (
    <header className="topbar">
      <Link href="/patient" className="brand"><BrandMark />VitalContext</Link>
      <nav className="switch" aria-label={t("top.surface")}>
        <Link href="/patient" aria-current={!onDoctor ? "page" : undefined}>{t("top.patient")}</Link>
        <Link href="/doctor" aria-current={onDoctor ? "page" : undefined}>{t("top.doctor")}</Link>
      </nav>
      <span className="spacer" />
      <label className="tb-group">
        <span>{onDoctor ? t("top.signedInDoctor") : t("top.signedInPatient")}</span>
        <select className="select" value={current} onChange={(e) => void switchUser(e.target.value)} aria-label={t("top.demoUser")}>
          {all.filter((u) => u.role === role).map((u) => (
            <option key={u.id} value={u.id}>{u.displayName}{u.detail ? ` · ${u.detail}` : ""}</option>
          ))}
        </select>
      </label>
      <div className="switch" role="group" aria-label={t("top.language")}>
        <button aria-pressed={lang === "pl"} onClick={() => setLang("pl")}>PL</button>
        <button aria-pressed={lang === "en"} onClick={() => setLang("en")}>EN</button>
      </div>
      <button className="ghost" onClick={() => setTheme(nextTheme)} aria-label={t("top.theme", { theme: t(`top.theme.${theme}` as "top.theme.system") })}
              title={t("top.theme", { theme: t(`top.theme.${theme}` as "top.theme.system") })}>
        <ThemeIcon size={16} aria-hidden />
      </button>
      <span className="demo-note" title={sys ? `FHIR: ${sys.fhirBackend} · red-flag rules ${sys.redFlagRulesVersion}` : ""}>
        {t("top.note")}{sys ? ` · AI: ${sys.llmProvider === "mock" ? t("top.aiOffline") : sys.model}` : ""}
      </span>
      <button className="ghost" disabled={busy} onClick={async () => { setBusy(true); try { await resetDemo(); } finally { setBusy(false); } }}>
        <RotateCcw size={14} aria-hidden style={{ verticalAlign: "-2px", marginRight: 6 }} />{t("top.reset")}
      </button>
    </header>
  );
}
