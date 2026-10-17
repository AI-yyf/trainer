import type { ComposerLanguage } from "./types";

/**
 * 内置课程模板（§3.5 / §4.3 冷启动种子）。
 * P0 阶段仅作只读预览：空计划态在 Learning 底部以 disclosure
 * 展示第一条真实路径，fork 写入本地计划属 P1（course.json 导入）。
 * 文案八语言齐全；内容结构抽取自 mockData.ts 的三阶段切片并转正。
 */

export interface StarterTemplateStage {
  title: string;
  objective: string;
}

export interface StarterTemplate {
  title: string;
  summary: string;
  stages: StarterTemplateStage[];
}

/** P2 #16: a built-in course template is subject-scoped data. The code
 * starter stays the default; literature ships three packs (close reading,
 * imitation writing, one-theory-concept reading). Governance semantics are
 * not touched — these are cold-start previews that fork into a local plan. */
export interface StarterTemplateDef {
  id: string;
  subjectFamily: "code" | "literature";
  byLanguage: Record<ComposerLanguage, StarterTemplate>;
}

export const starterTemplate: Record<ComposerLanguage, StarterTemplate> = {
  "zh-CN": {
    title: "三步修一个 Bug",    summary: "一条最小但完整的修复路径：先定位，再小步改，最后用证据收尾。",
    stages: [
      { title: "找到会报错的那段", objective: "打开当前文件，读一遍出错时走到的代码，别急着改。" },
      { title: "只改这一处", objective: "改当前文件里这一段，别同时动别的，改完说清为什么这样改。" },
      { title: "用一次真实运行收尾", objective: "用会触发问题的方式跑一遍，亲眼确认现象变了再往下走。" },
    ],
  },
  "en-US": {
    title: "Fix a bug in three steps",
    summary: "A minimal but complete repair path: locate first, change in a small step, close with evidence.",
    stages: [
      { title: "Find the failing part", objective: "Open the current file and read the code path that fails — before changing anything." },
      { title: "Change only this spot", objective: "Edit just this part of the current file, nothing else, and explain why the change works." },
      { title: "Close with a real run", objective: "Run the failing case once and confirm with your own eyes that the behavior changed." },
    ],
  },
  "es-ES": {
    title: "Arregla un error en tres pasos",
    summary: "Una ruta mínima pero completa: localizar primero, cambiar en pasos pequeños y cerrar con evidencia.",
    stages: [
      { title: "Encuentra la parte que falla", objective: "Abre el archivo actual y lee el código que falla antes de cambiar nada." },
      { title: "Cambia solo este punto", objective: "Edita solo esta parte del archivo actual y explica por qué el cambio funciona." },
      { title: "Cierra con una ejecución real", objective: "Ejecuta el caso que falla y confirma con tus propios ojos que el comportamiento cambió." },
    ],
  },
  "fr-FR": {
    title: "Corriger un bug en trois étapes",
    summary: "Un chemin minimal mais complet : localiser d'abord, modifier par petites touches, conclure par une preuve.",
    stages: [
      { title: "Trouver la partie qui échoue", objective: "Ouvre le fichier courant et lis le code qui échoue avant de rien modifier." },
      { title: "Ne modifier que cet endroit", objective: "Modifie uniquement cette partie du fichier courant et explique pourquoi le changement fonctionne." },
      { title: "Conclure par une exécution réelle", objective: "Lance le cas qui échoue et confirme de tes propres yeux que le comportement a changé." },
    ],
  },
  "de-DE": {
    title: "Einen Bug in drei Schritten beheben",
    summary: "Ein minimaler, aber vollständiger Weg: erst lokalisieren, dann klein ändern, am Ende mit einem Nachweis abschließen.",
    stages: [
      { title: "Die fehlerhafte Stelle finden", objective: "Öffne die aktuelle Datei und lies den Codepfad, der fehlschlägt — bevor du etwas änderst." },
      { title: "Nur diese Stelle ändern", objective: "Ändere nur diesen Teil der aktuellen Datei und erkläre, warum die Änderung funktioniert." },
      { title: "Mit einem echten Lauf abschließen", objective: "Führe den fehlschlagenden Fall einmal aus und bestätige selbst, dass sich das Verhalten geändert hat." },
    ],
  },
  "ja-JP": {
    title: "3 ステップでバグを直す",
    summary: "最小だが完全な修正パス：まず特定し、小さく直し、最後は証拠で締める。",
    stages: [
      { title: "失敗している部分を見つける", objective: "現在のファイルを開き、失敗時のコードの流れを読む。まだ直さない。" },
      { title: "その一箇所だけ直す", objective: "現在のファイルのこの部分だけを直し、なぜそれで直るのかを言葉にする。" },
      { title: "実際の実行で締める", objective: "失敗するケースを一度実行し、挙動が変わったのを自分の目で確かめる。" },
    ],
  },
  "ko-KR": {
    title: "세 단계로 버그 고치기",
    summary: "최소지만 완전한 수정 경로: 먼저 찾고, 조금씩 고치고, 증거로 마무리합니다.",
    stages: [
      { title: "실패하는 부분 찾기", objective: "현재 파일을 열고 실패 시 실행되는 코드를 읽습니다. 아직 고치지 않습니다." },
      { title: "그 한 곳만 고치기", objective: "현재 파일의 이 부분만 고치고, 왜 이 변경이 동작하는지 설명합니다." },
      { title: "실제 실행으로 마무리", objective: "실패하는 케이스를 한 번 실행하고, 동작이 바뀐 것을 직접 확인합니다." },
    ],
  },
  "pt-BR": {
    title: "Corrigir um bug em três passos",
    summary: "Um caminho mínimo, mas completo: localizar primeiro, mudar em passos pequenos e fechar com evidência.",
    stages: [
      { title: "Encontrar a parte que falha", objective: "Abra o arquivo atual e leia o código que falha antes de mudar qualquer coisa." },
      { title: "Mudar só este ponto", objective: "Edite apenas esta parte do arquivo atual e explique por que a mudança funciona." },
      { title: "Fechar com uma execução real", objective: "Execute o caso que falha uma vez e confirme com os próprios olhos que o comportamento mudou." },
    ],
  },
};

const codeStarterDef: StarterTemplateDef = { id: "code-fix-bug-three-steps", subjectFamily: "code", byLanguage: starterTemplate };

/** P2 #16: three built-in literature course packs (close reading / imitation
 * writing / one-theory-concept reading). Eight-language complete; each stage
 * ends in something verifiable (an anchor, a stat, a question) so forking
 * into a plan keeps the evidence discipline. */
export const starterTemplates: StarterTemplateDef[] = [
  codeStarterDef,
  {
    id: "literature-close-reading-three-steps",
    subjectFamily: "literature",
    byLanguage: {
      "zh-CN": {
        title: "精读一篇短篇：三步",
        summary: "从叙述视角到批注，再到一个可验证的理解问题——每步都落在原文锚点上。",
        stages: [
          { title: "锚定叙述视角", objective: "找出叙事者是谁，引用一个 ¶ 锚点证明你的判断。" },
          { title: "分层批注三段", objective: "对三个段落各写一条批注：一条词汇、一条句式、一条结构，各自带锚点。" },
          { title: "以一个理解问题收尾", objective: "提出一个可验证的问题，并写明你能用哪个锚点回答它。" },
        ],
      },
      "en-US": {
        title: "Close-read one story in three steps",
        summary: "From narrative viewpoint to annotations to one verifiable comprehension question — every step lands on a source anchor.",
        stages: [
          { title: "Anchor the narrative viewpoint", objective: "Identify who narrates and cite one ¶ anchor that proves your judgement." },
          { title: "Annotate three passages in layers", objective: "Write one annotation for each of three passages — diction, syntax, structure — each with its anchor." },
          { title: "Close with a comprehension question", objective: "Pose one verifiable question and name the anchor you would use to answer it." },
        ],
      },
      "es-ES": {
        title: "Lee atentamente un relato en tres pasos",
        summary: "Del punto de vista narrativo a las anotaciones y una pregunta verificable: cada paso se apoya en un ancla del original.",
        stages: [
          { title: "Ancla el punto de vista narrativo", objective: "Identifica quién narra y cita un ancla ¶ que respalde tu juicio." },
          { title: "Anota tres pasajes por capas", objective: "Escribe una anotación para cada uno de tres pasajes — léxico, sintaxis, estructura — con su ancla." },
          { title: "Cierra con una pregunta de comprensión", objective: "Plantea una pregunta verificable y nombra el ancla con la que la responderías." },
        ],
      },
      "fr-FR": {
        title: "Lire analytiquement une nouvelle en trois étapes",
        summary: "Du point de vue narratif aux annotations, jusqu'à une question de compréhension vérifiable — chaque étape s'ancre dans le texte.",
        stages: [
          { title: "Ancrer le point de vue narratif", objective: "Identifie qui raconte et cite une ancre ¶ qui prouve ton jugement." },
          { title: "Annoter trois passages par couches", objective: "Écris une annotation pour chacun de trois passages — lexique, syntaxe, structure — avec son ancre." },
          { title: "Conclure par une question de compréhension", objective: "Pose une question vérifiable et nomme l'ancre qui permettrait d'y répondre." },
        ],
      },
      "de-DE": {
        title: "Eine Erzählung in drei Schritten nahlesen",
        summary: "Vom Erzählperspektiv-Anker über Anmerkungen bis zu einer überprüfbaren Verständnisfrage — jeder Schritt landet am Quellenanker.",
        stages: [
          { title: "Die Erzählperspektive verankern", objective: "Bestimme, wer erzählt, und zitiere einen ¶-Anker, der dein Urteil belegt." },
          { title: "Drei Passagen schichtweise anmerken", objective: "Schreibe zu drei Passagen je eine Anmerkung — Wortwahl, Syntax, Struktur — mit Anker." },
          { title: "Mit einer Verständnisfrage abschließen", objective: "Stelle eine überprüfbare Frage und nenne den Anker, mit dem du sie beantworten würdest." },
        ],
      },
      "ja-JP": {
        title: "短編を精読する三歩",
        summary: "語り手の視点から注釈、そして検証可能な理解問題へ——各ステップが原文アンカーに着地する。",
        stages: [
          { title: "語りの視点をアンカーする", objective: "誰が語っているかを特定し、判断を裏づける ¶ アンカーをひとつ引用する。" },
          { title: "三つの箇所を層ごとに注釈する", objective: "語彙・構文・構造の観点で三箇所にそれぞれ注釈を書き、各々にアンカーを付ける。" },
          { title: "理解問題で締める", objective: "検証可能な問題をひとつ立て、どのアンカーで答えられるかを書き添える。" },
        ],
      },
      "ko-KR": {
        title: "한 편의 단편을 정독하는 세 걸음",
        summary: "서술 시점부터 주석, 검증 가능한 이해 질문까지 — 매 단계가 원문 앵커에 닿습니다.",
        stages: [
          { title: "서술 시점 고정", objective: "누가 서술하는지 밝히고 판단을 뒷받침하는 ¶ 앵커 하나를 인용합니다." },
          { title: "세 구절 층위별 주석", objective: "어휘·구문·구조 관점으로 세 구절에 각각 주석을 쓰고 앵커를 붙입니다." },
          { title: "이해 질문으로 마무리", objective: "검증 가능한 질문을 하나 세우고 어떤 앵커로 답할지 적습니다." },
        ],
      },
      "pt-BR": {
        title: "Ler atentamente um conto em três passos",
        summary: "Do ponto de vista narrativo às anotações e a uma pergunta verificável — cada passo se ancora no texto.",
        stages: [
          { title: "Ancorar o ponto de vista narrativo", objective: "Identifique quem narra e cite uma âncora ¶ que prove seu julgamento." },
          { title: "Anotar três trechos em camadas", objective: "Escreva uma anotação para cada um dos três trechos — léxico, sintaxe, estrutura — com âncora." },
          { title: "Fechar com uma pergunta de compreensão", objective: "Coloque uma pergunta verificável e indique a âncora que a responderia." },
        ],
      },
    },
  },
  {
    id: "literature-imitation-writing-three-steps",
    subjectFamily: "literature",
    byLanguage: {
      "zh-CN": {
        title: "仿写一段：从读到写",
        summary: "先做确定性节奏统计，再写同构仿写，最后用对照统计自查——仿写不作为证据。",
        stages: [
          { title: "统计锚点节奏", objective: "数出锚点段落的句数、平均句长与标点密度（用 compare_with_anchor 的信号）。" },
          { title: "同构仿写", objective: "写一段句式结构相同的仿写，并明确标注你有意改变的地方。" },
          { title: "对照自查", objective: "用确定性信号对照两段，说清哪些差异是故意的、哪些是失误。" },
        ],
      },
      "en-US": {
        title: "Imitate one passage: from reading to writing",
        summary: "Deterministic rhythm stats first, then a structurally parallel imitation, then a comparison pass — the imitation is not evidence.",
        stages: [
          { title: "Take the anchor's rhythm stats", objective: "Count sentences, mean length, and punctuation density using compare_with_anchor signals." },
          { title: "Write the parallel imitation", objective: "Draft a passage with the same sentence structure, explicitly marking what you changed on purpose." },
          { title: "Compare and self-check", objective: "Compare both passages on the deterministic signals and state which differences are intentional." },
        ],
      },
      "es-ES": {
        title: "Imita un pasaje: de leer a escribir",
        summary: "Primero estadísticas rítmicas deterministas, luego una imitación estructurada y una pasada comparativa — la imitación no es evidencia.",
        stages: [
          { title: "Toma el ritmo del ancla", objective: "Cuenta oraciones, longitud media y densidad de puntuación con las señales de compare_with_anchor." },
          { title: "Escribe la imitación paralela", objective: "Redacta un pasaje con la misma estructura sintáctica, marcando lo que cambiaste a propósito." },
          { title: "Compara y autocorrige", objective: "Compara ambos pasajes con las señales deterministas y aclara qué diferencias son intencionales." },
        ],
      },
      "fr-FR": {
        title: "Imiter un passage : de la lecture à l'écriture",
        summary: "D'abord les statistiques rythmiques déterministes, puis une imitation structurée, enfin un passage comparatif — l'imitation n'est pas une preuve.",
        stages: [
          { title: "Prendre le rythme de l'ancre", objective: "Compte phrases, longueur moyenne et densité de ponctuation avec les signaux de compare_with_anchor." },
          { title: "Écrire l'imitation parallèle", objective: "Rédige un passage de même structure syntaxique en marquant ce que tu as changé volontairement." },
          { title: "Comparer et s'autocontrôler", objective: "Compare les deux passages sur les signaux déterministes et précise quelles différences sont intentionnelles." },
        ],
      },
      "de-DE": {
        title: "Eine Passage nachahmen: vom Lesen zum Schreiben",
        summary: "Zuerst die deterministische Rhythmusstatistik, dann eine strukturell parallele Nachahmung, zuletzt ein Vergleichslauf — die Nachahmung ist kein Beleg.",
        stages: [
          { title: "Den Rhythmus des Ankers erfassen", objective: "Zähle Sätze, mittlere Länge und Satzzeichen-Dichte mit den compare_with_anchor-Signalen." },
          { title: "Die parallele Nachahmung schreiben", objective: "Entwirf eine Passage gleicher Satzstruktur und markiere, was du absichtlich geändert hast." },
          { title: "Vergleichen und selbst prüfen", objective: "Vergleiche beide Passagen über die deterministischen Signale und benenne die absichtlichen Unterschiede." },
        ],
      },
      "ja-JP": {
        title: "一節を模倣する：読みから書きへ",
        summary: "決定論的なリズム統計→同型の模倣→対照統計で自己点検。模倣はエビデンスにならない。",
        stages: [
          { title: "アンカーのリズムを数える", objective: "compare_with_anchor の信号で文数・平均文長・句読点密度を出す。" },
          { title: "同型の模倣を書く", objective: "同じ文構造の模倣文を書き、意図的に変えた箇所を明示する。" },
          { title: "対照して自己点検する", objective: "決定論的信号で両者を比較し、どの差異が意図的かを言い切る。" },
        ],
      },
      "ko-KR": {
        title: "한 구절 모방하기: 읽기에서 쓰기로",
        summary: "결정론적 리듬 통계 → 같은 구조의 모방 → 대조 통계로 자기 점검. 모방은 증거가 아닙니다.",
        stages: [
          { title: "앵커의 리듬 재기", objective: "compare_with_anchor 신호로 문장 수·평균 길이·문장부호 밀도를 셉니다." },
          { title: "평행 모방 쓰기", objective: "같은 문장 구조의 모방문을 쓰고 의도적으로 바꾼 곳을 표시합니다." },
          { title: "대조하며 자기 점검", objective: "결정론적 신호로 두 구절을 비교하고 어떤 차이가 의도적인지 말합니다." },
        ],
      },
      "pt-BR": {
        title: "Imitar um trecho: da leitura à escrita",
        summary: "Primeiro as estatísticas rítmicas determinísticas, depois uma imitação estrutural e uma passagem comparativa — a imitação não é evidência.",
        stages: [
          { title: "Colher o ritmo da âncora", objective: "Conte frases, comprimento médio e densidade de pontuação com os sinais de compare_with_anchor." },
          { title: "Escrever a imitação paralela", objective: "Rascunhe um trecho com a mesma estrutura de frases, marcando o que mudou de propósito." },
          { title: "Comparar e autoavaliar", objective: "Compare os dois trechos nos sinais determinísticos e diga quais diferenças são intencionais." },
        ],
      },
    },
  },
  {
    id: "literature-one-theory-concept",
    subjectFamily: "literature",
    byLanguage: {
      "zh-CN": {
        title: "用一个文论概念读一篇",
        summary: "最小定义、两个锚点证据、150 字应用——概念要有出处，观察与解读分开。",
        stages: [
          { title: "选定并定义概念", objective: "挑一个概念（如不可靠叙述），写出最小定义与其出处。" },
          { title: "找两个锚点证据", objective: "在文本中找两处支持该概念的段落，各引一个 ¶ 锚点。" },
          { title: "写 150 字应用", objective: "综合两处证据写一段应用，把事实观察与个人解读分开陈述。" },
        ],
      },
      "en-US": {
        title: "Read one text through one theory concept",
        summary: "Minimal definition, two anchored pieces of evidence, a 150-word application — concepts need provenance; observation stays separate from interpretation.",
        stages: [
          { title: "Pick and define the concept", objective: "Choose one concept (e.g. unreliable narration) and write its minimal definition with provenance." },
          { title: "Find two anchored evidence passages", objective: "Locate two passages supporting the concept, each cited with a ¶ anchor." },
          { title: "Write a 150-word application", objective: "Synthesize both pieces of evidence into a short application, separating factual observation from interpretation." },
        ],
      },
      "es-ES": {
        title: "Leer un texto con un concepto de teoría",
        summary: "Definición mínima, dos evidencias ancladas, una aplicación de 150 palabras — el concepto necesita procedencia; la observación se separa de la interpretación.",
        stages: [
          { title: "Elige y define el concepto", objective: "Escoge un concepto (p. ej., narrador no fiable) y escribe su definición mínima con procedencia." },
          { title: "Encuentra dos evidencias ancladas", objective: "Localiza dos pasajes que apoyen el concepto, cada uno citado con un ancla ¶." },
          { title: "Escribe una aplicación de 150 palabras", objective: "Sintetiza ambas evidencias en una aplicación breve, separando observación fáctica de interpretación." },
        ],
      },
      "fr-FR": {
        title: "Lire un texte avec un concept de théorie",
        summary: "Définition minimale, deux preuves ancrées, une application de 150 mots — le concept a besoin d'une provenance ; l'observation reste séparée de l'interprétation.",
        stages: [
          { title: "Choisir et définir le concept", objective: "Choisis un concept (p. ex. narrateur non fiable) et écris sa définition minimale avec sa provenance." },
          { title: "Trouver deux preuves ancrées", objective: "Repère deux passages appuyant le concept, chacun cité avec une ancre ¶." },
          { title: "Écrire une application de 150 mots", objective: "Synthétise les deux preuves en une courte application, en séparant l'observation factuelle de l'interprétation." },
        ],
      },
      "de-DE": {
        title: "Einen Text mit einem Theoriebegriff lesen",
        summary: "Minimaldefinition, zwei verankerte Belege, eine 150-Wort-Anwendung — Begriffe brauchen Herkunft; Beobachtung bleibt getrennt von Deutung.",
        stages: [
          { title: "Den Begriff wählen und definieren", objective: "Wähle einen Begriff (z. B. unzuverlässiges Erzählen) und schreibe seine Minimaldefinition mit Herkunft." },
          { title: "Zwei verankerte Belege finden", objective: "Finde zwei Passagen, die den Begriff stützen, jeweils mit ¶-Anker zitiert." },
          { title: "Eine 150-Wort-Anwendung schreiben", objective: "Führe beide Belege in einer kurzen Anwendung zusammen und trenne Beobachtung von Deutung." },
        ],
      },
      "ja-JP": {
        title: "ひとつの理論概念で読む",
        summary: "最小定義・アンカー付きの根拠二つ・150 字の応用。概念には出典を、観察と解釈は分けて。",
        stages: [
          { title: "概念を選び定義する", objective: "ひとつの概念（例：信頼できない語り手）を選び、出典付きの最小定義を書く。" },
          { title: "アンカー付きの根拠を二つ探す", objective: "概念を裏づける箇所を二つ見つけ、それぞれ ¶ アンカーを引用する。" },
          { title: "150 字で応用する", objective: "二つの根拠をまとめた短い応用を書き、事実の観察と解釈を分けて述べる。" },
        ],
      },
      "ko-KR": {
        title: "하나의 이론 개념으로 읽기",
        summary: "최소 정의, 앵커로 고정된 근거 두 개, 150자 적용 — 개념에는 출처가 필요하고 관찰과 해석은 분리합니다.",
        stages: [
          { title: "개념 선택과 정의", objective: "개념 하나(예: 신뢰할 수 없는 서술자)를 골라 출처와 함께 최소 정의를 씁니다." },
          { title: "앵커 근거 두 개 찾기", objective: "개념을 뒷받침하는 구절 두 곳을 찾아 각각 ¶ 앵커로 인용합니다." },
          { title: "150자 적용 쓰기", objective: "두 근거를 종합한 짧은 적용문을 쓰고 사실 관찰과 해석을 분리해 서술합니다." },
        ],
      },
      "pt-BR": {
        title: "Ler um texto com um conceito de teoria",
        summary: "Definição mínima, duas evidências ancoradas, uma aplicação de 150 palavras — o conceito precisa de procedência; observação fica separada da interpretação.",
        stages: [
          { title: "Escolher e definir o conceito", objective: "Escolha um conceito (ex.: narrador não confiável) e escreva sua definição mínima com procedência." },
          { title: "Encontrar duas evidências ancoradas", objective: "Localize dois trechos que sustentem o conceito, cada um citado com uma âncora ¶." },
          { title: "Escrever uma aplicação de 150 palavras", objective: "Sintetize as duas evidências em uma aplicação curta, separando observação factual de interpretação." },
        ],
      },
    },
  },
];

/** Templates matching a subject family; unknown families see the code starter
 * only (fail-closed, same fallback as SubjectProfile resolution). */
export function starterTemplateDefsFor(subjectFamily: string | undefined): StarterTemplateDef[] {
  const family = strFamily(subjectFamily);
  if (family === "literature") {
    return starterTemplates.filter((def) => def.subjectFamily === "literature");
  }
  return [codeStarterDef];
}

function strFamily(value: string | undefined): string {
  return String(value || "").trim().toLowerCase();
}

/** P2 #16/#21: subject signal for the template disclosure. A projection that
 * carries the literature-only dimensions (expression/appreciation) marks a
 * literature workspace; everything else keeps the code starter. Pure and
 * fail-closed — no React, no store reads. */
export function resolveStarterSubjectFamily(
  projection?: { dimensions?: Record<string, unknown> } | undefined,
): "code" | "literature" {
  const dims = projection?.dimensions;
  if (dims && ("expression" in dims || "appreciation" in dims)) {
    return "literature";
  }
  return "code";
}
