#!/usr/bin/env node
// §十 Layer 2 manual acceptance checklist generator.
//
// The nightly Remote-SSH workflow cannot robotically assert a human sitting
// in a real Remote-SSH VS Code Server window, so every nightly run produces
// this bilingual (zh-CN + en-US) checklist artifact instead: the exact
// click-path, the expected outcome of each step, and a blank pass/fail
// column to fill in as evidence.
//
// Usage: node scripts/generate-remote-ssh-l2-checklist.mjs [--out <path>] [--run-url <url>]
import fs from "node:fs";
import path from "node:path";

function parseArguments(argv) {
  const options = { out: "remote-ssh-l2-manual-checklist.md", runUrl: "" };
  for (let index = 2; index < argv.length; index += 1) {
    const flag = argv[index];
    if (flag === "--out") {
      index += 1;
      options.out = argv[index] ?? options.out;
    } else if (flag === "--run-url") {
      index += 1;
      options.runUrl = String(argv[index] ?? "").trim();
    } else {
      throw new Error(`Unknown flag: ${flag}`);
    }
  }
  return options;
}

// Steps are the §十 Layer 2 journey: install → sidebar → five views → one
// coaching turn → workspace attach → companion capability. Both locales
// share row order so the tables stay comparable side by side.
const STEPS = [
  {
    id: 1,
    zh: "在 Remote-SSH 窗口安装 Trainer VSIX（Extensions → … → Install from VSIX…）",
    zhExpect: "扩展安装成功，无报错；窗口按提示重新加载。",
    en: "Install the Trainer VSIX in the Remote-SSH window (Extensions → … → Install from VSIX…)",
    enExpect: "The extension installs without errors; the window reloads as prompted.",
  },
  {
    id: 2,
    zh: "点击活动栏中的 Trainer 图标，打开 Trainer 侧边栏",
    zhExpect: "侧边栏打开并进入 Coach（对话）视图，没有白屏或报错。",
    en: "Click the Trainer icon in the activity bar to open the Trainer sidebar",
    enExpect: "The sidebar opens on the Coach view with no blank screen or error.",
  },
  {
    id: 3,
    zh: "依次切换五个视图：对话 Coach / 学习 Plan / 资料 Resources / 训练 Training / 设置 Settings",
    zhExpect: "五个视图都能打开并渲染各自内容，切换时无崩溃。",
    en: "Switch through all five views: Coach / Plan / Resources / Training / Settings",
    enExpect: "All five views open and render their content; no crashes while switching.",
  },
  {
    id: 4,
    zh: "在 Coach 视图发送一条关于远程项目的消息，跑一轮教练对话",
    zhExpect: "回复流式完成（出现完整回复，无 provider/stream 错误提示）。",
    en: "Send one message about the remote project in Coach to run a full coaching turn",
    enExpect: "The reply streams to completion (full reply, no provider/stream error).",
  },
  {
    id: 5,
    zh: "在设置中附加（attach）远程工作区并确认信任状态",
    zhExpect: "工作区显示为已附加且受信任；路径与远程主机一致。",
    en: "Attach the remote workspace in Settings and confirm its trust state",
    enExpect: "The workspace shows as attached and trusted; the path matches the remote host.",
  },
  {
    id: 6,
    zh: "验证 Companion capability 握手（设置 → 工作区 → 安装远程支持 / 能力状态）",
    zhExpect: "远端 Companion 已安装且能力握手显示已验证（文件/搜索/哈希/验证可用）。",
    en: "Verify the Companion capability handshake (Settings → Workspace → Install Remote Support / capability status)",
    enExpect: "The remote Companion is installed and the capability handshake reads verified (file/search/hash/verify available).",
  },
];

function renderStepTable(language) {
  const head =
    language === "zh"
      ? ["#", "步骤", "预期结果", "通过/失败"]
      : ["#", "Step", "Expected outcome", "Pass/Fail"];
  const rows = STEPS.map((step) => {
    const name = language === "zh" ? step.zh : step.en;
    const expect = language === "zh" ? step.zhExpect : step.enExpect;
    return `| ${step.id} | ${name} | ${expect} |　|`;
  });
  return [
    `| ${head.join(" | ")} |`,
    `| ${head.map(() => "---").join(" | ")} |`,
    ...rows,
  ].join("\n");
}

function renderChecklist(options) {
  const generatedAt = new Date().toISOString();
  const runLine = options.runUrl
    ? `- Nightly run: ${options.runUrl}`
    : "- Nightly run: (fill in the run URL)";
  return `# Remote-SSH L2 手动验收清单 / Layer 2 Manual Acceptance Checklist

> §十 Layer 2：真实的人在一个 Remote-SSH VS Code Server 窗口里完成 Trainer 侧边栏旅程。
> 这一步无法在 CI 中机器人化断言，因此每晚的 Remote-SSH 工作流会随构件产出本清单，
> 由人工执行并把结果作为证据回填。

> §十 Layer 2: a real human completes the Trainer sidebar journey inside a
> Remote-SSH VS Code Server window. CI cannot assert this robotically, so the
> nightly Remote-SSH workflow ships this checklist as a run artifact for a
> human to execute and paste back as evidence.

- 生成时间 / Generated at: ${generatedAt}
${runLine}
- VSIX 构件 / VSIX artifact: \`trainer-remote-ssh-l2-vsix\`（下载 \`extension/*.vsix\`）
- 本清单构件 / Checklist artifact: \`trainer-remote-ssh-l2-manual-checklist\`

## 前置条件 / Prerequisites

- 一台可通过 Remote-SSH 连接的主机（ssh 可达，远端有 python3 与 git）。
  / A host reachable over Remote-SSH (ssh works; the remote has python3 and git).
- 从本次 nightly run 下载 VSIX 构件。 / Download the VSIX artifact from this nightly run.
- 远端已准备好一个测试工作区（例如 \`/tmp/trainer-e2e\`）。
  / A test workspace exists on the remote (for example \`/tmp/trainer-e2e\`).

## 步骤（zh-CN）

${renderStepTable("zh")}

## Steps (en-US)

${renderStepTable("en")}

## 结果回填 / Evidence to paste back

- 通过：把填好的清单（或截图）贴回 issue / PR / 记录。截图需覆盖步骤 2–6。
  / On pass: paste the filled checklist (or screenshots covering steps 2-6) back into the issue / PR / log.
- 失败：保留失败的视图截图与 VS Code 的输出面板（Trainer 通道）日志，一并贴回。
  / On fail: keep screenshots of the failing view plus the VS Code output panel (Trainer channel) log and paste both back.
- 任何一步失败即整份清单记为失败，并在下次 nightly 复测。
  / Any failed step fails the whole checklist; re-run against the next nightly.
`;
}

function main() {
  const options = parseArguments(process.argv);
  const content = renderChecklist(options);
  const outPath = path.resolve(options.out);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, content, "utf8");
  console.log(`  ok  L2 manual checklist written: ${outPath}`);
}

main();
