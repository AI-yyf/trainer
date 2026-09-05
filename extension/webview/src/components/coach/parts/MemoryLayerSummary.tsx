import { StatusPill } from "../../StatusPill";
import type { ComposerLanguage, MemoryLayerView } from "../../../lib/types";

function text(language: ComposerLanguage, zh: string, en: string): string {
  return language === "zh-CN" ? zh : en;
}

function toneForStatus(status: MemoryLayerView["status"]): "connected" | "pending" | "offline" {
  if (status === "active") {
    return "connected";
  }
  if (status === "quiet") {
    return "pending";
  }
  return "offline";
}

function labelForStatus(language: ComposerLanguage, status: MemoryLayerView["status"]): string {
  if (status === "active") {
    return text(language, "活跃", "Active");
  }
  if (status === "quiet") {
    return text(language, "轻量", "Quiet");
  }
  return text(language, "空", "Empty");
}

/**
 * Human-readable layer names that make sense to learners
 */
const LAYER_HUMAN_NAMES: Record<string, Partial<Record<ComposerLanguage, { title: string; description: string }>>> = {
  master_plan: {
    "zh-CN": {
      title: "总计划",
      description: "目标与路线",
    },
    "en-US": {
      title: "Master Plan",
      description: "Goals and route",
    },
  },
  project: {
    "zh-CN": {
      title: "当前项目",
      description: "这个项目的目标、约束与进展",
    },
    "en-US": {
      title: "Current Project",
      description: "Goals, constraints, and progress for this project",
    },
  },
  session: {
    "zh-CN": {
      title: "当前对话",
      description: "这一轮会话中的上下文与记忆",
    },
    "en-US": {
      title: "Current Session",
      description: "Context and memories from this conversation",
    },
  },
  training: {
    "zh-CN": {
      title: "训练进度",
      description: "练习记录",
    },
    "en-US": {
      title: "Training Progress",
      description: "Practice history",
    },
  },
  review: {
    "zh-CN": {
      title: "复习节奏",
      description: "间隔重复",
    },
    "en-US": {
      title: "Review Rhythm",
      description: "Spaced repetition",
    },
  },
  resources: {
    "zh-CN": {
      title: "学习资料",
      description: "已导入的文档、代码与网页",
    },
    "en-US": {
      title: "Learning Materials",
      description: "Imported documents, code, and web pages",
    },
  },
  episodic: {
    "zh-CN": {
      title: "经验记忆",
      description: "训练事件、错误与反馈",
    },
    "en-US": {
      title: "Experiences",
      description: "Training events, mistakes, and feedback",
    },
  },
  skill_mastery: {
    "zh-CN": {
      title: "技能掌握",
      description: "概念的熟练度与误区",
    },
    "en-US": {
      title: "Skill Mastery",
      description: "Concept proficiency and misconceptions",
    },
  },
  provider: {
    "zh-CN": {
      title: "模型状态",
      description: "当前模型的健康状况与能力",
    },
    "en-US": {
      title: "Model Status",
      description: "Current model health and capabilities",
    },
  },
};

/**
 * Get human-friendly name for a memory layer
 */
function getHumanLayerInfo(layer: MemoryLayerView, language: ComposerLanguage): { title: string; description: string } {
  const layerKey = layer.layer.toLowerCase().replace(/[_-]/g, "_");
  const humanInfo = LAYER_HUMAN_NAMES[layerKey]?.[language];
  if (humanInfo) {
    return humanInfo;
  }
  // Fallback: try to find partial match
  for (const [key, info] of Object.entries(LAYER_HUMAN_NAMES)) {
    if (layerKey.includes(key) || key.includes(layerKey)) {
      const langInfo = info[language];
      if (langInfo) {
        return langInfo;
      }
    }
  }
  // Ultimate fallback: use layer title as-is
  return {
    title: layer.title,
    description: layer.summary,
  };
}

/**
 * Get a motivational hint for inject-ready layers
 */
function getInjectionHint(language: ComposerLanguage, canInject: boolean, evidenceCount: number): string {
  if (!canInject) {
    return text(language, "可作为参考", "Available as reference");
  }
  if (evidenceCount > 5) {
    return text(language, "素材丰富，可注入", "Rich material, ready to inject");
  }
  if (evidenceCount > 0) {
    return text(language, "有信号，可注入", "Has signals, ready to inject");
  }
  return text(language, "可注入训练卡", "Can inject training card");
}

function renderResourceSignal(language: ComposerLanguage, signal: NonNullable<MemoryLayerView["resourceSignals"]>[number]): string {
  const focus = signal.sourceFocus ? " · " + signal.sourceFocus : "";
  const scenario = signal.scenario ? " · " + signal.scenario : "";
  return text(language, "Resource signal: " + signal.signal + focus + scenario, "Resource signal: " + signal.signal + focus + scenario);
}

function renderTeachingAsset(language: ComposerLanguage, asset: NonNullable<MemoryLayerView["teachingAssets"]>[number]): string {
  const focus = asset.focusArea ? " · " + asset.focusArea : "";
  const trust = typeof asset.trustScore === "number" ? " · " + Math.round(asset.trustScore * 100) + "% trust" : "";
  return text(language, "Teaching asset: " + asset.title + focus + trust, "Teaching asset: " + asset.title + focus + trust);
}

export interface MemoryLayerSummaryProps {
  language: ComposerLanguage;
  layers?: MemoryLayerView[];
  className?: string;
}

export function MemoryLayerSummary({ language, layers = [], className }: MemoryLayerSummaryProps) {
  const visibleLayers = layers.slice(0, 4);
  if (!visibleLayers.length) {
    return null;
  }

  const injectReadyCount = visibleLayers.filter((layer) => layer.canInjectTrainingCard).length;
  const totalSignals = visibleLayers.reduce((sum, layer) => sum + layer.evidenceCount, 0);

  return (
    <section className={["section-block", "memory-layer-summary", className].filter(Boolean).join(" ")}>
      <div className="section-block__header memory-layer-summary__header">
        <div>
          <span className="eyebrow">{text(language, "记忆层级", "Memory layers")}</span>
          <p className="memory-layer-summary__lede">
            {text(
              language,
              "这些层级把训练、计划、资源、复习和 provider 诊断连在一起。",
              "These layers keep training, planning, resources, review, and provider diagnostics connected.",
            )}
          </p>
        </div>
        <StatusPill tone={injectReadyCount > 0 ? "connected" : "pending"}>
          {text(language, `${injectReadyCount} 个可注入`, `${injectReadyCount} inject-ready`)}
        </StatusPill>
      </div>
      <div className="memory-layer-summary__grid">
        {visibleLayers.map((layer) => {
          const humanInfo = getHumanLayerInfo(layer, language);
          return (
            <article key={layer.layer} className="memory-layer-summary__card">
              <div className="memory-layer-summary__card-head">
                <strong>{humanInfo.title}</strong>
                <StatusPill tone={toneForStatus(layer.status)}>{labelForStatus(language, layer.status)}</StatusPill>
              </div>
              <p className="memory-layer-summary__summary">{humanInfo.description}</p>
              {layer.highlights.length ? (
                <p className="memory-layer-summary__highlights">{layer.highlights.slice(0, 2).join(" · ")}</p>
              ) : null}
              {layer.resourceSignals?.length ? (
                <div className="memory-layer-summary__chips" aria-label={text(language, "资源信号", "Resource signals")}>
                  {layer.resourceSignals.slice(0, 2).map((signal) => (
                    <span key={signal.key} className="memory-layer-summary__chip">
                      {renderResourceSignal(language, signal)}
                    </span>
                  ))}
                </div>
              ) : null}
              {layer.teachingAssets?.length ? (
                <div className="memory-layer-summary__chips" aria-label={text(language, "教学资产", "Teaching assets")}>
                  {layer.teachingAssets.slice(0, 2).map((asset) => (
                    <span key={asset.id} className="memory-layer-summary__chip">
                      {renderTeachingAsset(language, asset)}
                    </span>
                  ))}
                </div>
              ) : null}
              <div className="memory-layer-summary__meta">
                <span>
                  {layer.evidenceCount} {text(language, "条信号", "signals")}
                </span>
                <span>{getInjectionHint(language, layer.canInjectTrainingCard ?? false, layer.evidenceCount)}</span>
              </div>
            </article>
          );
        })}
      </div>
      {totalSignals > 0 && (
        <p className="memory-layer-summary__footer-note">
          {text(
            language,
            `共 ${totalSignals} 条信号等待被训练利用`,
            `${totalSignals} signals waiting to power your training`,
          )}
        </p>
      )}
    </section>
  );
}
