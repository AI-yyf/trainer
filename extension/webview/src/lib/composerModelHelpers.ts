/**
 * Composer model helper functions (§四十八: extracted from App.tsx).
 * Pure functions — no React or state dependencies.
 */

import type { ComposerLanguage, ProviderConfigView } from "./types";
import type { ProviderModelPolicyReason } from "../../../../shared/src/providerModelPolicy";
import {
  evaluateProviderModelPolicy,
  filterProviderModelOptions,
} from "../../../../shared/src/providerModelPolicy";

export type ComposerProviderMenuItem = {
  id: string;
  selectionKind: "profile" | "model";
  label: string;
  model: string;
  isActive: boolean;
  isSelectable?: boolean;
  policyReason?: ProviderModelPolicyReason;
};

export function composerModelPolicyHint(
  language: ComposerLanguage,
  reason: ProviderModelPolicyReason | undefined,
): string | undefined {
  if (reason !== "denied" && reason !== "not_allowed") {
    return undefined;
  }

  const denied = reason === "denied";
  switch (language) {
    case "zh-CN":
      return denied
        ? "\u8fd9\u4e2a\u8fde\u63a5\u5df2\u505c\u7528\u5f53\u524d\u6a21\u578b\uff0c\u8bf7\u4ece\u5217\u8868\u91cc\u91cd\u65b0\u9009\u4e00\u4e2a\u3002"
        : "\u5f53\u524d\u6a21\u578b\u4e0d\u5728\u8fd9\u4e2a\u8fde\u63a5\u7684\u53ef\u7528\u8303\u56f4\u5185\uff0c\u8bf7\u4ece\u5217\u8868\u91cc\u91cd\u65b0\u9009\u4e00\u4e2a\u3002";
    case "es-ES":
      return denied
        ? "Este modelo esta desactivado para esta conexion. Elige uno de la lista."
        : "El modelo actual no esta en la lista permitida de esta conexion. Elige uno de la lista.";
    case "fr-FR":
      return denied
        ? "Ce modele est desactive pour cette connexion. Choisissez-en un dans la liste."
        : "Le modele actuel ne fait pas partie de la liste autorisee pour cette connexion. Choisissez-en un dans la liste.";
    case "de-DE":
      return denied
        ? "Dieses Modell ist fuer diese Verbindung deaktiviert. Waehle eines aus der Liste."
        : "Das aktuelle Modell ist fuer diese Verbindung nicht freigegeben. Waehle eines aus der Liste.";
    case "ja-JP":
      return denied
        ? "\u3053\u306e\u63a5\u7d9a\u3067\u306f\u73fe\u5728\u306e\u30e2\u30c7\u30eb\u306f\u4f7f\u3048\u307e\u305b\u3093\u3002\u4e00\u89a7\u304b\u3089\u9078\u3073\u76f4\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
        : "\u73fe\u5728\u306e\u30e2\u30c7\u30eb\u306f\u3053\u306e\u63a5\u7d9a\u306e\u4f7f\u7528\u7bc4\u56f2\u306b\u542b\u307e\u308c\u3066\u3044\u307e\u305b\u3093\u3002\u4e00\u89a7\u304b\u3089\u9078\u3073\u76f4\u3057\u3066\u304f\u3060\u3055\u3044\u3002";
    case "ko-KR":
      return denied
        ? "\uc774 \uc5f0\uacb0\uc5d0\uc11c\ub294 \ud604\uc7ac \ubaa8\ub378\uc744 \uc0ac\uc6a9\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4. \ubaa9\ub85d\uc5d0\uc11c \ub2e4\uc2dc \uc120\ud0dd\ud558\uc138\uc694."
        : "\ud604\uc7ac \ubaa8\ub378\uc740 \uc774 \uc5f0\uacb0\uc758 \uc0ac\uc6a9 \ubc94\uc704\uc5d0 \ud3ec\ud568\ub418\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4. \ubaa9\ub85d\uc5d0\uc11c \ub2e4\uc2dc \uc120\ud0dd\ud558\uc138\uc694.";
    case "pt-BR":
      return denied
        ? "Este modelo esta desativado para esta conexao. Escolha um da lista."
        : "O modelo atual nao esta na lista permitida desta conexao. Escolha um da lista.";
    default:
      return denied
        ? "This connection has turned off the current model. Choose one from the list."
        : "The current model is not in the allowed list for this connection. Choose one from the list.";
  }
}

/** §十五: composer model fallback labels in eight languages (no zh/en binary). */
const COMPOSER_MODEL_TEXT: Record<string, Record<ComposerLanguage, string>> = {
  "模型": {
    "zh-CN": "模型",
    "en-US": "Model",
    "es-ES": "Modelo",
    "fr-FR": "Modèle",
    "de-DE": "Modell",
    "ja-JP": "モデル",
    "ko-KR": "모델",
    "pt-BR": "Modelo",
  },
  "当前连接": {
    "zh-CN": "当前连接",
    "en-US": "Current connection",
    "es-ES": "Conexión actual",
    "fr-FR": "Connexion actuelle",
    "de-DE": "Aktuelle Verbindung",
    "ja-JP": "現在の接続",
    "ko-KR": "현재 연결",
    "pt-BR": "Conexão atual",
  },
};

function composerModelCopy(language: ComposerLanguage, key: string): string {
  return COMPOSER_MODEL_TEXT[key]?.[language] ?? COMPOSER_MODEL_TEXT[key]?.["en-US"] ?? key;
}

export function compactComposerModelLabel(
  modelLabel: string,
  _providerLabel: string | undefined,
  language: ComposerLanguage,
): string {
  const normalized = modelLabel.trim();
  if (!normalized) {
    return composerModelCopy(language, "模型");
  }
  const tail = normalized.split("/").filter(Boolean).pop() ?? normalized;
  return (
    tail
      .replace(/[-_ ]compatible$/i, "")
      .replace(/[:/](latest|default)$/i, "")
      .trim() || normalized
  );
}

/**
 * Builds the model-menu entries: one item per known model for the active
 * connection, then saved connection profiles (active one first). Falls back
 * to a single synthetic profile entry when nothing else is available
 * (§四十八: extracted from App.tsx).
 */
export function buildComposerProviderMenuItems(
  provider: ProviderConfigView,
  language: ComposerLanguage,
): ComposerProviderMenuItem[] {
  const providerApplied = provider.configured;
  const activeProfileId = providerApplied ? provider.profileId?.trim() : undefined;
  const resolvedModel = provider.resolvedModel?.trim() ?? "";
  const configuredModel = provider.model.trim();
  const activeModel = providerApplied ? resolvedModel || configuredModel : "";
  const activeModelKey = activeModel.toLowerCase();
  const resolvedModelKey = resolvedModel.toLowerCase();
  const configuredModelKey = configuredModel.toLowerCase();
  const configuredModelIsAlias = Boolean(
    resolvedModelKey && configuredModelKey && resolvedModelKey !== configuredModelKey,
  );
  // P0 "all known models": the menu exposes every model Trainer knows about —
  // discovered live models, the saved catalog, manually added IDs, and the
  // current selection — merged instead of the live list shadowing the rest.
  const liveModels = Array.isArray(provider.availableModels) ? provider.availableModels : [];
  const fallbackModels = [
    ...(Array.isArray(provider.catalogModels) ? provider.catalogModels : []),
    ...Object.keys(provider.modelTokenLimits ?? {}),
  ];
  const modelCandidates = providerApplied
    ? [...liveModels, ...fallbackModels, resolvedModel, configuredModel]
    : [];
  const currentProviderModelPolicy = {
    allowedModels: provider.allowedModels,
    deniedModels: provider.deniedModels,
  };
  const filteredModelCandidates = filterProviderModelOptions(
    modelCandidates,
    currentProviderModelPolicy,
    { retainModels: activeModel ? [activeModel] : [] },
  );
  const knownModelMap = new Map<string, string>();
  for (const candidate of filteredModelCandidates) {
    const modelName = typeof candidate === "string" ? candidate.trim() : "";
    const modelKey = modelName.toLowerCase();
    if (
      !modelName ||
      (configuredModelIsAlias && modelKey === configuredModelKey) ||
      knownModelMap.has(modelKey)
    ) {
      continue;
    }
    knownModelMap.set(modelKey, modelName);
  }
  const knownModels = Array.from(knownModelMap.values());
  const activeProviderLabel =
    provider.profileLabel?.trim() ??
    provider.name?.trim() ??
    composerModelCopy(language, "当前连接");
  const activeProviderModelItems =
    knownModels.length > 0
      ? knownModels.map((modelName) => {
          const modelPolicy = evaluateProviderModelPolicy(modelName, currentProviderModelPolicy);
          const isActive = modelName.toLowerCase() === activeModelKey;
          return {
            id: `model:${modelName}`,
            selectionKind: "model" as const,
            label: modelName,
            model: modelName,
            isActive,
            isSelectable: modelPolicy.allowed && !isActive,
            policyReason: modelPolicy.reason,
          };
        })
      : [];
  const profileRecords = Array.isArray(provider.providerProfiles)
    ? provider.providerProfiles
    : [];
  const items = profileRecords
    .map((profile) => {
      if (!profile || typeof profile !== "object" || Array.isArray(profile)) {
        return undefined;
      }

      const record = profile as Record<string, unknown>;
      const id = typeof record.id === "string" ? record.id.trim() : "";
      if (!id) {
        return undefined;
      }

      const label =
        typeof record.label === "string" && record.label.trim()
          ? record.label.trim()
          : typeof record.name === "string" && record.name.trim()
            ? record.name.trim()
            : id;
      const model =
        typeof record.model === "string" && record.model.trim()
          ? record.model.trim()
          : provider.model;
      return {
        id,
        selectionKind: "profile" as const,
        label,
        model,
        isActive: activeProfileId ? activeProfileId === id : false,
      };
    })
    .filter(Boolean) as ComposerProviderMenuItem[];

  if (items.length > 0) {
    const activeIndex = items.findIndex((item) => item.isActive);
    if (activeIndex > 0) {
      const [activeItem] = items.splice(activeIndex, 1);
      if (activeItem) {
        items.unshift(activeItem);
      }
    }
    if (activeProviderModelItems.length > 0) {
      return [...activeProviderModelItems, ...items.filter((item) => !item.isActive)];
    }
    return items;
  }

  if (!providerApplied) {
    return [];
  }

  if (activeProviderModelItems.length > 0) {
    return activeProviderModelItems;
  }

  return [
    {
      id: activeProfileId ?? provider.name ?? "provider",
      selectionKind: "profile",
      label: activeProviderLabel,
      model: activeModel,
      isActive: true,
    },
  ];
}
