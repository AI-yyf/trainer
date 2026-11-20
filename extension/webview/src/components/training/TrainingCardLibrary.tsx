import type { FormEvent } from "react";
import type { ComposerLanguage, TrainingCardCandidate } from "../../lib/types";

const labels: Record<ComposerLanguage, readonly string[]> = {
  "zh-CN": ["练习记录", "待确认", "已保存", "题目", "验收标准（每行一项）", "保存练习", "暂缓", "拒绝", "打开练习", "归档", "标记重要", "取消重要标记", "优先级", "合并到此练习", "已暂缓"],
  "en-US": ["Training cards", "Awaiting review", "Saved cards", "Prompt", "Acceptance criteria (one per line)", "Save to library", "Defer", "Reject", "Open practice", "Archive", "Mark important", "Remove importance", "Priority", "Merge into this card", "Deferred"],
  "es-ES": ["Tarjetas de práctica", "Pendientes de revisión", "Tarjetas guardadas", "Pregunta", "Criterios de aceptación (uno por línea)", "Guardar", "Posponer", "Rechazar", "Abrir práctica", "Archivar", "Marcar como importante", "Quitar marca", "Prioridad", "Combinar con esta tarjeta", "Pospuesta"],
  "fr-FR": ["Cartes d’exercice", "À examiner", "Cartes enregistrées", "Question", "Critères d’acceptation (un par ligne)", "Enregistrer", "Reporter", "Refuser", "Ouvrir l’exercice", "Archiver", "Marquer comme importante", "Retirer la marque", "Priorité", "Fusionner dans cette carte", "Reportée"],
  "de-DE": ["Trainingskarten", "Zur Prüfung", "Gespeicherte Karten", "Aufgabe", "Abnahmekriterien (eines pro Zeile)", "Speichern", "Zurückstellen", "Ablehnen", "Übung öffnen", "Archivieren", "Als wichtig markieren", "Markierung entfernen", "Priorität", "Mit dieser Karte zusammenführen", "Zurückgestellt"],
  "ja-JP": ["練習カード", "確認待ち", "保存済み", "問題", "合格基準（1 行に 1 項目）", "ライブラリに保存", "保留", "却下", "練習を開く", "アーカイブ", "重要にする", "重要マークを外す", "優先度", "このカードに統合", "保留中"],
  "ko-KR": ["연습 카드", "검토 대기", "저장된 카드", "문제", "완료 기준(한 줄에 하나)", "보관함에 저장", "보류", "거절", "연습 열기", "보관 처리", "중요 표시", "중요 표시 해제", "우선순위", "이 카드로 병합", "보류됨"],
  "pt-BR": ["Cartões de prática", "Aguardando revisão", "Cartões salvos", "Pergunta", "Critérios de aceitação (um por linha)", "Salvar na biblioteca", "Adiar", "Rejeitar", "Abrir prática", "Arquivar", "Marcar como importante", "Remover marca", "Prioridade", "Mesclar neste cartão", "Adiado"],
};

export type TrainingCardLibraryAction = "save" | "defer" | "reject" | "start" | "archive";

export function TrainingCardLibrary({
  language, cards, selectedCardId, busy, onAction, onImportance, onPriority, onMerge,
}: {
  language: ComposerLanguage;
  cards: TrainingCardCandidate[];
  selectedCardId?: string;
  busy: boolean;
  onAction: (cardId: string, action: TrainingCardLibraryAction, edits?: { prompt?: string; acceptanceCriteria?: string[] }) => void;
  onImportance: (cardId: string, important: boolean) => void;
  onPriority: (cardId: string, priority: number) => void;
  onMerge: (cardId: string, duplicates: string[]) => void;
}) {
  const [title, awaiting, saved, promptLabel, criteriaLabel, save, defer, reject, start, archive,
    mark, unmark, priorityLabel, merge, deferred] = labels[language];
  const proposed = cards.filter((card) => !card.mergedInto &&
    (card.reviewState === "pending" || card.reviewState === "deferred"));
  const library = cards.filter((card) => (!card.reviewState || card.reviewState === "saved") &&
    card.status !== "archived");
  if (!proposed.length && !library.length) return null;

  function saveCandidate(event: FormEvent<HTMLFormElement>, card: TrainingCardCandidate, prompt: string, criteria: string) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const editedPrompt = fields.get("prompt");
    const editedCriteria = fields.get("criteria");
    onAction(card.cardId, "save", {
      prompt: typeof editedPrompt === "string" && editedPrompt.trim() !== prompt ? editedPrompt.trim() : undefined,
      acceptanceCriteria: typeof editedCriteria === "string" && editedCriteria.trim() !== criteria
        ? editedCriteria.split("\n").map((line) => line.trim()).filter(Boolean)
        : undefined,
    });
  }

  const management = (card: TrainingCardCandidate) => (
    <div className="training-library__actions">
      <button type="button" className="button button--ghost" disabled={busy}
        onClick={() => onImportance(card.cardId, !card.important)}>{card.important ? unmark : mark}</button>
      <label>
        {priorityLabel}{" "}
        <select value={card.cardPriority ?? 0} disabled={busy}
          onChange={(event) => onPriority(card.cardId, Number(event.target.value))}>
          {Array.from({ length: 11 }, (_, index) => index - 5).map((value) => (
            <option key={value} value={value}>{value}</option>
          ))}
        </select>
      </label>
    </div>
  );

  return (
    <details className="template-disclosure training-library" data-training-library open={!selectedCardId}>
      <summary>
        <span>{title}</span>
        <span className="training-library__counts">
          {proposed.length > 0 && <span>{awaiting} {proposed.length}</span>}
          {library.length > 0 && <span>{saved} {library.length}</span>}
        </span>
      </summary>
      <div>
        {proposed.length > 0 && <h3>{awaiting}</h3>}
        {proposed.map((card) => {
          const prompt = (card.type === "flash" ? card.question : card.problemStatement)?.trim() || "";
          const criteria = card.acceptanceCriteria?.join("\n").trim() || "";
          return (
            <details key={card.cardId} className="training-library__card" data-candidate-id={card.cardId}>
              <summary>{card.title}{card.reviewState === "deferred" ? ` · ${deferred}` : ""}</summary>
              <form className="training-library__editor" onSubmit={(event) => saveCandidate(event, card, prompt, criteria)}>
                <label>{promptLabel}
                  <textarea name="prompt" rows={3} defaultValue={prompt} maxLength={8000}
                    readOnly={Boolean(card.type === "flash" && card.answerMode && card.answerMode !== "text")} />
                </label>
                <label>{criteriaLabel}
                  <textarea name="criteria" rows={3} defaultValue={criteria} />
                </label>
                <div className="training-library__actions">
                  <button type="submit" className="button button--primary" disabled={busy}>{save}</button>
                  {card.reviewState !== "deferred" && (
                    <button type="button" className="button button--ghost" disabled={busy}
                      onClick={() => onAction(card.cardId, "defer")}>{defer}</button>
                  )}
                  <button type="button" className="button button--ghost" disabled={busy}
                    onClick={() => onAction(card.cardId, "reject")}>{reject}</button>
                </div>
              </form>
              {management(card)}
              {card.status === "candidate" && proposed.filter((other) => other.cardId !== card.cardId &&
                other.status === "candidate").map((other) => (
                <button type="button" className="button button--ghost" key={other.cardId} disabled={busy}
                  onClick={() => onMerge(card.cardId, [other.cardId])}>{merge} · {other.title}</button>
              ))}
            </details>
          );
        })}
        {library.length > 0 && <h3>{saved}</h3>}
        {library.map((card) => (
          <details key={card.cardId} className="training-library__card" data-library-card-id={card.cardId}>
            <summary>{card.title}</summary>
            {card.learnerAnswer && <p className="template-metadata">{card.learnerAnswer}</p>}
            <div className="training-library__actions">
              {card.cardId !== selectedCardId &&
                (!card.status || ["candidate", "active", "needs_primer", "blocked", "skipped"].includes(card.status)) && (
                  <button type="button" className="button button--primary" disabled={busy}
                    onClick={() => onAction(card.cardId, "start")}>{start}</button>
              )}
              <button type="button" className="button button--ghost" disabled={busy}
                onClick={() => onAction(card.cardId, "archive")}>{archive}</button>
            </div>
            {management(card)}
          </details>
        ))}
      </div>
    </details>
  );
}
