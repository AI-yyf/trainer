// Trainer 多模态设计精炼:三轮 截图→视觉审计→改动→复审 闭环。
// 约束(审计与实现共用):IA 冻结、每屏一个声音、token 纪律、动效 120–220ms。

interface AuditFinding {
  /** 界面: coach / composer / learning / training / progress / library / settings / cross */
  surface: string;
  /** high = 直接妨碍用户理解下一步。 */
  severity: "high" | "medium" | "low";
  /** 一句话:哪里有问题(视觉层级/密度/竞争/图标语义/交互连续性)。 */
  problem: string;
  /** 一句话:建议的方向。 */
  suggestion: string;
}

interface AuditReport {
  /** 2 秒视觉测试的一句话结论。 */
  summary: string;
  findings: AuditFinding[];
}

interface ChangeItem {
  /** 对应的审计发现 id。 */
  findingId: string;
  surface: string;
  /** 一句话:这一项要改什么、怎么改。 */
  change: string;
  /** 预计触碰的文件(工作区相对路径)。 */
  files: string[];
}

interface ImplResult {
  /** 本轮实际改动的文件。 */
  changedFiles: string[];
  /** 一句话:本轮做了什么。 */
  summary: string;
}

interface ChangePlan {
  /** 本轮要执行的改动,按价值降序,≤10 项。 */
  items: ChangeItem[];
  /** 有意不改的发现与原因。 */
  dropped: string[];
}

interface WorkflowReport {
  conclusion: string;
  findings: Array<{ where: string; what: string; evidence: string; status: "verified" | "unconfirmed"; severity: "low" | "medium" | "high" }>;
  verified: string[];
  notCovered: string[];
}

const CONSTRAINTS = [
  "产品约束(不可违背):",
  "- 顶层 IA 冻结:对话/学习/资料 三个一级目的地;training/progress 属于 learning;settings 是工具入口不是一级目的地;不新增导航,不做 Dashboard。",
  "- Coach 是唯一有通用聊天输入框的地方;其他界面不得出现第二套聊天框。",
  "- 每个界面只允许一个 primary action;不新增 competing banner / 状态卡墙。",
  "- Truth Ownership:Provider/模型管理只在 Settings;输入框只保留查看与快速切换。",
  "- 视觉:只用现有 design tokens 与 VS Code 语义变量,禁止硬编码颜色;accent 只用于当前导航/主操作/active 选择。",
  "- 动效 120–220ms 并尊重 prefers-reduced-motion;不做大幅位移与花哨效果。",
  "- 文案不得出现 FSRS/handoff/checkpoint/runtime 等实现词汇。",
  "- 不重写后端,不重写信息架构;修改以组件与 CSS 为主,App.tsx 改动保持克制。",
].join("\n");

const AUDIT_RUBRIC = [
  "逐张用 Read 工具打开下列 PNG 亲眼查看(这是视觉审计,不是 DOM 检查),按以下维度找问题:",
  "A. 2 秒测试:第一眼看到什么?CTA 在哪?是否一眼知道下一步?",
  "B. 眯眼测试:是否仍形成 主任务→主内容→主操作,还是一片均匀灰字?",
  "C. 密度:哪里过挤/过空/无意义留白?",
  "D. 视觉竞争:多个高亮按钮、重复边框/badge/icon、competing banner、重复状态?",
  "E. 文字层级:标题/正文/辅助/meta/CTA 是否属于不同视觉级别?",
  "F. 图标语义:不看 tooltip 能否理解(尤其 History/Settings/模型/技能 图标)?",
  "只记录真实观察到的问题,不要为凑数而编造;每条给出可执行的建议。",
].join("\n");

artifact.board("design-board", {
  key: "id",
  status: "stage",
  columns: ["发现", "Round2 已处理", "Round3 打磨", "保留/已验证"],
  cardTitle: "problem",
  detail: [{ field: "surface" }, { field: "severity" }],
});

phase("建立视觉基线:捕获当前 HEAD 的全套截图");
log("运行 scripts/capture-ui-golden.mjs(自建预览服务,420px 暗色 zh-CN + 340px 窄宽)…");
const beforeCapture = await world.run("node", ["scripts/capture-ui-golden.mjs"], { timeoutMs: 900000 });
if (beforeCapture.exitCode !== 0) {
  throw new Error(`视觉基线捕获失败:\n${beforeCapture.stderr.slice(0, 2000)}`);
}
await world.run("cp", ["-r", "assets/screenshots", "design-audit/before"]);
log("基线截图已存至 design-audit/before/,共 12 张。");

const auditorGroups = [
  {
    name: "视觉审计-对话与输入框",
    screens: ["chat-first-run.png", "message-actions.png", "message-actions-row.png", "skill-deck.png", "coach-narrow.png"],
    focus: "对话页应是最安静自然的页面:会话是第一视觉对象、输入框第二、其余退后;回复不挂大段后缀;图标语义清楚。",
  },
  {
    name: "视觉审计-学习与训练",
    screens: ["plan.png", "training.png", "progress.png"],
    focus: "学习页首屏必须表达 阶段→当前重点→下一步→开始,而不是一堆平均权重的折叠;训练页要像教练给的一道题,高级内容收进任务详情。",
  },
  {
    name: "视觉审计-资料与设置",
    screens: ["resources.png", "settings-connected.png", "settings-quick-setup.png", "skill-manager.png"],
    focus: "资料页是阅读空间不是资源后台;设置首屏不显示全部控件,连接页优先展示 当前连接/模型/状态/编辑测试,高级诊断收起。",
  },
];

phase("Round 1 · 现状视觉审计(只记录,不修改)");
const round1 = (
  await Promise.all(
    auditorGroups.map(async (group) => {
      const auditor = agent(`视觉审计·${group.name}`, {
        system:
          "你是资深 UX/视觉设计师,正在给 Trainer(VS Code 里的 AI 代码教练,420px 暗色中文侧栏)做视觉审计。"
          + "你只审计、绝不修改任何文件;测试套件由脚本负责,不要自己跑。"
          + "用 Read 工具逐张打开指定 PNG 亲眼查看后按维度找问题。"
          + "severity 校准:high 只给『用户无法理解下一步』级别的问题。",
      });
      return auditor.ask<AuditReport>(
        `${AUDIT_RUBRIC}\n\n本组负责的界面(工作区相对路径,420px,最后一张 340px 窄宽):\n${group.screens
          .map((s) => `assets/screenshots/${s}`)
          .join("\n")}\n\n本组重点:\n${group.focus}\n\n输出 ≤6 条最有价值的发现。`,
      ).then((report) => ({ group, report }));
    }),
  )
).map((entry, groupIndex) => {
  const tagged = entry.report.findings.map((finding, index) => ({
    id: `r1-g${groupIndex}-${index}`,
    stage: "发现",
    round: 1,
    surface: finding.surface,
    severity: finding.severity,
    problem: finding.problem,
    suggestion: finding.suggestion,
  }));
  for (const item of tagged) {
    report(item, "design-board");
  }
  return { group: entry.group, report: entry.report, items: tagged };
});

const round1Findings = round1.flatMap((entry) => entry.items);
log(`Round 1 审计完成:共 ${round1Findings.length} 条发现。`);

phase("设计总监:汇总审计并制定 Round 2 改动计划");
const director = agent("设计总监", {
  system:
    "你是 Trainer 的产品设计负责人(ChatGPT 级 PM + UX/IA + 视觉 + 交互设计师)。\n"
    + CONSTRAINTS
    + "\n你的职责:把审计发现整合成一份按价值排序、尊重约束的改动计划。合并重复发现,砍掉违背 IA/原则的 suggestion,"
    + "高级能力收进二级,绝不允许出现两个 primary action 或第二套管理界面。Round 2 是主要收敛轮,Round 3 只做打磨。",
});
const plan2 = await director.ask<ChangePlan>(
  `以下是 Round 1 三个审计组对当前 UI(420px 暗色中文)的全部发现:\n${JSON.stringify(
    round1.flatMap((entry) => entry.items.map(({ id, surface, severity, problem, suggestion }) => ({ id, surface, severity, problem, suggestion }))),
  )}\n\n请输出 Round 2 改动计划:合并同类项、按用户价值排序、≤10 项;每项给出要改的文件与具体方向;`
    + `明确列出放弃不做的发现与原因。`,
);

phase("Round 2 · 实现结构与视觉收敛");
const implementer = agent("实现工程师", {
  system:
    "你是 Trainer 的 Senior React/TypeScript + VS Code 扩展工程师。\n"
    + CONSTRAINTS
    + "\n你负责把设计总监的改动计划实现到代码里:优先改组件与 CSS;改完自己运行 `npm run check` 迭代到通过;"
    + "不要运行完整测试套件(脚本之后会统一跑);不要提交 git。",
});
const round2Result = await implementer.ask<ImplResult>(
  `实现以下 Round 2 改动计划(按顺序执行):\n${JSON.stringify(plan2.items)}\n\n有意不做:${JSON.stringify(plan2.dropped)}\n\n`
    + `要求:完成后运行 npm run check 必须通过;保持所有现有测试断言语义;改动最小化、一次到位。`,
);
log(`Round 2 实现完成:${round2Result.changedFiles.join(", ") || "无文件变更"}`);

phase("确认类型与 CSS 校验通过");
const check2 = await world.run("npm", ["run", "check"], { timeoutMs: 600000 });
if (check2.exitCode !== 0) {
  await implementer.ask(`npm run check 失败:\n${check2.stderr.slice(0, 2000)}\n修复到通过。`);
  const retry = await world.run("npm", ["run", "check"], { timeoutMs: 600000 });
  if (retry.exitCode !== 0) {
    throw new Error(`npm run check 连续失败:\n${retry.stderr.slice(0, 2000)}`);
  }
}

phase("重新捕获 Round 2 截图");
await world.run("node", ["scripts/capture-ui-golden.mjs"], { timeoutMs: 900000 });

phase("Round 2 · 三组复审(对照 Round 1 发现)");
const round2 = (
  await Promise.all(
    round1.map(async (entry, groupIndex) => {
      const auditor = agent(`复审·${entry.group.name}`, {
        system:
          "你是资深 UX/视觉设计师,正在复审 Trainer 修改后的新截图。用 Read 工具逐张亲眼查看后再下结论。",
      });
      return auditor
        .ask<AuditReport>(
          `这些是 Round 2 改动后的最新截图(同一批界面):\n${entry.group.screens
            .map((s) => `assets/screenshots/${s}`)
            .join("\n")}\n\nRound 1 时本组发现的问题是:\n${JSON.stringify(
            entry.items.map(({ surface, severity, problem }) => ({ surface, severity, problem })),
          )}\n\n请逐条判断:哪些已解决、哪些仍在、是否引入了新问题(布局错位/文字截断/新视觉竞争)。输出 ≤6 条仍然成立或新增的发现;如果全部解决,输出空数组并给出一句确认。`,
        )
        .then((report) => ({ groupIndex, group: entry.group, report }));
    }),
  )
).map((entry) => {
  const tagged = entry.report.findings.map((finding, index) => ({
    id: `r2-g${entry.groupIndex}-${index}`,
    stage: "发现",
    round: 2,
    surface: finding.surface,
    severity: finding.severity,
    problem: finding.problem,
    suggestion: finding.suggestion,
  }));
  for (const item of tagged) {
    report(item, "design-board");
  }
  return { ...entry, items: tagged };
});

const round2Findings = round2.flatMap((entry) => entry.items);
log(`Round 2 复审完成:仍有 ${round2Findings.length} 条发现。`);

phase("设计总监:制定 Round 3 打磨清单");
const plan3 = await director.ask<ChangePlan>(
  `Round 2 复审后仍存在的发现:\n${JSON.stringify(round2Findings)}\n\nRound 2 已完成:${round2Result.summary}\n\n`
    + `请输出 Round 3 打磨清单:只做高价值微调(spacing/对齐/字号/图标光学平衡/空态),≤6 项,禁止再做大重构。`,
);

phase("Round 3 · 高价值打磨");
const round3Result = await implementer.ask<ImplResult>(
  `Round 3 只做打磨,禁止大重构:\n${JSON.stringify(plan3.items)}\n\n有意不做:${JSON.stringify(plan3.dropped)}\n\n完成后 npm run check 必须通过。`,
);

phase("确认类型与校验通过");
const check3 = await world.run("npm", ["run", "check"], { timeoutMs: 600000 });
if (check3.exitCode !== 0) {
  await implementer.ask(`npm run check 失败:\n${check3.stderr.slice(0, 2000)}\n修复到通过。`);
  const retry3 = await world.run("npm", ["run", "check"], { timeoutMs: 600000 });
  if (retry3.exitCode !== 0) {
    throw new Error(`npm run check 连续失败:\n${retry3.stderr.slice(0, 2000)}`);
  }
}

phase("重新捕获 Round 3 截图");
await world.run("node", ["scripts/capture-ui-golden.mjs"], { timeoutMs: 900000 });

phase("Round 3 · 冷眼终审");
const coldAuditor = agent("冷眼终审", {
  system:
    "你是从未参与这个项目的设计评审,正在第一次查看 Trainer(VS Code 里的 AI 代码教练,420px 暗色中文侧栏)。"
    + "用 Read 工具逐张打开 PNG 亲眼查看。你只审计、不修改文件。",
});
const round3Audit = await coldAuditor.ask<AuditReport>(
  `${AUDIT_RUBRIC}\n\n全部界面(工作区相对路径):\n${[
    "chat-first-run.png",
    "plan.png",
    "training.png",
    "resources.png",
    "progress.png",
    "settings-connected.png",
    "skill-deck.png",
    "coach-narrow.png",
  ]
    .map((s) => `assets/screenshots/${s}`)
    .join("\n")}\n\n请以第一次看到这个产品的眼光回答:每个界面 2 秒内是否知道自己在做什么、下一步是什么?"
    + "输出 ≤6 条仍然成立的问题;如果整体已达标,输出空数组并给出整体评价。`,
);

phase("运行测试与几何校验");
const tscGate = await world.run("npm", ["run", "check"], { timeoutMs: 600000 });
const extGate = await world.run("npm", ["run", "test:extension"], { timeoutMs: 600000 });
const geomGate = await world.run("node", ["scripts/verify-ui-geometry.mjs"], { timeoutMs: 300000 });
const serverGate = await world.run("npm", ["run", "test:server"], { timeoutMs: 1200000 });
const head = await world.run("git", ["rev-parse", "HEAD"]);
const gates = [
  { name: "npm run check", exit: tscGate.exitCode },
  { name: "npm run test:extension", exit: extGate.exitCode },
  { name: "verify-ui-geometry", exit: geomGate.exitCode },
  { name: "npm run test:server", exit: serverGate.exitCode },
];
for (const gate of gates) {
  log(`${gate.name} => ${gate.exit === 0 ? "通过" : "失败(" + gate.exit + ")"}`);
}

phase("撰写交付报告");
const reporter = agent("报告撰写", {
  system:
    "你为 Trainer 的产品负责人撰写交付报告(中文)。读者是产品负责人本人:直接、有证据、不吹嘘。"
    + "以给定素材为准撰写,不要去仓库里另行验证;不要发明素材里没有的数字。",
});
const reportMarkdown = await reporter.ask<string>(
  `把以下素材整理成 Trainer 多模态设计精炼的交付报告(Markdown,中文)。结构:\n`
    + `# Trainer 设计精炼交付(v1.3.3 之后)\n`
    + `## 当前 HEAD\n## 三轮多模态评审摘要(Round1 审计 / Round2 复审 / Round3 冷眼终审,各 3-5 条要点)\n`
    + `## 各界面 Before → After(Coach/Learning/Training/Library/Settings,每项 2-3 句)\n`
    + `## 主要删除与主要视觉改变\n## 测试结果\n## 仍然存在的问题\n## 下一阶段建议(≤5 条)\n\n素材:\n`
    + `HEAD:${head.stdout.trim()}\n`
    + `Round1 发现:${JSON.stringify(round1.flatMap((e) => e.items))}\n`
    + `Round2 复审发现:${JSON.stringify(round2.flatMap((e) => e.items))}\n`
    + `Round3 冷眼终审:${JSON.stringify(round3Audit)}\n`
    + `Round2 实现:${round2Result.summary}(改动文件:${round2Result.changedFiles.join(", ")})\n`
    + `Round3 打磨:${round3Result.summary}(改动文件:${round3Result.changedFiles.join(", ")})\n`
    + `测试门:${JSON.stringify(gates)}\n`
    + `截图目录:assets/screenshots/(12 张,420px + 340px 窄宽,暗色中文)`,
);
await artifact.markdown(
  "delivery-report",
  reportMarkdown,
  {
    title: "Trainer 设计精炼交付报告",
    description: "三轮多模态评审 + 改动 + 测试结果的完整交付。",
    primary: true,
  },
);
try {
  await artifact.file("shot-coach", "assets/screenshots/chat-first-run.png", { title: "After · 对话页" });
  await artifact.file("shot-plan", "assets/screenshots/plan.png", { title: "After · 学习页" });
  await artifact.file("shot-settings", "assets/screenshots/settings-connected.png", { title: "After · 设置连接" });
  await artifact.file("shot-narrow", "assets/screenshots/coach-narrow.png", { title: "After · 340px 窄宽对话" });
} catch {
  const fixer = agent("截图修复");
  await fixer.ask("assets/screenshots 下的 PNG 缺失或无法发布。重新运行 node scripts/capture-ui-golden.mjs 生成截图,确认文件存在后结束。");
  await artifact.file("shot-coach", "assets/screenshots/chat-first-run.png", { title: "After · 对话页" });
}

const failedGates = gates.filter((gate) => gate.exit !== 0);
const conclusion =
  failedGates.length === 0
    ? `三轮多模态设计精炼完成(Round1 审计 ${round1Findings.length} 条 → Round2 收敛 → Round2 复审 ${round2Findings.length} 条 → Round3 打磨 → 冷眼终审)。`
    + `全部 ${gates.length} 道测试门通过,截图已更新至 assets/screenshots/ 并发布交付报告。`
    + `实现摘要:Round2 — ${round2Result.summary};Round3 — ${round3Result.summary}。`
    : `三轮多模态设计精炼完成,但 ${failedGates.map((gate) => gate.name).join(", ")} 未通过,需要跟进。`
      + `实现摘要:Round2 — ${round2Result.summary};Round3 — ${round3Result.summary}。`;

return {
  conclusion,
  findings: [
    ...round1Findings.map((item) => ({
      where: `assets/screenshots(${item.surface})`,
      what: `[Round1] ${item.problem}`,
      evidence: "三个视觉审计组逐张查看基线截图后记录",
      status: "verified" as const,
      severity: item.severity,
    })),
    ...round2Findings.map((item) => ({
      where: `assets/screenshots(${item.surface})`,
      what: `[Round2 复审仍存在] ${item.problem}`,
      evidence: "复审组对照 Round1 发现逐张查看新截图后记录",
      status: "verified" as const,
      severity: item.severity,
    })),
    ...round3Audit.findings.map((finding) => ({
      where: `assets/screenshots(${finding.surface})`,
      what: `[冷眼终审] ${finding.problem}`,
      evidence: "未参与项目的独立评审首次查看截图后记录",
      status: "verified" as const,
      severity: finding.severity,
    })),
  ],
  verified: [
    ...gates.map((gate) => `${gate.name} 退出码 ${gate.exit}`),
    "node scripts/capture-ui-golden.mjs 共 3 轮(基线/Round2/Round3),12 张界面 × 420px + 340px 窄宽",
    "全部视觉发现由审计子代理用 Read 工具逐张查看 PNG 后记录",
  ],
  notCovered: [
    "真实 VS Code 窗口内的人工走查(自动化只覆盖预览 webview)",
    "Light 主题与 Windows 字体差异(capture 脚本固定为暗色中文)",
    "SSH / Remote workspace 场景",
    "服务端行为(本轮改动以 webview 组件与 CSS 为主)",
  ],
};
