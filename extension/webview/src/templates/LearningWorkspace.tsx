import type { ReactNode } from "react";
import type { LearningActivity } from "../../../../shared/src/models";
import { CoachMessageParts } from "../components/coach/CoachMessageParts";

import { resourceLibraryText } from "../lib/i18n/segments/resourcesInlineText";
import { unifiedComposerCopy } from "../lib/i18n/unifiedComposerCopy";
import type { ComposerLanguage, ResourceRecord, ResourceSearchState, TrainingEventLedgerEntry } from "../lib/types";
import { SystemState } from "./SystemState";
import { templateCopy } from "./templateCopy";

const learnerActivityTypes = new Set([
  "training_card_started",
  "training_card_status_changed",
  "practice_evaluation_recorded",
]);

const ACTIVITY_LABELS: Record<ComposerLanguage, string[]> = {
  "zh-CN": ["收到浏览器来源", "资料已保存", "资料已关联", "开始练习", "提交回答", "记录证据", "安排复习", "练习已生成", "验证反馈已记录"],
  "en-US": ["Browser source received", "Resource saved", "Resource linked", "Practice started", "Answer submitted", "Evidence recorded", "Review scheduled", "Practice created", "Verification recorded"],
  "es-ES": ["Fuente recibida", "Recurso guardado", "Recurso vinculado", "Práctica iniciada", "Respuesta enviada", "Evidencia registrada", "Repaso programado", "Práctica creada", "Verificación registrada"],
  "fr-FR": ["Source reçue", "Ressource enregistrée", "Ressource associée", "Exercice lancé", "Réponse envoyée", "Preuve enregistrée", "Révision planifiée", "Exercice créé", "Vérification enregistrée"],
  "de-DE": ["Quelle empfangen", "Ressource gespeichert", "Ressource verknüpft", "Übung begonnen", "Antwort abgegeben", "Nachweis erfasst", "Wiederholung geplant", "Übung erstellt", "Prüfung erfasst"],
  "ja-JP": ["出典を受信", "資料を保存", "資料を関連付け", "練習を開始", "回答を提出", "証拠を記録", "復習を予約", "練習を作成", "検証結果を記録"],
  "ko-KR": ["출처 받음", "자료 저장", "자료 연결", "연습 시작", "답변 제출", "증거 기록", "복습 예약", "연습 생성", "검증 결과 기록"],
  "pt-BR": ["Fonte recebida", "Recurso salvo", "Recurso vinculado", "Prática iniciada", "Resposta enviada", "Evidência registrada", "Revisão agendada", "Prática criada", "Verificação registrada"],
};
const activityKinds = ["browser_source_received", "resource_indexed", "resource_linked", "card_status_transitioned",
  "practice_submission_recorded", "training_evidence_recorded", "review_scheduled", "card_candidate_created", "evaluation_feedback_recorded"];

export type LearningWorkspaceTab = "progress" | "training" | "plan";

const LEARNING_TAB_ORDER: LearningWorkspaceTab[] = ["progress", "training", "plan"];

export function LearningWorkspace({ language, goal, details, activity, entries, onReview, reviewLabel, evidence, overview, librarySearch, resources, activeTab, onTabChange, children }: {
  language: ComposerLanguage;
  goal?: string;
  details?: string;
  activity?: LearningActivity[];
  entries: TrainingEventLedgerEntry[];
  onReview?: () => void;
  reviewLabel?: string;
  evidence?: ReactNode;
  overview?: { label: string; content: ReactNode };
  librarySearch?: { requestId: string; query: string; result?: ResourceSearchState; failed?: boolean };
  resources: ResourceRecord[];
  /** P1: Learning presents 进度 / 练习 / 长期规划 as three views over one stream. */
  activeTab?: LearningWorkspaceTab;
  onTabChange?: (tab: LearningWorkspaceTab) => void;
  children: ReactNode;
}) {
  const copy = unifiedComposerCopy[language];
  const legacy = entries.filter((entry) => entry.eventId && entry.createdAt && learnerActivityTypes.has(entry.eventType ?? ""))
    .map((entry) => ({
      id: entry.eventId ?? "", timestamp: entry.createdAt ?? "", kind: "",
      title: entry.returnSummary || entry.statusSummary || entry.selectedCardTitle || entry.cardCandidateTitle || entry.candidateStatusReason,
    }));
  const events: LearningActivity[] = (activity?.length ? [...activity] : legacy)
    .filter((entry) => Number.isFinite(Date.parse(entry.timestamp)))
    .sort((left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp))
    .slice(0, 20);
  return (
    <section className="template-learning-workspace" data-template="LearningWorkspace" aria-label={templateCopy[language].currentLearning}>
      {activeTab && onTabChange ? (
        <div className="template-learning-tabs" role="tablist" aria-label={templateCopy[language].currentLearning} data-learning-tabs="true">
          {LEARNING_TAB_ORDER.map((tab) => {
            const label = tab === "progress"
              ? templateCopy[language].learningProgress
              : tab === "training"
                ? templateCopy[language].learningPractice
                : templateCopy[language].learningPlan;
            const selected = activeTab === tab;
            return (
              <button
                key={tab}
                type="button"
                role="tab"
                aria-selected={selected}
                className={selected ? "template-learning-tab is-active" : "template-learning-tab"}
                data-learning-tab={tab}
                onClick={() => { if (!selected) onTabChange(tab); }}
              >
                {label}
              </button>
            );
          })}
        </div>
      ) : null}
      {goal ? <header className="template-learning-workspace__goal">
        <p className="template-metadata">{templateCopy[language].currentLearning}</p>
        <h2>{goal}</h2>
        {details ? <p className="template-metadata">{details}</p> : null}
      </header> : null}
      {children}
      {librarySearch ? (
        <details key={librarySearch.requestId} className="template-disclosure" data-learning-library-search="true" open>
          <summary>{librarySearch.query}</summary>
          {librarySearch.failed ? <SystemState kind="error" title={resourceLibraryText(language, "searchFailed")} />
            : !librarySearch.result ? <SystemState kind="processing" title={resourceLibraryText(language, "searching")} />
            : !librarySearch.result.hits.length ? <SystemState kind="empty" title={resourceLibraryText(language, "noMatches")} />
            : <CoachMessageParts language={language} resources={resources} parts={librarySearch.result.hits.map((hit) => ({
              type: "citation",
              resourceId: hit.id,
              title: hit.title,
              label: hit.title,
              versionId: hit.versionId,
              contentHash: hit.contentHash,
              citationId: hit.citationId,
              location: hit.location,
            }))} />}
        </details>
      ) : null}
      <details className="template-disclosure" data-learning-activity="true">
        <summary>{copy.history}</summary>
        {events.length ? <ol className="template-learning-timeline">
          {events.map((entry) => {
            const label = ACTIVITY_LABELS[language][activityKinds.indexOf(entry.kind)] ?? copy.task;
            return (
              <li key={entry.id} data-learning-event={entry.kind}>
                <time dateTime={entry.timestamp} className="template-metadata">
                  {new Date(entry.timestamp).toLocaleString(language, { dateStyle: "medium", timeStyle: "short" })}
                </time>
                <p>{entry.title ? label + " · " + entry.title : label}</p>
                {entry.nextDue && Number.isFinite(Date.parse(entry.nextDue)) ? (
                  <time dateTime={entry.nextDue} className="template-metadata">{new Date(entry.nextDue).toLocaleDateString(language)}</time>
                ) : null}
              </li>
            );
          })}
        </ol> : <p className="template-metadata">{copy.emptyHistory}</p>}
        {onReview && reviewLabel ? <button type="button" className="template-back" onClick={onReview}>{reviewLabel}</button> : null}
      </details>
      {evidence}
      {overview ? <details className="template-disclosure" data-learning-plan-overview="true">
        <summary>{overview.label}</summary>
        {overview.content}
      </details> : null}
    </section>
  );
}
