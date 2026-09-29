import { StatusPill } from "../../StatusPill";
import type { ComposerLanguage, MemoryLayerView } from "../../../lib/types";

/** §十五: memory-layer summary copy in eight languages (no zh/en binary). */

/**
 * Chrome copy for the memory layer grid. The zh-CN source string is the
 * record key — entries whose historical zh text was an English literal use
 * that literal as the key; {n} / {body} are positional slots.
 */
const MEMORY_LAYER_SUMMARY_TEXT: Record<string, Record<string, string>> = {
  "活跃": {
    "en-US": "Active",
    "es-ES": "Activo",
    "fr-FR": "Actif",
    "de-DE": "Aktiv",
    "ja-JP": "アクティブ",
    "ko-KR": "활성",
    "pt-BR": "Ativo",
  },
  "轻量": {
    "en-US": "Quiet",
    "es-ES": "En reposo",
    "fr-FR": "Au repos",
    "de-DE": "Ruhend",
    "ja-JP": "低頻度",
    "ko-KR": "대기",
    "pt-BR": "Em repouso",
  },
  "空": {
    "en-US": "Empty",
    "es-ES": "Vacío",
    "fr-FR": "Vide",
    "de-DE": "Leer",
    "ja-JP": "空",
    "ko-KR": "비어 있음",
    "pt-BR": "Vazio",
  },
  "可作为参考": {
    "en-US": "Available as reference",
    "es-ES": "Disponible como referencia",
    "fr-FR": "Disponible comme référence",
    "de-DE": "Als Referenz verfügbar",
    "ja-JP": "参考として利用可能",
    "ko-KR": "참고용으로 사용 가능",
    "pt-BR": "Disponível como referência",
  },
  "素材丰富，可注入": {
    "en-US": "Rich material, ready to inject",
    "es-ES": "Material abundante, listo para inyectar",
    "fr-FR": "Matériau riche, prêt à injecter",
    "de-DE": "Reichhaltiges Material, bereit zum Injizieren",
    "ja-JP": "素材が豊富で注入可能",
    "ko-KR": "소재가 풍부하여 주입 가능",
    "pt-BR": "Material rico, pronto para injetar",
  },
  "有信号，可注入": {
    "en-US": "Has signals, ready to inject",
    "es-ES": "Tiene señales, listo para inyectar",
    "fr-FR": "A des signaux, prêt à injecter",
    "de-DE": "Hat Signale, bereit zum Injizieren",
    "ja-JP": "シグナルがあり注入可能",
    "ko-KR": "신호가 있어 주입 가능",
    "pt-BR": "Tem sinais, pronto para injetar",
  },
  "可注入训练卡": {
    "en-US": "Can inject training card",
    "es-ES": "Puede inyectar tarjeta de entrenamiento",
    "fr-FR": "Peut injecter une carte d'entraînement",
    "de-DE": "Kann Trainingskarte injizieren",
    "ja-JP": "トレーニングカードに注入可能",
    "ko-KR": "훈련 카드 주입 가능",
    "pt-BR": "Pode injetar cartão de treino",
  },
  "Resource signal: {body}": {
    "en-US": "Resource signal: {body}",
    "es-ES": "Señal de recurso: {body}",
    "fr-FR": "Signal de ressource : {body}",
    "de-DE": "Ressourcen-Signal: {body}",
    "ja-JP": "資料シグナル: {body}",
    "ko-KR": "자료 신호: {body}",
    "pt-BR": "Sinal de recurso: {body}",
  },
  "Teaching asset: {body}": {
    "en-US": "Teaching asset: {body}",
    "es-ES": "Activo didáctico: {body}",
    "fr-FR": "Actif pédagogique : {body}",
    "de-DE": "Lehr-Asset: {body}",
    "ja-JP": "教材アセット: {body}",
    "ko-KR": "교육 자산: {body}",
    "pt-BR": "Ativo de ensino: {body}",
  },
  "记忆层级": {
    "en-US": "Memory layers",
    "es-ES": "Capas de memoria",
    "fr-FR": "Couches de mémoire",
    "de-DE": "Speicherebenen",
    "ja-JP": "記憶レイヤー",
    "ko-KR": "기억 레이어",
    "pt-BR": "Camadas de memória",
  },
  "这些层级把训练、计划、资源、复习和 provider 诊断连在一起。": {
    "en-US": "These layers keep training, planning, resources, review, and provider diagnostics connected.",
    "es-ES": "Estas capas conectan el entrenamiento, la planificación, los recursos, la revisión y el diagnóstico del proveedor.",
    "fr-FR": "Ces couches relient l'entraînement, la planification, les ressources, la révision et le diagnostic du fournisseur.",
    "de-DE": "Diese Ebenen verbinden Training, Planung, Ressourcen, Wiederholung und Provider-Diagnose.",
    "ja-JP": "これらのレイヤーはトレーニング、計画、資料、復習、プロバイダー診断をつなげます。",
    "ko-KR": "이 레이어들은 훈련, 계획, 자료, 복습, 프로바이더 진단을 연결합니다.",
    "pt-BR": "Essas camadas conectam treino, planejamento, recursos, revisão e diagnóstico do provedor.",
  },
  "{n} 个可注入": {
    "en-US": "{n} inject-ready",
    "es-ES": "{n} listas para inyectar",
    "fr-FR": "{n} prêtes à injecter",
    "de-DE": "{n} injektionsbereit",
    "ja-JP": "注入可能 {n} 件",
    "ko-KR": "주입 가능 {n}개",
    "pt-BR": "{n} prontos para injetar",
  },
  "资源信号": {
    "en-US": "Resource signals",
    "es-ES": "Señales de recursos",
    "fr-FR": "Signaux de ressources",
    "de-DE": "Ressourcen-Signale",
    "ja-JP": "資料シグナル",
    "ko-KR": "자료 신호",
    "pt-BR": "Sinais de recursos",
  },
  "教学资产": {
    "en-US": "Teaching assets",
    "es-ES": "Activos didácticos",
    "fr-FR": "Actifs pédagogiques",
    "de-DE": "Lehr-Assets",
    "ja-JP": "教材アセット",
    "ko-KR": "교육 자산",
    "pt-BR": "Ativos de ensino",
  },
  "条信号": {
    "en-US": "signals",
    "es-ES": "señales",
    "fr-FR": "signaux",
    "de-DE": "Signale",
    "ja-JP": "件のシグナル",
    "ko-KR": "개 신호",
    "pt-BR": "sinais",
  },
  "共 {n} 条信号等待被训练利用": {
    "en-US": "{n} signals waiting to power your training",
    "es-ES": "{n} señales esperando para impulsar tu entrenamiento",
    "fr-FR": "{n} signaux prêts à alimenter votre entraînement",
    "de-DE": "{n} Signale warten darauf, dein Training zu speisen",
    "ja-JP": "{n} 件のシグナルがトレーニングでの活用を待っています",
    "ko-KR": "{n}개의 신호가 훈련에 활용되기를 기다립니다",
    "pt-BR": "{n} sinais esperando para alimentar seu treino",
  },
};

function text(language: ComposerLanguage, key: string): string {
  return MEMORY_LAYER_SUMMARY_TEXT[key]?.[language] ?? key;
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
    return text(language, "活跃");
  }
  if (status === "quiet") {
    return text(language, "轻量");
  }
  return text(language, "空");
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
    "es-ES": {
      title: "Plan maestro",
      description: "Objetivos y ruta",
    },
    "fr-FR": {
      title: "Plan principal",
      description: "Objectifs et itinéraire",
    },
    "de-DE": {
      title: "Gesamtplan",
      description: "Ziele und Route",
    },
    "ja-JP": {
      title: "全体プラン",
      description: "目標とルート",
    },
    "ko-KR": {
      title: "종합 계획",
      description: "목표와 경로",
    },
    "pt-BR": {
      title: "Plano mestre",
      description: "Metas e rota",
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
    "es-ES": {
      title: "Proyecto actual",
      description: "Metas, restricciones y progreso de este proyecto",
    },
    "fr-FR": {
      title: "Projet en cours",
      description: "Objectifs, contraintes et progrès de ce projet",
    },
    "de-DE": {
      title: "Aktuelles Projekt",
      description: "Ziele, Randbedingungen und Fortschritt dieses Projekts",
    },
    "ja-JP": {
      title: "現在のプロジェクト",
      description: "このプロジェクトの目標・制約・進捗",
    },
    "ko-KR": {
      title: "현재 프로젝트",
      description: "이 프로젝트의 목표, 제약, 진행 상황",
    },
    "pt-BR": {
      title: "Projeto atual",
      description: "Metas, restrições e progresso deste projeto",
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
    "es-ES": {
      title: "Sesión actual",
      description: "Contexto y memorias de esta conversación",
    },
    "fr-FR": {
      title: "Session en cours",
      description: "Contexte et souvenirs de cette conversation",
    },
    "de-DE": {
      title: "Aktuelle Sitzung",
      description: "Kontext und Erinnerungen aus dieser Unterhaltung",
    },
    "ja-JP": {
      title: "現在の会話",
      description: "この会話のコンテキストと記憶",
    },
    "ko-KR": {
      title: "현재 대화",
      description: "이 대화의 컨텍스트와 기억",
    },
    "pt-BR": {
      title: "Sessão atual",
      description: "Contexto e memórias desta conversa",
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
    "es-ES": {
      title: "Progreso de entrenamiento",
      description: "Historial de práctica",
    },
    "fr-FR": {
      title: "Progression de l'entraînement",
      description: "Historique de pratique",
    },
    "de-DE": {
      title: "Trainingsfortschritt",
      description: "Übungsverlauf",
    },
    "ja-JP": {
      title: "トレーニング進捗",
      description: "練習履歴",
    },
    "ko-KR": {
      title: "훈련 진행도",
      description: "연습 기록",
    },
    "pt-BR": {
      title: "Progresso de treino",
      description: "Histórico de prática",
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
    "es-ES": {
      title: "Ritmo de repaso",
      description: "Repetición espaciada",
    },
    "fr-FR": {
      title: "Rythme de révision",
      description: "Répétition espacée",
    },
    "de-DE": {
      title: "Wiederholungsrhythmus",
      description: "Verteilte Wiederholung",
    },
    "ja-JP": {
      title: "復習リズム",
      description: "間隔反復",
    },
    "ko-KR": {
      title: "복습 리듬",
      description: "간격 반복",
    },
    "pt-BR": {
      title: "Ritmo de revisão",
      description: "Repetição espaçada",
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
    "es-ES": {
      title: "Materiales de aprendizaje",
      description: "Documentos, código y páginas web importados",
    },
    "fr-FR": {
      title: "Supports d'apprentissage",
      description: "Documents, code et pages web importés",
    },
    "de-DE": {
      title: "Lernmaterialien",
      description: "Importierte Dokumente, Code und Webseiten",
    },
    "ja-JP": {
      title: "学習資料",
      description: "取り込んだドキュメント、コード、Web ページ",
    },
    "ko-KR": {
      title: "학습 자료",
      description: "가져온 문서, 코드, 웹 페이지",
    },
    "pt-BR": {
      title: "Materiais de aprendizagem",
      description: "Documentos, códigos e páginas web importados",
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
    "es-ES": {
      title: "Experiencias",
      description: "Eventos de entrenamiento, errores y comentarios",
    },
    "fr-FR": {
      title: "Expériences",
      description: "Événements d'entraînement, erreurs et retours",
    },
    "de-DE": {
      title: "Erfahrungen",
      description: "Trainingsereignisse, Fehler und Feedback",
    },
    "ja-JP": {
      title: "経験記憶",
      description: "トレーニングイベント、ミス、フィードバック",
    },
    "ko-KR": {
      title: "경험 기억",
      description: "훈련 이벤트, 실수, 피드백",
    },
    "pt-BR": {
      title: "Experiências",
      description: "Eventos de treino, erros e feedback",
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
    "es-ES": {
      title: "Dominio de habilidades",
      description: "Dominio de conceptos y errores comunes",
    },
    "fr-FR": {
      title: "Maîtrise des compétences",
      description: "Maîtrise des concepts et idées reçues",
    },
    "de-DE": {
      title: "Kompetenzfortschritt",
      description: "Konzeptbeherrschung und Missverständnisse",
    },
    "ja-JP": {
      title: "スキル習得",
      description: "概念の熟練度と誤解",
    },
    "ko-KR": {
      title: "스킬 숙달",
      description: "개념 숙련도와 오해",
    },
    "pt-BR": {
      title: "Domínio de habilidades",
      description: "Proficiência em conceitos e equívocos",
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
    "es-ES": {
      title: "Estado del modelo",
      description: "Salud y capacidades del modelo actual",
    },
    "fr-FR": {
      title: "État du modèle",
      description: "Santé et capacités du modèle actuel",
    },
    "de-DE": {
      title: "Modellstatus",
      description: "Aktueller Modellzustand und Fähigkeiten",
    },
    "ja-JP": {
      title: "モデル状態",
      description: "現在のモデルの健全性と能力",
    },
    "ko-KR": {
      title: "모델 상태",
      description: "현재 모델의 상태와 능력",
    },
    "pt-BR": {
      title: "Status do modelo",
      description: "Saúde e capacidades do modelo atual",
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
    return text(language, "可作为参考");
  }
  if (evidenceCount > 5) {
    return text(language, "素材丰富，可注入");
  }
  if (evidenceCount > 0) {
    return text(language, "有信号，可注入");
  }
  return text(language, "可注入训练卡");
}

function renderResourceSignal(language: ComposerLanguage, signal: NonNullable<MemoryLayerView["resourceSignals"]>[number]): string {
  const focus = signal.sourceFocus ? " · " + signal.sourceFocus : "";
  const scenario = signal.scenario ? " · " + signal.scenario : "";
  return text(language, "Resource signal: {body}").replace(
    "{body}",
    signal.signal + focus + scenario,
  );
}

function renderTeachingAsset(language: ComposerLanguage, asset: NonNullable<MemoryLayerView["teachingAssets"]>[number]): string {
  const focus = asset.focusArea ? " · " + asset.focusArea : "";
  const trust = typeof asset.trustScore === "number" ? " · " + Math.round(asset.trustScore * 100) + "% trust" : "";
  return text(language, "Teaching asset: {body}").replace(
    "{body}",
    asset.title + focus + trust,
  );
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
          <span className="eyebrow">{text(language, "记忆层级")}</span>
          <p className="memory-layer-summary__lede">
            {text(
              language,
              "这些层级把训练、计划、资源、复习和 provider 诊断连在一起。",
            )}
          </p>
        </div>
        <StatusPill tone={injectReadyCount > 0 ? "connected" : "pending"}>
          {text(language, "{n} 个可注入").replace("{n}", String(injectReadyCount))}
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
                <div className="memory-layer-summary__chips" aria-label={text(language, "资源信号")}>
                  {layer.resourceSignals.slice(0, 2).map((signal) => (
                    <span key={signal.key} className="memory-layer-summary__chip">
                      {renderResourceSignal(language, signal)}
                    </span>
                  ))}
                </div>
              ) : null}
              {layer.teachingAssets?.length ? (
                <div className="memory-layer-summary__chips" aria-label={text(language, "教学资产")}>
                  {layer.teachingAssets.slice(0, 2).map((asset) => (
                    <span key={asset.id} className="memory-layer-summary__chip">
                      {renderTeachingAsset(language, asset)}
                    </span>
                  ))}
                </div>
              ) : null}
              <div className="memory-layer-summary__meta">
                <span>
                  {layer.evidenceCount} {text(language, "条信号")}
                </span>
                <span>{getInjectionHint(language, layer.canInjectTrainingCard ?? false, layer.evidenceCount)}</span>
              </div>
            </article>
          );
        })}
      </div>
      {totalSignals > 0 && (
        <p className="memory-layer-summary__footer-note">
          {text(language, "共 {n} 条信号等待被训练利用").replace("{n}", String(totalSignals))}
        </p>
      )}
    </section>
  );
}
