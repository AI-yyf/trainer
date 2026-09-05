import { createContext, useContext, useLayoutEffect } from "react";
import type { ComposerLanguage } from "../types";
import { resolveTextDirection, type TextDirection } from "./direction";

export interface I18nContextValue {
  language: ComposerLanguage;
  direction: TextDirection;
}

export const I18nContext = createContext<I18nContextValue | undefined>(undefined);

export function useI18nContext(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18nContext must be used within I18nProvider");
  }
  return ctx;
}

export function I18nProvider({
  language,
  direction: directionOverride,
  children,
}: {
  language: ComposerLanguage;
  direction?: TextDirection;
  children: React.ReactNode;
}) {
  const direction = directionOverride ?? resolveTextDirection(language);

  useLayoutEffect(() => {
    if (typeof document === "undefined") {
      return;
    }

    document.documentElement.setAttribute("lang", language);
    document.documentElement.setAttribute("dir", direction);
    document.body?.setAttribute("dir", direction);
  }, [direction, language]);

  return (
    <I18nContext.Provider value={{ language, direction }}>
      {children}
    </I18nContext.Provider>
  );
}
