import { describeTrainerStopReason } from "../../../../../shared/src/protocol";
import type { AgentToolActivity } from "../../app/useWorkbenchState";
import type { ComposerLanguage } from "../../lib/types";
import { agentActivityStripCopy } from "./agentActivityStripCopy";
import {
  hasCoachToolResultFailure,
  resolveCoachToolResultCopy,
  summarizeSafeCoachToolResult,
} from "./coachToolResultCopy";

export interface AgentActivityStripProps {
  activities: AgentToolActivity[];
  step?: number;
  language?: ComposerLanguage;
  stopReason?: string;
}

/** §十五: per-tool labels in eight languages (keyed by tool id; zh keys collide). */
const TOOL_LABELS: Record<string, Record<ComposerLanguage, string>> = {
  search_resources: {
    "zh-CN": "搜索资料", "en-US": "Search resources", "es-ES": "Buscar recursos",
    "fr-FR": "Rechercher des ressources", "de-DE": "Ressourcen durchsuchen",
    "ja-JP": "資料を検索", "ko-KR": "자료 검색", "pt-BR": "Buscar recursos",
  },
  search: {
    "zh-CN": "搜索", "en-US": "Search", "es-ES": "Buscar",
    "fr-FR": "Rechercher", "de-DE": "Suchen",
    "ja-JP": "検索", "ko-KR": "검색", "pt-BR": "Buscar",
  },
  read_workspace_file: {
    "zh-CN": "读取文件", "en-US": "Read file", "es-ES": "Leer archivo",
    "fr-FR": "Lire le fichier", "de-DE": "Datei lesen",
    "ja-JP": "ファイルを読み取り", "ko-KR": "파일 읽기", "pt-BR": "Ler arquivo",
  },
  list_workspace_files: {
    "zh-CN": "浏览文件", "en-US": "List files", "es-ES": "Listar archivos",
    "fr-FR": "Lister les fichiers", "de-DE": "Dateien auflisten",
    "ja-JP": "ファイル一覧", "ko-KR": "파일 목록", "pt-BR": "Listar arquivos",
  },
  recall_memory: {
    "zh-CN": "回顾记忆", "en-US": "Recall memory", "es-ES": "Recordar memoria",
    "fr-FR": "Retrouver la mémoire", "de-DE": "Erinnerung abrufen",
    "ja-JP": "記憶を思い出す", "ko-KR": "기억 불러오기", "pt-BR": "Recordar memória",
  },
  record_learning_note: {
    "zh-CN": "保存观察", "en-US": "Save note", "es-ES": "Guardar observación",
    "fr-FR": "Enregistrer l'observation", "de-DE": "Beobachtung speichern",
    "ja-JP": "観察を保存", "ko-KR": "관찰 저장", "pt-BR": "Salvar observação",
  },
  inspect_plan: {
    "zh-CN": "查看计划", "en-US": "Inspect plan", "es-ES": "Inspeccionar plan",
    "fr-FR": "Inspecter le plan", "de-DE": "Plan prüfen",
    "ja-JP": "プランを確認", "ko-KR": "계획 검사", "pt-BR": "Inspecionar plano",
  },
  save_formal_plan: {
    "zh-CN": "保存计划", "en-US": "Save plan", "es-ES": "Guardar plan",
    "fr-FR": "Enregistrer le plan", "de-DE": "Plan speichern",
    "ja-JP": "プランを保存", "ko-KR": "계획 저장", "pt-BR": "Salvar plano",
  },
  verify_practice_current_file: {
    "zh-CN": "验证实战", "en-US": "Verify practice", "es-ES": "Verificar práctica",
    "fr-FR": "Vérifier la pratique", "de-DE": "Praxis prüfen",
    "ja-JP": "実践を検証", "ko-KR": "실습 검증", "pt-BR": "Verificar prática",
  },
  generate_training_card: {
    "zh-CN": "生成训练卡", "en-US": "Generate card", "es-ES": "Generar tarjeta",
    "fr-FR": "Générer une carte", "de-DE": "Karte erstellen",
    "ja-JP": "カードを生成", "ko-KR": "카드 생성", "pt-BR": "Gerar cartão",
  },
  generate_cards: {
    "zh-CN": "生成训练卡", "en-US": "Generate cards", "es-ES": "Generar tarjetas",
    "fr-FR": "Générer des cartes", "de-DE": "Karten erstellen",
    "ja-JP": "カードを生成", "ko-KR": "카드 생성", "pt-BR": "Gerar cartões",
  },
  card_generation: {
    "zh-CN": "生成训练卡", "en-US": "Card generation", "es-ES": "Generación de tarjeta",
    "fr-FR": "Génération de carte", "de-DE": "Kartenerstellung",
    "ja-JP": "カード生成", "ko-KR": "카드 생성", "pt-BR": "Geração de cartão",
  },
  run_diagnostics: {
    "zh-CN": "运行诊断", "en-US": "Run diagnostics", "es-ES": "Ejecutar diagnóstico",
    "fr-FR": "Exécuter le diagnostic", "de-DE": "Diagnose ausführen",
    "ja-JP": "診断を実行", "ko-KR": "진단 실행", "pt-BR": "Executar diagnóstico",
  },
  align_plan: {
    "zh-CN": "对齐计划", "en-US": "Align plan", "es-ES": "Alinear plan",
    "fr-FR": "Aligner le plan", "de-DE": "Plan abstimmen",
    "ja-JP": "プランを整合", "ko-KR": "계획 정렬", "pt-BR": "Alinhar plano",
  },
  plan_alignment: {
    "zh-CN": "对齐计划", "en-US": "Align plan", "es-ES": "Alinear plan",
    "fr-FR": "Aligner le plan", "de-DE": "Plan abstimmen",
    "ja-JP": "プランを整合", "ko-KR": "계획 정렬", "pt-BR": "Alinhar plano",
  },
  evaluation: {
    "zh-CN": "评估结果", "en-US": "Evaluation", "es-ES": "Evaluación",
    "fr-FR": "Évaluation", "de-DE": "Auswertung",
    "ja-JP": "評価", "ko-KR": "평가", "pt-BR": "Avaliação",
  },
  coach_finalize: {
    "zh-CN": "收束回复", "en-US": "Finalize", "es-ES": "Finalizar",
    "fr-FR": "Finaliser", "de-DE": "Abschließen",
    "ja-JP": "まとめ", "ko-KR": "마무리", "pt-BR": "Finalizar",
  },
};

function toolLabel(name: string, language: ComposerLanguage): string {
  const labels = TOOL_LABELS[name];
  const label = labels?.[language];
  if (label) {
    return label;
  }
  return resolveCoachToolResultCopy(language).currentStep;
}

/** The en sentence lowercases the label; other locales use it verbatim. */
function sentenceLabel(label: string, language: ComposerLanguage): string {
  return language === "en-US" ? label.toLowerCase() : label;
}

function summarizeResult(
  activity: AgentToolActivity,
  language: ComposerLanguage,
): string | undefined {
  if (activity.status === "running") {
    return undefined;
  }
  const copy = resolveCoachToolResultCopy(language);
  if (activity.status === "failed" || hasCoachToolResultFailure(undefined, activity.result)) {
    return copy.needsRetry;
  }
  return summarizeSafeCoachToolResult(activity.result, language) ?? copy.completed;
}

function summarizeActivitySet(
  activities: AgentToolActivity[],
  language: ComposerLanguage,
): string {
  const running = activities.filter((activity) => activity.status === "running");
  const failed = activities.filter(
    (activity) =>
      activity.status === "failed" || hasCoachToolResultFailure(undefined, activity.result),
  );
  const succeeded = activities.filter((activity) => activity.status === "succeeded");

  if (failed.length > 0) {
    const copy = resolveCoachToolResultCopy(language);
    if (running.length > 0) {
      return agentActivityStripCopy(language, "正在核对上下文，同时有一步需要重试");
    }
    return copy.blocked;
  }

  if (running.length > 0) {
    if (running.length === 1) {
      const label = toolLabel(running[0].name, language);
      return agentActivityStripCopy(language, "正在{label}").replace(
        "{label}",
        sentenceLabel(label, language),
      );
    }

    return agentActivityStripCopy(language, "正在核对 {n} 项上下文").replace(
      "{n}",
      String(running.length),
    );
  }

  if (succeeded.length > 1) {
    return agentActivityStripCopy(language, "已完成 {n} 个步骤，正在整理回复").replace(
      "{n}",
      String(succeeded.length),
    );
  }

  if (succeeded.length === 1) {
    const label = toolLabel(succeeded[0].name, language);
    return agentActivityStripCopy(language, "已完成：{label}").replace(
      "{label}",
      sentenceLabel(label, language),
    );
  }

  return agentActivityStripCopy(language, "正在准备回复");
}

function activityPills(activities: AgentToolActivity[], language: ComposerLanguage) {
  return (
    <div className="agent-activity-strip__pills">
      {activities.map((activity) => {
        const hint = summarizeResult(activity, language);
        const title = toolLabel(activity.name, language);
        return (
          <span
            key={activity.id}
            className={`agent-activity-pill agent-activity-pill--${activity.status}`}
            title={hint ? `${title} - ${hint}` : title}
          >
            <span
              className={`agent-activity-pill__dot agent-activity-pill__dot--${activity.status}`}
              aria-hidden="true"
            />
            <span className="agent-activity-pill__label">{title}</span>
            {hint ? <span className="agent-activity-pill__hint">{hint}</span> : null}
          </span>
        );
      })}
    </div>
  );
}

function stopReasonLine(stopReason: string | undefined, language: ComposerLanguage) {
  const stopReasonLabel = describeTrainerStopReason(stopReason, language);
  if (!stopReasonLabel) {
    return null;
  }
  return (
    <span className="agent-activity-strip__stop-reason">
      {agentActivityStripCopy(language, "结束原因：{reason}").replace("{reason}", stopReasonLabel)}
    </span>
  );
}

function activityDetails(activities: AgentToolActivity[], language: ComposerLanguage) {
  const hasRunningItems = activities.some((item) => item.status === "running");
  return (
    <>
      {hasRunningItems ? (
        <span className="agent-activity-strip__working">
          {agentActivityStripCopy(language, "正在核对上下文...")}
        </span>
      ) : null}
      {activityPills(activities, language)}
    </>
  );
}

export function AgentActivityStrip({
  activities,
  step,
  language = "en-US",
  stopReason,
}: AgentActivityStripProps) {
  if (activities.length === 0) {
    return null;
  }

  const summary = summarizeActivitySet(activities, language);
  const displayStep =
    typeof step === "number"
      ? Math.max(1, step >= activities.length ? step : step + 1)
      : undefined;

  return (
    <div className="agent-activity-strip" role="status">
      <div className="agent-activity-strip__summary">
        {typeof displayStep === "number" ? (
          <span className="agent-activity-strip__step">
            {agentActivityStripCopy(language, "第 {n} 步").replace("{n}", String(displayStep))}
          </span>
        ) : null}
        <span className="agent-activity-strip__lead">{summary}</span>
      </div>
      <div className="agent-activity-strip__details">
        {activityDetails(activities, language)}
        {stopReasonLine(stopReason, language)}
      </div>
    </div>
  );
}
