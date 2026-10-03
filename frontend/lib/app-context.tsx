"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import en from "@/locales/en.json";
import pl from "@/locales/pl.json";
import { api, getStoredUser, login as apiLogin } from "@/lib/api";
import type { DemoUser, Role } from "@/types/api";

export type Lang = "en" | "pl";
export type MessageKey = keyof typeof en;
const DICTS: Record<Lang, Record<string, string>> = { en, pl };

type Ctx = {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
  theme: "system" | "light" | "dark";
  setTheme: (t: "system" | "light" | "dark") => void;
  users: Partial<Record<Role, DemoUser>>;
  switchUser: (username: string) => Promise<void>;
  ready: boolean;
  apiError: string | null;
  epoch: number; // bumps after a demo reset or a user switch, so views refetch
  bump: () => void;
  toast: (msg: string) => void;
  resetDemo: () => Promise<void>;
};

const AppContext = createContext<Ctx | null>(null);

const DEFAULT_USERS: Record<Role, string> = { patient: "anna", doctor: "ewa" };

function readPref<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T) || fallback;
  } catch {
    return fallback;
  }
}
function writePref(key: string, v: string) {
  try {
    localStorage.setItem(key, v);
  } catch {
    /* ignore */
  }
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("pl");
  const [theme, setThemeState] = useState<"system" | "light" | "dark">("system");
  const [users, setUsers] = useState<Partial<Record<Role, DemoUser>>>({});
  const [ready, setReady] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const t = useCallback((key: MessageKey, vars?: Record<string, string | number>) => {
    let s = DICTS[lang][key] ?? en[key] ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
    return s;
  }, [lang]);

  const toast = useCallback((msg: string) => {
    setToastMsg(msg);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToastMsg(null), 2400);
  }, []);

  const ensureLogin = useCallback(async (role: Role, username?: string) => {
    const stored = getStoredUser(role);
    const name = username ?? stored?.id ?? DEFAULT_USERS[role];
    const u = await apiLogin(name); // fresh token each load (demo tokens are cheap)
    setUsers((prev) => ({ ...prev, [role]: u }));
    return u;
  }, []);

  const boot = useCallback(async () => {
    try {
      await Promise.all([ensureLogin("patient"), ensureLogin("doctor")]);
      setApiError(null);
      setReady(true);
    } catch (e) {
      setApiError(e instanceof Error ? e.message : String(e));
    }
  }, [ensureLogin]);

  useEffect(() => {
    // Preferences live in localStorage, which only exists in the browser.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLangState(readPref<Lang>("vc-lang", "pl"));
    setThemeState(readPref("vc-theme", "system"));
    void boot();
  }, [boot]);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
  }, [theme]);

  const value = useMemo<Ctx>(() => ({
    lang,
    setLang: (l) => { setLangState(l); writePref("vc-lang", l); },
    t,
    theme,
    setTheme: (v) => { setThemeState(v); writePref("vc-theme", v); },
    users,
    switchUser: async (username) => {
      const all = await api.demoUsers();
      const u = all.find((x) => x.id === username);
      if (!u) return;
      await ensureLogin(u.role, username);
      setEpoch((e) => e + 1);
    },
    ready,
    apiError,
    epoch,
    bump: () => setEpoch((e) => e + 1),
    toast,
    resetDemo: async () => {
      await api.resetDemo();
      await Promise.all([ensureLogin("patient"), ensureLogin("doctor")]);
      setEpoch((e) => e + 1);
      toast(t("demo.reset.done"));
    },
  }), [lang, t, theme, users, ensureLogin, ready, apiError, epoch, toast]);

  return (
    <AppContext.Provider value={value}>
      {children}
      {toastMsg && <div className="toast" role="status">{toastMsg}</div>}
      {apiError && (
        <div className="toast" role="alert" style={{ background: "var(--alert)" }}>
          {apiError} <button className="linkbtn" style={{ color: "inherit", marginLeft: 8 }} onClick={() => void boot()}>{t("common.retry")}</button>
        </div>
      )}
    </AppContext.Provider>
  );
}

export function useApp(): Ctx {
  const c = useContext(AppContext);
  if (!c) throw new Error("useApp outside AppProvider");
  return c;
}
