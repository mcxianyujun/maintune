import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { enUS, zhCN, type MessageKey } from "./resources";

export type Locale = "zh-CN" | "en-US";
const STORAGE_KEY = "maintainer.locale";

function initialLocale(): Locale {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === "zh-CN" || saved === "en-US") return saved;
  return navigator.languages?.some((value) => value.toLowerCase().startsWith("zh")) ? "zh-CN" : "en-US";
}

type I18nValue = { locale: Locale; setLocale: (locale: Locale) => void; t: (key: MessageKey, values?: Record<string, string | number>) => string; date: (timestamp: number) => string };
const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);
  const value = useMemo<I18nValue>(() => {
    const messages = locale === "zh-CN" ? zhCN : enUS;
    return {
      locale,
      setLocale(next) { localStorage.setItem(STORAGE_KEY, next); setLocaleState(next); },
      t(key, values = {}) { return Object.entries(values).reduce((text, [name, replacement]) => text.replaceAll(`{${name}}`, String(replacement)), messages[key]); },
      date(timestamp) { return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(timestamp * 1000)); },
    };
  }, [locale]);
  useEffect(() => { document.documentElement.lang = locale; }, [locale]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const value = useContext(I18nContext);
  if (!value) throw new Error("I18nProvider is missing");
  return value;
}

export function LanguageSwitch({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale, t } = useI18n();
  return <div className={`language-switch${compact ? " compact" : ""}`} role="group" aria-label={t("language.label")}>
    <button type="button" className={locale === "zh-CN" ? "active" : ""} onClick={() => setLocale("zh-CN")}>{t("language.zh")}</button>
    <button type="button" className={locale === "en-US" ? "active" : ""} onClick={() => setLocale("en-US")}>{t("language.en")}</button>
  </div>;
}
