/**
 * TrainingMemoryPanel Component
 *
 * Displays the layered memory architecture in a humanized, accessible way.
 * Shows:
 * - Master plan memory (long-term goals)
 * - Project memory (current project context)
 * - Session memory (current conversation)
 * - Training memory (FSRS cards, mastery state)
 * - Resource memory (learned resources)
 *
 * Reference: docs/open-source-fit-and-provider-strategy.md §11 (memory layers)
 */

import React, { useState } from "react";
import { ChevronDownIcon, ChevronRightIcon, BrainIcon, FolderIcon, FileIcon, LightBulbIcon, BookOpenIcon } from "../icons";
import type { ComposerLanguage } from "../../lib/types";

export interface MemoryLayer {
  id: string;
  name: string;
  description: string;
  status: "active" | "idle" | "syncing" | "error";
  itemCount: number;
  lastUpdated: Date;
  /** Summary text for this layer */
  summary?: string;
  /** Key items in this layer */
  highlights?: Array<{
    id: string;
    label: string;
    type: "concept" | "skill" | "resource" | "goal" | "pattern";
    description?: string;
  }>;
  /** Expandable detail */
  details?: string[];
}

/** Type for highlight items used in the component */
export type MemoryLayerHighlight = NonNullable<MemoryLayer["highlights"]>[0];
export type HighlightType = MemoryLayerHighlight["type"];

export interface TrainingMemoryPanelProps {
  /** Current language */
  language: "zh-CN" | "en-US";
  /** All memory layers */
  layers: MemoryLayer[];
  /** Which layer is currently active/focused */
  activeLayerId?: string;
  /** Callback when user selects a layer */
  onLayerSelect?: (layerId: string) => void;
  /** Callback when user clicks to expand layer details */
  onLayerExpand?: (layerId: string) => void;
  /** Callback when user wants to add memory to a layer */
  onAddMemory?: (layerId: string) => void;
}

/**
 * Get icon for memory layer type
 */
function getLayerIcon(layerId: string): React.ReactNode {
  const icons: Record<string, React.ReactNode> = {
    master: <BrainIcon size={16} />,
    project: <FolderIcon size={16} />,
    session: <FileIcon size={16} />,
    training: <LightBulbIcon size={16} />,
    resource: <BookOpenIcon size={16} />,
  };
  return icons[layerId] ?? <BrainIcon size={16} />;
}

/** §十五: relative-time copy in eight languages (no zh/en binary). */
interface TrainingRelativeTimeCopy {
  justNow: string;
  minutesAgo: (amount: number) => string;
  hoursAgo: (amount: number) => string;
  daysAgo: (amount: number) => string;
  weekAgo: string;
}

const trainingRelativeTimeCopy: Record<ComposerLanguage, TrainingRelativeTimeCopy> = {
  "zh-CN": {
    justNow: "刚刚",
    minutesAgo: (amount) => `${amount} 分钟前`,
    hoursAgo: (amount) => `${amount} 小时前`,
    daysAgo: (amount) => `${amount} 天前`,
    weekAgo: "一周前",
  },
  "en-US": {
    justNow: "Just now",
    minutesAgo: (amount) => `${amount} min ago`,
    hoursAgo: (amount) => `${amount} hr ago`,
    daysAgo: (amount) => `${amount} days ago`,
    weekAgo: "A week ago",
  },
  "es-ES": {
    justNow: "Justo ahora",
    minutesAgo: (amount) => `hace ${amount} min`,
    hoursAgo: (amount) => `hace ${amount} h`,
    daysAgo: (amount) => `hace ${amount} días`,
    weekAgo: "Hace una semana",
  },
  "fr-FR": {
    justNow: "À l'instant",
    minutesAgo: (amount) => `il y a ${amount} min`,
    hoursAgo: (amount) => `il y a ${amount} h`,
    daysAgo: (amount) => `il y a ${amount} j`,
    weekAgo: "Il y a une semaine",
  },
  "de-DE": {
    justNow: "Gerade eben",
    minutesAgo: (amount) => `vor ${amount} Min.`,
    hoursAgo: (amount) => `vor ${amount} Std.`,
    daysAgo: (amount) => `vor ${amount} Tagen`,
    weekAgo: "Vor einer Woche",
  },
  "ja-JP": {
    justNow: "たった今",
    minutesAgo: (amount) => `${amount}分前`,
    hoursAgo: (amount) => `${amount}時間前`,
    daysAgo: (amount) => `${amount}日前`,
    weekAgo: "1週間前",
  },
  "ko-KR": {
    justNow: "방금 전",
    minutesAgo: (amount) => `${amount}분 전`,
    hoursAgo: (amount) => `${amount}시간 전`,
    daysAgo: (amount) => `${amount}일 전`,
    weekAgo: "1주 전",
  },
  "pt-BR": {
    justNow: "Agora mesmo",
    minutesAgo: (amount) => `há ${amount} min`,
    hoursAgo: (amount) => `há ${amount} h`,
    daysAgo: (amount) => `há ${amount} dias`,
    weekAgo: "Há uma semana",
  },
};

/**
 * Format relative time (elapsed-time bucketing stays here; copy lives in the
 * eight-language record).
 */
function formatRelativeTime(date: Date, language: ComposerLanguage): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  const copy = trainingRelativeTimeCopy[language];

  if (diffMins < 1) {
    return copy.justNow;
  }
  if (diffMins < 60) {
    return copy.minutesAgo(diffMins);
  }
  if (diffHours < 24) {
    return copy.hoursAgo(diffHours);
  }
  if (diffDays < 7) {
    return copy.daysAgo(diffDays);
  }
  return copy.weekAgo;
}

type TrainingMemoryTextKey =
  | "titleLabel"
  | "itemsLabel"
  | "updatedLabel"
  | "addMemoryLabel"
  | "noLayersLabel"
  | "totalLabel"
  | "layersActive"
  | "conceptLabel"
  | "skillLabel"
  | "resourceLabel"
  | "goalLabel"
  | "patternLabel";

/** §十五: memory-panel labels in eight languages (no zh/en binary). */
const trainingMemoryTextCopy: Record<ComposerLanguage, Record<TrainingMemoryTextKey, string>> = {
  "zh-CN": {
    titleLabel: "学习记忆",
    itemsLabel: "条记录",
    updatedLabel: "更新于",
    addMemoryLabel: "添加",
    noLayersLabel: "暂无记忆记录",
    totalLabel: "总计",
    layersActive: "层活跃",
    conceptLabel: "概念",
    skillLabel: "技能",
    resourceLabel: "资源",
    goalLabel: "目标",
    patternLabel: "模式",
  },
  "en-US": {
    titleLabel: "Learning Memory",
    itemsLabel: "items",
    updatedLabel: "Updated",
    addMemoryLabel: "Add",
    noLayersLabel: "No memory records yet",
    totalLabel: "Total",
    layersActive: "layers active",
    conceptLabel: "Concept",
    skillLabel: "Skill",
    resourceLabel: "Resource",
    goalLabel: "Goal",
    patternLabel: "Pattern",
  },
  "es-ES": {
    titleLabel: "Memoria de aprendizaje",
    itemsLabel: "elementos",
    updatedLabel: "Actualizado",
    addMemoryLabel: "Añadir",
    noLayersLabel: "Aún no hay registros de memoria",
    totalLabel: "Total",
    layersActive: "capas activas",
    conceptLabel: "Concepto",
    skillLabel: "Habilidad",
    resourceLabel: "Recurso",
    goalLabel: "Meta",
    patternLabel: "Patrón",
  },
  "fr-FR": {
    titleLabel: "Mémoire d'apprentissage",
    itemsLabel: "éléments",
    updatedLabel: "Mis à jour",
    addMemoryLabel: "Ajouter",
    noLayersLabel: "Aucun souvenir enregistré pour le moment",
    totalLabel: "Total",
    layersActive: "couches actives",
    conceptLabel: "Concept",
    skillLabel: "Compétence",
    resourceLabel: "Ressource",
    goalLabel: "Objectif",
    patternLabel: "Motif",
  },
  "de-DE": {
    titleLabel: "Lerngedächtnis",
    itemsLabel: "Einträge",
    updatedLabel: "Aktualisiert",
    addMemoryLabel: "Hinzufügen",
    noLayersLabel: "Noch keine Gedächtniseinträge",
    totalLabel: "Gesamt",
    layersActive: "Ebenen aktiv",
    conceptLabel: "Konzept",
    skillLabel: "Fähigkeit",
    resourceLabel: "Ressource",
    goalLabel: "Ziel",
    patternLabel: "Muster",
  },
  "ja-JP": {
    titleLabel: "学習メモリ",
    itemsLabel: "件",
    updatedLabel: "更新",
    addMemoryLabel: "追加",
    noLayersLabel: "メモリ記録はまだありません",
    totalLabel: "合計",
    layersActive: "層がアクティブ",
    conceptLabel: "概念",
    skillLabel: "スキル",
    resourceLabel: "リソース",
    goalLabel: "目標",
    patternLabel: "パターン",
  },
  "ko-KR": {
    titleLabel: "학습 메모리",
    itemsLabel: "개 항목",
    updatedLabel: "업데이트",
    addMemoryLabel: "추가",
    noLayersLabel: "아직 메모리 기록이 없습니다",
    totalLabel: "합계",
    layersActive: "개 레이어 활성",
    conceptLabel: "개념",
    skillLabel: "스킬",
    resourceLabel: "리소스",
    goalLabel: "목표",
    patternLabel: "패턴",
  },
  "pt-BR": {
    titleLabel: "Memória de aprendizagem",
    itemsLabel: "itens",
    updatedLabel: "Atualizado",
    addMemoryLabel: "Adicionar",
    noLayersLabel: "Ainda sem registros de memória",
    totalLabel: "Total",
    layersActive: "camadas ativas",
    conceptLabel: "Conceito",
    skillLabel: "Habilidade",
    resourceLabel: "Recurso",
    goalLabel: "Meta",
    patternLabel: "Padrão",
  },
};

function trainingMemoryText(language: ComposerLanguage, key: TrainingMemoryTextKey): string {
  return trainingMemoryTextCopy[language]?.[key] ?? trainingMemoryTextCopy["en-US"][key];
}

/**
 * Get item type label and icon
 */
function getItemTypeInfo(
  type: HighlightType,
  language: ComposerLanguage
): { label: string } {
  const info: Record<HighlightType, { label: string }> = {
    concept: {
      label: trainingMemoryText(language, "conceptLabel"),
    },
    skill: {
      label: trainingMemoryText(language, "skillLabel"),
    },
    resource: {
      label: trainingMemoryText(language, "resourceLabel"),
    },
    goal: {
      label: trainingMemoryText(language, "goalLabel"),
    },
    pattern: {
      label: trainingMemoryText(language, "patternLabel"),
    },
  };
  return info[type];
}

export const TrainingMemoryPanel: React.FC<TrainingMemoryPanelProps> = ({
  language,
  layers,
  activeLayerId,
  onLayerSelect,
  onLayerExpand,
  onAddMemory,
}) => {
  const [expandedLayers, setExpandedLayers] = useState<Set<string>>(new Set());

  const toggleExpanded = (layerId: string) => {
    setExpandedLayers((prev) => {
      const next = new Set(prev);
      if (next.has(layerId)) {
        next.delete(layerId);
      } else {
        next.add(layerId);
      }
      return next;
    });
    onLayerExpand?.(layerId);
  };

  // Labels
  const titleLabel = trainingMemoryText(language, "titleLabel");
  const itemsLabel = trainingMemoryText(language, "itemsLabel");
  const updatedLabel = trainingMemoryText(language, "updatedLabel");
  const addMemoryLabel = trainingMemoryText(language, "addMemoryLabel");
  const noLayersLabel = trainingMemoryText(language, "noLayersLabel");
  const totalLabel = trainingMemoryText(language, "totalLabel");

  // Calculate total stats
  const totalItems = layers.reduce((sum, layer) => sum + layer.itemCount, 0);
  const activeLayers = layers.filter((l) => l.status === "active").length;

  return (
    <div className="training-memory-panel">
      {/* Header */}
      <div className="memory-header">
        <div className="memory-title-row">
          <BrainIcon size={18} />
          <span className="memory-title">{titleLabel}</span>
        </div>
        <div className="memory-summary">
          {activeLayers} / {layers.length} {trainingMemoryText(language, "layersActive")}
          <span className="memory-divider">·</span>
          {totalItems} {itemsLabel}
        </div>
      </div>

      {/* Layers list */}
      {layers.length === 0 ? (
        <div className="memory-empty">{noLayersLabel}</div>
      ) : (
        <div className="memory-layers">
          {layers.map((layer) => {
            const isExpanded = expandedLayers.has(layer.id);
            const isActive = activeLayerId === layer.id;
            const icon = getLayerIcon(layer.id);

            return (
              <div
                key={layer.id}
                className={`memory-layer ${isActive ? "is-active" : ""}`}
              >
                {/* Layer header */}
                <button
                  className="layer-header"
                  onClick={() => onLayerSelect?.(layer.id)}
                  type="button"
                >
                  {/* Status indicator */}
                  <div
                    className={`layer-status layer-status--${layer.status}`}
                    title={layer.status}
                  />

                  {/* Icon and name */}
                  <div className="layer-identity">
                    <div className="layer-icon">{icon}</div>
                    <div className="layer-name-group">
                      <div className="layer-name">{layer.name}</div>
                      <div className="layer-description">{layer.description}</div>
                    </div>
                  </div>

                  {/* Stats */}
                  <div className="layer-stats">
                    <div className="layer-item-count">
                      {layer.itemCount}
                      <span className="layer-item-label">{itemsLabel}</span>
                    </div>
                    <div className="layer-updated">
                      {formatRelativeTime(layer.lastUpdated, language)}
                    </div>
                  </div>

                  {/* Expand toggle */}
                  {layer.details && layer.details.length > 0 && (
                    <button
                      className="layer-expand-toggle"
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleExpanded(layer.id);
                      }}
                      type="button"
                      aria-expanded={isExpanded}
                    >
                      {isExpanded ? (
                        <ChevronDownIcon size={14} />
                      ) : (
                        <ChevronRightIcon size={14} />
                      )}
                    </button>
                  )}
                </button>

                {/* Expanded details */}
                {isExpanded && layer.details && (
                  <div className="layer-details">
                    {/* Summary */}
                    {layer.summary && (
                      <div className="layer-summary">{layer.summary}</div>
                    )}

                    {/* Highlights */}
                    {layer.highlights && layer.highlights.length > 0 && (
                      <div className="layer-highlights">
                        {layer.highlights.map((item) => {
                          const typeInfo = getItemTypeInfo(item.type, language);
                          return (
                            <div
                              key={item.id}
                              className={`highlight-item highlight-item--${item.type}`}
                            >
                              <span
                                className={`highlight-type highlight-type--${item.type}`}
                              >
                                {typeInfo.label}
                              </span>
                              <span className="highlight-label">{item.label}</span>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Details list */}
                    {layer.details.length > 0 && (
                      <div className="layer-details-list">
                        {layer.details.map((detail, index) => (
                          <div key={index} className="detail-item">
                            {detail}
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Add memory button */}
                    {onAddMemory && (
                      <button
                        className="add-memory-button"
                        onClick={() => onAddMemory(layer.id)}
                        type="button"
                      >
                        + {addMemoryLabel}
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Footer stats */}
      <div className="memory-footer">
        <div className="footer-stat">
          <span className="footer-label">{totalLabel}:</span>
          <span className="footer-value">{totalItems} {itemsLabel}</span>
        </div>
      </div>
    </div>
  );
};
