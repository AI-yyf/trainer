"use strict";

// This matrix deliberately tests the browser Preview with Playwright. It is not
// evidence that a real VS Code host, credential, or FastAPI sidecar was used.
const PREVIEW_EVIDENCE = Object.freeze({
  primaryLayer: "PW",
  label: "Playwright browser Preview",
  realSidecar: false,
  limitation:
    "Preview fixtures exercise the webview only; VSIX host, workspace filesystem, and live model behavior need a separate run.",
});

const VIEW_ORDER = ["coach", "plan", "resources", "training", "settings"];

const PAIR_VARIANTS = [
  { language: "zh-CN", viewport: { width: 360, height: 900 }, theme: "dark" },
  { language: "en-US", viewport: { width: 420, height: 900 }, theme: "light" },
];

const CROSS_VARIANTS = [
  { language: "zh-CN", viewport: { width: 300, height: 820 }, theme: "dark" },
  { language: "en-US", viewport: { width: 360, height: 900 }, theme: "light" },
  { language: "es-ES", viewport: { width: 420, height: 900 }, theme: "system" },
  { language: "fr-FR", viewport: { width: 300, height: 820 }, theme: "dark" },
  { language: "de-DE", viewport: { width: 360, height: 900 }, theme: "light" },
  { language: "ja-JP", viewport: { width: 420, height: 900 }, theme: "system" },
  { language: "ko-KR", viewport: { width: 300, height: 820 }, theme: "dark" },
  { language: "pt-BR", viewport: { width: 360, height: 900 }, theme: "light" },
];

const TRAINING_VARIANTS = [
  { language: "zh-CN", viewport: { width: 300, height: 900 }, theme: "dark" },
  { language: "en-US", viewport: { width: 360, height: 900 }, theme: "light" },
  { language: "es-ES", viewport: { width: 420, height: 900 }, theme: "system" },
  { language: "de-DE", viewport: { width: 360, height: 900 }, theme: "dark" },
];

// Personas are selected by the authored journey. They must never be inferred
// from a scenario ID: the same user may appear across views, and a domain is
// not an experience level.
const PERSONAS = Object.freeze({
  python_career_switcher: {
    role: "career-switching backend learner",
    experience: "new to Python projects",
    context: "reading an unfamiliar service repository",
    goal: "make one safe, testable change",
  },
  typescript_extension_builder: {
    role: "VS Code extension contributor",
    experience: "comfortable with TypeScript",
    context: "maintaining a strict webview bridge",
    goal: "understand a type boundary before editing it",
  },
  javascript_product_builder: {
    role: "product-minded JavaScript learner",
    experience: "ships small web features",
    context: "triaging an interaction regression",
    goal: "narrow the browser-visible cause",
  },
  ai_evaluator: {
    role: "AI application engineer",
    experience: "evaluates model behavior",
    context: "comparing answer quality and recovery paths",
    goal: "keep model output grounded and useful",
  },
  github_collaborator: {
    role: "open-source collaborator",
    experience: "reviews pull requests",
    context: "needs a small reviewable change",
    goal: "turn feedback into one verifiable review step",
  },
  api_integrator: {
    role: "API integration engineer",
    experience: "works with HTTP clients and contracts",
    context: "connecting a service without leaking credentials",
    goal: "separate reachability from usable teaching output",
  },
  remote_operator: {
    role: "remote development user",
    experience: "uses SSH and containers",
    context: "does not know which machine owns a file",
    goal: "prove the workspace boundary before editing",
  },
  debugging_learner: {
    role: "developer learning systematic debugging",
    experience: "can reproduce a failure but not isolate it",
    context: "a bug report has too many possible causes",
    goal: "build a minimal repro and one check",
  },
  vscode_power_user: {
    role: "daily VS Code user",
    experience: "uses editor commands and diagnostics",
    context: "needs editor guidance without losing focus",
    goal: "use one native editor capability deliberately",
  },
  research_reader: {
    role: "scientific research learner",
    experience: "reads papers and methods sections",
    context: "needs to distinguish a claim from its evidence",
    goal: "make one reproducible research note",
  },
  technical_english_learner: {
    role: "English learner in a technical team",
    experience: "reads issues and API docs in English",
    context: "needs a precise explanation without a translation dump",
    goal: "write one clear technical sentence",
  },
  writing_practitioner: {
    role: "knowledge worker improving writing",
    experience: "writes design notes and summaries",
    context: "has an unstructured draft",
    goal: "produce a concise, evidence-backed revision",
  },
  platform_recovery_owner: {
    role: "workspace maintainer",
    experience: "owns local tooling and migrations",
    context: "a path, workspace, or saved connection may be stale",
    goal: "recover safely without losing the current thread",
  },
  learning_lead: {
    role: "technical learning lead",
    experience: "coordinates individual learning plans",
    context: "needs evidence before promoting progress",
    goal: "keep plan and training truth aligned",
  },
});

const VISIBLE_CONTRACTS = Object.freeze({
  five_top_level_views: "five fixed top-level views are visible",
  one_active_view: "exactly one top-level view is active",
  coach_composer: "the Coach composer is visible and can receive a user request",
  coach_recovery_surface: "the Coach recovery surface remains visible instead of silently failing",
  workspace_admission: "the workspace admission panel explains the next safe choice",
  plan_surface: "the Plan surface shows its current governance context",
  resources_surface: "the Resources library and search control are visible",
  training_card: "one current training card is visible with its five-step loop",
  settings_surface: "the Settings connection surface is visible",
  provider_profiles: "saved provider profiles are visible before a switch is attempted",
});

const FORBIDDEN_CONTRACTS = Object.freeze({
  no_sixth_top_level_view: "the shell must not grow a sixth top-level view",
  no_horizontal_overflow: "the narrow sidebar must not horizontally overflow",
  no_preview_as_real_sidecar: "the matrix must not claim that Preview used a live sidecar",
  no_fake_provider_ready: "a blocked provider path must not be represented as usable",
  no_silent_plan_mutation: "a discussion must not silently change formal plan truth",
  no_unverified_mastery: "a card must not claim mastery without evidence",
  no_cross_workspace_leakage: "a workspace recovery path must not use another workspace as proof",
  no_secret_persistence: "a Preview credential flow must not treat a secret as durable metadata",
});

const RECOVERY_CONTRACTS = Object.freeze({
  keep_context: {
    kind: "keep_context",
    description: "Keep the learner's current question visible while the next small step is chosen.",
    verification: "PW",
  },
  show_provider_recovery: {
    kind: "show_provider_recovery",
    description: "Show a plain path to connection settings instead of inventing a reply.",
    verification: "PW",
  },
  admit_workspace: {
    kind: "admit_workspace",
    description: "Ask the user to add, browse, or ignore the discovered workspace before running work.",
    verification: "PW",
  },
  preserve_card: {
    kind: "preserve_card",
    description: "Keep the current training card and turn a failure into one retryable evidence gap.",
    verification: "PW",
  },
  repair_path: {
    kind: "repair_path",
    description: "Keep the migration target explicit and ask for a safe path decision.",
    verification: "VSIX",
    limitation: "Preview has no real workspace filesystem or migration command.",
  },
});

const PERSISTENCE_CONTRACTS = Object.freeze({
  conversation_after_stream: {
    kind: "conversation_after_stream",
    description: "The user request and the completed fixture reply remain visible in the current Preview session.",
    verification: "PW",
  },
  surface_context: {
    kind: "surface_context",
    description: "The opened Plan context remains available while the learner inspects it.",
    verification: "PW",
  },
  resource_query: {
    kind: "resource_query",
    description: "The current resource search query remains in the visible control during the session.",
    verification: "PW",
  },
  current_training_card: {
    kind: "current_training_card",
    description: "The same current card keeps its Learn-Try-Verify-Reflect-Return structure.",
    verification: "PW",
  },
  settings_detail: {
    kind: "settings_detail",
    description: "The opened Settings detail remains visible while the learner reviews it.",
    verification: "PW",
  },
  preview_active_view: {
    kind: "preview_active_view",
    description: "The selected view is written to Preview's local state for the current query.",
    verification: "PW",
    limitation: "The Preview storage key is query-scoped; this is not VS Code workbench restoration evidence.",
  },
  provider_profile: {
    kind: "provider_profile",
    description: "The selected Preview profile becomes the active profile in the current browser session.",
    verification: "PW",
    limitation: "No live credential or provider request is used by this matrix.",
  },
  locale_session: {
    kind: "locale_session",
    description: "The chosen response language becomes active in the current Preview session.",
    verification: "PW",
  },
  path_migration: {
    kind: "path_migration",
    description: "A migrated sandbox path must remain associated with the same workspace identity.",
    verification: "VSIX",
    limitation: "Requires the extension host and a real filesystem migration.",
  },
});

function prompt(english, chinese) {
  return { default: english, "zh-CN": chinese };
}

function journey(definition) {
  return Object.freeze(definition);
}

const COACH_JOURNEYS = [
  journey({
    key: "python-first-file",
    title: "Python learner starts with one unfamiliar file",
    domain: "Python",
    personaId: "python_career_switcher",
    userGoal: "Understand one Python service file before changing it.",
    state: "empty",
    userAction: { kind: "send_coach_message", input: prompt("I opened a Python service file. Help me find one safe first thing to verify without writing the change for me.", "我刚打开一个 Python 服务文件。请帮我找一个可以先验证的小步骤，不要直接替我改代码。") },
  }),
  journey({
    key: "typescript-contract",
    title: "TypeScript contributor recovers a webview contract",
    domain: "TypeScript",
    personaId: "typescript_extension_builder",
    userGoal: "Recover one TypeScript boundary before editing the bridge.",
    state: "ready",
    userAction: { kind: "send_coach_message", input: prompt("I need to understand one TypeScript message boundary before I edit it. Give me one contract check first.", "我需要先理解一个 TypeScript 消息边界再修改。请先给我一个合同检查步骤。") },
  }),
  journey({
    key: "project-orientation",
    title: "Existing project orientation keeps one concrete next move",
    domain: "Project orientation",
    personaId: "learning_lead",
    userGoal: "Understand an existing project without being pushed into a formal plan too early.",
    state: "ready",
    userAction: { kind: "send_coach_message", input: prompt("I just joined an existing project. Help me identify one small area to understand before planning a larger change.", "我刚加入一个已有项目。请帮我先找一个小范围理解，再决定是否需要更大的计划。") },
    extraForbidden: ["no_silent_plan_mutation"],
  }),
  journey({
    key: "javascript-regression",
    title: "JavaScript learner narrows an interaction regression",
    domain: "JavaScript",
    personaId: "javascript_product_builder",
    userGoal: "Narrow a browser interaction regression without guessing.",
    state: "ready",
    userAction: { kind: "send_coach_message", input: prompt("A JavaScript interaction regressed after a small UI change. Help me choose one observable symptom to test first.", "一个小 UI 改动后 JavaScript 交互回归了。请帮我先选一个可观察的现象来测试。") },
  }),
  journey({
    key: "ai-answer-evaluation",
    title: "AI engineer evaluates an off-topic answer",
    domain: "AI",
    personaId: "ai_evaluator",
    userGoal: "Evaluate why a model answer missed the user's question.",
    state: "rich-content",
    userAction: { kind: "send_coach_message", input: prompt("This AI answer sounds fluent but misses the user's goal. Help me write one evaluation check for relevance.", "这条 AI 回答很流畅但偏离了用户目标。请帮我写一个相关性检查。") },
  }),
  journey({
    key: "github-review",
    title: "GitHub collaborator turns review feedback into one check",
    domain: "GitHub",
    personaId: "github_collaborator",
    userGoal: "Turn a pull-request comment into a narrow review step.",
    state: "ready",
    userAction: { kind: "send_coach_message", input: prompt("A GitHub review says this change is hard to verify. Help me turn that into one small review check.", "GitHub 评审说这个改动难以验证。请帮我把它变成一个小的检查步骤。") },
  }),
  journey({
    key: "api-contract",
    title: "API integrator distinguishes reachability from usable output",
    domain: "API",
    personaId: "api_integrator",
    userGoal: "Check whether an API response is usable for coaching, not merely HTTP-successful.",
    state: "ready",
    userAction: { kind: "send_coach_message", input: prompt("My API returns 200 but the teaching text is empty. What is the first contract I should verify?", "我的 API 返回了 200，但教学文字是空的。第一步应该验证什么合同？") },
  }),
  journey({
    key: "remote-ssh-boundary",
    title: "Remote SSH user verifies the workspace owner",
    domain: "Remote SSH",
    personaId: "remote_operator",
    userGoal: "Prove which machine owns the current workspace before changing a file.",
    state: "ready",
    userAction: { kind: "send_coach_message", input: prompt("I am connected with Remote SSH and do not know which machine owns this file. Give me one boundary check.", "我正在使用 Remote SSH，不确定这个文件属于哪台机器。请给我一个边界检查。") },
  }),
  journey({
    key: "debug-minimal-repro",
    title: "Debugger reduces a report to one minimal repro",
    domain: "Debugging",
    personaId: "debugging_learner",
    userGoal: "Build a minimal reproduction before proposing a fix.",
    state: "ready",
    userAction: { kind: "send_coach_message", input: prompt("I can reproduce a bug but have too many hypotheses. Help me choose one minimal repro step.", "我能复现一个 bug，但假设太多了。请帮我选择一个最小复现步骤。") },
  }),
  journey({
    key: "vscode-diagnostic",
    title: "VS Code user starts from one editor diagnostic",
    domain: "VS Code",
    personaId: "vscode_power_user",
    userGoal: "Use one editor signal to guide the next learning move.",
    state: "ready",
    userAction: { kind: "send_coach_message", input: prompt("VS Code shows a diagnostic in the active file. Help me inspect it without expanding to the whole repository.", "VS Code 在当前文件里显示一个诊断。请帮我检查它，不要一下扩大到整个仓库。") },
  }),
  journey({
    key: "research-method",
    title: "Scientific reader separates a method claim from evidence",
    domain: "Scientific research",
    personaId: "research_reader",
    userGoal: "Extract one reproducible method claim from a paper.",
    state: "rich-content",
    userAction: { kind: "send_coach_message", input: prompt("I am reading a research paper. Help me separate one method claim from the evidence that supports it.", "我在读一篇科研论文。请帮我区分一个方法主张和支持它的证据。") },
  }),
  journey({
    key: "english-issue",
    title: "English learner clarifies a technical issue",
    domain: "English",
    personaId: "technical_english_learner",
    userGoal: "Write one clear technical clarification for an issue thread.",
    state: "ready",
    userAction: { kind: "send_coach_message", input: prompt("Help me write one clear English sentence asking for the missing reproduction step in an issue.", "请帮我写一句清晰的英文，询问 issue 里缺失的复现步骤。") },
  }),
  journey({
    key: "writing-revision",
    title: "Writer turns an unstructured note into one evidence-backed paragraph",
    domain: "Writing",
    personaId: "writing_practitioner",
    userGoal: "Revise a technical note without losing its evidence.",
    state: "ready",
    userAction: { kind: "send_coach_message", input: prompt("I have a rough technical note. Help me choose one paragraph to tighten while keeping the evidence visible.", "我有一份粗糙的技术笔记。请帮我选一段压缩，同时保留证据。") },
  }),
  journey({
    key: "provider-recovery-thread",
    title: "Provider recovery preserves the learner's question",
    domain: "Provider and runtime",
    personaId: "platform_recovery_owner",
    userGoal: "Recover from an unavailable model without losing the coaching thread.",
    state: "provider-failure",
    userAction: { kind: "observe_recovery", input: undefined },
    recovery: RECOVERY_CONTRACTS.show_provider_recovery,
    persistence: PERSISTENCE_CONTRACTS.conversation_after_stream,
    extraVisible: ["coach_recovery_surface"],
    extraForbidden: ["no_fake_provider_ready"],
  }),
  journey({
    key: "agent-failure-context-recovery",
    title: "Agent failure keeps the current question recoverable",
    domain: "AI",
    personaId: "ai_evaluator",
    userGoal: "Recover from a failed tool step by retaining the user's evidence gap.",
    state: "recovery",
    userAction: { kind: "observe_recovery", input: undefined },
    recovery: RECOVERY_CONTRACTS.keep_context,
    persistence: PERSISTENCE_CONTRACTS.conversation_after_stream,
  }),
  journey({
    key: "workspace-root-missing",
    title: "Damaged workspace root asks for a safe admission choice",
    domain: "Workspace recovery",
    personaId: "platform_recovery_owner",
    userGoal: "Recover when the configured Trainer workspace root is missing.",
    state: "workspace-admission",
    workspaceAdmission: "root-missing",
    userAction: { kind: "observe_workspace_admission", input: undefined },
    recovery: RECOVERY_CONTRACTS.admit_workspace,
    persistence: PERSISTENCE_CONTRACTS.path_migration,
    extraVisible: ["workspace_admission"],
    extraForbidden: ["no_cross_workspace_leakage"],
  }),
  journey({
    key: "stream-interruption",
    title: "Interrupted stream keeps the next safe move visible",
    domain: "Provider and runtime",
    personaId: "platform_recovery_owner",
    userGoal: "Recover a partially received coaching reply without inventing the missing text.",
    state: "stream",
    userAction: { kind: "observe_recovery", input: undefined },
    recovery: RECOVERY_CONTRACTS.keep_context,
    persistence: PERSISTENCE_CONTRACTS.conversation_after_stream,
  }),
];

const PLAN_JOURNEYS = [
  journey({ key: "python-no-plan", title: "Python learner sees no formal plan yet", domain: "Python", personaId: "python_career_switcher", userGoal: "Start a Python learning path without pretending a formal plan already exists.", state: "ready" }),
  journey({ key: "typescript-mainline", title: "TypeScript contributor reads current mainline", domain: "TypeScript", personaId: "typescript_extension_builder", userGoal: "See why the current TypeScript task is next and how to verify it.", state: "ready" }),
  journey({ key: "javascript-discussion", title: "JavaScript discussion stays out of formal plan truth", domain: "JavaScript", personaId: "javascript_product_builder", userGoal: "Discuss a UI regression without silently rewriting the plan.", state: "ready", extraForbidden: ["no_silent_plan_mutation"] }),
  journey({ key: "ai-evidence", title: "AI evaluation keeps candidate evidence separate", domain: "AI", personaId: "ai_evaluator", userGoal: "Compare AI evidence before it becomes a formal learning decision.", state: "ready", extraForbidden: ["no_silent_plan_mutation"] }),
  journey({ key: "github-review-evidence", title: "GitHub review becomes pending evidence", domain: "GitHub", personaId: "github_collaborator", userGoal: "Keep pull-request feedback pending until it has a check.", state: "ready" }),
  journey({ key: "api-plan-generation", title: "API study proposes a formal plan explicitly", domain: "API", personaId: "api_integrator", userGoal: "Generate an API learning plan only after the learner asks for it.", state: "ready" }),
  journey({ key: "remote-ssh-blocker", title: "Remote SSH boundary blocks unsafe planning", domain: "Remote SSH", personaId: "remote_operator", userGoal: "Keep a plan blocked until the remote workspace owner is known.", state: "plan-blocked", recovery: RECOVERY_CONTRACTS.keep_context, extraForbidden: ["no_unverified_mastery"] }),
  journey({ key: "debug-evidence", title: "Debug repro returns evidence to the plan", domain: "Debugging", personaId: "debugging_learner", userGoal: "Return a minimal repro as evidence, not as a mastery claim.", state: "ready", extraForbidden: ["no_unverified_mastery"] }),
  journey({ key: "vscode-subplan", title: "VS Code task preserves subplan continuity", domain: "VS Code", personaId: "vscode_power_user", userGoal: "Keep an editor-guidance subplan visible after navigation.", state: "ready" }),
  journey({ key: "research-method-plan", title: "Research method learning names evidence requirements", domain: "Scientific research", personaId: "research_reader", userGoal: "Record a method claim with the evidence needed to adopt it.", state: "ready" }),
  journey({ key: "english-writing-plan", title: "English practice has a verifiable next step", domain: "English", personaId: "technical_english_learner", userGoal: "Make an English-writing task concrete enough to review.", state: "ready" }),
  journey({ key: "writing-plan", title: "Writing revision remains a small plan slice", domain: "Writing", personaId: "writing_practitioner", userGoal: "Keep a writing revision plan focused on one paragraph and one proof point.", state: "ready" }),
  journey({ key: "frozen-plan", title: "Frozen plan exposes only explicit return-to-live control", domain: "Plan governance", personaId: "learning_lead", userGoal: "Inspect a frozen plan without an accidental mutation.", state: "plan-frozen", extraForbidden: ["no_silent_plan_mutation"] }),
  journey({ key: "provider-block", title: "Provider failure never fabricates a plan", domain: "Provider and runtime", personaId: "platform_recovery_owner", userGoal: "Stay honest when a provider is not usable.", state: "provider-failure-empty", recovery: RECOVERY_CONTRACTS.show_provider_recovery, extraForbidden: ["no_fake_provider_ready"] }),
  journey({ key: "workspace-corruption", title: "Damaged workspace blocks cross-project plan leakage", domain: "Workspace recovery", personaId: "platform_recovery_owner", userGoal: "Keep the plan tied to the correct workspace after a root problem.", state: "plan-blocked", recovery: RECOVERY_CONTRACTS.admit_workspace, extraForbidden: ["no_cross_workspace_leakage"] }),
  journey({ key: "path-migration", title: "Path migration keeps plan identity intact", domain: "Path migration", personaId: "platform_recovery_owner", userGoal: "Move a sandbox path without losing plan identity.", state: "ready", recovery: RECOVERY_CONTRACTS.repair_path, persistence: PERSISTENCE_CONTRACTS.path_migration }),
  journey({ key: "language-switch-plan", title: "Language switch preserves formal plan semantics", domain: "Language switching", personaId: "technical_english_learner", userGoal: "Switch language without turning plan evidence into generic chat text.", state: "ready" }),
];

const RESOURCE_JOURNEYS = [
  journey({ key: "python-library", title: "Python learner starts with an empty library", domain: "Python", personaId: "python_career_switcher", userGoal: "Find the first reusable Python resource.", state: "ready" }),
  journey({ key: "typescript-docs", title: "TypeScript contributor searches API documentation", domain: "TypeScript", personaId: "typescript_extension_builder", userGoal: "Find one TypeScript contract reference.", state: "resource-preview-loaded" }),
  journey({ key: "javascript-material", title: "JavaScript learner searches project material", domain: "JavaScript", personaId: "javascript_product_builder", userGoal: "Find a project note about an interaction regression.", state: "ready" }),
  journey({ key: "ai-provenance", title: "AI evaluator checks source provenance", domain: "AI", personaId: "ai_evaluator", userGoal: "Know where an AI evaluation artifact came from.", state: "resource-preview-loaded" }),
  journey({ key: "github-link", title: "GitHub collaborator keeps issue source visible", domain: "GitHub", personaId: "github_collaborator", userGoal: "Keep a pull-request or issue link traceable to the learning task.", state: "ready" }),
  journey({ key: "api-doc-search", title: "API integrator searches a service reference", domain: "API", personaId: "api_integrator", userGoal: "Search API documentation before inferring an endpoint contract.", state: "resource-preview-loaded" }),
  journey({ key: "remote-sandbox", title: "Remote SSH user sees sandbox boundary", domain: "Remote SSH", personaId: "remote_operator", userGoal: "Tell a resource sandbox from the real remote workspace.", state: "ready", extraForbidden: ["no_cross_workspace_leakage"] }),
  journey({ key: "debug-index-retry", title: "Debug learner sees indexing retry path", domain: "Debugging", personaId: "debugging_learner", userGoal: "Retry a missing debug resource instead of treating it as evidence.", state: "ready" }),
  journey({ key: "vscode-resource", title: "VS Code user selects one editor reference", domain: "VS Code", personaId: "vscode_power_user", userGoal: "Select one editor-related resource without opening an admin panel.", state: "resource-preview-loaded" }),
  journey({ key: "research-freshness", title: "Research reader checks source freshness", domain: "Scientific research", personaId: "research_reader", userGoal: "Check whether a cited method source is current enough to use.", state: "ready" }),
  journey({ key: "english-source", title: "English learner searches a technical example", domain: "English", personaId: "technical_english_learner", userGoal: "Find one clear English example rather than a broad translation dump.", state: "ready" }),
  journey({ key: "writing-source", title: "Writer turns one source into a revision candidate", domain: "Writing", personaId: "writing_practitioner", userGoal: "Use one source as evidence for a concise revision.", state: "resource-preview-loaded" }),
  journey({ key: "resource-to-card", title: "Resource becomes a training candidate with trace", domain: "Training handoff", personaId: "learning_lead", userGoal: "Move a resource to practice while retaining its provenance.", state: "ready", extraForbidden: ["no_unverified_mastery"] }),
  journey({ key: "resource-to-plan", title: "Resource becomes pending plan evidence", domain: "Plan governance", personaId: "learning_lead", userGoal: "Offer a resource as evidence without silently adopting it.", state: "ready", extraForbidden: ["no_silent_plan_mutation"] }),
  journey({ key: "path-migration-resource", title: "Path migration keeps resource identity", domain: "Path migration", personaId: "platform_recovery_owner", userGoal: "Move a sandbox path without duplicating or losing a resource identity.", state: "resource-preview-loaded", recovery: RECOVERY_CONTRACTS.repair_path, persistence: PERSISTENCE_CONTRACTS.path_migration }),
  journey({ key: "workspace-damaged-resource", title: "Damaged workspace avoids unsafe resource reuse", domain: "Workspace recovery", personaId: "platform_recovery_owner", userGoal: "Avoid treating resources from a damaged workspace as current evidence.", state: "ready", extraForbidden: ["no_cross_workspace_leakage"] }),
  journey({ key: "locale-resource", title: "Language switch keeps resource discovery usable", domain: "Language switching", personaId: "technical_english_learner", userGoal: "Change language while keeping search and selected-resource state understandable.", state: "ready" }),
  journey({ key: "provider-resource-recovery", title: "Provider failure does not hide resource work", domain: "Provider and runtime", personaId: "platform_recovery_owner", userGoal: "Keep the library usable when a model connection needs repair.", state: "provider-failure", recovery: RECOVERY_CONTRACTS.show_provider_recovery, extraForbidden: ["no_fake_provider_ready"] }),
  journey({ key: "resource-restore", title: "Restored resource retains a clear identity", domain: "Recovery", personaId: "learning_lead", userGoal: "Restore one archived resource without confusing it with a new import.", state: "resource-preview-loaded" }),
];

const TRAINING_JOURNEYS = [
  journey({ key: "remote-boundary-card", title: "Remote workspace boundary card", domain: "Remote SSH", personaId: "remote_operator", userGoal: "Verify which machine owns the workspace files.", state: "training-remote" }),
  journey({ key: "debug-loop-card", title: "Minimal debug loop card", domain: "Debugging", personaId: "debugging_learner", userGoal: "Build one minimal debug loop before proposing a fix.", state: "training-debug" }),
  journey({ key: "typescript-function-card", title: "TypeScript function contract card", domain: "TypeScript", personaId: "typescript_extension_builder", userGoal: "Recover one function contract with editor guidance.", state: "training-function" }),
  journey({ key: "python-resource-card", title: "Python resource-grounded practice card", domain: "Python", personaId: "python_career_switcher", userGoal: "Practice one Python task using a traceable resource.", state: "training-resource" }),
  journey({ key: "javascript-dependency-card", title: "JavaScript dependency mastery card", domain: "JavaScript", personaId: "javascript_product_builder", userGoal: "Understand one JavaScript dependency before transfer practice.", state: "training-dependency" }),
  journey({ key: "ai-evaluation-card", title: "AI response evaluation card", domain: "AI", personaId: "ai_evaluator", userGoal: "Verify a response stays aligned to the user's stated goal.", state: "training-debug" }),
  journey({ key: "github-review-card", title: "GitHub review evidence card", domain: "GitHub", personaId: "github_collaborator", userGoal: "Return a review result with one concrete proof point.", state: "training-resource" }),
  journey({ key: "api-contract-card", title: "API contract verification card", domain: "API", personaId: "api_integrator", userGoal: "Verify an API contract before claiming the integration works.", state: "training-function" }),
  journey({ key: "research-method-card", title: "Scientific method transfer card", domain: "Scientific research", personaId: "research_reader", userGoal: "Return a reproducible method note with its evidence.", state: "training-dependency" }),
  journey({ key: "english-writing-card", title: "English technical writing card", domain: "English", personaId: "technical_english_learner", userGoal: "Write one precise technical clarification and verify its meaning.", state: "training-remote" }),
  journey({ key: "blocked-card-recovery", title: "Blocked card recovery", domain: "Recovery", personaId: "learning_lead", userGoal: "Keep the same card after a failed check and name the missing proof.", state: "recovery", recovery: RECOVERY_CONTRACTS.preserve_card }),
];

const SETTINGS_JOURNEYS = [
  journey({ key: "provider-setup", title: "Empty provider setup stays honest", domain: "Provider and runtime", personaId: "platform_recovery_owner", userGoal: "See which connection detail is missing before coaching begins.", state: "empty", userAction: { kind: "open_connection_details" }, extraForbidden: ["no_fake_provider_ready"] }),
  journey({ key: "provider-switch", title: "Provider profile switch is explicit", domain: "Provider switching", personaId: "api_integrator", userGoal: "Switch to a saved provider profile deliberately.", state: "ready", userAction: { kind: "switch_provider_profile" }, persistence: PERSISTENCE_CONTRACTS.provider_profile, extraVisible: ["provider_profiles"] }),
  journey({ key: "provider-failure", title: "Unavailable provider offers a plain recovery path", domain: "Provider and runtime", personaId: "platform_recovery_owner", userGoal: "Repair an unavailable model without exposing implementation jargon.", state: "provider-failure", userAction: { kind: "open_connection_details" }, recovery: RECOVERY_CONTRACTS.show_provider_recovery, extraForbidden: ["no_fake_provider_ready"] }),
  journey({ key: "provider-auth", title: "Authentication failure keeps recovery specific", domain: "API", personaId: "api_integrator", userGoal: "Distinguish an access problem from a usable connection.", state: "provider-auth-failure", userAction: { kind: "open_connection_details" }, recovery: RECOVERY_CONTRACTS.show_provider_recovery, extraForbidden: ["no_fake_provider_ready", "no_secret_persistence"] }),
  journey({ key: "model-catalog", title: "Model catalog remains capability-gated", domain: "AI", personaId: "ai_evaluator", userGoal: "Inspect model availability without treating a list as teaching readiness.", state: "ready", userAction: { kind: "open_connection_details" }, extraForbidden: ["no_fake_provider_ready"] }),
  journey({ key: "api-protocol", title: "API protocol choice is visible", domain: "API", personaId: "api_integrator", userGoal: "Inspect the selected API protocol before testing it.", state: "ready", userAction: { kind: "open_connection_details" } }),
  journey({ key: "tool-capability", title: "Agent tool capability is shown honestly", domain: "AI", personaId: "ai_evaluator", userGoal: "Know whether a model can use tools before asking for agent work.", state: "ready", userAction: { kind: "open_connection_details" }, extraForbidden: ["no_fake_provider_ready"] }),
  journey({ key: "language-switch", title: "Language switch updates the current settings session", domain: "Language switching", personaId: "technical_english_learner", userGoal: "Switch the response language without losing settings context.", state: "ready", userAction: { kind: "switch_language" }, persistence: PERSISTENCE_CONTRACTS.locale_session }),
  journey({ key: "workspace-recovery", title: "Workspace recovery control stays in Settings", domain: "Workspace recovery", personaId: "platform_recovery_owner", userGoal: "Recover a managed workspace path without moving business content into Settings.", state: "ready", userAction: { kind: "open_connection_details" }, recovery: RECOVERY_CONTRACTS.repair_path, persistence: PERSISTENCE_CONTRACTS.path_migration, extraForbidden: ["no_cross_workspace_leakage"] }),
  journey({ key: "writing-defaults", title: "Writing learner chooses humane coach defaults", domain: "Writing", personaId: "writing_practitioner", userGoal: "Inspect language and coach defaults before a writing practice round.", state: "ready", userAction: { kind: "open_connection_details" } }),
];

const CROSS_JOURNEYS = [
  journey({ key: "five-view-shell", title: "Five-view shell remains stable", domain: "Navigation", personaId: "learning_lead", userGoal: "Move from Coach to Plan without losing the sidebar shell.", nextView: "plan" }),
  journey({ key: "python-coach-plan", title: "Python question hands off to Plan", domain: "Python", personaId: "python_career_switcher", userGoal: "Move a Python goal from conversation to a formal plan deliberately.", nextView: "plan" }),
  journey({ key: "typescript-plan-training", title: "TypeScript plan hands off to Training", domain: "TypeScript", personaId: "typescript_extension_builder", userGoal: "Move a TypeScript task from plan to one current training card.", nextView: "training" }),
  journey({ key: "javascript-training-coach", title: "JavaScript result returns to Coach", domain: "JavaScript", personaId: "javascript_product_builder", userGoal: "Return a JavaScript practice result to the conversation thread.", nextView: "coach" }),
  journey({ key: "ai-provider-settings", title: "AI failure routes to Settings", domain: "AI", personaId: "ai_evaluator", userGoal: "Move from a blocked AI request to the connection controls.", nextView: "settings" }),
  journey({ key: "github-resource-training", title: "GitHub evidence routes from Resources to Training", domain: "GitHub", personaId: "github_collaborator", userGoal: "Use a GitHub artifact as an explicit training handoff.", nextView: "training" }),
  journey({ key: "api-settings-coach", title: "API connection check returns to Coach", domain: "API", personaId: "api_integrator", userGoal: "Return from API settings to the original coaching flow.", nextView: "coach" }),
  journey({ key: "remote-resource-boundary", title: "Remote SSH user sees Resources boundary", domain: "Remote SSH", personaId: "remote_operator", userGoal: "Navigate to Resources without mistaking it for the remote workspace.", nextView: "resources" }),
  journey({ key: "debug-plan-training", title: "Debug evidence moves from Plan to Training", domain: "Debugging", personaId: "debugging_learner", userGoal: "Move one debug proof point into a focused training card.", nextView: "training" }),
  journey({ key: "vscode-settings", title: "VS Code controls remain in Settings", domain: "VS Code", personaId: "vscode_power_user", userGoal: "Navigate to runtime controls without turning Coach into a control panel.", nextView: "settings" }),
  journey({ key: "research-resource-plan", title: "Research source routes to Plan evidence", domain: "Scientific research", personaId: "research_reader", userGoal: "Move a research source toward plan evidence without adopting it silently.", nextView: "plan" }),
  journey({ key: "english-language-switch", title: "English learner switches language then continues", domain: "Language switching", personaId: "technical_english_learner", userGoal: "Navigate after a language change while keeping the five-view labels coherent.", nextView: "coach" }),
  journey({ key: "writing-resource-coach", title: "Writing source returns to Coach", domain: "Writing", personaId: "writing_practitioner", userGoal: "Bring a writing source back to one focused coaching question.", nextView: "coach" }),
  journey({ key: "workspace-damaged-settings", title: "Damaged workspace routes to recovery controls", domain: "Workspace recovery", personaId: "platform_recovery_owner", userGoal: "Navigate from a workspace blocker to the recovery controls.", nextView: "settings", recovery: RECOVERY_CONTRACTS.admit_workspace, extraForbidden: ["no_cross_workspace_leakage"] }),
  journey({ key: "path-migration-resources", title: "Path migration returns to Resources", domain: "Path migration", personaId: "platform_recovery_owner", userGoal: "Navigate after a sandbox path migration without losing resource identity.", nextView: "resources", recovery: RECOVERY_CONTRACTS.repair_path, persistence: PERSISTENCE_CONTRACTS.path_migration }),
];

function pad(number) {
  return String(number).padStart(2, "0");
}

function materializePersona(personaId, language) {
  const profile = PERSONAS[personaId];
  if (!profile) {
    throw new Error(`Unknown authored persona: ${personaId}`);
  }
  return Object.freeze({ id: personaId, language, ...profile });
}

function materializeInput(input, language) {
  if (typeof input === "string") {
    return input;
  }
  return input?.[language] ?? input?.default;
}

function materializeAction(action, language, journeyDefinition) {
  const authoredAction = action ?? { kind: "inspect_surface" };
  const input = materializeInput(authoredAction.input, language);
  const result = {
    ...authoredAction,
    label: authoredAction.label ?? journeyDefinition.userGoal,
  };
  delete result.input;
  return input ? { ...result, input } : result;
}

function expectedContracts({ runner, journeyDefinition }) {
  const viewVisible = {
    coach: "coach_composer",
    plan: "plan_surface",
    resources: "resources_surface",
    training: "training_card",
    settings: "settings_surface",
    cross: "one_active_view",
  }[runner];
  const defaultForbidden = [
    "no_sixth_top_level_view",
    "no_horizontal_overflow",
    "no_preview_as_real_sidecar",
  ];
  const recovery = journeyDefinition.recovery ?? RECOVERY_CONTRACTS.keep_context;
  const persistence =
    journeyDefinition.persistence ??
    {
      coach: PERSISTENCE_CONTRACTS.conversation_after_stream,
      plan: PERSISTENCE_CONTRACTS.surface_context,
      resources: PERSISTENCE_CONTRACTS.resource_query,
      training: PERSISTENCE_CONTRACTS.current_training_card,
      settings: PERSISTENCE_CONTRACTS.settings_detail,
      cross: PERSISTENCE_CONTRACTS.preview_active_view,
    }[runner];

  return Object.freeze({
    visible: Object.freeze([
      "five_top_level_views",
      "one_active_view",
      viewVisible,
      ...(journeyDefinition.extraVisible ?? []),
    ].map((id) => Object.freeze({ id, description: VISIBLE_CONTRACTS[id] }))),
    forbidden: Object.freeze([
      ...new Set([...defaultForbidden, ...(journeyDefinition.extraForbidden ?? [])]),
    ].map((id) => Object.freeze({
      id,
      description: FORBIDDEN_CONTRACTS[id],
      verification: id === "no_preview_as_real_sidecar" || id === "no_sixth_top_level_view" || id === "no_horizontal_overflow" ? "PW" : "VSIX",
    }))),
    recovery: Object.freeze({ ...recovery }),
    persistence: Object.freeze({ ...persistence }),
  });
}

function createScenario({ id, runner, view, journeyDefinition, variant, requirements, followUpLayer }) {
  const userAction = materializeAction(journeyDefinition.userAction, variant.language, journeyDefinition);
  const inferredAction = {
    plan: { kind: "inspect_plan_context" },
    resources: { kind: "search_library", input: `scenario ${id}` },
    training: { kind: "inspect_training_card" },
    settings: { kind: "open_connection_details" },
    cross: { kind: "navigate_to_view", targetView: journeyDefinition.nextView },
  }[runner];
  const finalAction = userAction.kind === "inspect_surface" ? { ...userAction, ...inferredAction } : userAction;

  return Object.freeze({
    id,
    title: `${journeyDefinition.title} (${variant.language}, ${variant.viewport.width}px)`,
    definitionId: journeyDefinition.key,
    domain: journeyDefinition.domain,
    persona: materializePersona(journeyDefinition.personaId, variant.language),
    userGoal: journeyDefinition.userGoal,
    userAction: Object.freeze(finalAction),
    expected: expectedContracts({ runner, journeyDefinition }),
    view,
    state: journeyDefinition.state ?? "ready",
    runner,
    primaryLayer: PREVIEW_EVIDENCE.primaryLayer,
    evidence: PREVIEW_EVIDENCE,
    followUpLayer: followUpLayer ?? "VSIX",
    requirements: Object.freeze(requirements),
    language: variant.language,
    viewport: Object.freeze({ ...variant.viewport }),
    theme: variant.theme,
    nextView: journeyDefinition.nextView,
    workspaceAdmission: journeyDefinition.workspaceAdmission,
  });
}

function pairedScenarios({ prefix, view, journeys, runner, requirements }) {
  return journeys.flatMap((journeyDefinition, journeyIndex) =>
    PAIR_VARIANTS.map((variant, variantIndex) =>
      createScenario({
        id: `${prefix}${pad(journeyIndex * PAIR_VARIANTS.length + variantIndex + 1)}`,
        runner,
        view,
        journeyDefinition,
        variant,
        requirements,
      }),
    ),
  );
}

const coachScenarios = pairedScenarios({
  prefix: "C",
  view: "coach",
  journeys: COACH_JOURNEYS,
  runner: "coach",
  requirements: ["five_views", "conversation_first", "trust", "recoverability"],
});

const planScenarios = pairedScenarios({
  prefix: "P",
  view: "plan",
  journeys: PLAN_JOURNEYS,
  runner: "plan",
  requirements: ["five_views", "dual_planning", "evidence", "truth"],
});

const resourceScenarios = pairedScenarios({
  prefix: "R",
  view: "resources",
  journeys: RESOURCE_JOURNEYS,
  runner: "resources",
  requirements: ["five_views", "workspace_first", "resource_sandbox", "recoverability"],
});

const trainingScenarios = TRAINING_JOURNEYS.flatMap((journeyDefinition, journeyIndex) =>
  TRAINING_VARIANTS.map((variant, variantIndex) =>
    createScenario({
      id: `T${pad(journeyIndex * TRAINING_VARIANTS.length + variantIndex + 1)}`,
      runner: "training",
      view: "training",
      journeyDefinition,
      variant,
      requirements: ["five_views", "learn_try_verify_reflect_return", "single_card", "evidence"],
    }),
  ),
);

const settingsScenarios = pairedScenarios({
  prefix: "S",
  view: "settings",
  journeys: SETTINGS_JOURNEYS,
  runner: "settings",
  requirements: ["five_views", "capability_truth", "provider_neutral", "secret_safety"],
});

const crossScenarios = CROSS_JOURNEYS.flatMap((journeyDefinition, journeyIndex) =>
  [0, 1].map((variantOffset) => {
    const variant = CROSS_VARIANTS[(journeyIndex * 2 + variantOffset) % CROSS_VARIANTS.length];
    return createScenario({
      id: `X${pad(journeyIndex * 2 + variantOffset + 1)}`,
      runner: "cross",
      view: VIEW_ORDER[(journeyIndex + variantOffset) % VIEW_ORDER.length],
      journeyDefinition,
      variant,
      followUpLayer: "VSIX",
      requirements: ["five_views", "i18n", "narrow_sidebar", "recoverability"],
    });
  }),
);

const SCENARIOS = Object.freeze([
  ...coachScenarios,
  ...planScenarios,
  ...resourceScenarios,
  ...trainingScenarios,
  ...settingsScenarios,
  ...crossScenarios,
]);

const GROUP_COUNTS = Object.freeze({
  coach: coachScenarios.length,
  plan: planScenarios.length,
  resources: resourceScenarios.length,
  training: trainingScenarios.length,
  settings: settingsScenarios.length,
  cross: crossScenarios.length,
});

if (SCENARIOS.length !== 200) {
  throw new Error(`Trainer experience matrix must contain 200 scenarios, found ${SCENARIOS.length}.`);
}

if (new Set(SCENARIOS.map((scenario) => scenario.id)).size !== SCENARIOS.length) {
  throw new Error("Trainer experience matrix contains duplicate scenario IDs.");
}

module.exports = {
  FORBIDDEN_CONTRACTS,
  GROUP_COUNTS,
  PERSONAS,
  PREVIEW_EVIDENCE,
  SCENARIOS,
  VIEW_ORDER,
  VISIBLE_CONTRACTS,
};
