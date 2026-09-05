import type { ComposerLanguage } from "./types";

type ScratchPaperPromptInput = {
  cardTitle?: string;
  learnerNote?: string;
  verificationItems: string[];
};

type ScratchPaperCopy = {
  lead: string;
  card: string;
  criteria: string;
  learnerNote: string;
  noNote: string;
  workflow: string;
  genericImage: string;
};

const scratchPaperCopy: Record<ComposerLanguage, ScratchPaperCopy> = {
  "zh-CN": {
    lead: "我上传的是当前训练卡的手写草稿纸或作业图片。请把它作为候选证据核验。",
    card: "当前卡片",
    criteria: "核验标准",
    learnerNote: "我的说明",
    noNote: "没有额外文字说明，请先读图。",
    workflow:
      "请按顺序：1. 转写看得清的关键步骤或答案；2. 对照核验标准指出已证明与未证明的部分；3. 明确任何看不清、缺失或不能由图片证明的地方；4. 给出“可继续”或“需补充”的结论，以及最小补充动作。不要仅凭图片自动把训练卡或正式计划标记为通过。",
    genericImage:
      "请检查我附上的图片。先说明你实际看到了什么、哪些内容不清楚，再给出最小的下一步；不要假设图片已经证明了学习结果。",
  },
  "en-US": {
    lead: "I uploaded a handwritten scratch-paper or assignment image for the current training card. Treat it as candidate evidence.",
    card: "Current card",
    criteria: "Verification criteria",
    learnerNote: "My note",
    noNote: "There is no extra written note. Read the image first.",
    workflow:
      "Work in order: 1. transcribe the visible key steps or answer; 2. compare them with the criteria and identify what is and is not proven; 3. name anything unclear, missing, or impossible to prove from the image; 4. give a clear ‘continue’ or ‘needs more evidence’ conclusion with the smallest follow-up action. Do not automatically mark the training card or formal plan as passed from an image alone.",
    genericImage:
      "Inspect the attached image. First say what is actually visible and what is unclear, then give the smallest next step. Do not assume the image proves learning success.",
  },
  "es-ES": {
    lead: "He subido una imagen de apuntes manuscritos o de una tarea para la tarjeta de entrenamiento actual. Trátala como evidencia candidata.",
    card: "Tarjeta actual",
    criteria: "Criterios de verificación",
    learnerNote: "Mi nota",
    noNote: "No hay nota adicional. Lee primero la imagen.",
    workflow:
      "Sigue este orden: 1. transcribe los pasos o la respuesta que se vean; 2. compáralos con los criterios e indica qué está y qué no está demostrado; 3. señala todo lo borroso, ausente o imposible de demostrar con la imagen; 4. da una conclusión clara de ‘continuar’ o ‘necesita más evidencia’ con la acción mínima siguiente. No marques automáticamente la tarjeta ni el plan formal como aprobados solo por una imagen.",
    genericImage:
      "Inspecciona la imagen adjunta. Primero di qué se ve realmente y qué no está claro; después da el siguiente paso mínimo. No supongas que la imagen prueba el aprendizaje.",
  },
  "fr-FR": {
    lead: "J'ai joint une photo de brouillon manuscrit ou de devoir pour la carte d'entraînement en cours. Traite-la comme une preuve candidate.",
    card: "Carte en cours",
    criteria: "Critères de vérification",
    learnerNote: "Ma note",
    noNote: "Il n'y a pas de note complémentaire. Lis d'abord l'image.",
    workflow:
      "Procède dans cet ordre : 1. transcris les étapes ou la réponse clairement visibles ; 2. compare-les aux critères et indique ce qui est prouvé ou non ; 3. nomme tout élément illisible, manquant ou impossible à prouver par l'image ; 4. donne une conclusion claire ‘continuer’ ou ‘preuves supplémentaires nécessaires’ avec l'action minimale suivante. Ne marque pas automatiquement la carte ou le plan formel comme validé à partir d'une image seule.",
    genericImage:
      "Examine l'image jointe. Dis d'abord ce qui est réellement visible et ce qui reste flou, puis propose la plus petite étape suivante. Ne suppose pas que l'image prouve la réussite de l'apprentissage.",
  },
  "de-DE": {
    lead: "Ich habe ein Bild mit handschriftlichem Entwurf oder einer Aufgabe für die aktuelle Trainingskarte hochgeladen. Behandle es als möglichen Beleg.",
    card: "Aktuelle Karte",
    criteria: "Prüfkriterien",
    learnerNote: "Meine Notiz",
    noNote: "Es gibt keine zusätzliche Notiz. Lies zuerst das Bild.",
    workflow:
      "Arbeite der Reihe nach: 1. schreibe die sichtbar wichtigen Schritte oder die Antwort ab; 2. vergleiche sie mit den Kriterien und benenne, was bewiesen ist und was nicht; 3. nenne alles Unklare, Fehlende oder aus dem Bild nicht Beweisbare; 4. gib ein klares Urteil ‘weiter’ oder ‘mehr Belege nötig’ mit der kleinsten Folgeaktion. Markiere die Trainingskarte oder den formalen Plan nicht allein wegen eines Bildes automatisch als bestanden.",
    genericImage:
      "Prüfe das angehängte Bild. Sage zuerst, was tatsächlich sichtbar und was unklar ist, und gib dann den kleinsten nächsten Schritt an. Nimm nicht an, dass das Bild Lernerfolg beweist.",
  },
  "ja-JP": {
    lead: "現在の Training card に対する手書きの下書き・課題の画像を添付しました。候補となる証拠として扱ってください。",
    card: "現在のカード",
    criteria: "検証基準",
    learnerNote: "補足",
    noNote: "補足はありません。まず画像を読んでください。",
    workflow:
      "次の順で進めてください。1. 読み取れる主要な手順または答えを書き起こす。2. 基準と照らして、証明できた点とできない点を示す。3. 不鮮明・不足・画像から証明できない点を明示する。4. 「続行可」または「追加の証拠が必要」の結論と、最小の次の行動を示す。画像だけで Training card や正式な計画を自動的に合格にしないでください。",
    genericImage:
      "添付画像を確認してください。まず実際に見える内容と不明な内容を説明し、その後で最小の次の行動を示してください。画像が学習成果を証明したとは仮定しないでください。",
  },
  "ko-KR": {
    lead: "현재 Training card를 위한 손글씨 초안 또는 과제 이미지를 올렸습니다. 후보 증거로 다뤄 주세요.",
    card: "현재 카드",
    criteria: "검증 기준",
    learnerNote: "내 메모",
    noNote: "추가 메모가 없습니다. 먼저 이미지를 읽어 주세요.",
    workflow:
      "다음 순서로 진행하세요. 1. 보이는 핵심 단계 또는 답을 옮겨 적기. 2. 기준과 대조하여 증명된 부분과 증명되지 않은 부분 밝히기. 3. 흐리거나 누락되었거나 이미지로 증명할 수 없는 부분 명시하기. 4. ‘계속 가능’ 또는 ‘추가 증거 필요’라는 명확한 결론과 최소 후속 행동 제시하기. 이미지 하나만으로 Training card나 공식 plan을 자동 통과 처리하지 마세요.",
    genericImage:
      "첨부 이미지를 살펴보세요. 먼저 실제로 보이는 내용과 불분명한 내용을 말한 뒤 가장 작은 다음 행동을 제안하세요. 이미지가 학습 성과를 증명한다고 가정하지 마세요.",
  },
  "pt-BR": {
    lead: "Enviei uma imagem de rascunho manuscrito ou tarefa para o Training card atual. Trate-a como evidência candidata.",
    card: "Cartão atual",
    criteria: "Critérios de verificação",
    learnerNote: "Minha observação",
    noNote: "Não há observação adicional. Leia primeiro a imagem.",
    workflow:
      "Siga esta ordem: 1. transcreva os passos ou a resposta visíveis; 2. compare-os com os critérios e identifique o que está ou não comprovado; 3. indique tudo o que está ilegível, ausente ou impossível de provar pela imagem; 4. dê uma conclusão clara de ‘continuar’ ou ‘precisa de mais evidência’ com a menor ação seguinte. Não marque automaticamente o Training card ou o plano formal como aprovado apenas por uma imagem.",
    genericImage:
      "Examine a imagem anexada. Primeiro diga o que está realmente visível e o que não está claro; depois dê o menor próximo passo. Não suponha que a imagem prova sucesso de aprendizagem.",
  },
};

export function buildScratchPaperVerificationPrompt(
  language: ComposerLanguage,
  input: ScratchPaperPromptInput,
): string {
  const copy = scratchPaperCopy[language] ?? scratchPaperCopy["en-US"];
  const criteria = input.verificationItems.filter((item) => item.trim()).slice(0, 4);
  const sections = [copy.lead];

  if (input.cardTitle?.trim()) {
    sections.push(`${copy.card}: ${input.cardTitle.trim()}`);
  }
  if (criteria.length > 0) {
    sections.push(`${copy.criteria}:\n${criteria.map((item) => `- ${item}`).join("\n")}`);
  }
  sections.push(`${copy.learnerNote}: ${input.learnerNote?.trim() || copy.noNote}`);
  sections.push(copy.workflow);
  return sections.join("\n\n");
}

export function buildGenericImageReviewPrompt(language: ComposerLanguage, note?: string): string {
  const copy = scratchPaperCopy[language] ?? scratchPaperCopy["en-US"];
  return [copy.genericImage, note?.trim()].filter(Boolean).join("\n\n");
}

export type TrainingFeedbackPromptInput = {
  cardTitle?: string;
  question?: string;
  learnerAnswer?: string;
  phase: "answer" | "reflection" | "evidence";
  evidenceItems?: string[];
};

/**
 * Keep deterministic card bookkeeping separate from model feedback, while
 * giving the Agent enough grounded detail to stream a useful teaching turn.
 */
export function buildTrainingFeedbackPrompt(
  language: ComposerLanguage,
  input: TrainingFeedbackPromptInput,
): string {
  const isZh = language === "zh-CN";
  const phaseLabel =
    input.phase === "answer"
      ? isZh
        ? "作答"
        : "answer"
      : input.phase === "reflection"
        ? isZh
          ? "复盘"
          : "reflection"
        : isZh
          ? "证据记录"
          : "evidence note";
  const sections = [
    isZh
      ? `我刚提交了本轮训练${phaseLabel}。请基于同一训练线程给出可见的教练反馈。`
      : `I just submitted a training ${phaseLabel}. Continue the same learning thread with a visible coaching response.`,
  ];
  if (input.cardTitle?.trim()) {
    sections.push(isZh ? `训练卡：${input.cardTitle.trim()}` : `Training card: ${input.cardTitle.trim()}`);
  }
  if (input.question?.trim()) {
    sections.push(isZh ? `题目或任务：${input.question.trim()}` : `Question or task: ${input.question.trim()}`);
  }
  if (input.learnerAnswer?.trim()) {
    sections.push(
      isZh ? `我的提交：${input.learnerAnswer.trim()}` : `Learner submission: ${input.learnerAnswer.trim()}`,
    );
  }
  const evidenceItems = input.evidenceItems?.filter((item) => item.trim()).slice(0, 4) ?? [];
  if (evidenceItems.length > 0) {
    sections.push(
      `${isZh ? "核验线索" : "Verification signals"}:\n${evidenceItems
        .map((item) => `- ${item}`)
        .join("\n")}`,
    );
  }
  sections.push(
    isZh
      ? "不要静默修改正式计划。说明这次提交证明了什么、仍有哪些不确定性，以及最小的下一步。答案不完整时要如实说明，回复保持足够精炼，便于马上行动。"
      : "Do not silently change the formal plan. Explain what the submission proves, what is still uncertain, and the smallest next action. Be honest when the answer is incomplete; keep the response concise enough to act on.",
  );
  return sections.join("\n\n");
}
