import type { ComposerLanguage, ProviderConfigView } from "../../lib/types";
import type { Copy } from "../../lib/i18n/copyTypes";
import {
  normalizeProviderModelThinkingConfig,
  type ProviderThinkingConfig,
  type ProviderThinkingDescriptor,
} from "../../../../../shared/src/providerThinking";
import type { ComposerProviderMenuItem } from "../../lib/composerModelHelpers";
import { composerModelPolicyHint } from "../../lib/composerModelHelpers";
import {
  formatCompactTokenLimit,
  resolveEffectiveTokenBudgetProfile,
} from "../../../../../shared/src/smartTokenBudget";
import { filterProviderModelOptions } from "../../../../../shared/src/providerModelPolicy";
import { providerBaseUrlIsLocalService } from "../../../../../shared/src/providerStatus";
import { ComposerIconButton } from "./ComposerIconButton";
import {
  CheckMarkIcon,
  EyeIcon,
  RefreshIcon,
  SearchIcon,
  TerminalIcon,
} from "../icons";

export interface ComposerModelMenuProps {
  copy: Copy;
  /** providerSettingsLocale(layout.composerLanguage) — modelPicker 文案。 */
  providerCopy: {
    modelPicker: {
      currentModel: string;
      onlyCurrentModel: string;
    };
  };
  composerLanguage: ComposerLanguage;
  localize: (language: ComposerLanguage, text: string) => string;
  localizeAlt: (language: ComposerLanguage, text: string) => string;
  providerConfig: ProviderConfigView;
  /** buildComposerProviderMenuItems 的完整列表（未过滤）。 */
  menuItems: ComposerProviderMenuItem[];
  /** useComposerModelQuery 过滤后的可见项。 */
  filteredMenuItems: ComposerProviderMenuItem[];
  hasSavedProfiles: boolean;
  modelQuery: string;
  onModelQueryChange: (query: string) => void;
  modelSearchRef: { current: HTMLInputElement | null };
  thinkingDescriptor: ProviderThinkingDescriptor | undefined;
  onThinkingChange: (config: ProviderThinkingConfig) => void;
  onRefreshModels: () => void;
  onSwitchModel: (model: string) => void;
  onSwitchProviderModel: (profileId: string, model: string) => void;
  initialOptionLimit: number;
}

const VISION_LABEL: Record<ComposerLanguage, string> = {
  "zh-CN": "视觉",
  "en-US": "Vision",
  "es-ES": "Visión",
  "fr-FR": "Vision",
  "de-DE": "Vision",
  "ja-JP": "視覚",
  "ko-KR": "비전",
  "pt-BR": "Visão",
};

const THINKING_LABEL: Record<ComposerLanguage, string> = {
  "zh-CN": "思考",
  "en-US": "Thinking",
  "es-ES": "Razonamiento",
  "fr-FR": "Réflexion",
  "de-DE": "Denken",
  "ja-JP": "思考",
  "ko-KR": "사고",
  "pt-BR": "Raciocínio",
};

const EFFORT_LABEL: Record<"low" | "medium" | "high", Record<ComposerLanguage, string>> = {
  low: {
    "zh-CN": "低",
    "en-US": "Low",
    "es-ES": "Bajo",
    "fr-FR": "Faible",
    "de-DE": "Niedrig",
    "ja-JP": "低",
    "ko-KR": "낮음",
    "pt-BR": "Baixo",
  },
  medium: {
    "zh-CN": "中",
    "en-US": "Medium",
    "es-ES": "Medio",
    "fr-FR": "Moyen",
    "de-DE": "Mittel",
    "ja-JP": "中",
    "ko-KR": "중간",
    "pt-BR": "Médio",
  },
  high: {
    "zh-CN": "最高",
    "en-US": "Max",
    "es-ES": "Máximo",
    "fr-FR": "Max",
    "de-DE": "Maximal",
    "ja-JP": "最高",
    "ko-KR": "최고",
    "pt-BR": "Máximo",
  },
};

type OtherProviderGroup = {
  id: string;
  label: string;
  models: string[];
  visionModels: Set<string>;
  thinkingByModel: Record<string, ProviderThinkingConfig>;
};

/**
 * Composer 的“切换模型”菜单面板。
 *
 * One calm list: provider identity, search, flat model rows and a single
 * thinking-intensity control. The active row carries a check; a verified
 * vision capability gets a small eye badge. Thinking sits at the bottom and
 * reads as a slider, not a second navigation surface.
 */
export function ComposerModelMenu({
  copy,
  providerCopy,
  composerLanguage,
  localize,
  localizeAlt,
  providerConfig,
  menuItems,
  filteredMenuItems,
  hasSavedProfiles,
  modelQuery,
  onModelQueryChange,
  modelSearchRef,
  thinkingDescriptor,
  onThinkingChange,
  onRefreshModels,
  onSwitchModel,
  onSwitchProviderModel,
  initialOptionLimit,
}: ComposerModelMenuProps) {
  const providerApplied = providerConfig.configured;
  const visibleModels = filteredMenuItems.filter(
    (profile) => profile.selectionKind === "model",
  );
  const hasModelQuery = modelQuery.trim().length > 0;
  const activeModelItem = menuItems.find(
    (item) => item.selectionKind === "model" && item.isActive,
  );
  const activeModelPolicyHint = composerModelPolicyHint(
    composerLanguage,
    activeModelItem?.policyReason,
  );
  const retainedBlockedActiveModel =
    activeModelItem && activeModelPolicyHint ? activeModelItem : undefined;
  const defaultVisibleModels = menuItems
    .filter((profile) => profile.selectionKind === "model" && !profile.isActive)
    .slice(0, initialOptionLimit);
  const activeModelPinned =
    activeModelItem && activeModelItem.id !== retainedBlockedActiveModel?.id
      ? [activeModelItem]
      : [];
  const nonActiveModelCount = menuItems.filter(
    (item) => item.selectionKind === "model" && !item.isActive,
  ).length;
  // Multiple providers: every saved profile becomes its own model group.
  // Selecting a row from another group sends the profile half of the
  // {profileId, modelId} identity with the model, so the host switches both
  // atomically instead of switching the provider and then racing the model.
  const activeProfileId = providerConfig.profileId?.trim() ?? "";
  const providerRecords = Array.isArray(providerConfig.providerProfiles)
    ? providerConfig.providerProfiles
    : [];
  const otherProviderGroups = providerRecords.flatMap((record) => {
    if (!record || typeof record !== "object" || Array.isArray(record)) {
      return [];
    }
    const raw = record as Record<string, unknown>;
    const id = typeof raw.id === "string" ? raw.id.trim() : "";
    if (!id || id === activeProfileId) {
      return [];
    }
    const label =
      (typeof raw.label === "string" && raw.label.trim()) ||
      (typeof raw.name === "string" && raw.name.trim()) ||
      id;
    const defaultModel = typeof raw.model === "string" ? raw.model.trim() : "";
    const availableModels = Array.isArray(raw.availableModels)
      ? raw.availableModels.filter((value): value is string => typeof value === "string")
      : [];
    const catalogModels = Array.isArray(raw.catalogModels)
      ? raw.catalogModels.filter((value): value is string => typeof value === "string")
      : [];
    const allowedModels = Array.isArray(raw.allowedModels)
      ? raw.allowedModels.filter((value): value is string => typeof value === "string")
      : [];
    const deniedModels = Array.isArray(raw.deniedModels)
      ? raw.deniedModels.filter((value): value is string => typeof value === "string")
      : [];
    const rawModels = Array.from(
      new Set(
        [defaultModel, ...availableModels, ...catalogModels]
          .map((value) => value.trim())
          .filter(Boolean),
      ),
    );
    const models = filterProviderModelOptions(
      rawModels,
      { allowedModels, deniedModels },
      { retainModels: defaultModel ? [defaultModel] : [] },
    );
    if (models.length === 0) {
      return [];
    }
    const rawCapabilities =
      raw.capabilities && typeof raw.capabilities === "object" && !Array.isArray(raw.capabilities)
        ? (raw.capabilities as Record<string, unknown>)
        : {};
    const rawModelCapabilities =
      raw.modelCapabilities && typeof raw.modelCapabilities === "object"
        ? (raw.modelCapabilities as Record<string, unknown>)
        : {};
    const visionModels = new Set(
      models.filter((model) => {
        const modelCapability = rawModelCapabilities[model];
        if (
          modelCapability &&
          typeof modelCapability === "object" &&
          !Array.isArray(modelCapability) &&
          typeof (modelCapability as Record<string, unknown>).vision === "boolean"
        ) {
          return (modelCapability as Record<string, unknown>).vision === true;
        }
        return rawCapabilities.vision === true;
      }),
    );
    const thinkingByModel =
      normalizeProviderModelThinkingConfig(
        raw.modelThinkingConfig,
        typeof raw.protocol === "string" ? raw.protocol : undefined,
      ) ?? {};
    return [{ id, label, models, visionModels, thinkingByModel }];
  });
  const queryKey = modelQuery.trim().toLowerCase();
  const visibleOtherGroups = otherProviderGroups
    .map((group) => {
      if (!hasModelQuery) {
        return { ...group, models: group.models.slice(0, initialOptionLimit) };
      }
      const labelMatches = group.label.toLowerCase().includes(queryKey);
      const matchingModels = group.models.filter((model) =>
        model.toLowerCase().includes(queryKey),
      );
      return {
        ...group,
        models: matchingModels.length > 0 ? matchingModels : labelMatches ? group.models : [],
      };
    })
    .filter((group) => group.models.length > 0);
  const hasQueryMatch = visibleModels.length > 0 || visibleOtherGroups.length > 0;
  const displayedModels = hasModelQuery
    ? hasQueryMatch
      ? [
          ...(retainedBlockedActiveModel ? [retainedBlockedActiveModel] : []),
          ...activeModelPinned,
          ...visibleModels.filter(
            (item) =>
              item.id !== retainedBlockedActiveModel?.id && item.id !== activeModelItem?.id,
          ),
        ]
      : []
    : [
        ...(retainedBlockedActiveModel ? [retainedBlockedActiveModel] : []),
        ...activeModelPinned,
        ...defaultVisibleModels.filter((item) => item.id !== activeModelItem?.id),
      ];
  const hasOnlyCurrentModel =
    Boolean(activeModelItem) &&
    nonActiveModelCount === 0 &&
    otherProviderGroups.length === 0;
  const showModelSection =
    hasModelQuery ||
    defaultVisibleModels.length > 0 ||
    Boolean(activeModelItem) ||
    otherProviderGroups.length > 0;
  const searchLabel = localize(composerLanguage, "搜索模型或已保存连接");
  const emptyStateLabel = hasModelQuery
    ? localize(composerLanguage, "没有匹配的模型或已保存连接。")
    : hasOnlyCurrentModel
      ? providerCopy.modelPicker.onlyCurrentModel
      : hasSavedProfiles
        ? localize(composerLanguage, "可从下方展开已保存连接。")
        : localize(composerLanguage, "还没有可切换的模型。请到“设置”保存连接。");

  const visibleSelectionCount =
    displayedModels.length +
    visibleOtherGroups.reduce((count, group) => count + group.models.length, 0);
  const modelSectionLabel = hasModelQuery
    ? localize(composerLanguage, "匹配的模型")
    : localize(composerLanguage, "可切换模型");
  const providerIsLocalService = providerBaseUrlIsLocalService(providerConfig.baseUrl);
  const refreshModelsDisabled =
    !providerApplied ||
    (!providerConfig.apiKeyConfigured && !providerIsLocalService) ||
    providerConfig.modelListStatus === "loading";
  const refreshModelsLabel = localize(composerLanguage, "刷新模型");
  const refreshModelsTitle = !providerApplied
    ? localize(composerLanguage, "先保存连接，再更新模型列表")
    : !providerConfig.apiKeyConfigured && !providerIsLocalService
      ? localize(composerLanguage, "先在“设置”填写访问密钥，再更新模型列表")
      : providerConfig.modelListStatus === "loading"
        ? localize(composerLanguage, "正在更新模型列表")
        : localize(composerLanguage, "更新模型列表");
  const providerLabel =
    providerConfig.profileLabel?.trim() ||
    providerConfig.name?.trim() ||
    copy.chatModel;
  const visionLabel = VISION_LABEL[composerLanguage];
  const modelHasVision = (model: string): boolean => {
    const modelCapability = providerConfig.modelCapabilities?.[model]?.vision;
    if (typeof modelCapability === "boolean") {
      return modelCapability;
    }
    return providerConfig.capabilities.vision === true;
  };
  const savedThinkingLabelFor = (
    thinking: ProviderThinkingConfig | undefined,
  ): string | undefined => {
    if (!thinking) return undefined;
    if (thinking.mode === "disabled") {
      return localize(composerLanguage, "关闭");
    }
    if (thinking.mode === "enabled" && thinking.reasoningEffort) {
      return EFFORT_LABEL[thinking.reasoningEffort][composerLanguage];
    }
    if (thinking.mode === "enabled" && typeof thinking.budgetTokens === "number") {
      return formatCompactTokenLimit(thinking.budgetTokens) || localize(composerLanguage, "开启");
    }
    if (thinking.mode === "enabled") {
      return localize(composerLanguage, "开启");
    }
    return undefined;
  };

  const effortOptions: readonly ("low" | "medium" | "high")[] | undefined =
    thinkingDescriptor?.kind === "reasoning_effort"
      ? thinkingDescriptor.effortOptions ?? ["low", "medium", "high"]
      : undefined;
  const modeStops = ["disabled", "auto", "enabled"] as const;
  const thinkingStops = effortOptions ?? (thinkingDescriptor ? modeStops : undefined);
  const thinkingIndex = (() => {
    if (!thinkingDescriptor || !thinkingStops) return 0;
    if (effortOptions) {
      if (thinkingDescriptor.config.mode === "disabled") {
        return 0;
      }
      const effort = thinkingDescriptor.config.reasoningEffort ?? "medium";
      return Math.max(0, effortOptions.indexOf(effort));
    }
    return Math.max(0, modeStops.indexOf(thinkingDescriptor.config.mode));
  })();
  const thinkingValueLabel = (() => {
    if (!thinkingDescriptor || !thinkingStops) return "";
    if (effortOptions) {
      if (thinkingDescriptor.config.mode === "disabled") {
        return localize(composerLanguage, "关闭");
      }
      if (thinkingDescriptor.config.mode === "auto") {
        return localize(composerLanguage, "自动");
      }
      const effort = thinkingDescriptor.config.reasoningEffort ?? "medium";
      return EFFORT_LABEL[effort][composerLanguage];
    }
    return thinkingIndex === 0
      ? localize(composerLanguage, "关闭")
      : thinkingIndex === 1
        ? localize(composerLanguage, "自动")
        : localize(composerLanguage, "开启");
  })();
  const onThinkingIndexChange = (index: number) => {
    if (!thinkingDescriptor || !thinkingStops) return;
    if (effortOptions) {
      const effort = effortOptions[index] ?? "medium";
      onThinkingChange({
        mode: "enabled",
        reasoningEffort: effort,
      });
      return;
    }
    const mode = modeStops[index] ?? "auto";
    onThinkingChange({
      ...thinkingDescriptor.config,
      mode,
      ...(mode !== "enabled" ? { budgetTokens: undefined, reasoningEffort: undefined } : {}),
    });
  };
  const onCycleEffortMode = () => {
    if (!thinkingDescriptor || !effortOptions || thinkingDescriptor.disabled) return;
    const nextMode =
      thinkingDescriptor.config.mode === "enabled"
        ? "auto"
        : thinkingDescriptor.config.mode === "auto"
          ? "disabled"
          : "enabled";
    onThinkingChange(
      nextMode === "enabled"
        ? { mode: "enabled", reasoningEffort: thinkingDescriptor.config.reasoningEffort ?? "medium" }
        : { mode: nextMode },
    );
  };

  return (
    <section className="composer-menu-panel composer-menu-panel--provider composer-model-menu">
      <header className="composer-model-menu__provider">
        <span className="composer-model-menu__provider-icon" aria-hidden="true">
          <TerminalIcon size={14} />
        </span>
        <span className="composer-model-menu__provider-name" title={providerLabel}>
          {providerLabel}
        </span>
        <span
          className="composer-model-menu__provider-pill"
          title={providerConfig.protocol || "API"}
        >
          API
        </span>
        <ComposerIconButton
          icon={<RefreshIcon size={14} />}
          label={refreshModelsLabel}
          ariaLabel={refreshModelsLabel}
          title={refreshModelsTitle}
          active={providerConfig.modelListStatus === "loading"}
          disabled={refreshModelsDisabled}
          onClick={onRefreshModels}
        />
      </header>

      <label className="composer-model-menu__search">
        <SearchIcon size={14} />
        <span className="sr-only">{searchLabel}</span>
        <input
          ref={modelSearchRef}
          type="search"
          value={modelQuery}
          onChange={(event) => onModelQueryChange(event.target.value)}
          placeholder={searchLabel}
        />
      </label>

      <div className="composer-model-menu__scroll">
        {showModelSection ? (
          visibleSelectionCount > 0 ? (
            <div className="composer-provider-groups">
              {displayedModels.length > 0 ? (
                <div
                  className="composer-provider-list"
                  role="list"
                  aria-label={modelSectionLabel}
                >
                  {displayedModels.map((profile) => {
                    const policyHint = composerModelPolicyHint(
                      composerLanguage,
                      profile.policyReason,
                    );
                    const modelDisabled = profile.isActive || profile.isSelectable === false;
                    const explicitModelContextTokens =
                      providerConfig.modelTokenLimits?.[profile.model]
                        ?.contextWindowTokens ?? providerConfig.contextWindowTokens;
                    const modelContextTokens =
                      explicitModelContextTokens ??
                      resolveEffectiveTokenBudgetProfile({
                        model: profile.model,
                        protocol: providerConfig.protocol,
                        baseUrl: providerConfig.baseUrl,
                        providerName: providerConfig.name,
                      }).effectiveContextWindowTokens;
                    const modelContextHint = modelContextTokens
                      ? localize(composerLanguage, "上下文 {n}").replace(
                          "{n}",
                          formatCompactTokenLimit(modelContextTokens) || String(modelContextTokens),
                        )
                      : undefined;
                    const vision = modelHasVision(profile.model);
                    const savedThinkingLabel = savedThinkingLabelFor(
                      providerConfig.modelThinkingConfig?.[profile.model],
                    );
                    return (
                      <button
                        key={profile.id}
                        className={`composer-provider-list__item ${profile.isActive ? "is-active" : ""}`}
                        type="button"
                        disabled={modelDisabled}
                        aria-current={profile.isActive ? "true" : undefined}
                        title={
                          [modelContextHint, policyHint].filter(Boolean).join(" · ") ||
                          profile.model
                        }
                        onClick={() => onSwitchModel(profile.model)}
                      >
                        <span className="composer-model-menu__row">
                          <span className="composer-provider-list__model">{profile.model}</span>
                          {vision ? (
                            <span className="composer-model-menu__vision">
                              <EyeIcon size={12} />
                              {visionLabel}
                            </span>
                          ) : null}
                          {savedThinkingLabel ? (
                            <span
                              className="composer-model-menu__thinking-badge"
                              title={localizeAlt(composerLanguage, "思考强度")}
                            >
                              {THINKING_LABEL[composerLanguage]} {savedThinkingLabel}
                            </span>
                          ) : null}
                          {profile.isActive ? (
                            <span className="composer-provider-list__state">
                              <CheckMarkIcon size={14} />
                              <span className="sr-only">{providerCopy.modelPicker.currentModel}</span>
                            </span>
                          ) : null}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : null}

              {visibleOtherGroups.map((group) => (
                <section
                  key={group.id}
                  className="composer-model-menu__provider-group"
                  aria-label={group.label}
                >
                  <div className="composer-model-menu__group-header">
                    <span className="composer-model-menu__group-icon" aria-hidden="true">
                      <TerminalIcon size={12} />
                    </span>
                    <span className="composer-model-menu__group-name">{group.label}</span>
                    <span className="composer-model-menu__provider-pill">API</span>
                  </div>
                  <div
                    className="composer-provider-list"
                    role="list"
                    aria-label={group.label}
                  >
                    {group.models.map((model) => {
                      const groupThinkingLabel = savedThinkingLabelFor(
                        group.thinkingByModel[model],
                      );
                      return (
                        <button
                          key={`${group.id}:${model}`}
                          className="composer-provider-list__item"
                          type="button"
                          title={model}
                          onClick={() => onSwitchProviderModel(group.id, model)}
                        >
                          <span className="composer-model-menu__row">
                            <span className="composer-provider-list__model">{model}</span>
                            {group.visionModels.has(model) ? (
                              <span className="composer-model-menu__vision">
                                <EyeIcon size={12} />
                                {visionLabel}
                              </span>
                            ) : null}
                            {groupThinkingLabel ? (
                              <span
                                className="composer-model-menu__thinking-badge"
                                title={localizeAlt(composerLanguage, "思考强度")}
                              >
                                {THINKING_LABEL[composerLanguage]} {groupThinkingLabel}
                              </span>
                            ) : null}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          ) : (
            <p className="composer-menu-panel__hint">{emptyStateLabel}</p>
          )
        ) : null}
      </div>

      {thinkingDescriptor && thinkingStops ? (
        <footer className="composer-model-menu__thinking">
          <div className="composer-model-menu__thinking-header">
            <span>{localize(composerLanguage, "思考强度")}</span>
            {effortOptions && !thinkingDescriptor.disabled ? (
              <button
                type="button"
                className="composer-model-menu__thinking-value"
                title={localize(composerLanguage, "点击在 自动 / 关闭 / 开启 之间切换")}
                onClick={onCycleEffortMode}
              >
                {thinkingValueLabel}
              </button>
            ) : (
              <span className="composer-model-menu__thinking-value">
                {thinkingDescriptor.disabled ? localize(composerLanguage, "关闭") : thinkingValueLabel}
              </span>
            )}
          </div>
          <input
            className="composer-model-menu__thinking-range"
            type="range"
            min={0}
            max={Math.max(0, thinkingStops.length - 1)}
            step={1}
            value={thinkingIndex}
            disabled={thinkingDescriptor.disabled === true}
            aria-label={localizeAlt(composerLanguage, "思考强度")}
            aria-valuetext={
              thinkingDescriptor.disabled ? localize(composerLanguage, "关闭") : thinkingValueLabel
            }
            onChange={(event) => onThinkingIndexChange(Number(event.target.value))}
            onClick={(event) => {
              if (effortOptions && thinkingDescriptor.config.mode !== "enabled") {
                onThinkingIndexChange(Number(event.currentTarget.value));
              }
            }}
          />
          {thinkingDescriptor.kind === "thinking_budget" ||
          thinkingDescriptor.kind === "gemini_thinking" ||
          typeof thinkingDescriptor.config.budgetTokens === "number" ? (
            <p className="composer-menu-panel__hint">
              {localize(
                composerLanguage,
                typeof thinkingDescriptor.config.budgetTokens === "number"
                  ? "思考预算 {n}，可在“设置”里调整。"
                  : "思考预算 自动，可在“设置”里调整。",
              ).replace(
                "{n}",
                typeof thinkingDescriptor.config.budgetTokens === "number"
                  ? formatCompactTokenLimit(thinkingDescriptor.config.budgetTokens) ||
                      String(thinkingDescriptor.config.budgetTokens)
                  : "",
              )}
            </p>
          ) : null}
        </footer>
      ) : null}
    </section>
  );
}
