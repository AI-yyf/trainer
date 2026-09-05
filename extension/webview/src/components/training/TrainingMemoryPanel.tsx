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

/**
 * Format relative time
 */
function formatRelativeTime(date: Date, language: "zh-CN" | "en-US"): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffMins < 1) {
    return language === "zh-CN" ? "刚刚" : "Just now";
  }
  if (diffMins < 60) {
    return language === "zh-CN" ? `${diffMins} 分钟前` : `${diffMins} min ago`;
  }
  if (diffHours < 24) {
    return language === "zh-CN" ? `${diffHours} 小时前` : `${diffHours} hr ago`;
  }
  if (diffDays < 7) {
    return language === "zh-CN" ? `${diffDays} 天前` : `${diffDays} days ago`;
  }
  return language === "zh-CN" ? "一周前" : "A week ago";
}

/**
 * Get item type label and icon
 */
function getItemTypeInfo(
  type: HighlightType,
  language: "zh-CN" | "en-US"
): { label: string } {
  const info: Record<HighlightType, { label: string }> = {
    concept: {
      label: language === "zh-CN" ? "概念" : "Concept",
    },
    skill: {
      label: language === "zh-CN" ? "技能" : "Skill",
    },
    resource: {
      label: language === "zh-CN" ? "资源" : "Resource",
    },
    goal: {
      label: language === "zh-CN" ? "目标" : "Goal",
    },
    pattern: {
      label: language === "zh-CN" ? "模式" : "Pattern",
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
  const titleLabel = language === "zh-CN" ? "学习记忆" : "Learning Memory";
  const itemsLabel = language === "zh-CN" ? "条记录" : "items";
  const updatedLabel = language === "zh-CN" ? "更新于" : "Updated";
  const addMemoryLabel = language === "zh-CN" ? "添加" : "Add";
  const noLayersLabel = language === "zh-CN" ? "暂无记忆记录" : "No memory records yet";
  const totalLabel = language === "zh-CN" ? "总计" : "Total";

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
          {activeLayers} / {layers.length} {language === "zh-CN" ? "层活跃" : "layers active"}
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
