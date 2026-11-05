import type { ComposerLanguage, ProviderConfigView } from "../../lib/types";
import type { Copy } from "../../lib/i18n/copyTypes";
import type {
  ProviderThinkingConfig,
  ProviderThinkingDescriptor,
} from "../../../../../shared/src/providerThinking";
import type { ComposerProviderMenuItem } from "../../lib/composerModelHelpers";
import { composerModelPolicyHint } from "../../lib/composerModelHelpers";
import { formatTokenCount } from "../../lib/formatUtils";
import { ComposerIconButton } from "./ComposerIconButton";
import { CheckMarkIcon, RefreshIcon } from "../icons";

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
  onSwitchProfile: (profileId: string) => void;
  initialOptionLimit: number;
}

/**
 * Composer 的“切换模型”菜单面板 (P2 模块化第二块，自 App.tsx 迁出)。
 * 纯展示切片：模型搜索/思考强度/模型与已保存连接分组，无内部状态，
 * 行为与迁出前一致。
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
  onSwitchProfile,
  initialOptionLimit,
}: ComposerModelMenuProps) {
  const providerApplied = providerConfig.configured;
  const visibleSelections = filteredMenuItems;
  const visibleModels = visibleSelections.filter(
    (profile) => profile.selectionKind === "model",
  );
  const visibleProfiles = visibleSelections.filter(
    (profile) => profile.selectionKind === "profile" && !profile.isActive,
  );
  const savedProfiles = menuItems.filter(
    (profile) => profile.selectionKind === "profile" && !profile.isActive,
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
  const displayedModels = hasModelQuery
    ? [
        ...(retainedBlockedActiveModel ? [retainedBlockedActiveModel] : []),
        ...visibleModels.filter((item) => item.id !== retainedBlockedActiveModel?.id),
      ]
    : [
        ...(retainedBlockedActiveModel ? [retainedBlockedActiveModel] : []),
        ...defaultVisibleModels,
      ];
  const nonActiveModelCount = menuItems.filter(
    (item) => item.selectionKind === "model" && !item.isActive,
  ).length;
  const hasOnlyCurrentModel =
    Boolean(activeModelItem) && nonActiveModelCount === 0 && savedProfiles.length === 0;
  const showModelSection =
    hasModelQuery || defaultVisibleModels.length > 0 || hasOnlyCurrentModel;
  const searchLabel = localize(composerLanguage, "搜索模型或已保存连接");
  const emptyStateLabel = hasModelQuery
    ? localize(composerLanguage, "没有匹配的模型或已保存连接。")
    : hasOnlyCurrentModel
      ? providerCopy.modelPicker.onlyCurrentModel
      : hasSavedProfiles
        ? localize(composerLanguage, "可从下方展开已保存连接。")
        : localize(composerLanguage, "还没有可切换的模型。请到“设置”保存连接。");

  const visibleSelectionCount = displayedModels.length + (hasModelQuery ? visibleProfiles.length : 0);
  const showSearch = nonActiveModelCount > initialOptionLimit;
  const modelSectionLabel = hasModelQuery
    ? localize(composerLanguage, "匹配的模型")
    : localize(composerLanguage, "可切换模型");
  const profileSectionLabel = localize(composerLanguage, "已保存连接");
  const refreshModelsDisabled =
    !providerApplied ||
    !providerConfig.apiKeyConfigured ||
    providerConfig.modelListStatus === "loading";
  const refreshModelsLabel = localize(composerLanguage, "刷新模型");
  const refreshModelsTitle = !providerApplied
    ? localize(composerLanguage, "先保存连接，再更新模型列表")
    : !providerConfig.apiKeyConfigured
      ? localize(composerLanguage, "先在“设置”填写访问密钥，再更新模型列表")
      : providerConfig.modelListStatus === "loading"
        ? localize(composerLanguage, "正在更新模型列表")
        : localize(composerLanguage, "更新模型列表");

  return (
    <section className="composer-menu-panel composer-menu-panel--provider">
      <div className="composer-menu-panel__header">
        <span className="eyebrow">{copy.chatModel}</span>
        <div className="composer-menu-panel__header-actions">
          <ComposerIconButton
            icon={<RefreshIcon size={14} />}
            label={refreshModelsLabel}
            ariaLabel={refreshModelsLabel}
            title={refreshModelsTitle}
            active={providerConfig.modelListStatus === "loading"}
            disabled={refreshModelsDisabled}
            onClick={onRefreshModels}
          />
        </div>
      </div>

      {showSearch || hasModelQuery ? (
        <label className="resources-search resources-search--hero composer-menu-panel__search">
          <span className="sr-only">{searchLabel}</span>
          <input
            ref={modelSearchRef}
            type="search"
            value={modelQuery}
            onChange={(event) => onModelQueryChange(event.target.value)}
            placeholder={searchLabel}
          />
        </label>
      ) : null}

      {thinkingDescriptor ? (
        <div className="composer-menu-panel__section composer-thinking">
          <div className="composer-thinking__header">
            <span className="eyebrow">{localize(composerLanguage, "思考强度")}</span>
            {thinkingDescriptor.disabled ? (
              <span className="composer-thinking__state">
                {localize(composerLanguage, "已关闭")}
              </span>
            ) : null}
          </div>
          <div
            className="composer-thinking__modes"
            role="group"
            aria-label={localizeAlt(composerLanguage, "思考强度")}
          >
            {(
              [
                { value: "auto", label: localize(composerLanguage, "自动") },
                { value: "disabled", label: localize(composerLanguage, "关闭") },
                { value: "enabled", label: localize(composerLanguage, "开启") },
              ] as const
            ).map((option) => {
              const active = thinkingDescriptor.config.mode === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  className={`composer-thinking__mode ${active ? "is-active" : ""}`}
                  aria-pressed={active}
                  onClick={() =>
                    onThinkingChange({
                      ...thinkingDescriptor.config,
                      mode: option.value,
                      // "On" must carry a concrete effort or nothing is
                      // emitted and the toggle falls back to "auto".
                      ...(option.value === "enabled" &&
                      thinkingDescriptor.kind === "reasoning_effort" &&
                      !thinkingDescriptor.config.reasoningEffort
                        ? { reasoningEffort: "medium" as const }
                        : {}),
                    })
                  }
                >
                  {option.label}
                </button>
              );
            })}
          </div>
          {thinkingDescriptor.config.mode === "enabled" &&
          thinkingDescriptor.kind === "reasoning_effort" &&
          thinkingDescriptor.effortOptions ? (
            <div
              className="composer-thinking__modes composer-thinking__modes--effort"
              role="group"
              aria-label={localize(composerLanguage, "推理力度")}
            >
              {thinkingDescriptor.effortOptions.map((option) => {
                const active =
                  (thinkingDescriptor.config.reasoningEffort ?? "medium") === option;
                return (
                  <button
                    key={option}
                    type="button"
                    className={`composer-thinking__mode ${active ? "is-active" : ""}`}
                    aria-pressed={active}
                    onClick={() =>
                      onThinkingChange({
                        ...thinkingDescriptor.config,
                        mode: "enabled",
                        reasoningEffort: option,
                      })
                    }
                  >
                    {option === "low"
                      ? localize(composerLanguage, "低")
                      : option === "high"
                        ? localize(composerLanguage, "高")
                        : localize(composerLanguage, "中")}
                  </button>
                );
              })}
            </div>
          ) : null}
          {thinkingDescriptor.config.mode === "enabled" &&
          (thinkingDescriptor.kind === "thinking_budget" ||
            thinkingDescriptor.kind === "gemini_thinking") ? (
            <p className="composer-menu-panel__hint">
              {localize(
                composerLanguage,
                typeof thinkingDescriptor.config.budgetTokens === "number"
                  ? "思考预算 {n}，可在“设置”里调整。"
                  : "思考预算 自动，可在“设置”里调整。",
              ).replace(
                "{n}",
                typeof thinkingDescriptor.config.budgetTokens === "number"
                  ? String(thinkingDescriptor.config.budgetTokens)
                  : "",
              )}
            </p>
          ) : null}
        </div>
      ) : null}

      {showModelSection ? (
        <div className="composer-menu-panel__section">
          {visibleSelectionCount > 0 ? (
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
                    const modelContextTokens =
                      providerConfig.modelTokenLimits?.[profile.model]
                        ?.contextWindowTokens ?? providerConfig.contextWindowTokens;
                    const modelContextHint = modelContextTokens
                      ? localize(composerLanguage, "上下文 {n}").replace(
                          "{n}",
                          formatTokenCount(modelContextTokens),
                        )
                      : undefined;
                    return (
                      <button
                        key={profile.id}
                        className={`composer-provider-list__item ${profile.isActive ? "is-active" : ""}`}
                        type="button"
                        disabled={modelDisabled}
                        aria-current={profile.isActive ? "true" : undefined}
                        title={
                          [policyHint, modelContextHint].filter(Boolean).join(" · ") ||
                          profile.model
                        }
                        onClick={() => onSwitchModel(profile.model)}
                      >
                        <div className="composer-provider-list__row">
                          <span className="composer-provider-list__stack">
                            <span className="composer-provider-list__model">{profile.model}</span>
                            {modelContextHint || policyHint ? (
                              <span className="composer-provider-list__label">
                                {[modelContextHint, policyHint].filter(Boolean).join(" · ")}
                              </span>
                            ) : null}
                          </span>
                          {profile.isActive ? (
                            <span className="composer-provider-list__state">
                              <CheckMarkIcon size={12} />
                              <span className="sr-only">{providerCopy.modelPicker.currentModel}</span>
                            </span>
                          ) : null}
                        </div>
                      </button>
                    );
                  })}
                </div>
              ) : null}

              {hasModelQuery && visibleProfiles.length > 0 ? (
                <section className="composer-provider-group">
                  <div className="composer-provider-group__header">
                    <span className="eyebrow">{profileSectionLabel}</span>
                  </div>
                  <div
                    className="composer-provider-list"
                    role="list"
                    aria-label={localize(composerLanguage, "已保存连接")}
                  >
                    {visibleProfiles.map((profile) => (
                      <button
                        key={profile.id}
                        className="composer-provider-list__item"
                        type="button"
                        title={profile.model}
                        onClick={() => onSwitchProfile(profile.id)}
                      >
                        <div className="composer-provider-list__row">
                          <span className="composer-provider-list__stack">
                            <span className="composer-provider-list__model">{profile.label}</span>
                            <span className="composer-provider-list__label">{profile.model}</span>
                          </span>
                        </div>
                      </button>
                    ))}
                  </div>
                </section>
              ) : null}
            </div>
          ) : (
            <p className="composer-menu-panel__hint">{emptyStateLabel}</p>
          )}
        </div>
      ) : null}

      {!hasModelQuery && savedProfiles.length > 0 ? (
        <details className="composer-provider-group">
          <summary className="composer-provider-group__header">
            <span className="eyebrow">{profileSectionLabel}</span>
          </summary>
          <div
            className="composer-provider-list"
            role="list"
            aria-label={localize(composerLanguage, "已保存连接")}
          >
            {savedProfiles.map((profile) => (
              <button
                key={profile.id}
                className="composer-provider-list__item"
                type="button"
                title={profile.model}
                onClick={() => onSwitchProfile(profile.id)}
              >
                <div className="composer-provider-list__row">
                  <span className="composer-provider-list__stack">
                    <span className="composer-provider-list__model">{profile.label}</span>
                    <span className="composer-provider-list__label">{profile.model}</span>
                  </span>
                </div>
              </button>
            ))}
          </div>
        </details>
      ) : null}

      {!hasModelQuery && !showSearch && !providerApplied && savedProfiles.length === 0 ? (
        <p className="composer-menu-panel__hint">{emptyStateLabel}</p>
      ) : null}
    </section>
  );
}
