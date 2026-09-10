import { useMemo, useState } from "react";
import { parseProviderConnectionPaste } from "../../../../../shared/src/providerGateway";
import type { ComposerLanguage } from "../../../../../shared/src/types";

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

function copy(language: ComposerLanguage, key: string): string {
  const zh: Record<string, string> = {
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
    step: "步骤",
    connectedLine: "已连接,可以直接开始对话。模型与密钥可在下方完整表单中调整。",
    parsedHint: "已识别:服务地址与密钥已自动填入。",
    modelHint: "模型将在保存时自动选择。",
    untrusted: "工作区未被信任:无法完成连接验证。请在 VS Code 中信任此窗口后重试。",
  };
  const en: Record<string, string> = {
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
    step: "Step",
    connectedLine: "Connected — start chatting. Tune the model and key in the full form below.",
    parsedHint: "Recognized: base URL and key were filled in automatically.",
    modelHint: "A model will be picked automatically when you save.",
    untrusted: "The workspace is not trusted — connection verification cannot run. Trust this window in VS Code, then retry.",
  };
  return (language === "zh-CN" ? zh : en)[key] ?? key;
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
        <span className="settings-quick-setup__connected-dot" aria-hidden>
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
          {step1Done ? " ✓" : ""}
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
          {step2Done ? " ✓" : ""}
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
        {busy ? copy(language, "saving") : copy(language, "saveLabel")}
      </button>

      <p className="settings-sheet__note settings-sheet__note--compact">
        {language === "zh-CN"
          ? "协议、测速与高级选项在下方完整表单中。"
          : "Protocol, speed test, and advanced options live in the full form below."}
      </p>
    </div>
  );
}
