import { useCallback } from "react";
import { useI18nContext } from "./context";
import type { CopyKey } from "./copy";
import { resolveCopy } from "./copy";

export function useTranslation() {
  const { language, direction } = useI18nContext();

  const t = useCallback(
    (key: string) => {
      const value = resolveCopy(language)[key as CopyKey];
      return value && value.trim() ? value : String(key);
    },
    [language],
  );

  return { t, language, direction };
}
