/**
 * Native-language showcase fixtures for scripts/capture-ui-golden.mjs across
 * all 8 supported Trainer locales. Ensures README screenshots show authentic,
 * up-to-date features (Two-Destination UI, Learning Drawer, 4-segment capability
 * bar, RethinkFun State-Flow lecture notes, Unified <LibraryRoot>, Direct Proxy
 * Bypass, Inline Practice Card + Single Composer, and Browser Capture) in each
 * target language without touching production/e2e mock fixtures.
 */

export const SUPPORTED_SCREENSHOT_LOCALES = [
  "en-US",
  "zh-CN",
  "de-DE",
  "es-ES",
  "fr-FR",
  "ja-JP",
  "ko-KR",
  "pt-BR",
];

const LOCALE_CONTENT = {
  "en-US": {
    sessionLabel: "Scaled Dot-Product Attention",
    userAuthor: "You",
    planTitle: "Attention Mechanism & PyTorch State Flow",
    planSummary:
      "Derive scaled dot-product attention from first principles, implement the module yourself, and verify gradient stability with tests.",
    stageTitles: [
      "Trace Query / Key dot-product variance",
      "Implement 1/sqrt(d_k) scaled attention",
      "Verify causal masking and gradient norms",
    ],
    stageObjectives: [
      "Track why raw QK^T variance grows linearly with d_k.",
      "Build scaled_dot_product_attention with explicit tensor shape guards and save notes.",
      "Verify numerical stability against PyTorch reference outputs on edge cases.",
    ],
    currentFocus: "Scaled Dot-Product Attention",
    currentTaskTitle: "Derive and test 1/sqrt(d_k) attention scaling",
    currentStep: "Pass unit tests comparing manual scaled attention vs F.scaled_dot_product_attention.",
    whyNow: "Without 1/sqrt(d_k) scaling, softmax saturates into one-hot spikes and gradients vanish.",
    verifyMethod: "Run pytest tests/test_attention.py with shape checks and gradient norm assertions.",
    nextAfter: "Extend single-head attention into multi-head projection.",
    userQuestion:
      "Walk me through why Scaled Dot-Product Attention divides by sqrt(d_k) using state flow, write the minimal PyTorch code, and save a Markdown note to my library.",
    coachReply: [
      "When `q` and `k` have zero-mean unit-variance entries, each dot product sums `d_k` independent products — so its variance grows to `d_k`.",
      "",
      "Large logits push `softmax` into flat tails where gradients nearly vanish. Dividing by `math.sqrt(d_k)` restores unit variance before normalization:",
      "",
      "```python",
      "scores = (q @ k.transpose(-2, -1)) / math.sqrt(d_k)",
      "weights = torch.softmax(scores, dim=-1)",
      "```",
      "",
      "Note saved to `Trainer Library / Lecture Notes / scaled-dot-product-attention.md`.",
    ].join("\n"),
    coachArtifactTitle: "Implement 1/sqrt(d_k) scaling in attention.py",
    coachArtifactSummary: "Add the scale factor and verify output + gradient norms match.",
    coachArtifactBullets: [
      "Read d_k from q.size(-1) instead of hardcoding 64",
      "Run pytest tests/test_attention.py",
    ],
    practiceScenario:
      "Open attention.py in pytorch-attention-lab and implement attention_forward(q, k, v, mask=None).",
    practiceProblem:
      "Raw dot products blow up softmax entropy as d_k increases. Add temperature scaling and optional causal masking.",
    practiceConstraints: [
      "Edit only attention.py in the active workspace",
      "Do not call F.scaled_dot_product_attention inside your implementation",
    ],
    practiceDeliverables: [
      "Exact 1/sqrt(d_k) scaling using q.size(-1)",
      "Verified max diff < 1e-5 against test fixture",
    ],
    practiceVerificationSteps: [
      "Run pytest tests/test_attention.py on the current file",
    ],
    practiceHint: "Use q.size(-1) ** 0.5 and masked_fill(mask == 0, float('-inf')).",
    practiceReflection: "Which tensor dimension shrinks variance back to 1?",
    dueConcepts: [
      {
        concept: "Why 1/sqrt(d_k) stabilizes softmax gradients",
        reason: "Explain variance scaling on QK^T under unit-variance inputs.",
      },
      {
        concept: "Causal mask placement before vs after softmax",
        reason: "Contrast additive -inf masking against zeroing probabilities post-softmax.",
      },
    ],
    resources: [
      {
        id: "res-lecture-attn",
        title: "scaled-dot-product-attention.md",
        summary: "Lecture note saved by Trainer: QK^T variance derivation and gradient check.",
        collectionPath: "Trainer Library/Lecture Notes/scaled-dot-product-attention.md",
        kind: "markdown",
      },
      {
        id: "res-paper-attn",
        title: "Attention Is All You Need (arXiv:1706.03762)",
        summary: "Section 3.2.1 Scaled Dot-Product Attention annotated PDF extract.",
        collectionPath: "Trainer Library/Papers/attention-is-all-you-need.pdf",
        kind: "pdf",
      },
      {
        id: "res-code-attn",
        title: "pytorch-attention-lab / attention.py",
        summary: "Workspace reference file monitored for read-only verification.",
        collectionPath: "Projects/pytorch-attention-lab/attention.py",
        kind: "code",
      },
    ],
    providerName: "MiniMax Direct",
    lastTestDetail: "Connection, model, proxy bypass, and Keychain API key verified.",
    projectName: "pytorch-attention-lab",
    libraryRoot: "~/TrainerLibrary",
    projectPath: "~/Projects/pytorch-attention-lab",
    browserTabTitle: "Attention Is All You Need (arXiv:1706.03762)",
  },

  "zh-CN": {
    sessionLabel: "缩放点积注意力机制",
    userAuthor: "你",
    planTitle: "注意力机制与 PyTorch 状态流实现",
    planSummary:
      "从方差膨胀推导缩放点积注意力，手写实现张量缩放与掩码逻辑，并用测试验证数值与梯度稳定性。",
    stageTitles: [
      "追踪 QK^T 点积方差随维度膨胀",
      "手写 1/sqrt(d_k) 缩放与注意力权重",
      "验证因果掩码与梯度范数边界",
    ],
    stageObjectives: [
      "定位未缩放点积在 d_k 增大时把 softmax 推向饱和区的数学原因。",
      "在 attention.py 中手写缩放点积与掩码，并沉淀一份结构化讲稿笔记。",
      "用单元测试比对参考实现，确认误差与梯度满足阈值要求。",
    ],
    currentFocus: "缩放点积注意力（1/sqrt(d_k)）",
    currentTaskTitle: "手写并验证 1/sqrt(d_k) 注意力缩放模块",
    currentStep: "运行 pytest tests/test_attention.py，验证前向数值误差与梯度均通过。",
    whyNow: "不除 sqrt(d_k) 会让点积方差按 d_k 放大，导致 softmax 退化成近似独热分布、梯度近乎消失。",
    verifyMethod: "在当前文件运行 pytest tests/test_attention.py 检查张量形状与梯度范数。",
    nextAfter: "继续扩展单头注意力为多头线性投影与拼接输出。",
    userQuestion:
      "请用状态流讲透 Scaled Dot-Product Attention 为什么一定要除以 sqrt(d_k)，给出最小 PyTorch 代码，并存一份 Markdown 讲稿到资料库。",
    coachReply: [
      "若 `q` 与 `k` 各分量均值 0、方差 1，点积是对 `d_k` 个独立乘积求和——因此点积结果本身的方差直接放大到 `d_k`。",
      "",
      "logits 过大时，`softmax` 会落入平坦尾部，反向梯度趋近 0。除以 `math.sqrt(d_k)` 可在归一化前把方差拉回 1：",
      "",
      "```python",
      "scores = (q @ k.transpose(-2, -1)) / math.sqrt(d_k)",
      "weights = torch.softmax(scores, dim=-1)",
      "```",
      "",
      "已保存至 `Trainer Library / 学习讲稿 / scaled-dot-product-attention.md`。",
    ].join("\n"),
    coachArtifactTitle: "在 attention.py 中实现 1/sqrt(d_k) 缩放",
    coachArtifactSummary: "补全温度缩放与掩码，并运行当前文件测试完成核验。",
    coachArtifactBullets: [
      "使用 q.size(-1) 动态读取 d_k，不要写死维度",
      "运行 pytest tests/test_attention.py 核验误差",
    ],
    practiceScenario:
      "打开 pytorch-attention-lab/attention.py，补全 attention_forward(q, k, v, mask=None)。",
    practiceProblem:
      "随着特征维度 d_k 升高，未缩放点积会锁死 softmax 分布。请补充缩放因子与因果掩码。",
    practiceConstraints: [
      "只修改当前工作区中的 attention.py",
      "不要直接调用 F.scaled_dot_product_attention 替代实现",
    ],
    practiceDeliverables: [
      "基于 q.size(-1) 计算 1/sqrt(d_k) 缩放",
      "单元测试与参考实现最大绝对误差 < 1e-5",
    ],
    practiceVerificationSteps: [
      "在当前文件执行 pytest tests/test_attention.py",
    ],
    practiceHint: "可用 q.size(-1) ** 0.5 缩放，在 softmax 前调用 masked_fill(mask == 0, float('-inf'))。",
    practiceReflection: "缩放因子具体消除了哪一维求和操作带来的方差累积？",
    dueConcepts: [
      {
        concept: "为什么 1/sqrt(d_k) 能防止 softmax 梯度消失",
        reason: "复述独立同分布假定下 QK^T 方差等于 d_k 的推导过程。",
      },
      {
        concept: "因果掩码必须在 softmax 之前施加的原因",
        reason: "对比 -inf 加法掩码与 softmax 后置零对权重归一化的影响。",
      },
    ],
    resources: [
      {
        id: "res-lecture-attn",
        title: "scaled-dot-product-attention.md",
        summary: "Trainer 自动保存的学习讲稿：QK^T 方差推导与梯度稳定性检查。",
        collectionPath: "Trainer Library/学习讲稿/scaled-dot-product-attention.md",
        kind: "markdown",
      },
      {
        id: "res-paper-attn",
        title: "Attention Is All You Need (arXiv:1706.03762)",
        summary: "论文第 3.2.1 节 Scaled Dot-Product Attention 核心推导摘录。",
        collectionPath: "Trainer Library/Papers/attention-is-all-you-need.pdf",
        kind: "pdf",
      },
      {
        id: "res-code-attn",
        title: "pytorch-attention-lab / attention.py",
        summary: "本地工作区实践代码文件（教练侧始终保持只读核验）。",
        collectionPath: "Projects/pytorch-attention-lab/attention.py",
        kind: "code",
      },
    ],
    providerName: "MiniMax 直连服务",
    lastTestDetail: "端点连通性、模型能力、直连代理及钥匙串 API Key 均已通过核验。",
    projectName: "pytorch-attention-lab",
    libraryRoot: "~/TrainerLibrary",
    projectPath: "~/Projects/pytorch-attention-lab",
    browserTabTitle: "Attention Is All You Need (arXiv:1706.03762)",
  },

  "de-DE": {
    sessionLabel: "Skalierte Punktprodukt-Attention",
    userAuthor: "Du",
    planTitle: "Attention-Mechanismus & PyTorch-Zustandsfluss",
    planSummary:
      "Leite skalierte Punktprodukt-Attention sauber her, implementiere das Modul selbst und prüfe die Gradientenstabilität mit Tests.",
    stageTitles: [
      "QK^T-Varianzwachstum herleiten",
      "1/sqrt(d_k)-Skalierung implementieren",
      "Kausale Maskierung & Gradienten prüfen",
    ],
    stageObjectives: [
      "Verstehen, warum die Varianz von QK^T linear mit d_k wächst.",
      "scaled_dot_product_attention mit Formprüfungen bauen und Notizen sichern.",
      "Numerische Stabilität gegen PyTorch-Referenzausgaben mit Tests verifizieren.",
    ],
    currentFocus: "Skalierte Punktprodukt-Attention",
    currentTaskTitle: "1/sqrt(d_k)-Skalierung umsetzen und testen",
    currentStep: "pytest tests/test_attention.py ausführen und Vorwärts- wie Gradiententests bestehen.",
    whyNow: "Ohne 1/sqrt(d_k) sättigt Softmax in extreme Spitzen und Gradienten verschwinden.",
    verifyMethod: "pytest tests/test_attention.py im aktuellen Workspace ausführen.",
    nextAfter: "Einzelkopf-Attention zur Multi-Head-Projektion erweitern.",
    userQuestion:
      "Erkläre mir schrittweise, warum Scaled Dot-Product Attention durch sqrt(d_k) teilt, zeig minimalen PyTorch-Code und speichere eine Markdown-Notiz.",
    coachReply: [
      "Haben `q` und `k` Mittelwert 0 und Varianz 1, summiert jedes Punktprodukt `d_k` Terme — die Varianz wächst also auf `d_k`.",
      "",
      "Große Logits drücken `softmax` in flache Sättigungsbereiche. Das Teilen durch `math.sqrt(d_k)` stellt vorab Varianz 1 wieder her:",
      "",
      "```python",
      "scores = (q @ k.transpose(-2, -1)) / math.sqrt(d_k)",
      "weights = torch.softmax(scores, dim=-1)",
      "```",
      "",
      "Gespeichert unter `Trainer Library / Vorlesungsnotizen / scaled-dot-product-attention.md`.",
    ].join("\n"),
    coachArtifactTitle: "1/sqrt(d_k) in attention.py implementieren",
    coachArtifactSummary: "Skalierungsfaktor ergänzen und Werte sowie Gradienten prüfen.",
    coachArtifactBullets: [
      "d_k dynamisch über q.size(-1) lesen",
      "pytest tests/test_attention.py zur Prüfung ausführen",
    ],
    practiceScenario:
      "Öffne pytorch-attention-lab/attention.py und implementiere attention_forward(q, k, v, mask=None).",
    practiceProblem:
      "Bei größerem d_k lässt rohes QK^T die Softmax-Entropie kollabieren. Ergänze Skalierung und kausale Maske.",
    practiceConstraints: [
      "Nur attention.py im aktiven Workspace bearbeiten",
      "Nicht direkt F.scaled_dot_product_attention aufrufen",
    ],
    practiceDeliverables: [
      "Korrekte 1/sqrt(d_k)-Skalierung mit q.size(-1)",
      "Abweichung unter 1e-5 gegenüber Referenztest",
    ],
    practiceVerificationSteps: [
      "pytest tests/test_attention.py auf der aktuellen Datei ausführen",
    ],
    practiceHint: "Nutze q.size(-1) ** 0.5 und masked_fill(mask == 0, float('-inf')) vor Softmax.",
    practiceReflection: "Welche Summationsdimension verursacht das Varianzwachstum auf d_k?",
    dueConcepts: [
      {
        concept: "Warum 1/sqrt(d_k) Softmax-Gradienten rettet",
        reason: "Varianzskalierung von QK^T bei standardisierten Eingängen erklären.",
      },
      {
        concept: "Maskierung vor vs. nach Softmax",
        reason: "Unterschied zwischen -inf vor Softmax und Nullen danach begründen.",
      },
    ],
    resources: [
      {
        id: "res-lecture-attn",
        title: "scaled-dot-product-attention.md",
        summary: "Gespeicherte Trainer-Notiz: QK^T-Herleitung und Gradientencheck.",
        collectionPath: "Trainer Library/Vorlesungsnotizen/scaled-dot-product-attention.md",
        kind: "markdown",
      },
      {
        id: "res-paper-attn",
        title: "Attention Is All You Need (arXiv:1706.03762)",
        summary: "Abschnitt 3.2.1 Scaled Dot-Product Attention PDF-Auszug.",
        collectionPath: "Trainer Library/Papers/attention-is-all-you-need.pdf",
        kind: "pdf",
      },
      {
        id: "res-code-attn",
        title: "pytorch-attention-lab / attention.py",
        summary: "Workspace-Datei zur schreibgeschützten Überprüfung.",
        collectionPath: "Projects/pytorch-attention-lab/attention.py",
        kind: "code",
      },
    ],
    providerName: "MiniMax Direkt",
    lastTestDetail: "Verbindung, Modell, Proxy-Bypass und Schlüsselbund-API-Key geprüft.",
    projectName: "pytorch-attention-lab",
    libraryRoot: "~/TrainerLibrary",
    projectPath: "~/Projects/pytorch-attention-lab",
    browserTabTitle: "Attention Is All You Need (arXiv:1706.03762)",
  },

  "es-ES": {
    sessionLabel: "Atención por producto escalar escalado",
    userAuthor: "Tú",
    planTitle: "Mecanismo de atención y flujo de estado en PyTorch",
    planSummary:
      "Deduce el factor 1/sqrt(d_k) desde primeros principios, implementa el módulo tú mismo y valida la estabilidad de gradientes.",
    stageTitles: [
      "Trazar la varianza de QK^T",
      "Implementar atención escalada 1/sqrt(d_k)",
      "Verificar máscara causal y normas de gradiente",
    ],
    stageObjectives: [
      "Comprender por qué la varianza de QK^T crece linealmente con d_k.",
      "Construir scaled_dot_product_attention con comprobación de dimensiones y notas.",
      "Validar la precisión numérica frente a la referencia de PyTorch.",
    ],
    currentFocus: "Atención por producto escalar escalado",
    currentTaskTitle: "Implementar y probar el escalado 1/sqrt(d_k)",
    currentStep: "Ejecutar pytest tests/test_attention.py verificando salida y gradientes.",
    whyNow: "Sin 1/sqrt(d_k), softmax se satura en extremos planos y el gradiente desaparece.",
    verifyMethod: "Ejecuta pytest tests/test_attention.py sobre el archivo actual.",
    nextAfter: "Extender atención de una cabeza hacia Multi-Head Attention.",
    userQuestion:
      "Explícame paso a paso por qué Scaled Dot-Product Attention divide entre sqrt(d_k), dame código mínimo en PyTorch y guarda una nota Markdown.",
    coachReply: [
      "Si `q` y `k` tienen media 0 y varianza 1, cada producto escalar suma `d_k` términos independientes, elevando la varianza a `d_k`.",
      "",
      "Logits grandes empujan a `softmax` a zonas planas donde el gradiente casi se anula. Dividir por `math.sqrt(d_k)` devuelve la varianza a 1:",
      "",
      "```python",
      "scores = (q @ k.transpose(-2, -1)) / math.sqrt(d_k)",
      "weights = torch.softmax(scores, dim=-1)",
      "```",
      "",
      "Nota guardada en `Trainer Library / Apuntes / scaled-dot-product-attention.md`.",
    ].join("\n"),
    coachArtifactTitle: "Implementar 1/sqrt(d_k) en attention.py",
    coachArtifactSummary: "Añade el factor de escala y comprueba salidas y gradientes.",
    coachArtifactBullets: [
      "Leer d_k desde q.size(-1) sin constantes fijas",
      "Ejecutar pytest tests/test_attention.py",
    ],
    practiceScenario:
      "Abre pytorch-attention-lab/attention.py e implementa attention_forward(q, k, v, mask=None).",
    practiceProblem:
      "Al crecer d_k, QK^T sin escalar colapsa la entropía de softmax. Añade escalado y máscara causal.",
    practiceConstraints: [
      "Editar solo attention.py en el proyecto activo",
      "No llamar directamente a F.scaled_dot_product_attention",
    ],
    practiceDeliverables: [
      "Escalado exacto 1/sqrt(d_k) usando q.size(-1)",
      "Diferencia máxima < 1e-5 frente al caso de prueba",
    ],
    practiceVerificationSteps: [
      "Ejecutar pytest tests/test_attention.py en el archivo actual",
    ],
    practiceHint: "Usa q.size(-1) ** 0.5 y masked_fill(mask == 0, float('-inf')) antes de softmax.",
    practiceReflection: "¿Qué dimensión del tensor acumula la varianza de tamaño d_k?",
    dueConcepts: [
      {
        concept: "Por qué 1/sqrt(d_k) estabiliza gradientes de softmax",
        reason: "Explicar la varianza de QK^T bajo entradas estandarizadas.",
      },
      {
        concept: "Máscara causal antes vs después de softmax",
        reason: "Comparar el enmascarado con -inf frente a anular probabilidades después.",
      },
    ],
    resources: [
      {
        id: "res-lecture-attn",
        title: "scaled-dot-product-attention.md",
        summary: "Nota guardada por Trainer: deducción de QK^T y control de gradiente.",
        collectionPath: "Trainer Library/Apuntes/scaled-dot-product-attention.md",
        kind: "markdown",
      },
      {
        id: "res-paper-attn",
        title: "Attention Is All You Need (arXiv:1706.03762)",
        summary: "Sección 3.2.1 Scaled Dot-Product Attention en PDF anotado.",
        collectionPath: "Trainer Library/Papers/attention-is-all-you-need.pdf",
        kind: "pdf",
      },
      {
        id: "res-code-attn",
        title: "pytorch-attention-lab / attention.py",
        summary: "Archivo del proyecto observado en modo solo lectura para verificación.",
        collectionPath: "Projects/pytorch-attention-lab/attention.py",
        kind: "code",
      },
    ],
    providerName: "MiniMax Directo",
    lastTestDetail: "Conexión, modelo, bypass de proxy y clave en llavero verificados.",
    projectName: "pytorch-attention-lab",
    libraryRoot: "~/TrainerLibrary",
    projectPath: "~/Projects/pytorch-attention-lab",
    browserTabTitle: "Attention Is All You Need (arXiv:1706.03762)",
  },

  "fr-FR": {
    sessionLabel: "Attention par produit scalaire mis à l'échelle",
    userAuthor: "Vous",
    planTitle: "Mécanisme d'attention & flux d'état PyTorch",
    planSummary:
      "Démontrez le facteur 1/sqrt(d_k), codez vous-même le module et vérifiez la stabilité des gradients par les tests.",
    stageTitles: [
      "Analyser la variance de QK^T",
      "Implémenter l'attention 1/sqrt(d_k)",
      "Vérifier le masque causal et les gradients",
    ],
    stageObjectives: [
      "Expliquer pourquoi la variance de QK^T croît linéairement avec d_k.",
      "Écrire scaled_dot_product_attention avec contrôle des dimensions et notes.",
      "Valider la précision numérique face aux références PyTorch.",
    ],
    currentFocus: "Attention mise à l'échelle (1/sqrt(d_k))",
    currentTaskTitle: "Implémenter et vérifier la mise à l'échelle 1/sqrt(d_k)",
    currentStep: "Lancer pytest tests/test_attention.py avec contrôle des gradients.",
    whyNow: "Sans 1/sqrt(d_k), softmax sature vers des pics et les gradients s'effondrent.",
    verifyMethod: "Exécutez pytest tests/test_attention.py sur le fichier courant.",
    nextAfter: "Étendre l'attention simple vers une projection Multi-Head.",
    userQuestion:
      "Explique-moi pourquoi Scaled Dot-Product Attention divise par sqrt(d_k), écris le code PyTorch minimal et sauvegarde une note Markdown.",
    coachReply: [
      "Si `q` et `k` ont moyenne 0 et variance 1, chaque produit scalaire somme `d_k` termes indépendants : sa variance atteint `d_k`.",
      "",
      "Des logits élevés poussent `softmax` dans des zones plates où le gradient disparaît. Diviser par `math.sqrt(d_k)` ramène la variance à 1 :",
      "",
      "```python",
      "scores = (q @ k.transpose(-2, -1)) / math.sqrt(d_k)",
      "weights = torch.softmax(scores, dim=-1)",
      "```",
      "",
      "Note enregistrée dans `Trainer Library / Notes de cours / scaled-dot-product-attention.md`.",
    ].join("\n"),
    coachArtifactTitle: "Implémenter 1/sqrt(d_k) dans attention.py",
    coachArtifactSummary: "Ajoutez le facteur d'échelle puis validez sorties et gradients.",
    coachArtifactBullets: [
      "Lire d_k dynamiquement via q.size(-1)",
      "Exécuter pytest tests/test_attention.py",
    ],
    practiceScenario:
      "Ouvrez pytorch-attention-lab/attention.py et codez attention_forward(q, k, v, mask=None).",
    practiceProblem:
      "Quand d_k augmente, QK^T brut sature softmax. Ajoutez l'échelle et le masque causal.",
    practiceConstraints: [
      "Modifier uniquement attention.py dans le projet actif",
      "Ne pas appeler F.scaled_dot_product_attention directement",
    ],
    practiceDeliverables: [
      "Mise à l'échelle exacte 1/sqrt(d_k) via q.size(-1)",
      "Écart maximal < 1e-5 par rapport au test de référence",
    ],
    practiceVerificationSteps: [
      "Lancer pytest tests/test_attention.py sur le fichier courant",
    ],
    practiceHint: "Utilisez q.size(-1) ** 0.5 et masked_fill(mask == 0, float('-inf')) avant softmax.",
    practiceReflection: "Quelle dimension provoque l'accumulation de variance d_k ?",
    dueConcepts: [
      {
        concept: "Pourquoi 1/sqrt(d_k) stabilise les gradients softmax",
        reason: "Expliquer l'échelle de variance de QK^T sous entrées centrées réduites.",
      },
      {
        concept: "Masque causal avant ou après softmax",
        reason: "Comparer le masquage additif -inf au zéro post-softmax.",
      },
    ],
    resources: [
      {
        id: "res-lecture-attn",
        title: "scaled-dot-product-attention.md",
        summary: "Note enregistrée par Trainer : dérivation QK^T et vérification des gradients.",
        collectionPath: "Trainer Library/Notes de cours/scaled-dot-product-attention.md",
        kind: "markdown",
      },
      {
        id: "res-paper-attn",
        title: "Attention Is All You Need (arXiv:1706.03762)",
        summary: "Extrait PDF annoté de la section 3.2.1 Scaled Dot-Product Attention.",
        collectionPath: "Trainer Library/Papers/attention-is-all-you-need.pdf",
        kind: "pdf",
      },
      {
        id: "res-code-attn",
        title: "pytorch-attention-lab / attention.py",
        summary: "Fichier du projet lu en mode lecture seule pour vérification.",
        collectionPath: "Projects/pytorch-attention-lab/attention.py",
        kind: "code",
      },
    ],
    providerName: "MiniMax Direct",
    lastTestDetail: "Connexion, modèle, contournement proxy et clé trousseau vérifiés.",
    projectName: "pytorch-attention-lab",
    libraryRoot: "~/TrainerLibrary",
    projectPath: "~/Projects/pytorch-attention-lab",
    browserTabTitle: "Attention Is All You Need (arXiv:1706.03762)",
  },

  "ja-JP": {
    sessionLabel: "スケール化内積アテンション",
    userAuthor: "あなた",
    planTitle: "Attention 機構と PyTorch 状態フロー実装",
    planSummary:
      "1/sqrt(d_k) スケーリングを第一原理から導出し、PyTorch モジュールを自力で実装して勾配安定性をテスト検証します。",
    stageTitles: [
      "QK^T の分散膨張を追跡する",
      "1/sqrt(d_k) スケーリングを実装する",
      "因果マスクと勾配ノルムを検証する",
    ],
    stageObjectives: [
      "d_k に比例して QK^T の分散が増大し Softmax が飽和する仕組みを理解する。",
      "attention.py にスケーリングとマスクを書き、解説ノートを保存する。",
      "PyTorch 参照実装と照合して数値誤差・勾配ノルムを単体テストで確認する。",
    ],
    currentFocus: "スケール化内積アテンション",
    currentTaskTitle: "1/sqrt(d_k) スケーリングの実装と検証",
    currentStep: "pytest tests/test_attention.py を実行し、誤差と勾配検証を通過する。",
    whyNow: "1/sqrt(d_k) がないと Softmax が極端な飽和領域に入り、逆伝播勾配が消失します。",
    verifyMethod: "現在のファイルに対して pytest tests/test_attention.py を実行します。",
    nextAfter: "単一ヘッドの実装を Multi-Head Attention へ拡張する。",
    userQuestion:
      "Scaled Dot-Product Attention が sqrt(d_k) で割る理由を状態フローで徹底解説し、最小の PyTorch コードと Markdown 講義ノートを保存してください。",
    coachReply: [
      "`q` と `k` の各要素が平均 0・分散 1 なら、内積は `d_k` 個の積の和になるため分散が `d_k` 倍に膨らみます。",
      "",
      "値が大きいままでは `softmax` が平坦な端に張り付き勾配が消えます。`math.sqrt(d_k)` で割ることで正規化前に分散を 1 へ戻せます：",
      "",
      "```python",
      "scores = (q @ k.transpose(-2, -1)) / math.sqrt(d_k)",
      "weights = torch.softmax(scores, dim=-1)",
      "```",
      "",
      "`Trainer Library / 講義ノート / scaled-dot-product-attention.md` に保存しました。",
    ].join("\n"),
    coachArtifactTitle: "attention.py に 1/sqrt(d_k) を実装する",
    coachArtifactSummary: "スケーリング係数を実装し、出力値と勾配ノルムをテスト検証します。",
    coachArtifactBullets: [
      "q.size(-1) から d_k を動的に取得する",
      "pytest tests/test_attention.py で検証する",
    ],
    practiceScenario:
      "pytorch-attention-lab/attention.py を開き、attention_forward(q, k, v, mask=None) を実装してください。",
    practiceProblem:
      "d_k が大きいほど未スケーリングの QK^T は Softmax エントロピーを潰します。温度スケーリングと因果マスクを追加しましょう。",
    practiceConstraints: [
      "現在のワークスペース内の attention.py のみ編集する",
      "F.scaled_dot_product_attention を直接呼ばない",
    ],
    practiceDeliverables: [
      "q.size(-1) を使った正確な 1/sqrt(d_k) スケーリング",
      "参照フィクスチャとの最大誤差 < 1e-5",
    ],
    practiceVerificationSteps: [
      "現在のファイルで pytest tests/test_attention.py を実行する",
    ],
    practiceHint: "q.size(-1) ** 0.5 を使い、Softmax 前に masked_fill(mask == 0, float('-inf')) を適用します。",
    practiceReflection: "分散が d_k 倍になるのはどの軸の内積和によるものですか？",
    dueConcepts: [
      {
        concept: "1/sqrt(d_k) が Softmax 勾配消失を防ぐ理由",
        reason: "単位分散入力における QK^T の分散スケーリングを説明する。",
      },
      {
        concept: "因果マスクを Softmax 前に適用する理由",
        reason: "-inf 加算マスクと Softmax 後のゼロ化の違いを比較する。",
      },
    ],
    resources: [
      {
        id: "res-lecture-attn",
        title: "scaled-dot-product-attention.md",
        summary: "Trainer が保存した講義ノート：QK^T 分散導出と勾配チェック。",
        collectionPath: "Trainer Library/講義ノート/scaled-dot-product-attention.md",
        kind: "markdown",
      },
      {
        id: "res-paper-attn",
        title: "Attention Is All You Need (arXiv:1706.03762)",
        summary: "3.2.1 節 Scaled Dot-Product Attention の注釈付き PDF 抜粋。",
        collectionPath: "Trainer Library/Papers/attention-is-all-you-need.pdf",
        kind: "pdf",
      },
      {
        id: "res-code-attn",
        title: "pytorch-attention-lab / attention.py",
        summary: "読み取り専用検証のために監視されるワークスペースコード。",
        collectionPath: "Projects/pytorch-attention-lab/attention.py",
        kind: "code",
      },
    ],
    providerName: "MiniMax 直接接続",
    lastTestDetail: "エンドポイント接続・モデル機能・直接プロキシ・キーチェーン API キー検証済み。",
    projectName: "pytorch-attention-lab",
    libraryRoot: "~/TrainerLibrary",
    projectPath: "~/Projects/pytorch-attention-lab",
    browserTabTitle: "Attention Is All You Need (arXiv:1706.03762)",
  },

  "ko-KR": {
    sessionLabel: "스케일드 닷-프로덕트 어텐션",
    userAuthor: "나",
    planTitle: "어텐션 메커니즘과 PyTorch 상태 흐름",
    planSummary:
      "1/sqrt(d_k) 스케일링 원리를 유도하고 모듈을 직접 구현한 뒤 단위 테스트로 기울기 안정성을 검증합니다.",
    stageTitles: [
      "QK^T 분산 증가 추적하기",
      "1/sqrt(d_k) 스케일 어텐션 구현",
      "인과 마스크 및 기울기 노름 검증",
    ],
    stageObjectives: [
      "d_k 가 커질수록 원시 QK^T 분산이 선형 증가하는 이유를 파악합니다.",
      "attention.py 에 스케일링과 마스크를 구현하고 강의 노트를 저장합니다.",
      "PyTorch 기준 출력과 비교해 수치 오차와 기울기 안정성을 검증합니다.",
    ],
    currentFocus: "스케일드 닷-프로덕트 어텐션",
    currentTaskTitle: "1/sqrt(d_k) 어텐션 스케일링 구현 및 테스트",
    currentStep: "pytest tests/test_attention.py 로 순전파 오차와 기울기를 검증하세요.",
    whyNow: "1/sqrt(d_k) 가 없으면 Softmax 가 포화 영역에 갇혀 역전파 기울기가 소실됩니다.",
    verifyMethod: "현재 파일에 대해 pytest tests/test_attention.py 를 실행해 검증합니다.",
    nextAfter: "단일 헤드 어텐션을 Multi-Head 투영 구조로 확장합니다.",
    userQuestion:
      "Scaled Dot-Product Attention 에서 왜 sqrt(d_k) 로 나누는지 상태 흐름으로 설명하고, 최소 PyTorch 코드와 Markdown 강의 노트를 라이브러리에 저장해 주세요.",
    coachReply: [
      "`q` 와 `k` 원소가 평균 0, 분산 1 이면 내적은 `d_k` 개의 항을 더해 분산이 `d_k` 로 커집니다.",
      "",
      "로짓이 커지면 `softmax` 가 평평한 꼬리로 밀려 기울기가 거의 0 이 됩니다. `math.sqrt(d_k)` 로 나누면 정규화 전 분산이 1 로 돌아옵니다:",
      "",
      "```python",
      "scores = (q @ k.transpose(-2, -1)) / math.sqrt(d_k)",
      "weights = torch.softmax(scores, dim=-1)",
      "```",
      "",
      "`Trainer Library / 강의 노트 / scaled-dot-product-attention.md` 에 저장했습니다.",
    ].join("\n"),
    coachArtifactTitle: "attention.py 에 1/sqrt(d_k) 구현하기",
    coachArtifactSummary: "스케일 계수를 추가하고 출력값과 기울기 노름을 검증하세요.",
    coachArtifactBullets: [
      "상수 대신 q.size(-1) 로 d_k 읽기",
      "pytest tests/test_attention.py 실행",
    ],
    practiceScenario:
      "pytorch-attention-lab/attention.py 를 열고 attention_forward(q, k, v, mask=None) 를 완성하세요.",
    practiceProblem:
      "d_k 가 증가하면 스케일 없는 내적이 Softmax 엔트로피를 무너뜨립니다. 온도 스케일링과 인과 마스크를 추가하세요.",
    practiceConstraints: [
      "현재 작업 영역의 attention.py 만 수정하기",
      "F.scaled_dot_product_attention 을 직접 호출하지 않기",
    ],
    practiceDeliverables: [
      "q.size(-1) 기반의 정확한 1/sqrt(d_k) 스케일링",
      "기준 픽스처 대비 최대 오차 < 1e-5 통과",
    ],
    practiceVerificationSteps: [
      "현재 파일에서 pytest tests/test_attention.py 실행",
    ],
    practiceHint: "q.size(-1) ** 0.5 로 나누고 Softmax 전에 masked_fill(mask == 0, float('-inf')) 를 적용하세요.",
    practiceReflection: "분산이 d_k 로 커지는 이유는 어느 차원의 내적 합산 때문인가요?",
    dueConcepts: [
      {
        concept: "1/sqrt(d_k) 가 Softmax 기울기 소실을 막는 이유",
        reason: "단위 분산 입력에서 QK^T 분산 스케일링 증명하기.",
      },
      {
        concept: "인과 마스크를 Softmax 이전에 적용하는 이유",
        reason: "-inf 가산 마스킹과 Softmax 이후 0 치환의 차이 설명하기.",
      },
    ],
    resources: [
      {
        id: "res-lecture-attn",
        title: "scaled-dot-product-attention.md",
        summary: "Trainer 가 저장한 강의 노트: QK^T 분산 유도 및 기울기 검증.",
        collectionPath: "Trainer Library/강의 노트/scaled-dot-product-attention.md",
        kind: "markdown",
      },
      {
        id: "res-paper-attn",
        title: "Attention Is All You Need (arXiv:1706.03762)",
        summary: "3.2.1 절 Scaled Dot-Product Attention 주석 PDF 발췌.",
        collectionPath: "Trainer Library/Papers/attention-is-all-you-need.pdf",
        kind: "pdf",
      },
      {
        id: "res-code-attn",
        title: "pytorch-attention-lab / attention.py",
        summary: "읽기 전용 검증을 위해 연결된 작업 영역 코드 파일.",
        collectionPath: "Projects/pytorch-attention-lab/attention.py",
        kind: "code",
      },
    ],
    providerName: "MiniMax 직접 연결",
    lastTestDetail: "연결, 모델, 프록시 우회 및 키체인 API 키가 검증되었습니다.",
    projectName: "pytorch-attention-lab",
    libraryRoot: "~/TrainerLibrary",
    projectPath: "~/Projects/pytorch-attention-lab",
    browserTabTitle: "Attention Is All You Need (arXiv:1706.03762)",
  },

  "pt-BR": {
    sessionLabel: "Atenção por produto escalar escalado",
    userAuthor: "Você",
    planTitle: "Mecanismo de atenção e fluxo de estado no PyTorch",
    planSummary:
      "Deduza o fator 1/sqrt(d_k) pelos primeiros princípios, implemente o módulo por conta própria e valide os gradientes com testes.",
    stageTitles: [
      "Rastrear a variância de QK^T",
      "Implementar atenção escalada 1/sqrt(d_k)",
      "Verificar máscara causal e normas de gradiente",
    ],
    stageObjectives: [
      "Entender por que a variância de QK^T cresce linearmente com d_k.",
      "Escrever scaled_dot_product_attention com checagem de forma e salvar nota.",
      "Validar estabilidade numérica contra a referência do PyTorch.",
    ],
    currentFocus: "Atenção por produto escalar escalado",
    currentTaskTitle: "Implementar e testar a escala 1/sqrt(d_k)",
    currentStep: "Rodar pytest tests/test_attention.py validando saída e normas de gradiente.",
    whyNow: "Sem 1/sqrt(d_k), a softmax satura nas caudas e os gradientes desaparecem.",
    verifyMethod: "Execute pytest tests/test_attention.py no arquivo atual.",
    nextAfter: "Estender atenção de cabeça única para projeção Multi-Head.",
    userQuestion:
      "Explique passo a passo por que Scaled Dot-Product Attention divide por sqrt(d_k), escreva o código PyTorch mínimo e salve uma nota Markdown na biblioteca.",
    coachReply: [
      "Quando `q` e `k` têm média 0 e variância 1, cada produto escalar soma `d_k` termos independentes, levando a variância a `d_k`.",
      "",
      "Logits altos empurram `softmax` para regiões planas onde o gradiente quase zera. Dividir por `math.sqrt(d_k)` restaura variância 1:",
      "",
      "```python",
      "scores = (q @ k.transpose(-2, -1)) / math.sqrt(d_k)",
      "weights = torch.softmax(scores, dim=-1)",
      "```",
      "",
      "Nota salva em `Trainer Library / Notas de aula / scaled-dot-product-attention.md`.",
    ].join("\n"),
    coachArtifactTitle: "Implementar 1/sqrt(d_k) em attention.py",
    coachArtifactSummary: "Adicione o fator de escala e confira saídas e gradientes.",
    coachArtifactBullets: [
      "Ler d_k via q.size(-1) sem valor fixo",
      "Executar pytest tests/test_attention.py",
    ],
    practiceScenario:
      "Abra pytorch-attention-lab/attention.py e implemente attention_forward(q, k, v, mask=None).",
    practiceProblem:
      "Com d_k maior, QK^T sem escala colapsa a entropia da softmax. Adicione escala e máscara causal.",
    practiceConstraints: [
      "Editar apenas attention.py no projeto ativo",
      "Não chamar F.scaled_dot_product_attention diretamente",
    ],
    practiceDeliverables: [
      "Escala exata 1/sqrt(d_k) usando q.size(-1)",
      "Diferença máxima < 1e-5 frente ao teste de referência",
    ],
    practiceVerificationSteps: [
      "Executar pytest tests/test_attention.py no arquivo atual",
    ],
    practiceHint: "Use q.size(-1) ** 0.5 e masked_fill(mask == 0, float('-inf')) antes da softmax.",
    practiceReflection: "Qual dimensão do tensor acumula a variância d_k?",
    dueConcepts: [
      {
        concept: "Por que 1/sqrt(d_k) estabiliza gradientes da softmax",
        reason: "Explicar o crescimento de variância em QK^T sob entradas padronizadas.",
      },
      {
        concept: "Máscara causal antes vs depois da softmax",
        reason: "Contrastar máscara aditiva -inf com zerar probabilidades depois.",
      },
    ],
    resources: [
      {
        id: "res-lecture-attn",
        title: "scaled-dot-product-attention.md",
        summary: "Nota salva pelo Trainer: dedução de QK^T e verificação de gradiente.",
        collectionPath: "Trainer Library/Notas de aula/scaled-dot-product-attention.md",
        kind: "markdown",
      },
      {
        id: "res-paper-attn",
        title: "Attention Is All You Need (arXiv:1706.03762)",
        summary: "Seção 3.2.1 Scaled Dot-Product Attention em PDF anotado.",
        collectionPath: "Trainer Library/Papers/attention-is-all-you-need.pdf",
        kind: "pdf",
      },
      {
        id: "res-code-attn",
        title: "pytorch-attention-lab / attention.py",
        summary: "Arquivo do projeto monitorado em modo somente leitura para verificação.",
        collectionPath: "Projects/pytorch-attention-lab/attention.py",
        kind: "code",
      },
    ],
    providerName: "MiniMax Direto",
    lastTestDetail: "Conexão, modelo, bypass de proxy e chave no cofre verificados.",
    projectName: "pytorch-attention-lab",
    libraryRoot: "~/TrainerLibrary",
    projectPath: "~/Projects/pytorch-attention-lab",
    browserTabTitle: "Attention Is All You Need (arXiv:1706.03762)",
  },
};

export function buildLocalizedShowcaseBootstrap(baseBootstrap, locale, { shotName = "" } = {}) {
  const c = LOCALE_CONTENT[locale] ?? LOCALE_CONTENT["en-US"];
  const cloned = structuredClone(baseBootstrap);

  cloned.workspaceName = c.projectName;
  cloned.sessionLabel = c.sessionLabel;

  const existingProfileId = cloned.providerConfig?.profileId || "minimax-core";
  const existingWorkspaceId = cloned.memory?.workspace?.workspaceId;
  const checkedAtIso = "2026-11-22T07:58:00.000Z";

  if (cloned.connection?.provider) {
    cloned.connection.provider.name = c.providerName;
    cloned.connection.provider.model = "MiniMax-M2.7";
    cloned.connection.provider.lastTestResult = {
      ...(existingWorkspaceId ? { workspaceId: existingWorkspaceId } : {}),
      profileId: existingProfileId,
      providerProfileId: existingProfileId,
      ok: true,
      status: "ok",
      message: c.lastTestDetail,
      detail: c.lastTestDetail,
      checkedAt: checkedAtIso,
      providerName: c.providerName,
      baseUrl: "https://api.example.com/v1",
      model: "MiniMax-M2.7",
      protocol: "openai_chat_completions_compatible",
      toolsReady: true,
      streamingReady: true,
      thinkingReady: true,
      visionReady: true,
    };
    cloned.connection.provider.capabilities = {
      chat: true,
      responses: true,
      vision: true,
      embeddings: false,
      tools: true,
      jsonSchema: true,
      structuredOutput: true,
      streaming: true,
    };
  }

  cloned.providerConfig = {
    ...(cloned.providerConfig ?? {}),
    configured: true,
    profileId: existingProfileId,
    name: c.providerName,
    baseUrl: "https://api.example.com/v1",
    model: "MiniMax-M2.7",
    apiKeyConfigured: true,
    protocol: "openai_chat_completions_compatible",
    credentialMode: "ui_proxy",
    ignoreSystemProxy: true,
    availableModels: ["MiniMax-M2.7", "MiniMax-M2.7-highspeed", "gpt-5.1-mini"],
    resolvedModel: "MiniMax-M2.7",
    modelListStatus: "ready",
    providerProfiles: [
      {
        id: existingProfileId,
        label: c.providerName,
        protocol: "openai_chat_completions_compatible",
        mode: "direct",
        credentialMode: "ui_proxy",
        baseUrl: "https://api.example.com/v1",
        apiKeyRef: "minimax.default",
        model: "MiniMax-M2.7",
        availableModels: ["MiniMax-M2.7", "MiniMax-M2.7-highspeed", "gpt-5.1-mini"],
      },
    ],
    lastTestResult: {
      ...(existingWorkspaceId ? { workspaceId: existingWorkspaceId } : {}),
      profileId: existingProfileId,
      providerProfileId: existingProfileId,
      ok: true,
      status: "ok",
      message: c.lastTestDetail,
      detail: c.lastTestDetail,
      checkedAt: checkedAtIso,
      providerName: c.providerName,
      baseUrl: "https://api.example.com/v1",
      model: "MiniMax-M2.7",
      protocol: "openai_chat_completions_compatible",
      latencyMs: 312,
      toolsReady: true,
      streamingReady: true,
      thinkingReady: true,
      visionReady: true,
      capabilities: {
        chat: true,
        responses: true,
        vision: true,
        embeddings: false,
        tools: true,
        jsonSchema: true,
        structuredOutput: true,
        streaming: true,
      },
    },
  };

  cloned.plan = {
    ...(cloned.plan ?? {}),
    title: c.planTitle,
    summary: c.planSummary,
    currentStep: c.currentStep,
    whyNow: c.whyNow,
    verifyMethod: [c.verifyMethod],
    nextAfterCurrent: c.nextAfter,
    stages: [
      {
        id: "stage-1",
        title: c.stageTitles[0],
        objective: c.stageObjectives[0],
        status: "done",
      },
      {
        id: "stage-2",
        title: c.stageTitles[1],
        objective: c.stageObjectives[1],
        status: "active",
      },
      {
        id: "stage-3",
        title: c.stageTitles[2],
        objective: c.stageObjectives[2],
        status: "queued",
      },
    ],
  };

  cloned.task = {
    ...(cloned.task ?? {}),
    id: "task-attention-scale",
    title: c.currentTaskTitle,
    description: c.practiceProblem,
    constraints: [...c.practiceConstraints],
    acceptanceCriteria: [...c.practiceDeliverables],
    nextActionLabel: c.currentStep,
  };

  cloned.coachingState = {
    ...(cloned.coachingState ?? {}),
    scenario: "project_adaptation",
    answerMode: "guided",
    learnerSignal: "steady",
    summary: c.planSummary,
    nextStep: c.currentStep,
    encouragement: c.verifyMethod,
  };

  cloned.coachTurn = {
    ...(cloned.coachTurn ?? {}),
    scenario: "project_adaptation",
    learnerSignal: "steady",
    summary: c.planSummary,
    nextStep: c.currentStep,
    encouragement: c.verifyMethod,
    activeStage: c.stageTitles[1],
    activeTask: c.currentTaskTitle,
    dueReviewCount: c.dueConcepts.length,
    teachingGoal: c.whyNow,
    reviewQueueSummary: c.verifyMethod,
  };

  cloned.coachFocus = {
    ...(cloned.coachFocus ?? {}),
    currentFocus: c.currentFocus,
    reviewRhythm: c.verifyMethod,
    nextStep: c.currentStep,
    activeStage: c.stageTitles[1],
    activeTask: c.currentTaskTitle,
    strategyPreferenceSummary: c.planSummary,
    continuitySummary: c.nextAfter,
    recentTeachingSignals: [c.verifyMethod],
    teachingObservations: [c.whyNow],
    recentWins: [c.stageTitles[0]],
    language: locale,
  };

  cloned.planRuntimeStatus = {
    ...(cloned.planRuntimeStatus ?? {}),
    currentStage: {
      ...(cloned.planRuntimeStatus?.currentStage ?? {}),
      title: c.stageTitles[1],
      goal: c.stageObjectives[1],
    },
    currentMainThread: {
      ...(cloned.planRuntimeStatus?.currentMainThread ?? {}),
      focusArea: c.currentFocus,
      summary: c.planSummary,
      nextStep: c.currentStep,
      currentStep: c.currentStep,
      whyNow: c.whyNow,
      nextAfterCurrent: c.nextAfter,
      verifyMethod: [c.verifyMethod],
    },
    coachJudgment: {
      ...(cloned.planRuntimeStatus?.coachJudgment ?? {}),
      summary: c.planSummary,
      teachingGoal: c.whyNow,
      supportStrategy: c.verifyMethod,
      resumeThread: c.currentStep,
    },
    reviewQueueSummary: c.verifyMethod,
    nextTrainingAction: c.currentStep,
    currentStep: c.currentStep,
    whyNow: c.whyNow,
    nextAfterCurrent: c.nextAfter,
    verifyMethod: [c.verifyMethod],
  };

  cloned.memory = {
    ...(cloned.memory ?? {}),
    currentFocus: c.currentFocus,
    reviewSummary: c.verifyMethod,
    reviewRhythm: c.verifyMethod,
    activeThread: {
      ...(cloned.memory?.activeThread ?? {}),
      focusArea: c.currentFocus,
      summary: c.planSummary,
      nextStep: c.currentStep,
      blocker: "",
      verifiedResult: c.verifyMethod,
    },
    memoryEvidence: [c.planSummary, c.verifyMethod],
    workspace: {
      ...(cloned.memory?.workspace ?? {}),
      workspaceName: c.projectName,
      workspacePath: c.projectPath,
      windowTrusted: true,
      responseLanguage: locale,
      resourceSandbox: {
        ...(cloned.memory?.workspace?.resourceSandbox ?? {}),
        configuredPath: `${c.libraryRoot}/.trainer/runtime`,
        effectivePath: `${c.libraryRoot}/.trainer/runtime`,
        defaultPath: `${c.libraryRoot}/.trainer/runtime`,
        source: "recommended",
        status: "ready",
      },
      trainerWorkspace: {
        status: "managed",
        rootPath: c.libraryRoot,
        projectId: "trainer-demo",
        projectName: c.projectName,
        projectPath: c.projectPath,
        updatedAt: "2026-11-22T07:50:00.000Z",
      },
      trainerProjects: {
        rootPath: c.libraryRoot,
        projects: [
          {
            projectId: "trainer-demo",
            projectName: c.projectName,
            projectPath: c.projectPath,
            adoptionMode: "managed",
            isCurrent: true,
          },
        ],
      },
    },
  };

  const practiceCard = {
    cardId: "card-attention-scale",
    type: "practice",
    title: c.currentTaskTitle,
    whyNow: c.whyNow,
    status: "active",
    learningFamily: "coding",
    learningSubtype: "implementation",
    expectedSymbols: ["attention_forward", "math.sqrt"],
    apiHints: ["q.size(-1)", "q.transpose(-2, -1)", "torch.softmax(..., dim=-1)"],
    suggestedWorkspaceAction: c.practiceScenario,
    scenario: c.practiceScenario,
    constraints: [...c.practiceConstraints],
    problemStatement: c.practiceProblem,
    validationMethod: c.verifyMethod,
    successSignal: c.practiceDeliverables[1],
    selfCheck: [...c.practiceDeliverables],
    filesToTouch: ["attention.py", "tests/test_attention.py"],
    hintLadder: [c.practiceHint],
    commonMistakes: [c.whyNow],
    stuckRecovery: c.practiceHint,
    reflectionPrompt: c.practiceReflection,
    learnerDeliverables: [...c.practiceDeliverables],
    verificationSteps: [...c.practiceVerificationSteps],
  };

  cloned.workspaceTrainingState = {
    ...(cloned.workspaceTrainingState ?? {}),
    capabilitySummary: {
      updatedAt: "2026-11-22T07:55:00.000Z",
      capabilities: {
        comprehension: { state: "repeat_verified", verifiedCount: 9 },
        implementation: { state: "independent", verifiedCount: 5 },
        debugging: { state: "independent", verifiedCount: 4 },
        transfer: { state: "assisted", verifiedCount: 2 },
      },
    },
    latestTrainingHandoff: {
      candidateId: "candidate-attention-1",
      continueIn: "training",
      cardType: "practice",
      cardTitle: c.currentTaskTitle,
      learnerDeliverables: [...c.practiceDeliverables],
      verificationSteps: [...c.practiceVerificationSteps],
      returnWith: c.verifyMethod,
      nextAfterCompletion: c.nextAfter,
    },
    latestTrainingSubmode: "practice",
    latestLearningFocusArea: c.currentFocus,
    selectedCardId: "card-attention-scale",
    selectedCardType: "practice",
    selectedCardTitle: c.currentTaskTitle,
    selectedCardStatus: "active",
    trainingCardCandidates: [practiceCard],
    activeTrainingCardRouting: {
      selectedCardId: "card-attention-scale",
      selectedCard: practiceCard,
      whyThisCard: c.whyNow,
      candidateCount: 2,
      eligibleCount: 1,
    },
    dueReviews: c.dueConcepts.map((item) => ({
      concept: item.concept,
      reason: item.reason,
      source: "plan",
      severity: "high",
    })),
  };

  cloned.learningSession = {
    ...(cloned.learningSession ?? {}),
    activeCard: practiceCard,
    currentFocus: c.currentFocus,
    dueReviewCount: c.dueConcepts.length,
  };

  cloned.resources = c.resources.map((res) => ({
    id: res.id,
    title: res.title,
    kind: res.kind,
    status: "ready",
    summary: res.summary,
    source: `${c.libraryRoot}/${res.collectionPath}`,
    collectionPath: res.collectionPath,
    collectionRoot: c.libraryRoot,
    sandboxPath: `${c.libraryRoot}/.trainer/runtime/${res.id}`,
    previewTier: "rich",
    previewKind: res.kind === "code" ? "code" : "markdown",
    trustScore: 0.95,
    freshness: "fresh",
    indexState: "indexed",
  }));

  if (shotName === "chat-first-run") {
    cloned.conversation = [];
    cloned.plan = undefined;
    cloned.task = undefined;
    cloned.planRuntimeStatus = undefined;
    cloned.coachingState = undefined;
    cloned.coachTurn = undefined;
    cloned.coachFocus = undefined;
    cloned.workspaceTrainingState = undefined;
    cloned.learningSession = undefined;
    cloned.memory.currentFocus = "";
    cloned.memory.activeThread = undefined;
  } else {
    cloned.conversation = [
      {
        id: "teach-u1",
        role: "user",
        author: c.userAuthor,
        body: c.userQuestion,
        timestamp: "15:18",
      },
      {
        id: "teach-a1",
        role: "assistant",
        author: "Trainer",
        body: c.coachReply,
        timestamp: "15:19",
        artifacts: [
          {
            kind: "next_step",
            title: c.coachArtifactTitle,
            summary: c.coachArtifactSummary,
            bullets: [...c.coachArtifactBullets],
            focusArea: c.currentFocus,
            rationale: c.whyNow,
            verification: [...c.practiceVerificationSteps],
            recommendedAction: "task",
          },
        ],
      },
    ];
  }

  return cloned;
}

export function browserExtensionTabForLocale(locale) {
  const c = LOCALE_CONTENT[locale] ?? LOCALE_CONTENT["en-US"];
  return {
    title: c.browserTabTitle,
    url: "https://arxiv.org/pdf/1706.03762.pdf",
  };
}
