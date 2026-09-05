import type { ComposerLanguage } from "../types";

export type PlanComposerCopyMode = "explain" | "generate" | "evidence" | "blocker";

type PlanComposerPromptCopy = {
  label: string;
  prompt: string;
};

type PlanComposerModeCopy = {
  label: string;
  header: string;
  hint: string;
  placeholder: string;
  accessibilityLabel: string;
  primaryPrompt: PlanComposerPromptCopy;
  secondaryPrompt: PlanComposerPromptCopy;
};

export type PlanComposerCopy = {
  currentThread: string;
  planLabel: string;
  modes: Record<PlanComposerCopyMode, PlanComposerModeCopy>;
};

const planComposerCopy: Record<ComposerLanguage, PlanComposerCopy> = {
  "zh-CN": {
    currentThread: "当前主线",
    planLabel: "计划",
    modes: {
      explain: {
        label: "解释这一步",
        header: "解释当前阶段",
        hint: "说明为什么当前先做这一步、何时算完成，以及怎么做最小验证。",
        placeholder: "讨论当前阶段、为什么现在做，以及最小验证标准。",
        accessibilityLabel: "提交阶段解释或澄清请求",
        primaryPrompt: {
          label: "解释阶段",
          prompt: "请解释当前阶段为什么排在现在，以及完成它的最小验证标准。",
        },
        secondaryPrompt: {
          label: "为什么现在",
          prompt: "请说明当前这一步为什么应先做，而不是先做别的。",
        },
      },
      generate: {
        label: "生成计划",
        header: "生成或重排正式计划",
        hint: "生成第一版正式计划，或把当前主线重排成更清晰的阶段。",
        placeholder: "生成、重排，或冻结当前正式计划。",
        accessibilityLabel: "提交正式计划生成或重排请求",
        primaryPrompt: {
          label: "生成计划",
          prompt: "请基于当前目标生成正式计划，按阶段说明目标、为什么现在、验证方式和下一步。",
        },
        secondaryPrompt: {
          label: "重排主线",
          prompt: "请把当前主线重排成更清晰的阶段，但不要静默修改正式计划。",
        },
      },
      evidence: {
        label: "证据",
        header: "记下这次结果",
        hint: "改完了、卡住了，还是结果对不上，写在这里。",
        placeholder: "改完了、卡住了，还是结果对不上？",
        accessibilityLabel: "提交计划证据整理请求",
        primaryPrompt: {
          label: "整理证据",
          prompt: "请把我当前的结果整理成一条可采纳的证据，并指出还缺什么。",
        },
        secondaryPrompt: {
          label: "还缺什么",
          prompt: "请指出这条证据离正式采纳还缺什么，以及最小补齐动作。",
        },
      },
      blocker: {
        label: "收小一步",
        header: "把卡点缩成更小一步",
        hint: "把卡点缩成可恢复的小步骤，并说明应该退回到哪里。",
        placeholder: "把卡点缩成更小的下一步，先别直接改正式计划。",
        accessibilityLabel: "提交计划卡点收紧请求",
        primaryPrompt: {
          label: "缩小下一步",
          prompt: "请把当前主线缩成一个最小下一步，先说明理由和证据，不要直接改正式计划。",
        },
        secondaryPrompt: {
          label: "收紧卡点",
          prompt: "请把当前卡点收紧成一个更小步骤，先告诉我应该退回到哪里。",
        },
      },
    },
  },
  "en-US": {
    currentThread: "Current thread",
    planLabel: "Plan",
    modes: {
      explain: {
        label: "Explain",
        header: "Explain the current stage",
        hint: "Explain why this stage comes first, what counts as done, and the smallest way to verify it.",
        placeholder: "Discuss the current stage, why it is now, and the smallest verification standard.",
        accessibilityLabel: "Submit a stage explanation or clarification request",
        primaryPrompt: {
          label: "Explain stage",
          prompt: "Explain why this stage is current and what the smallest verification standard is.",
        },
        secondaryPrompt: {
          label: "Why now",
          prompt: "Explain why this step belongs now instead of something else first.",
        },
      },
      generate: {
        label: "Generate",
        header: "Generate or restructure the plan",
        hint: "Generate the first formal plan or reshape the current thread into clearer stages.",
        placeholder: "Generate, restructure, or freeze the formal plan.",
        accessibilityLabel: "Submit a formal-plan generation or restructure request",
        primaryPrompt: {
          label: "Generate plan",
          prompt: "Generate a formal plan for the current goal with stages, why now, verification, and next step.",
        },
        secondaryPrompt: {
          label: "Restructure",
          prompt: "Restructure the current thread into clearer stages without silently changing the formal plan.",
        },
      },
      evidence: {
        label: "Evidence",
        header: "Log this result",
        hint: "Say whether it worked, where you got stuck, or what didn't match.",
        placeholder: "Done, stuck, or it didn't match?",
        accessibilityLabel: "Submit a plan-evidence request",
        primaryPrompt: {
          label: "Make evidence",
          prompt: "Turn my current result into evidence that can be adopted and point out what is still missing.",
        },
        secondaryPrompt: {
          label: "Find the gap",
          prompt: "Point out what this evidence still needs before formal adoption and the smallest way to fill it.",
        },
      },
      blocker: {
        label: "Shrink blocker",
        header: "Make the blocker smaller",
        hint: "Reduce a blocker to a recoverable step and say where to step back first.",
        placeholder: "Shrink the blocker into a smaller next step without changing the formal plan yet.",
        accessibilityLabel: "Submit a plan-blocker request",
        primaryPrompt: {
          label: "Shrink next step",
          prompt: "Compress the current thread into the smallest next step, with reasons and evidence, without changing the formal plan.",
        },
        secondaryPrompt: {
          label: "Tighten blocker",
          prompt: "Tighten the current blocker into a smaller step and tell me where I should step back first.",
        },
      },
    },
  },
  "es-ES": {
    currentThread: "Ruta actual",
    planLabel: "Plan",
    modes: {
      explain: {
        label: "Explicar",
        header: "Explicar la etapa actual",
        hint: "Explica por qué esta etapa va primero, cuándo cuenta como terminada y cómo verificarla con lo mínimo.",
        placeholder: "Habla de la etapa actual, por qué toca ahora y su criterio mínimo de verificación.",
        accessibilityLabel: "Enviar una solicitud para explicar o aclarar la etapa",
        primaryPrompt: {
          label: "Explicar etapa",
          prompt: "Explica por qué esta etapa es la actual y cuál es el criterio mínimo para verificarla.",
        },
        secondaryPrompt: {
          label: "Por qué ahora",
          prompt: "Explica por qué este paso debe hacerse ahora y no otra cosa primero.",
        },
      },
      generate: {
        label: "Generar",
        header: "Generar o reorganizar el plan",
        hint: "Genera el primer plan formal o reorganiza la ruta actual en etapas más claras.",
        placeholder: "Genera, reorganiza o congela el plan formal.",
        accessibilityLabel: "Enviar una solicitud para generar o reorganizar el plan formal",
        primaryPrompt: {
          label: "Generar plan",
          prompt: "Genera un plan formal para el objetivo actual con etapas, por qué ahora, verificación y siguiente paso.",
        },
        secondaryPrompt: {
          label: "Reorganizar",
          prompt: "Reorganiza la ruta actual en etapas más claras sin cambiar el plan formal en silencio.",
        },
      },
      evidence: {
        label: "Evidencia",
        header: "Convertir trabajo en evidencia",
        hint: "Convierte resultados, señales de aprendizaje o hallazgos de recursos en evidencia revisable.",
        placeholder: "Registra el resultado, el motivo del fallo o una señal de aprendizaje y lo que falta.",
        accessibilityLabel: "Enviar una solicitud de evidencia para el plan",
        primaryPrompt: {
          label: "Crear evidencia",
          prompt: "Convierte mi resultado actual en evidencia que pueda adoptarse e indica qué falta.",
        },
        secondaryPrompt: {
          label: "Ver brecha",
          prompt: "Indica qué necesita esta evidencia antes de adoptarla formalmente y la forma mínima de completarla.",
        },
      },
      blocker: {
        label: "Reducir bloqueo",
        header: "Hacer más pequeño el bloqueo",
        hint: "Reduce un bloqueo a un paso recuperable e indica dónde volver primero.",
        placeholder: "Reduce el bloqueo a un siguiente paso más pequeño sin cambiar todavía el plan formal.",
        accessibilityLabel: "Enviar una solicitud sobre un bloqueo del plan",
        primaryPrompt: {
          label: "Reducir siguiente paso",
          prompt: "Reduce la ruta actual al siguiente paso más pequeño, con razones y evidencia, sin cambiar el plan formal.",
        },
        secondaryPrompt: {
          label: "Ajustar bloqueo",
          prompt: "Reduce el bloqueo actual a un paso menor e indica a qué punto debo volver primero.",
        },
      },
    },
  },
  "fr-FR": {
    currentThread: "Fil actuel",
    planLabel: "Plan",
    modes: {
      explain: {
        label: "Expliquer",
        header: "Expliquer l'étape actuelle",
        hint: "Expliquez pourquoi cette étape vient d'abord, ce qui compte comme terminé et la plus petite vérification utile.",
        placeholder: "Discutez de l'étape actuelle, de sa priorité et de son critère minimal de vérification.",
        accessibilityLabel: "Envoyer une demande d'explication ou de clarification de l'étape",
        primaryPrompt: {
          label: "Expliquer l'étape",
          prompt: "Expliquez pourquoi cette étape est actuelle et quel est le critère minimal pour la vérifier.",
        },
        secondaryPrompt: {
          label: "Pourquoi maintenant",
          prompt: "Expliquez pourquoi cette étape doit venir maintenant plutôt qu'une autre.",
        },
      },
      generate: {
        label: "Générer",
        header: "Générer ou réorganiser le plan",
        hint: "Générez le premier plan formel ou réorganisez le fil actuel en étapes plus claires.",
        placeholder: "Générez, réorganisez ou gelez le plan formel.",
        accessibilityLabel: "Envoyer une demande de génération ou de réorganisation du plan formel",
        primaryPrompt: {
          label: "Générer le plan",
          prompt: "Générez un plan formel pour l'objectif actuel avec les étapes, pourquoi maintenant, vérification et prochaine action.",
        },
        secondaryPrompt: {
          label: "Réorganiser",
          prompt: "Réorganisez le fil actuel en étapes plus claires sans modifier silencieusement le plan formel.",
        },
      },
      evidence: {
        label: "Preuves",
        header: "Transformer le travail en preuves",
        hint: "Transformez les résultats, signaux d'apprentissage ou découvertes de ressources en preuves à examiner.",
        placeholder: "Notez le résultat, la raison d'un échec ou un signal d'apprentissage, ainsi que ce qui manque.",
        accessibilityLabel: "Envoyer une demande de preuve pour le plan",
        primaryPrompt: {
          label: "Créer une preuve",
          prompt: "Transformez mon résultat actuel en preuve adoptable et indiquez ce qui manque encore.",
        },
        secondaryPrompt: {
          label: "Voir l'écart",
          prompt: "Indiquez ce dont cette preuve a encore besoin avant son adoption formelle et le plus petit complément utile.",
        },
      },
      blocker: {
        label: "Réduire le blocage",
        header: "Rendre le blocage plus petit",
        hint: "Réduisez un blocage à une étape récupérable et indiquez où revenir d'abord.",
        placeholder: "Réduisez le blocage en une prochaine étape plus petite sans modifier encore le plan formel.",
        accessibilityLabel: "Envoyer une demande sur un blocage du plan",
        primaryPrompt: {
          label: "Réduire la prochaine étape",
          prompt: "Réduisez le fil actuel à la plus petite prochaine étape, avec raisons et preuves, sans modifier le plan formel.",
        },
        secondaryPrompt: {
          label: "Préciser le blocage",
          prompt: "Réduisez le blocage actuel en une étape plus petite et indiquez où je dois revenir d'abord.",
        },
      },
    },
  },
  "de-DE": {
    currentThread: "Aktueller Pfad",
    planLabel: "Plan",
    modes: {
      explain: {
        label: "Erklären",
        header: "Aktuelle Phase erklären",
        hint: "Erklären Sie, warum diese Phase zuerst kommt, wann sie erledigt ist und wie sie minimal geprüft wird.",
        placeholder: "Besprechen Sie die aktuelle Phase, warum sie jetzt dran ist und den kleinsten Prüfschritt.",
        accessibilityLabel: "Anfrage zur Erklärung oder Klärung der Phase senden",
        primaryPrompt: {
          label: "Phase erklären",
          prompt: "Erklären Sie, warum diese Phase aktuell ist und was der kleinste Prüfschritt ist.",
        },
        secondaryPrompt: {
          label: "Warum jetzt",
          prompt: "Erklären Sie, warum dieser Schritt jetzt kommt und nicht zuerst etwas anderes.",
        },
      },
      generate: {
        label: "Erstellen",
        header: "Plan erstellen oder umstrukturieren",
        hint: "Erstellen Sie den ersten formellen Plan oder gliedern Sie den aktuellen Pfad in klarere Phasen.",
        placeholder: "Erstellen, strukturieren oder frieren Sie den formellen Plan ein.",
        accessibilityLabel: "Anfrage zum Erstellen oder Umstrukturieren des formellen Plans senden",
        primaryPrompt: {
          label: "Plan erstellen",
          prompt: "Erstellen Sie für das aktuelle Ziel einen formellen Plan mit Phasen, Warum jetzt, Prüfung und nächstem Schritt.",
        },
        secondaryPrompt: {
          label: "Umstrukturieren",
          prompt: "Gliedern Sie den aktuellen Pfad in klarere Phasen, ohne den formellen Plan stillschweigend zu ändern.",
        },
      },
      evidence: {
        label: "Evidenz",
        header: "Arbeit in Evidenz überführen",
        hint: "Machen Sie Ergebnisse, Lernsignale oder Ressourcenfunde zu überprüfbarer Evidenz.",
        placeholder: "Halten Sie Ergebnis, Fehlergrund oder Lernsignal und die noch fehlenden Punkte fest.",
        accessibilityLabel: "Anfrage für Plan-Evidenz senden",
        primaryPrompt: {
          label: "Evidenz erstellen",
          prompt: "Machen Sie aus meinem aktuellen Ergebnis übernehmbare Evidenz und nennen Sie die noch fehlenden Punkte.",
        },
        secondaryPrompt: {
          label: "Lücke finden",
          prompt: "Nennen Sie, was dieser Evidenz vor der formellen Übernahme noch fehlt und wie es minimal ergänzt wird.",
        },
      },
      blocker: {
        label: "Blocker verkleinern",
        header: "Den Blocker kleiner machen",
        hint: "Reduzieren Sie einen Blocker auf einen wiederaufnehmbaren Schritt und sagen Sie, wohin Sie zuerst zurückgehen.",
        placeholder: "Reduzieren Sie den Blocker auf einen kleineren nächsten Schritt, ohne den formellen Plan schon zu ändern.",
        accessibilityLabel: "Anfrage zu einem Plan-Blocker senden",
        primaryPrompt: {
          label: "Nächsten Schritt verkleinern",
          prompt: "Reduzieren Sie den aktuellen Pfad auf den kleinsten nächsten Schritt, mit Gründen und Evidenz, ohne den formellen Plan zu ändern.",
        },
        secondaryPrompt: {
          label: "Blocker präzisieren",
          prompt: "Machen Sie aus dem aktuellen Blocker einen kleineren Schritt und sagen Sie, wohin ich zuerst zurückgehen soll.",
        },
      },
    },
  },
  "ja-JP": {
    currentThread: "現在の流れ",
    planLabel: "計画",
    modes: {
      explain: {
        label: "段階を説明",
        header: "現在の段階を説明",
        hint: "なぜこの段階を先に行うのか、完了の基準と最小の確認方法を説明します。",
        placeholder: "現在の段階、なぜ今行うのか、最小の確認基準について書いてください。",
        accessibilityLabel: "段階の説明または確認依頼を送信",
        primaryPrompt: {
          label: "段階を説明",
          prompt: "なぜこの段階が現在必要なのか、最小の確認基準は何かを説明してください。",
        },
        secondaryPrompt: {
          label: "なぜ今か",
          prompt: "なぜ別の作業より先にこの手順を行うのかを説明してください。",
        },
      },
      generate: {
        label: "計画を作成",
        header: "正式な計画を作成または整理",
        hint: "最初の正式な計画を作成するか、現在の流れをより分かりやすい段階に整理します。",
        placeholder: "正式な計画を作成、整理、または固定します。",
        accessibilityLabel: "正式な計画の作成または整理依頼を送信",
        primaryPrompt: {
          label: "計画を作成",
          prompt: "現在の目標に対する正式な計画を、段階、なぜ今か、確認方法、次の一手とともに作成してください。",
        },
        secondaryPrompt: {
          label: "流れを整理",
          prompt: "正式な計画を勝手に変えずに、現在の流れをより分かりやすい段階に整理してください。",
        },
      },
      evidence: {
        label: "証拠を整理",
        header: "作業を証拠にする",
        hint: "結果、学習の手がかり、資料からの発見を確認できる証拠に整理します。",
        placeholder: "結果、失敗の理由、学習の手がかりと、まだ足りないことを書いてください。",
        accessibilityLabel: "計画用の証拠整理依頼を送信",
        primaryPrompt: {
          label: "証拠を作る",
          prompt: "現在の結果を採用できる証拠に整理し、まだ足りないことを示してください。",
        },
        secondaryPrompt: {
          label: "不足を確認",
          prompt: "この証拠を正式に採用する前に何が足りないか、最小の補い方を示してください。",
        },
      },
      blocker: {
        label: "詰まりを小さくする",
        header: "詰まりを小さな一歩にする",
        hint: "詰まりを再開できる小さな手順にし、どこに戻るかを示します。",
        placeholder: "正式な計画はまだ変えず、詰まりをより小さな次の一歩にしてください。",
        accessibilityLabel: "計画の詰まりに関する依頼を送信",
        primaryPrompt: {
          label: "次の一手を小さく",
          prompt: "正式な計画を変えずに、理由と証拠を添えて現在の流れを最小の次の一手にしてください。",
        },
        secondaryPrompt: {
          label: "詰まりを整理",
          prompt: "現在の詰まりを小さな手順にし、最初にどこへ戻るかを教えてください。",
        },
      },
    },
  },
  "ko-KR": {
    currentThread: "현재 흐름",
    planLabel: "계획",
    modes: {
      explain: {
        label: "단계 설명",
        header: "현재 단계 설명",
        hint: "왜 이 단계를 먼저 하는지, 완료 기준과 가장 작은 확인 방법을 설명합니다.",
        placeholder: "현재 단계, 지금 해야 하는 이유, 최소 확인 기준을 적어 보세요.",
        accessibilityLabel: "단계 설명 또는 확인 요청 제출",
        primaryPrompt: {
          label: "단계 설명",
          prompt: "왜 이 단계가 지금 필요한지와 가장 작은 확인 기준을 설명해 주세요.",
        },
        secondaryPrompt: {
          label: "왜 지금인가",
          prompt: "다른 작업보다 먼저 이 단계를 해야 하는 이유를 설명해 주세요.",
        },
      },
      generate: {
        label: "계획 생성",
        header: "공식 계획 생성 또는 재구성",
        hint: "첫 공식 계획을 만들거나 현재 흐름을 더 분명한 단계로 재구성합니다.",
        placeholder: "공식 계획을 생성, 재구성 또는 고정합니다.",
        accessibilityLabel: "공식 계획 생성 또는 재구성 요청 제출",
        primaryPrompt: {
          label: "계획 생성",
          prompt: "현재 목표의 공식 계획을 단계, 지금 해야 하는 이유, 확인 방법, 다음 단계와 함께 만들어 주세요.",
        },
        secondaryPrompt: {
          label: "흐름 재구성",
          prompt: "공식 계획을 조용히 바꾸지 말고 현재 흐름을 더 분명한 단계로 재구성해 주세요.",
        },
      },
      evidence: {
        label: "증거 정리",
        header: "작업을 증거로 정리",
        hint: "결과, 학습 신호 또는 자료 발견을 검토할 수 있는 증거로 정리합니다.",
        placeholder: "결과, 실패 이유 또는 학습 신호와 아직 부족한 점을 적어 보세요.",
        accessibilityLabel: "계획 증거 정리 요청 제출",
        primaryPrompt: {
          label: "증거 만들기",
          prompt: "현재 결과를 채택 가능한 증거로 정리하고 아직 부족한 점을 알려 주세요.",
        },
        secondaryPrompt: {
          label: "부족한 점 확인",
          prompt: "이 증거를 공식 채택하기 전에 무엇이 더 필요한지와 최소 보완 방법을 알려 주세요.",
        },
      },
      blocker: {
        label: "막힌 점 줄이기",
        header: "막힌 점을 작은 다음 단계로",
        hint: "막힌 점을 다시 시작할 수 있는 작은 단계로 줄이고 어디로 돌아갈지 알려 줍니다.",
        placeholder: "공식 계획은 아직 바꾸지 말고 막힌 점을 더 작은 다음 단계로 줄여 보세요.",
        accessibilityLabel: "계획의 막힌 점 관련 요청 제출",
        primaryPrompt: {
          label: "다음 단계 줄이기",
          prompt: "공식 계획을 바꾸지 말고 이유와 증거를 포함해 현재 흐름을 가장 작은 다음 단계로 줄여 주세요.",
        },
        secondaryPrompt: {
          label: "막힌 점 구체화",
          prompt: "현재 막힌 점을 더 작은 단계로 만들고 먼저 어디로 돌아가야 하는지 알려 주세요.",
        },
      },
    },
  },
  "pt-BR": {
    currentThread: "Trilha atual",
    planLabel: "Plano",
    modes: {
      explain: {
        label: "Explicar",
        header: "Explicar a etapa atual",
        hint: "Explique por que esta etapa vem primeiro, o que conta como concluído e a menor forma de verificá-la.",
        placeholder: "Fale sobre a etapa atual, por que ela é agora e o menor critério de verificação.",
        accessibilityLabel: "Enviar uma solicitação para explicar ou esclarecer a etapa",
        primaryPrompt: {
          label: "Explicar etapa",
          prompt: "Explique por que esta é a etapa atual e qual é o menor critério de verificação.",
        },
        secondaryPrompt: {
          label: "Por que agora",
          prompt: "Explique por que esta etapa vem agora, e não outra primeiro.",
        },
      },
      generate: {
        label: "Gerar",
        header: "Gerar ou reorganizar o plano",
        hint: "Gere o primeiro plano formal ou reorganize a trilha atual em etapas mais claras.",
        placeholder: "Gere, reorganize ou congele o plano formal.",
        accessibilityLabel: "Enviar uma solicitação para gerar ou reorganizar o plano formal",
        primaryPrompt: {
          label: "Gerar plano",
          prompt: "Gere um plano formal para o objetivo atual com etapas, por que agora, verificação e próximo passo.",
        },
        secondaryPrompt: {
          label: "Reorganizar",
          prompt: "Reorganize a trilha atual em etapas mais claras sem mudar o plano formal silenciosamente.",
        },
      },
      evidence: {
        label: "Evidência",
        header: "Transformar trabalho em evidência",
        hint: "Transforme resultados, sinais de aprendizado ou descobertas de recursos em evidência revisável.",
        placeholder: "Registre o resultado, a razão da falha ou um sinal de aprendizado e o que ainda falta.",
        accessibilityLabel: "Enviar uma solicitação de evidência para o plano",
        primaryPrompt: {
          label: "Criar evidência",
          prompt: "Transforme meu resultado atual em evidência adotável e indique o que ainda falta.",
        },
        secondaryPrompt: {
          label: "Ver lacuna",
          prompt: "Indique o que esta evidência ainda precisa antes da adoção formal e a menor forma de completar isso.",
        },
      },
      blocker: {
        label: "Reduzir bloqueio",
        header: "Tornar o bloqueio menor",
        hint: "Reduza um bloqueio a uma etapa recuperável e diga para onde voltar primeiro.",
        placeholder: "Reduza o bloqueio a um próximo passo menor sem mudar o plano formal ainda.",
        accessibilityLabel: "Enviar uma solicitação sobre um bloqueio do plano",
        primaryPrompt: {
          label: "Reduzir próximo passo",
          prompt: "Reduza a trilha atual ao menor próximo passo, com razões e evidência, sem mudar o plano formal.",
        },
        secondaryPrompt: {
          label: "Ajustar bloqueio",
          prompt: "Transforme o bloqueio atual em uma etapa menor e diga para onde devo voltar primeiro.",
        },
      },
    },
  },
};

export function resolvePlanComposerCopy(language: ComposerLanguage): PlanComposerCopy {
  return planComposerCopy[language] ?? planComposerCopy["en-US"];
}
