import type { ComposerLanguage } from "../types";

export type ResourceComposerCopyMode = "locate" | "download" | "organize" | "cards";

type ResourceComposerPromptCopy = {
  label: string;
  prompt: string;
};

type ResourceComposerModeCopy = {
  label: string;
  header: string;
  summary: string;
  hint: string;
  placeholder: string;
  accessibilityLabel: string;
  primaryPrompt: ResourceComposerPromptCopy;
  secondaryPrompt: ResourceComposerPromptCopy;
};

export type ResourceComposerCopy = {
  nextResource: string;
  modes: Record<ResourceComposerCopyMode, ResourceComposerModeCopy>;
};

const resourceComposerCopy: Record<ComposerLanguage, ResourceComposerCopy> = {
  "zh-CN": {
    nextResource: "下一份资料",
    modes: {
      locate: {
        label: "定位",
        header: "定位下一份资料",
        summary: "资料 · 定位",
        hint: "找出现在最值得打开的资料。",
        placeholder: "搜一份资料",
        accessibilityLabel: "提交资料定位或打开请求",
        primaryPrompt: {
          label: "找文件",
          prompt: "在资料库中找出当前任务最该先打开的文件或文件夹，并说明理由。",
        },
        secondaryPrompt: {
          label: "打开下一个",
          prompt: "建议我下一步打开哪份相关资料，并说明理由。",
        },
      },
      download: {
        label: "补资料",
        header: "补齐缺少的资料",
        summary: "资料 · 补齐",
        hint: "判断还缺什么，是否值得导入。",
        placeholder: "讨论缺少的资料、要导入什么，以及放在哪里。",
        accessibilityLabel: "提交资料补齐请求",
        primaryPrompt: {
          label: "找缺口",
          prompt: "根据当前任务，找出还缺哪些资料，以及最值得先补齐的内容。",
        },
        secondaryPrompt: {
          label: "补来源",
          prompt: "判断当前资料库还缺哪类基础来源，并给出最小补齐建议。",
        },
      },
      organize: {
        label: "整理",
        header: "整理资料结构",
        summary: "资料 · 整理",
        hint: "把资料分组得更清楚、更好找。",
        placeholder: "整理资料结构、项目文件夹或命名方式。",
        accessibilityLabel: "提交资料整理请求",
        primaryPrompt: {
          label: "整理结构",
          prompt: "检查当前资料库，给出更清楚的 sources、knowledge、cards、notes 和项目资料分组方式。",
        },
        secondaryPrompt: {
          label: "按项目分组",
          prompt: "把当前资料库重组为总体资料和按项目分类的两层结构。",
        },
      },
      cards: {
        label: "做成卡片",
        header: "把资料变成可练习的卡片",
        summary: "资料 · 卡片",
        hint: "挑出最值得练习的内容。",
        placeholder: "挑选最值得转成训练卡或闪卡的资料。",
        accessibilityLabel: "提交资料转卡请求",
        primaryPrompt: {
          label: "生成卡片",
          prompt: "从当前资料中挑出最值得转成训练卡或闪卡的内容，并说明理由。",
        },
        secondaryPrompt: {
          label: "提知识点",
          prompt: "从当前资料中提取几个可直接教学的知识点，并说明各自适合哪类卡片。",
        },
      },
    },
  },
  "en-US": {
    nextResource: "Next resource",
    modes: {
      locate: {
        label: "Locate",
        header: "Locate the next resource",
        summary: "Resources · Locate",
        hint: "Find the resource worth opening now.",
        placeholder: "Find a file",
        accessibilityLabel: "Submit a resource locate or open request",
        primaryPrompt: {
          label: "Find file",
          prompt: "Find the file or folder in Resources that is most useful for the current task, and explain why.",
        },
        secondaryPrompt: {
          label: "Open next",
          prompt: "Recommend the related resource I should open next and explain why.",
        },
      },
      download: {
        label: "Fill gaps",
        header: "Fill missing resources",
        summary: "Resources · Fill gaps",
        hint: "Decide what is missing and worth importing.",
        placeholder: "Discuss what is missing, what to import, and where it should go.",
        accessibilityLabel: "Submit a resource completion request",
        primaryPrompt: {
          label: "Find gaps",
          prompt: "Based on the current task, identify what material is missing and what is most worth adding first.",
        },
        secondaryPrompt: {
          label: "Fill sources",
          prompt: "Identify the missing source type in the library and give the smallest useful way to fill it.",
        },
      },
      organize: {
        label: "Organize",
        header: "Organize the library",
        summary: "Resources · Organize",
        hint: "Make the library clearer and easier to find things in.",
        placeholder: "Organize the library, project folders, or naming rules.",
        accessibilityLabel: "Submit a resource organization request",
        primaryPrompt: {
          label: "Organize library",
          prompt: "Review this library and suggest a clearer grouping for sources, knowledge, cards, notes, and project materials.",
        },
        secondaryPrompt: {
          label: "Group by project",
          prompt: "Reorganize the library into one overall layer and one layer for each project.",
        },
      },
      cards: {
        label: "Make cards",
        header: "Turn resources into practice cards",
        summary: "Resources · Cards",
        hint: "Choose the material most worth practicing.",
        placeholder: "Choose material to turn into training or flash cards.",
        accessibilityLabel: "Submit a resource-to-card request",
        primaryPrompt: {
          label: "Make cards",
          prompt: "Choose the most valuable current material to turn into training or flash cards, and explain why.",
        },
        secondaryPrompt: {
          label: "Extract ideas",
          prompt: "Extract a few teaching-ready ideas from the current material and say which kind of card each fits.",
        },
      },
    },
  },
  "es-ES": {
    nextResource: "Siguiente recurso",
    modes: {
      locate: {
        label: "Ubicar",
        header: "Ubicar el siguiente recurso",
        summary: "Recursos · Ubicar",
        hint: "Encuentra el recurso que conviene abrir ahora.",
        placeholder: "Ubica, abre o filtra el recurso más relevante.",
        accessibilityLabel: "Enviar una solicitud para ubicar o abrir un recurso",
        primaryPrompt: {
          label: "Buscar archivo",
          prompt: "Busca en Recursos el archivo o carpeta más útil para la tarea actual y explica por qué.",
        },
        secondaryPrompt: {
          label: "Abrir siguiente",
          prompt: "Recomienda el recurso relacionado que debería abrir ahora y explica por qué.",
        },
      },
      download: {
        label: "Completar",
        header: "Completar recursos faltantes",
        summary: "Recursos · Completar",
        hint: "Decide qué falta y qué vale la pena importar.",
        placeholder: "Habla de qué falta, qué importar y dónde guardarlo.",
        accessibilityLabel: "Enviar una solicitud para completar recursos",
        primaryPrompt: {
          label: "Buscar faltantes",
          prompt: "Según la tarea actual, identifica qué material falta y qué conviene añadir primero.",
        },
        secondaryPrompt: {
          label: "Completar fuentes",
          prompt: "Identifica qué tipo de fuente falta y propone la forma más pequeña de completarla.",
        },
      },
      organize: {
        label: "Organizar",
        header: "Organizar la biblioteca",
        summary: "Recursos · Organizar",
        hint: "Haz la biblioteca más clara y fácil de explorar.",
        placeholder: "Organiza la biblioteca, carpetas de proyecto o nombres.",
        accessibilityLabel: "Enviar una solicitud para organizar recursos",
        primaryPrompt: {
          label: "Organizar biblioteca",
          prompt: "Revisa esta biblioteca y propone grupos más claros para fuentes, conocimiento, tarjetas, notas y proyectos.",
        },
        secondaryPrompt: {
          label: "Agrupar por proyecto",
          prompt: "Reorganiza la biblioteca en una capa general y otra para cada proyecto.",
        },
      },
      cards: {
        label: "Crear tarjetas",
        header: "Convertir recursos en tarjetas",
        summary: "Recursos · Tarjetas",
        hint: "Elige el material que más vale la pena practicar.",
        placeholder: "Elige material para convertirlo en tarjetas de práctica.",
        accessibilityLabel: "Enviar una solicitud para convertir recursos en tarjetas",
        primaryPrompt: {
          label: "Crear tarjetas",
          prompt: "Elige el material actual más valioso para convertirlo en tarjetas de práctica o repaso y explica por qué.",
        },
        secondaryPrompt: {
          label: "Extraer ideas",
          prompt: "Extrae ideas listas para enseñar y di qué tipo de tarjeta encaja con cada una.",
        },
      },
    },
  },
  "fr-FR": {
    nextResource: "Prochaine ressource",
    modes: {
      locate: {
        label: "Trouver",
        header: "Trouver la prochaine ressource",
        summary: "Ressources · Trouver",
        hint: "Trouvez la ressource à ouvrir maintenant.",
        placeholder: "Trouvez, ouvrez ou filtrez la ressource la plus utile.",
        accessibilityLabel: "Envoyer une demande pour trouver ou ouvrir une ressource",
        primaryPrompt: {
          label: "Trouver un fichier",
          prompt: "Trouvez dans Ressources le fichier ou dossier le plus utile pour la tâche actuelle et expliquez pourquoi.",
        },
        secondaryPrompt: {
          label: "Ouvrir ensuite",
          prompt: "Recommandez la ressource liée que je devrais ouvrir ensuite et expliquez pourquoi.",
        },
      },
      download: {
        label: "Compléter",
        header: "Compléter les ressources manquantes",
        summary: "Ressources · Compléter",
        hint: "Décidez ce qui manque et mérite d'être importé.",
        placeholder: "Discutez de ce qui manque, de ce qu'il faut importer et de son emplacement.",
        accessibilityLabel: "Envoyer une demande pour compléter les ressources",
        primaryPrompt: {
          label: "Trouver les manques",
          prompt: "Selon la tâche actuelle, identifiez le matériel manquant et ce qu'il faut ajouter en premier.",
        },
        secondaryPrompt: {
          label: "Compléter les sources",
          prompt: "Identifiez le type de source manquant et proposez le plus petit moyen utile de le compléter.",
        },
      },
      organize: {
        label: "Organiser",
        header: "Organiser la bibliothèque",
        summary: "Ressources · Organiser",
        hint: "Rendez la bibliothèque plus claire et facile à parcourir.",
        placeholder: "Organisez la bibliothèque, les dossiers de projet ou les noms.",
        accessibilityLabel: "Envoyer une demande pour organiser les ressources",
        primaryPrompt: {
          label: "Organiser la bibliothèque",
          prompt: "Examinez cette bibliothèque et proposez des groupes plus clairs pour les sources, connaissances, cartes, notes et projets.",
        },
        secondaryPrompt: {
          label: "Grouper par projet",
          prompt: "Réorganisez la bibliothèque avec une couche générale et une couche par projet.",
        },
      },
      cards: {
        label: "Créer des cartes",
        header: "Transformer les ressources en cartes",
        summary: "Ressources · Cartes",
        hint: "Choisissez le matériel qui mérite le plus d'être pratiqué.",
        placeholder: "Choisissez du matériel à transformer en cartes d'entraînement.",
        accessibilityLabel: "Envoyer une demande pour transformer des ressources en cartes",
        primaryPrompt: {
          label: "Créer des cartes",
          prompt: "Choisissez le matériel actuel le plus utile à transformer en cartes d'entraînement ou de révision, et expliquez pourquoi.",
        },
        secondaryPrompt: {
          label: "Extraire des idées",
          prompt: "Extrayez quelques idées prêtes à enseigner et indiquez le type de carte adapté à chacune.",
        },
      },
    },
  },
  "de-DE": {
    nextResource: "Nächstes Material",
    modes: {
      locate: {
        label: "Finden",
        header: "Nächstes Material finden",
        summary: "Material · Finden",
        hint: "Finden Sie das Material, das jetzt geöffnet werden sollte.",
        placeholder: "Material finden, öffnen oder gezielt eingrenzen.",
        accessibilityLabel: "Anfrage zum Finden oder Öffnen von Material senden",
        primaryPrompt: {
          label: "Datei finden",
          prompt: "Finden Sie in Ressourcen die Datei oder den Ordner, der für die aktuelle Aufgabe am nützlichsten ist, und erklären Sie warum.",
        },
        secondaryPrompt: {
          label: "Als Nächstes öffnen",
          prompt: "Empfehlen Sie das verwandte Material, das ich als Nächstes öffnen sollte, und erklären Sie warum.",
        },
      },
      download: {
        label: "Ergänzen",
        header: "Fehlendes Material ergänzen",
        summary: "Material · Ergänzen",
        hint: "Entscheiden Sie, was fehlt und importiert werden sollte.",
        placeholder: "Besprechen Sie fehlendes Material, den Import und den Ablageort.",
        accessibilityLabel: "Anfrage zum Ergänzen von Material senden",
        primaryPrompt: {
          label: "Lücken finden",
          prompt: "Bestimmen Sie anhand der aktuellen Aufgabe, welches Material fehlt und was zuerst ergänzt werden sollte.",
        },
        secondaryPrompt: {
          label: "Quellen ergänzen",
          prompt: "Bestimmen Sie den fehlenden Quellentyp und schlagen Sie die kleinste sinnvolle Ergänzung vor.",
        },
      },
      organize: {
        label: "Ordnen",
        header: "Bibliothek ordnen",
        summary: "Material · Ordnen",
        hint: "Machen Sie die Bibliothek klarer und leichter durchsuchbar.",
        placeholder: "Bibliothek, Projektordner oder Benennungen ordnen.",
        accessibilityLabel: "Anfrage zum Ordnen von Material senden",
        primaryPrompt: {
          label: "Bibliothek ordnen",
          prompt: "Prüfen Sie diese Bibliothek und schlagen Sie klarere Gruppen für Quellen, Wissen, Karten, Notizen und Projekte vor.",
        },
        secondaryPrompt: {
          label: "Nach Projekt ordnen",
          prompt: "Ordnen Sie die Bibliothek mit einer allgemeinen Ebene und einer Ebene pro Projekt neu.",
        },
      },
      cards: {
        label: "Karten erstellen",
        header: "Material in Übungskarten verwandeln",
        summary: "Material · Karten",
        hint: "Wählen Sie Material, das sich am meisten zum Üben lohnt.",
        placeholder: "Material für Trainings- oder Lernkarten auswählen.",
        accessibilityLabel: "Anfrage zum Umwandeln von Material in Karten senden",
        primaryPrompt: {
          label: "Karten erstellen",
          prompt: "Wählen Sie das wertvollste aktuelle Material für Trainings- oder Lernkarten aus und erklären Sie warum.",
        },
        secondaryPrompt: {
          label: "Ideen extrahieren",
          prompt: "Extrahieren Sie einige lehrbereite Ideen und nennen Sie den passenden Kartentyp.",
        },
      },
    },
  },
  "ja-JP": {
    nextResource: "次の資料",
    modes: {
      locate: {
        label: "探す",
        header: "次に開く資料を探す",
        summary: "資料 · 探す",
        hint: "今開くべき資料を見つけます。",
        placeholder: "資料を探す、開く、または絞り込みます。",
        accessibilityLabel: "資料の検索または表示を依頼する",
        primaryPrompt: {
          label: "ファイルを探す",
          prompt: "現在の課題に最も役立つファイルまたはフォルダーを資料から探し、理由を説明してください。",
        },
        secondaryPrompt: {
          label: "次を開く",
          prompt: "次に開くべき関連資料と、その理由を提案してください。",
        },
      },
      download: {
        label: "補う",
        header: "足りない資料を補う",
        summary: "資料 · 補う",
        hint: "不足している資料と、取り込む価値を判断します。",
        placeholder: "不足している資料、取り込む内容、保存先を相談します。",
        accessibilityLabel: "資料を補う依頼を送信する",
        primaryPrompt: {
          label: "不足を探す",
          prompt: "現在の課題に基づいて不足している資料と、最初に補うべき内容を特定してください。",
        },
        secondaryPrompt: {
          label: "ソースを補う",
          prompt: "不足しているソースの種類を特定し、最小限の補い方を提案してください。",
        },
      },
      organize: {
        label: "整理",
        header: "資料庫を整理する",
        summary: "資料 · 整理",
        hint: "資料庫を分かりやすく、探しやすくします。",
        placeholder: "資料庫、プロジェクトフォルダー、命名を整理します。",
        accessibilityLabel: "資料の整理を依頼する",
        primaryPrompt: {
          label: "資料庫を整理",
          prompt: "この資料庫を確認し、ソース、知識、カード、メモ、プロジェクト資料の分かりやすい分類を提案してください。",
        },
        secondaryPrompt: {
          label: "プロジェクト別に整理",
          prompt: "資料庫を全体用の層とプロジェクトごとの層に再編成してください。",
        },
      },
      cards: {
        label: "カード化",
        header: "資料を練習カードにする",
        summary: "資料 · カード",
        hint: "最も練習する価値のある内容を選びます。",
        placeholder: "トレーニングカードや暗記カードにする資料を選びます。",
        accessibilityLabel: "資料をカードにする依頼を送信する",
        primaryPrompt: {
          label: "カードを作る",
          prompt: "現在の資料から、トレーニングカードや暗記カードにする価値が最も高い内容を選び、理由を説明してください。",
        },
        secondaryPrompt: {
          label: "知識を取り出す",
          prompt: "現在の資料から教える準備ができた知識をいくつか取り出し、それぞれに合うカードの種類を示してください。",
        },
      },
    },
  },
  "ko-KR": {
    nextResource: "다음 자료",
    modes: {
      locate: {
        label: "찾기",
        header: "다음 자료 찾기",
        summary: "자료 · 찾기",
        hint: "지금 열어 볼 자료를 찾습니다.",
        placeholder: "자료를 찾거나 열고, 가장 관련 있는 항목으로 좁힙니다.",
        accessibilityLabel: "자료 찾기 또는 열기 요청 보내기",
        primaryPrompt: {
          label: "파일 찾기",
          prompt: "현재 작업에 가장 유용한 파일이나 폴더를 자료에서 찾고 이유를 설명해 주세요.",
        },
        secondaryPrompt: {
          label: "다음 열기",
          prompt: "다음에 열 관련 자료와 이유를 추천해 주세요.",
        },
      },
      download: {
        label: "보완",
        header: "부족한 자료 보완",
        summary: "자료 · 보완",
        hint: "무엇이 부족하고 가져올 가치가 있는지 판단합니다.",
        placeholder: "부족한 자료, 가져올 내용, 저장할 곳을 논의합니다.",
        accessibilityLabel: "자료 보완 요청 보내기",
        primaryPrompt: {
          label: "부족한 점 찾기",
          prompt: "현재 작업을 기준으로 부족한 자료와 먼저 보완할 내용을 찾아 주세요.",
        },
        secondaryPrompt: {
          label: "출처 보완",
          prompt: "부족한 출처 유형을 찾고 가장 작은 보완 방법을 제안해 주세요.",
        },
      },
      organize: {
        label: "정리",
        header: "자료 라이브러리 정리",
        summary: "자료 · 정리",
        hint: "자료 라이브러리를 더 명확하고 찾기 쉽게 만듭니다.",
        placeholder: "자료 라이브러리, 프로젝트 폴더, 이름을 정리합니다.",
        accessibilityLabel: "자료 정리 요청 보내기",
        primaryPrompt: {
          label: "라이브러리 정리",
          prompt: "이 자료 라이브러리를 검토하고 출처, 지식, 카드, 메모, 프로젝트 자료를 더 명확하게 분류해 주세요.",
        },
        secondaryPrompt: {
          label: "프로젝트별 정리",
          prompt: "자료 라이브러리를 전체 층과 프로젝트별 층으로 다시 구성해 주세요.",
        },
      },
      cards: {
        label: "카드 만들기",
        header: "자료를 연습 카드로 만들기",
        summary: "자료 · 카드",
        hint: "가장 연습할 가치가 있는 내용을 고릅니다.",
        placeholder: "훈련 카드나 암기 카드로 바꿀 자료를 고릅니다.",
        accessibilityLabel: "자료를 카드로 바꾸는 요청 보내기",
        primaryPrompt: {
          label: "카드 만들기",
          prompt: "현재 자료 중 훈련 카드나 암기 카드로 바꿀 가치가 가장 높은 내용을 고르고 이유를 설명해 주세요.",
        },
        secondaryPrompt: {
          label: "지식 추출",
          prompt: "현재 자료에서 바로 가르칠 수 있는 지식을 몇 개 추출하고 맞는 카드 종류를 알려 주세요.",
        },
      },
    },
  },
  "pt-BR": {
    nextResource: "Próximo material",
    modes: {
      locate: {
        label: "Localizar",
        header: "Localizar o próximo material",
        summary: "Materiais · Localizar",
        hint: "Encontre o material que vale abrir agora.",
        placeholder: "Localize, abra ou filtre o material mais relevante.",
        accessibilityLabel: "Enviar um pedido para localizar ou abrir material",
        primaryPrompt: {
          label: "Encontrar arquivo",
          prompt: "Encontre em Materiais o arquivo ou pasta mais útil para a tarefa atual e explique o motivo.",
        },
        secondaryPrompt: {
          label: "Abrir em seguida",
          prompt: "Recomende o material relacionado que devo abrir em seguida e explique o motivo.",
        },
      },
      download: {
        label: "Completar",
        header: "Completar materiais faltantes",
        summary: "Materiais · Completar",
        hint: "Decida o que falta e vale importar.",
        placeholder: "Fale sobre o que falta, o que importar e onde guardar.",
        accessibilityLabel: "Enviar um pedido para completar materiais",
        primaryPrompt: {
          label: "Encontrar lacunas",
          prompt: "Com base na tarefa atual, identifique o material que falta e o que vale adicionar primeiro.",
        },
        secondaryPrompt: {
          label: "Completar fontes",
          prompt: "Identifique o tipo de fonte que falta e proponha a menor forma útil de completá-la.",
        },
      },
      organize: {
        label: "Organizar",
        header: "Organizar a biblioteca",
        summary: "Materiais · Organizar",
        hint: "Deixe a biblioteca mais clara e fácil de explorar.",
        placeholder: "Organize a biblioteca, pastas do projeto ou nomes.",
        accessibilityLabel: "Enviar um pedido para organizar materiais",
        primaryPrompt: {
          label: "Organizar biblioteca",
          prompt: "Revise esta biblioteca e sugira grupos mais claros para fontes, conhecimento, cartões, notas e projetos.",
        },
        secondaryPrompt: {
          label: "Agrupar por projeto",
          prompt: "Reorganize a biblioteca em uma camada geral e outra para cada projeto.",
        },
      },
      cards: {
        label: "Criar cartões",
        header: "Transformar materiais em cartões",
        summary: "Materiais · Cartões",
        hint: "Escolha o material que mais vale praticar.",
        placeholder: "Escolha material para transformar em cartões de treino ou revisão.",
        accessibilityLabel: "Enviar um pedido para transformar materiais em cartões",
        primaryPrompt: {
          label: "Criar cartões",
          prompt: "Escolha o material atual mais valioso para transformar em cartões de treino ou revisão e explique o motivo.",
        },
        secondaryPrompt: {
          label: "Extrair ideias",
          prompt: "Extraia algumas ideias prontas para ensinar e diga qual tipo de cartão combina com cada uma.",
        },
      },
    },
  },
};

export function resolveResourceComposerCopy(language: ComposerLanguage): ResourceComposerCopy {
  return resourceComposerCopy[language] ?? resourceComposerCopy["en-US"];
}

export type ResourceOrganizationConfirmCopy = {
  message: string;
  messageWithCount: string;
  confirm: string;
  cancel: string;
};

const resourceOrganizationConfirmCopy: Record<ComposerLanguage, ResourceOrganizationConfirmCopy> = {
  "zh-CN": {
    message: "整理方案待确认。确认后才会改动资料库结构。",
    messageWithCount: "整理方案待确认（{count} 项）。确认后才会改动资料库结构。",
    confirm: "确认整理",
    cancel: "取消",
  },
  "en-US": {
    message: "Organization proposal ready. Confirm before any library changes.",
    messageWithCount: "Organization proposal ready ({count} changes). Confirm before any library changes.",
    confirm: "Confirm organize",
    cancel: "Cancel",
  },
  "es-ES": {
    message: "Propuesta de organización lista. Confirma antes de cambiar la biblioteca.",
    messageWithCount: "Propuesta de organización lista ({count} cambios). Confirma antes de cambiar la biblioteca.",
    confirm: "Confirmar organización",
    cancel: "Cancelar",
  },
  "fr-FR": {
    message: "Proposition d'organisation prête. Confirmez avant toute modification.",
    messageWithCount: "Proposition d'organisation prête ({count} changements). Confirmez avant toute modification.",
    confirm: "Confirmer l'organisation",
    cancel: "Annuler",
  },
  "de-DE": {
    message: "Organisationsvorschlag bereit. Bestätigen, bevor die Bibliothek geändert wird.",
    messageWithCount: "Organisationsvorschlag bereit ({count} Änderungen). Bestätigen, bevor die Bibliothek geändert wird.",
    confirm: "Organisation bestätigen",
    cancel: "Abbrechen",
  },
  "ja-JP": {
    message: "整理案の確認待ちです。確認するまで資料庫は変わりません。",
    messageWithCount: "整理案の確認待ちです（{count} 件）。確認するまで資料庫は変わりません。",
    confirm: "整理を確定",
    cancel: "キャンセル",
  },
  "ko-KR": {
    message: "정리 제안이 준비되었습니다. 확인 후에만 자료실이 바뀝니다.",
    messageWithCount: "정리 제안이 준비되었습니다({count}개). 확인 후에만 자료실이 바뀝니다.",
    confirm: "정리 확인",
    cancel: "취소",
  },
  "pt-BR": {
    message: "Proposta de organização pronta. Confirme antes de alterar a biblioteca.",
    messageWithCount: "Proposta de organização pronta ({count} alterações). Confirme antes de alterar a biblioteca.",
    confirm: "Confirmar organização",
    cancel: "Cancelar",
  },
};

export function resolveResourceOrganizationConfirmCopy(
  language: ComposerLanguage,
): ResourceOrganizationConfirmCopy {
  return resourceOrganizationConfirmCopy[language] ?? resourceOrganizationConfirmCopy["en-US"];
}
