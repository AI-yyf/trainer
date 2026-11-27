import type { MutableRefObject } from "react";
import { useCallback,useEffect,useMemo,useRef,useState } from "react";

import { trainerCommands } from "../../../../shared/src/commands";
import { providerModelTokenLimitsKey } from "../../../../shared/src/providerModelTokenLimits";
import { normalizeProviderProtocol } from "../../../../shared/src/providerProtocols";
import type { ProviderDraft } from "../components/settings/CoachSettingsView";
import { providerDraftStringArrayKey,providerRequestDefaultsKey } from "../lib/formatUtils";
import type { HostMessage,ProviderConfigView,ProviderEndpointSpeedTestResult } from "../lib/types";
import { postMessage } from "../lib/vscode";

/**
 * Provider-connection controller (DESIGN.md §3, round 2).
 *
 * One owner for the connection's interaction state: the editable draft, its
 * derivation from the single ProviderFacts record, the save payload, the
 * endpoint speed test and the API-key focus request. The three previously
 * hand-copied 16-field lists (initial state, source projection, alignment
 * reset) collapse into one field table below, so a new fact field can never be
 * projected in one place and forgotten in another.
 *
 * Facts stay in the store (`data.providerConfig`); the draft is the local
 * overlay the learner edits.
 */

/** The editable fields (the API key is write-only and never derived). */
type DraftFieldKey = Exclude<keyof ProviderDraft, "apiKey">;

type DraftFieldDescriptor = {
  key: DraftFieldKey;
  /** The fact this field starts from (host-owned projection). */
  fromFacts: (facts: ProviderConfigView) => ProviderDraft[DraftFieldKey];
  /** Whether the learner's value differs from the current fact. */
  differs: (draftValue: ProviderDraft[DraftFieldKey], facts: ProviderConfigView) => boolean;
};

/**
 * Single field table: projection, comparison and reset all read from it.
 * `name` keeps the host's display fallback out of the editable draft — a user
 * who saves without noticing would otherwise persist "未配置模型服务" as the
 * real connection name.
 */
const DRAFT_FIELDS: readonly DraftFieldDescriptor[] = [
  {
    key: "name",
    fromFacts: (facts) => (facts.configured ? facts.name : ""),
    differs: (value, facts) => value !== (facts.configured ? facts.name : ""),
  },
  {
    key: "protocol",
    fromFacts: (facts) => facts.protocol ?? "openai_chat_completions_compatible",
    differs: (value, facts) =>
      normalizeProviderProtocol(value as ProviderDraft["protocol"]) !==
      normalizeProviderProtocol(facts.protocol),
  },
  {
    key: "baseUrl",
    fromFacts: (facts) => facts.baseUrl,
    differs: (value, facts) => value !== facts.baseUrl,
  },
  {
    key: "model",
    fromFacts: (facts) => facts.model,
    differs: (value, facts) => value !== facts.model,
  },
  {
    key: "contextWindowTokens",
    fromFacts: (facts) => facts.contextWindowTokens,
    differs: (value, facts) => value !== facts.contextWindowTokens,
  },
  {
    key: "maxOutputTokens",
    fromFacts: (facts) => facts.maxOutputTokens,
    differs: (value, facts) => value !== facts.maxOutputTokens,
  },
  {
    key: "modelTokenLimits",
    fromFacts: (facts) => facts.modelTokenLimits,
    differs: (value, facts) =>
      providerModelTokenLimitsKey(value as ProviderDraft["modelTokenLimits"]) !==
      providerModelTokenLimitsKey(facts.modelTokenLimits),
  },
  {
    key: "credentialMode",
    fromFacts: (facts) => facts.credentialMode ?? "ui_proxy",
    differs: (value, facts) => value !== (facts.credentialMode ?? "ui_proxy"),
  },
  {
    key: "ignoreSystemProxy",
    fromFacts: (facts) => Boolean(facts.ignoreSystemProxy),
    differs: (value, facts) => Boolean(value) !== Boolean(facts.ignoreSystemProxy),
  },
  {
    key: "catalogModels",
    fromFacts: (facts) => facts.catalogModels ?? [],
    differs: (value, facts) =>
      providerDraftStringArrayKey(value as string[] | undefined) !==
      providerDraftStringArrayKey(facts.catalogModels),
  },
  {
    key: "allowedModels",
    fromFacts: (facts) => facts.allowedModels ?? [],
    differs: (value, facts) =>
      providerDraftStringArrayKey(value as string[] | undefined) !==
      providerDraftStringArrayKey(facts.allowedModels),
  },
  {
    key: "deniedModels",
    fromFacts: (facts) => facts.deniedModels ?? [],
    differs: (value, facts) =>
      providerDraftStringArrayKey(value as string[] | undefined) !==
      providerDraftStringArrayKey(facts.deniedModels),
  },
  {
    key: "embeddingModel",
    fromFacts: (facts) => facts.embeddingModel ?? "",
    differs: (value, facts) => (value ?? "") !== (facts.embeddingModel ?? ""),
  },
  {
    key: "catalogSource",
    fromFacts: (facts) => facts.catalogSource ?? "provider_live",
    differs: (value, facts) => value !== (facts.catalogSource ?? "provider_live"),
  },
  {
    key: "cacheTtlSeconds",
    fromFacts: (facts) => facts.cacheTtlSeconds,
    differs: (value, facts) => value !== facts.cacheTtlSeconds,
  },
  {
    key: "requestDefaults",
    fromFacts: (facts) => facts.requestDefaults ?? {},
    differs: (value, facts) =>
      providerRequestDefaultsKey(value as Record<string, unknown> | undefined) !==
      providerRequestDefaultsKey(facts.requestDefaults),
  },
  {
    key: "capabilities",
    fromFacts: (facts) => facts.capabilities,
    differs: (value, facts) =>
      JSON.stringify(value ?? null) !== JSON.stringify(facts.capabilities ?? null),
  },
  {
    key: "thinkingConfig",
    fromFacts: (facts) => facts.thinkingConfig,
    // thinkingConfig is durable intent: a mode change can leave the wire
    // defaults untouched (no capability evidence), so it must count on its own.
    differs: (value, facts) =>
      JSON.stringify(value ?? null) !== JSON.stringify(facts.thinkingConfig ?? null),
  },
];

/** The draft starts from the facts projection with an empty key field. */
export function providerDraftFromFacts(facts: ProviderConfigView): ProviderDraft {
  const draft: ProviderDraft = {
    name: "",
    protocol: "openai_chat_completions_compatible",
    baseUrl: "",
    model: "",
    credentialMode: "ui_proxy",
    ignoreSystemProxy: false,
    catalogModels: [],
    allowedModels: [],
    deniedModels: [],
    embeddingModel: "",
    catalogSource: "provider_live",
    requestDefaults: {},
    capabilities: facts.capabilities,
    apiKey: "",
  };
  for (const field of DRAFT_FIELDS) {
    (draft[field.key] as unknown) = field.fromFacts(facts);
  }
  return draft;
}

export interface ProviderConnectionControllerOptions {
  /** The one ProviderFacts record (store-owned). */
  facts: ProviderConfigView;
  /** In-flight settings action; a save/clear keeps an unsaved draft. */
  settingsActionKind?: string;
  settingsScopeKey: string;
  /** Updated by App when a settings action starts. */
  settingsActionScopeRef: MutableRefObject<string>;
}

export interface ProviderConnectionController {
  providerDraft: ProviderDraft;
  /** User edit: marks the draft dirty so host refreshes cannot overwrite it. */
  setProviderDraft: (update: ProviderDraft | ((current: ProviderDraft) => ProviderDraft)) => void;
  providerDraftHasChanges: boolean;
  providerDraftHasUnsavedApiKey: boolean;
  /** Host payload for `save-provider` (the API key is trimmed and write-only). */
  providerSavePayload: Record<string, unknown>;
  /** Acknowledged save/clear: the draft matches the host again. */
  markProviderDraftSaved: () => void;
  /** Discard local edits and return to the host-owned connection facts. */
  resetProviderDraft: () => void;
  providerSpeedTestResults: ProviderEndpointSpeedTestResult[];
  providerSpeedTestPending: boolean;
  runProviderSpeedTest: (urls: string[]) => void;
  /** Consumes provider/speedTest acks; true when the message was handled. */
  handleProviderSpeedTestMessage: (message: HostMessage) => boolean;
  providerApiKeyFocusRequest: number;
  requestProviderApiKeyFocus: () => void;
}

export function useProviderConnectionController({
  facts,
  settingsActionKind,
  settingsScopeKey,
  settingsActionScopeRef,
}: ProviderConnectionControllerOptions): ProviderConnectionController {
  const [providerDraft, setDraftState] = useState<ProviderDraft>(() => providerDraftFromFacts(facts));
  const providerDraftIsDirtyRef = useRef(false);
  const providerDraftRef = useRef(providerDraft);
  providerDraftRef.current = providerDraft;
  const providerDraftSourceKeyRef = useRef<string>();
  const prevFactsSwitchSignatureRef = useRef<string>(
    `${facts.profileId ?? ""}\0${facts.model ?? ""}`,
  );

  // The facts projection is the single source the draft resets to.
  const providerDraftSource = useMemo(() => providerDraftFromFacts(facts), [facts]);
  const providerDraftSourceKey = useMemo(
    () => JSON.stringify(providerDraftSource),
    [providerDraftSource],
  );
  const factsSwitchSignature = `${facts.profileId ?? ""}\0${facts.model ?? ""}`;

  // Host facts changed (or the session scope changed): align the draft unless
  // the learner has unsaved edits that this very action is about to persist or
  // discard. Follow explicit external profile switches immediately, and never
  // wipe an actively edited Base URL / API key draft if a background model
  // refresh only updated resolvedModel on the same profile.
  useEffect(() => {
    const previousSignature = prevFactsSwitchSignatureRef.current;
    const externalSelectionChanged = previousSignature !== factsSwitchSignature;
    prevFactsSwitchSignatureRef.current = factsSwitchSignature;
    if (providerDraftSourceKeyRef.current === providerDraftSourceKey && !externalSelectionChanged) {
      return;
    }
    providerDraftSourceKeyRef.current = providerDraftSourceKey;

    const sameProfileBackgroundModelRefresh =
      externalSelectionChanged &&
      previousSignature.split("\0")[0] === factsSwitchSignature.split("\0")[0] &&
      typeof providerDraftRef !== "undefined" &&
      (providerDraftRef.current.apiKey.trim().length > 0 ||
        providerDraftRef.current.baseUrl.trim() !== providerDraftSource.baseUrl.trim());
    const shouldKeepUnsavedProviderDraft =
      (!externalSelectionChanged || sameProfileBackgroundModelRefresh) &&
      providerDraftIsDirtyRef.current &&
      (settingsActionScopeRef.current !== settingsScopeKey ||
        (settingsActionKind !== "save-provider" && settingsActionKind !== "clear-provider"));
    if (shouldKeepUnsavedProviderDraft) {
      return;
    }

    setDraftState(providerDraftSource);
    providerDraftIsDirtyRef.current = false;
  }, [
    factsSwitchSignature,
    providerDraftSource,
    providerDraftSourceKey,
    settingsActionKind,
    settingsScopeKey,
    settingsActionScopeRef,
  ]);

  const setProviderDraft = useCallback(
    (update: ProviderDraft | ((current: ProviderDraft) => ProviderDraft)) => {
      providerDraftIsDirtyRef.current = true;
      setDraftState(update);
    },
    [],
  );

  const markProviderDraftSaved = useCallback(() => {
    providerDraftIsDirtyRef.current = false;
    setDraftState((current) => (current.apiKey ? { ...current, apiKey: "" } : current));
  }, []);

  const resetProviderDraft = useCallback(() => {
    providerDraftIsDirtyRef.current = false;
    setDraftState(providerDraftSource);
  }, [providerDraftSource]);

  const providerDraftHasUnsavedApiKey = providerDraft.apiKey.trim().length > 0;
  const providerDraftHasChanges = useMemo(
    () =>
      providerDraftHasUnsavedApiKey ||
      DRAFT_FIELDS.some((field) => field.differs(providerDraft[field.key], facts)),
    [facts, providerDraft, providerDraftHasUnsavedApiKey],
  );

  const providerSavePayload = useMemo(() => {
    const trimmedApiKey = providerDraft.apiKey.trim();
    return {
      name: providerDraft.name,
      protocol: providerDraft.protocol,
      baseUrl: providerDraft.baseUrl,
      model: providerDraft.model,
      contextWindowTokens: providerDraft.contextWindowTokens ?? null,
      maxOutputTokens: providerDraft.maxOutputTokens ?? null,
      modelTokenLimits: providerDraft.modelTokenLimits,
      credentialMode: providerDraft.credentialMode,
      ignoreSystemProxy: Boolean(providerDraft.ignoreSystemProxy),
      catalogModels: providerDraft.catalogModels ?? [],
      allowedModels: providerDraft.allowedModels ?? [],
      deniedModels: providerDraft.deniedModels ?? [],
      embeddingModel: providerDraft.embeddingModel?.trim() || "",
      catalogSource: providerDraft.catalogSource,
      cacheTtlSeconds: providerDraft.cacheTtlSeconds ?? null,
      requestDefaults: providerDraft.requestDefaults ?? {},
      thinkingConfig: providerDraft.thinkingConfig ?? null,
      ...(trimmedApiKey ? { apiKey: trimmedApiKey, replaceApiKey: true } : {}),
      capabilities: providerDraft.capabilities ?? facts.capabilities,
    };
  }, [facts.capabilities, providerDraft]);

  const [providerSpeedTestResults, setProviderSpeedTestResults] = useState<
    ProviderEndpointSpeedTestResult[]
  >([]);
  const [providerSpeedTestPending, setProviderSpeedTestPending] = useState(false);
  const runProviderSpeedTest = useCallback((urls: string[]) => {
    if (urls.length === 0) {
      return;
    }
    setProviderSpeedTestPending(true);
    postMessage({
      type: "command/execute",
      payload: {
        commandId: trainerCommands.providerSpeedTest,
        payload: { urls },
      },
    });
  }, []);

  const handleProviderSpeedTestMessage = useCallback((message: HostMessage) => {
    if (message.type !== "provider/speedTest") {
      return false;
    }
    setProviderSpeedTestResults(message.payload.results);
    setProviderSpeedTestPending(false);
    return true;
  }, []);

  const [providerApiKeyFocusRequest, setProviderApiKeyFocusRequest] = useState(0);
  const requestProviderApiKeyFocus = useCallback(() => {
    setProviderApiKeyFocusRequest((request) => request + 1);
  }, []);

  return {
    providerDraft,
    setProviderDraft,
    providerDraftHasChanges,
    providerDraftHasUnsavedApiKey,
    providerSavePayload,
    markProviderDraftSaved,
    resetProviderDraft,
    providerSpeedTestResults,
    providerSpeedTestPending,
    runProviderSpeedTest,
    handleProviderSpeedTestMessage,
    providerApiKeyFocusRequest,
    requestProviderApiKeyFocus,
  };
}
