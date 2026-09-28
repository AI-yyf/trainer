/**
 * Remote verification button labels (§十五: eight languages, no zh/en
 * binaries in the training surface).
 */
import type { ComposerLanguage } from "../../lib/types";

const LABELS: Record<
  ComposerLanguage,
  {
    running: (remote: string) => string;
    verifyOn: (remote: string) => string;
  }
> = {
  "zh-CN": {
    running: (remote) => `正在 ${remote} 验证…`,
    verifyOn: (remote) => `在 ${remote} 上验证`,
  },
  "en-US": {
    running: (remote) => `Verifying on ${remote}…`,
    verifyOn: (remote) => `Verify on ${remote}`,
  },
  "es-ES": {
    running: (remote) => `Verificando en ${remote}…`,
    verifyOn: (remote) => `Verificar en ${remote}`,
  },
  "fr-FR": {
    running: (remote) => `Vérification sur ${remote}…`,
    verifyOn: (remote) => `Vérifier sur ${remote}`,
  },
  "de-DE": {
    running: (remote) => `Verifiziere auf ${remote}…`,
    verifyOn: (remote) => `Auf ${remote} verifizieren`,
  },
  "ja-JP": {
    running: (remote) => `${remote} で検証中…`,
    verifyOn: (remote) => `${remote} で検証`,
  },
  "ko-KR": {
    running: (remote) => `${remote}에서 검증 중…`,
    verifyOn: (remote) => `${remote}에서 검증`,
  },
  "pt-BR": {
    running: (remote) => `Verificando em ${remote}…`,
    verifyOn: (remote) => `Verificar em ${remote}`,
  },
};

export function remoteVerifyCopy(language: ComposerLanguage) {
  return LABELS[language];
}
