/**
 * Opt-in anonymous telemetry consent surface (P2 #18) — the settings copy.
 *
 * zh-CN is the source of truth; every other language must carry every key
 * (locked by telemetrySettingsCopy.test.js). The strings may NOT promise more
 * than the implementation: the export is coarse local event counts only
 * (schema trainer.telemetry.v1), never content, never identifiers.
 */

export const TELEMETRY_SETTINGS_TEXT: Record<string, Record<string, string>> = {
  "匿名遥测（可选）": {
    "en-US": "Anonymous telemetry (optional)",
    "es-ES": "Telemetría anónima (opcional)",
    "fr-FR": "Télémétrie anonyme (facultatif)",
    "de-DE": "Anonyme Telemetrie (optional)",
    "ja-JP": "匿名テレメトリ（任意）",
    "ko-KR": "익명 텔레메트리(선택)",
    "pt-BR": "Telemetria anônima (opcional)",
  },
  "默认关闭。开启后仅聚合本机事件计数，不含对话内容、文件路径、账号或密钥；随时可以关闭。": {
    "en-US":
      "Off by default. When on, only local event counts are aggregated — never chat content, file paths, accounts, or keys. You can turn it off any time.",
    "es-ES":
      "Desactivada por defecto. Al activarla solo se agregan conteos de eventos locales: nunca contenido del chat, rutas de archivos, cuentas ni claves. Puede desactivarla cuando quiera.",
    "fr-FR":
      "Désactivée par défaut. Une fois activée, seuls les comptages d'événements locaux sont agrégés — jamais le contenu des conversations, les chemins de fichiers, les comptes ni les clés. Vous pouvez la désactiver à tout moment.",
    "de-DE":
      "Standardmäßig aus. Wenn aktiviert, werden nur lokale Ereigniszähler aggregiert – niemals Chatinhalte, Dateipfade, Konten oder Schlüssel. Jederzeit abschaltbar.",
    "ja-JP":
      "既定はオフです。有効にすると、ローカルのイベント件数のみを集計します。会話の内容・ファイルパス・アカウント・鍵は含まれません。いつでもオフにできます。",
    "ko-KR":
      "기본값은 꺼짐입니다. 켜면 로컬 이벤트 건수만 집계하며, 대화 내용·파일 경로·계정·키는 절대 포함하지 않습니다. 언제든 끌 수 있습니다.",
    "pt-BR":
      "Desativada por padrão. Ao ativar, apenas contagens de eventos locais são agregadas — nunca conteúdo de conversa, caminhos de arquivos, contas ou chaves. Você pode desativar a qualquer momento.",
  },
  "允许聚合匿名使用统计": {
    "en-US": "Allow anonymous usage aggregation",
    "es-ES": "Permitir la agregación anónima de uso",
    "fr-FR": "Autoriser l'agrégation anonyme d'utilisation",
    "de-DE": "Anonyme Nutzungsaggregation erlauben",
    "ja-JP": "匿名の使用統計の集計を許可",
    "ko-KR": "익명 사용 통계 집계 허용",
    "pt-BR": "Permitir agregação anônima de uso",
  },
  "已开启 · 仅聚合本地事件计数": {
    "en-US": "On · aggregating local event counts only",
    "es-ES": "Activada · solo conteos de eventos locales",
    "fr-FR": "Activée · comptages d'événements locaux uniquement",
    "de-DE": "Ein · nur lokale Ereigniszähler",
    "ja-JP": "オン · ローカルイベント件数のみ",
    "ko-KR": "켬 · 로컬 이벤트 건수만",
    "pt-BR": "Ativada · apenas contagens de eventos locais",
  },
  "已关闭 · 不收集任何数据": {
    "en-US": "Off · collecting nothing",
    "es-ES": "Desactivada · no recoge ningún dato",
    "fr-FR": "Désactivée · ne collecte rien",
    "de-DE": "Aus · sammelt nichts",
    "ja-JP": "オフ · 何も収集しません",
    "ko-KR": "끔 · 아무 것도 수집하지 않음",
    "pt-BR": "Desativada · não coleta nada",
  },
  "状态未读取 · 侧边栏未连接时保持关闭": {
    "en-US": "State not read · stays off while the sidebar is disconnected",
    "es-ES": "Estado no leído · permanece desactivada si la barra lateral no está conectada",
    "fr-FR": "État non lu · reste désactivée quand la barre latérale est déconnectée",
    "de-DE": "Status nicht gelesen · bleibt aus, solange die Seitenleiste getrennt ist",
    "ja-JP": "状態未取得 · サイドバー未接続中はオフのまま",
    "ko-KR": "상태 미확인 · 사이드바 미연결 시 꺼짐 유지",
    "pt-BR": "Estado não lido · permanece desativada com a barra lateral desconectada",
  },
};

export const TELEMETRY_SETTINGS_SOURCE_KEYS = {
  title: "匿名遥测（可选）",
  detail:
    "默认关闭。开启后仅聚合本机事件计数，不含对话内容、文件路径、账号或密钥；随时可以关闭。",
  rowLabel: "允许聚合匿名使用统计",
  stateOn: "已开启 · 仅聚合本地事件计数",
  stateOff: "已关闭 · 不收集任何数据",
  stateUnknown: "状态未读取 · 侧边栏未连接时保持关闭",
} as const;

export type TelemetrySettingsCopy = Record<keyof typeof TELEMETRY_SETTINGS_SOURCE_KEYS, string>;

export function telemetrySettingsCopy(language: string): TelemetrySettingsCopy {
  const from = (zh: string): string => TELEMETRY_SETTINGS_TEXT[zh]?.[language] ?? zh;
  return {
    title: from(TELEMETRY_SETTINGS_SOURCE_KEYS.title),
    detail: from(TELEMETRY_SETTINGS_SOURCE_KEYS.detail),
    rowLabel: from(TELEMETRY_SETTINGS_SOURCE_KEYS.rowLabel),
    stateOn: from(TELEMETRY_SETTINGS_SOURCE_KEYS.stateOn),
    stateOff: from(TELEMETRY_SETTINGS_SOURCE_KEYS.stateOff),
    stateUnknown: from(TELEMETRY_SETTINGS_SOURCE_KEYS.stateUnknown),
  };
}
