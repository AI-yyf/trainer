import { useMemo, useState } from "react";
import { parseProviderConnectionPaste } from "../../../../../shared/src/providerGateway";
import type { ComposerLanguage } from "../../../../../shared/src/types";
import { CheckMarkIcon, GearIcon } from "../icons";

interface ProviderQuickSetupDraft {
  name: string;
  baseUrl: string;
  model: string;
  apiKey: string;
}

interface ProviderQuickSetupProps {
  language: ComposerLanguage;
  draft: ProviderQuickSetupDraft;
  savedBaseUrl: string;
  savedModel: string;
  connected: boolean;
  hasStoredApiKey: boolean;
  trusted: boolean;
  busy: boolean;
  onDraftChange: (patch: Partial<ProviderQuickSetupDraft & { apiKey: string }>) => void;
  onSave: () => void;
}

type QuickSetupLanguage =
  | "zh-CN" | "en-US" | "es-ES" | "fr-FR" | "de-DE" | "ja-JP" | "ko-KR" | "pt-BR";

const QUICK_SETUP_COPY: Record<QuickSetupLanguage, Record<string, string>> = {
  "zh-CN": {
    title: "快速设置",
    collapse: "收起",
    change: "更改",
    pasteLabel: "① 粘贴中转站连接信息或服务地址",
    pastePlaceholder: "粘贴 {\"url\":…,\"key\":…} 连接信息,或输入服务地址",
    keyLabel: "② 粘贴 API 密钥",
    keyPlaceholder: "粘贴密钥(sk-…)",
    keyStored: "密钥已保存",
    saveLabel: "③ 保存并连接",
    saving: "连接中…",
    connected: "已连接",
    connectedLine: "已连接,可以直接开始对话。模型与密钥可在下方完整表单中调整。",
    parsedHint: "已识别:服务地址与密钥已自动填入。",
    modelHint: "模型将在保存时自动选择。",
    untrusted: "工作区未信任:请先在下方「Trainer workspace」点「Choose workspace root」选择学习文件夹,信任后再保存。",
    advancedNote: "协议、测速与高级选项在下方完整表单中。",
  },
  "en-US": {
    title: "Quick setup",
    collapse: "Collapse",
    change: "Change",
    pasteLabel: "① Paste relay connection info or service address",
    pastePlaceholder: "Paste {\"url\":…,\"key\":…} connection info, or type a service address",
    keyLabel: "② Paste API key",
    keyPlaceholder: "Paste your key (sk-…)",
    keyStored: "Key saved",
    saveLabel: "③ Save & connect",
    saving: "Connecting…",
    connected: "Connected",
    connectedLine: "Connected — start chatting. Model and key can be tuned in the full form below.",
    parsedHint: "Recognized: base URL and key were filled in automatically.",
    modelHint: "A model will be picked automatically when you save.",
    untrusted: "Workspace not trusted — first click \"Choose workspace root\" in the Trainer workspace section below, pick your learning folder, then save.",
    advancedNote: "Protocol, speed test, and advanced options live in the full form below.",
  },
  "es-ES": {
    title: "Configuración rápida",
    collapse: "Contraer",
    change: "Cambiar",
    pasteLabel: "① Pega la información de conexión o la dirección del servicio",
    pastePlaceholder: "Pega {\"url\":…,\"key\":…} o escribe una dirección de servicio",
    keyLabel: "② Pega la clave API",
    keyPlaceholder: "Pega tu clave (sk-…)",
    keyStored: "Clave guardada",
    saveLabel: "③ Guardar y conectar",
    saving: "Conectando…",
    connected: "Conectado",
    connectedLine: "Conectado: empieza a conversar. Ajusta modelo y clave en el formulario completo de abajo.",
    parsedHint: "Reconocido: la URL y la clave se rellenaron automáticamente.",
    modelHint: "El modelo se seleccionará automáticamente al guardar.",
    untrusted: "Espacio de trabajo no confiable: primero elige \"Choose workspace root\" abajo, luego guarda.",
    advancedNote: "Protocolo, prueba de velocidad y opciones avanzadas en el formulario de abajo.",
  },
  "fr-FR": {
    title: "Configuration rapide",
    collapse: "Réduire",
    change: "Modifier",
    pasteLabel: "① Collez les infos de connexion ou l'adresse du service",
    pastePlaceholder: "Collez {\"url\":…,\"key\":…} ou saisissez une adresse de service",
    keyLabel: "② Collez la clé API",
    keyPlaceholder: "Collez votre clé (sk-…)",
    keyStored: "Clé enregistrée",
    saveLabel: "③ Enregistrer et connecter",
    saving: "Connexion…",
    connected: "Connecté",
    connectedLine: "Connecté : commencez à discuter. Ajustez modèle et clé dans le formulaire complet ci-dessous.",
    parsedHint: "Reconnu : l'URL et la clé ont été remplies automatiquement.",
    modelHint: "Un modèle sera sélectionné automatiquement à l'enregistrement.",
    untrusted: "Espace de travail non approuvé : cliquez d'abord sur \"Choose workspace root\" ci-dessous, puis enregistrez.",
    advancedNote: "Protocole, test de vitesse et options avancées dans le formulaire ci-dessous.",
  },
  "de-DE": {
    title: "Schnelleinrichtung",
    collapse: "Einklappen",
    change: "Ändern",
    pasteLabel: "① Verbindungsinfo oder Dienstadresse einfügen",
    pastePlaceholder: "{\"url\":…,\"key\":…} einfügen oder Dienstadresse eingeben",
    keyLabel: "② API-Schlüssel einfügen",
    keyPlaceholder: "Schlüssel einfügen (sk-…)",
    keyStored: "Schlüssel gespeichert",
    saveLabel: "③ Speichern & verbinden",
    saving: "Verbinde…",
    connected: "Verbunden",
    connectedLine: "Verbunden — leg los. Modell und Schlessel lassen sich im vollständigen Formular unten anpassen.",
    parsedHint: "Erkannt: Dienstadresse und Schlüssel wurden automatisch eingetragen.",
    modelHint: "Ein Modell wird beim Speichern automatisch ausgewählt.",
    untrusted: "Workspace nicht vertrauenswürdig — wähle zuerst unten \"Choose workspace root\", dann speichern.",
    advancedNote: "Protokoll, Geschwindigkeitstest und Optionen im vollständigen Formular unten.",
  },
  "ja-JP": {
    title: "クイック設定",
    collapse: "折りたたむ",
    change: "変更",
    pasteLabel: "① 接続情報またはサービスアドレスを貼り付け",
    pastePlaceholder: "{\"url\":…,\"key\":…} の接続情報を貼るか、サービスアドレスを入力",
    keyLabel: "② API キーを貼り付け",
    keyPlaceholder: "キーを貼り付け (sk-…)",
    keyStored: "キーは保存済み",
    saveLabel: "③ 保存して接続",
    saving: "接続中…",
    connected: "接続済み",
    connectedLine: "接続済み — すぐに会話を開始できます。モデルとキーは下の完全なフォームで調整できます。",
    parsedHint: "認識しました:アドレスとキーを自動入力しました。",
    modelHint: "保存時にモデルが自動選択されます。",
    untrusted: "ワークスペースが信頼されていません。まず下の「Trainer workspace」で \"Choose workspace root\" を選んでから保存してください。",
    advancedNote: "プロトコル、速度テスト、詳細オプションは下の完全なフォームにあります。",
  },
  "ko-KR": {
    title: "빠른 설정",
    collapse: "접기",
    change: "변경",
    pasteLabel: "① 연결 정보 또는 서비스 주소 붙여넣기",
    pastePlaceholder: "{\"url\":…,\"key\":…} 연결 정보를 붙여넣거나 서비스 주소 입력",
    keyLabel: "② API 키 붙여넣기",
    keyPlaceholder: "키 붙여넣기 (sk-…)",
    keyStored: "키 저장됨",
    saveLabel: "③ 저장 후 연결",
    saving: "연결 중…",
    connected: "연결됨",
    connectedLine: "연결됨 — 바로 대화를 시작하세요. 모델과 키는 아래 전체 폼에서 조정할 수 있습니다.",
    parsedHint: "인식됨: 주소와 키가 자동으로 채워졌습니다.",
    modelHint: "저장 시 모델이 자동으로 선택됩니다.",
    untrusted: "워크스페이스가 신뢰되지 않았습니다. 아래 Trainer workspace 섹션에서 Choose workspace root 를 먼저 선택한 뒤 저장하세요.",
    advancedNote: "프로토콜, 속도 테스트, 고급 옵션은 아래 전체 폼에 있습니다.",
  },
  "pt-BR": {
    title: "Configuração rápida",
    collapse: "Recolher",
    change: "Alterar",
    pasteLabel: "① Cole as informações de conexão ou o endereço do serviço",
    pastePlaceholder: "Cole {\"url\":…,\"key\":…} ou digite um endereço de serviço",
    keyLabel: "② Cole a chave da API",
    keyPlaceholder: "Cole sua chave (sk-…)",
    keyStored: "Chave salva",
    saveLabel: "③ Salvar e conectar",
    saving: "Conectando…",
    connected: "Conectado",
    connectedLine: "Conectado — comece a conversar. Ajuste modelo e chave no formulário completo abaixo.",
    parsedHint: "Reconhecido: endereço e chave preenchidos automaticamente.",
    modelHint: "Um modelo será escolhido automaticamente ao salvar.",
    untrusted: "Workspace não confiável — primeiro clique em \"Choose workspace root\" na seção abaixo, depois salve.",
    advancedNote: "Protocolo, teste de velocidade e opções avançadas no formulário completo abaixo.",
  },
};

function copy(language: ComposerLanguage, key: string): string {
  const table = QUICK_SETUP_COPY[(language as QuickSetupLanguage) ?? "en-US"] ?? QUICK_SETUP_COPY["en-US"];
  return table[key] ?? QUICK_SETUP_COPY["en-US"][key] ?? key;
}

export function ProviderQuickSetup({
  language,
  draft,
  savedBaseUrl,
  savedModel,
  connected,
  hasStoredApiKey,
  trusted,
  busy,
  onDraftChange,
  onSave,
}: ProviderQuickSetupProps) {
  const [open, setOpen] = useState(false);
  const [pasteHint, setPasteHint] = useState<string | null>(null);

  const baseUrlReady = draft.baseUrl.trim().length > 0;
  const keyReady = draft.apiKey.trim().length > 0 || hasStoredApiKey;
  const step1Done = baseUrlReady;
  const step2Done = keyReady;
  const canSave = baseUrlReady && keyReady;

  const connectedSummary = useMemo(
    () => Boolean(connected && savedBaseUrl),
    [connected, savedBaseUrl],
  );
  const collapsed = connectedSummary && !open && !draft.baseUrl.trim() && !draft.apiKey.trim();

  const handlePasteOrType = (value: string) => {
    const parsed = parseProviderConnectionPaste(value);
    if (parsed) {
      onDraftChange({ baseUrl: parsed.baseUrl, apiKey: parsed.apiKey });
      setPasteHint(copy(language, "parsedHint"));
      return;
    }
    setPasteHint(null);
    onDraftChange({ baseUrl: value });
  };

  if (collapsed) {
    return (
      <div className="settings-quick-setup settings-quick-setup--connected">
        <span
          className="settings-quick-setup__connected-dot"
          aria-hidden
          style={{ color: "var(--pass, var(--trainer-fallback-success))" }}
        >
          ✓
        </span>
        <span className="settings-quick-setup__connected-line">
          {copy(language, "connectedLine")}
        </span>
        <button
          type="button"
          className="toolbar-button"
          onClick={() => setOpen(true)}
        >
          {copy(language, "change")}
        </button>
      </div>
    );
  }

  return (
    <div className="settings-quick-setup">
      <div className="settings-quick-setup__head">
        <strong>{copy(language, "title")}</strong>
        {connectedSummary ? (
          <button
            type="button"
            className="toolbar-button"
            onClick={() => setOpen(false)}
          >
            {copy(language, "collapse")}
          </button>
        ) : null}
      </div>

      <label className="settings-field">
        <span>
          {copy(language, "pasteLabel")}
          {step1Done ? <span className="settings-quick-setup__done">✓</span> : ""}
        </span>
        <input
          type="text"
          value={draft.baseUrl}
          placeholder={copy(language, "pastePlaceholder")}
          onChange={(event) => handlePasteOrType(event.target.value)}
        />
        {pasteHint ? (
          <p className="settings-sheet__note settings-sheet__note--compact">{pasteHint}</p>
        ) : null}
      </label>

      <label className="settings-field">
        <span>
          {copy(language, "keyLabel")}
          {step2Done ? <span className="settings-quick-setup__done">✓</span> : ""}
        </span>
        <input
          type="password"
          value={draft.apiKey}
          placeholder={hasStoredApiKey && !draft.apiKey ? copy(language, "keyStored") : copy(language, "keyPlaceholder")}
          onChange={(event) => onDraftChange({ apiKey: event.target.value })}
        />
        <p className="settings-sheet__note settings-sheet__note--compact">
          {copy(language, "modelHint")}
        </p>
      </label>

      {!trusted ? (
        <p className="settings-sheet__note settings-sheet__note--warning settings-quick-setup__untrusted">
          {copy(language, "untrusted")}
        </p>
      ) : null}
      <button
        type="button"
        className="action-button action-button--accent"
        disabled={!canSave || busy}
        onClick={onSave}
      >
        {busy ? (
          <>
            <span className="settings-quick-setup__saving-dot" aria-hidden />
            {copy(language, "saving")}
          </>
        ) : (
          <>
            <CheckMarkIcon size={14} />
            {copy(language, "saveLabel")}
          </>
        )}
      </button>

      <p className="settings-sheet__note settings-sheet__note--compact">
        {language === "zh-CN"
          ? "协议、测速与高级选项在下方完整表单中。"
          : "Protocol, speed test, and advanced options live in the full form below."}
      </p>
    </div>
  );
}
