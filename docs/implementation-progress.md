# Trainer 体验优化总结与后续计划

> 基于 `docs/open-source-fit-and-provider-strategy.md` 的实施进展

## 已完成的工作

### 1. 强化学习训练数据 ✅

创建了 `extension/webview/src/lib/rlTrainingData.ts`，包含：

- **10+ 强化学习算法卡片**：
  - Q-Learning / SARSA（表格型）
  - DQN / Policy Gradient（函数逼近）
  - DDPG / TD3 / SAC（Actor-Critic）
  - PPO（近端策略优化）
  - A2C/A3C（异步方法）
  - MCTS（蒙特卡洛树搜索）

- **每张卡片包含**：
  - 算法描述与适用场景
  - 优缺点分析
  - 闪卡（Flash Cards）：原理/公式/概念
  - 练习卡（Practice Cards）：完整练习任务
  - 学习路径（5阶段）

### 2. UI 样式体系 ✅

styles.css 已包含现代设计系统：
- **Message Bubble V2**：类似 Codex/Copilot 的现代对话样式
- **三档预览徽章**：Tier A/B/C 标识
- **文件类型图标**：PDF/DOCX/CSV/音频/图片等
- **骨架屏动画**：加载状态友好
- **深色/浅色主题**：跟随 VS Code

### 3. 国际化 ✅

- `copy.ts` 包含完整中文翻译
- `useTranslation` hook 支持中英文切换
- UTF-8 编码，无乱码问题

## 八大能力现状评估

| 能力 | 当前状态 | 目标状态 | 差距 |
|------|---------|---------|------|
| Provider v2 | 有 profile 配置 | 多协议、多模型别名、task binding | 中 |
| Workspace Authority | 基础 sandbox | folder sovereignty、ledger、trash | 大 |
| File Preview | 基础支持 | 三层能力梯 (Tier A/B/C) | 中 |
| Search | 简单搜索 | SQLite FTS5 + metadata | 大 |
| Session Rendering | typed parts | 完整 typed parts registry | 小 |
| Training (FSRS) | 有卡片数据 | ts-fsrs 集成、状态机 | 中 |
| Memory | 基础 memory | 分层记忆体系 | 中 |
| Remote | 依赖 VS Code | 远程优先、本地优先 | 中 |

## 后续优化计划

### Phase 1: 核心体验提升（本周）

1. **训练视图改进**
   - 集成 rlTrainingData.ts 到训练视图
   - 实现单卡流 UI
   - 添加 FSRS 复习调度显示

2. **会话视图增强**
   - 启用 Message Bubble V2 样式
   - 添加学习路径可视化
   - 改进闪卡交互

3. **Provider 设置优化**
   - 添加协议选择器
   - 显示模型能力矩阵
   - 添加连接测试状态

### Phase 2: 核心能力建设（第二周）

1. **Workspace Authority**
   - 实现 activeWorkspaceRoot
   - 添加 operation ledger
   - 实现 trash 机制

2. **File Preview 三层能力**
   - Tier A: CodeMirror 6 + Shiki
   - Tier B: MarkItDown 转换
   - Tier C: metadata + open external

3. **Search 增强**
   - SQLite FTS5 集成
   - path/title/symbol 索引
   - 教学结果展示

### Phase 3: 高级能力（第三周）

1. **Memory 分层**
   - Master plan memory
   - Project memory
   - Session/Resource/Review memory

2. **Remote 优化**
   - credentialMode = workspace_secret | ui_proxy
   - 远程索引优化

## 验证证据

### 构建验证
```bash
npm run build  # ✅ 通过
```

### 类型检查
```bash
npm run check  # ✅ 通过
```

### UI 预览
- 浏览器可直接打开 `/` 查看主界面
- 支持 `?view=plan`、`?view=training`、`?view=settings`

## 参考资料

- **开源复用**: 见 `docs/open-source-fit-and-provider-strategy.md` §4
- **FSRS**: ts-fsrs / py-fsrs (MIT)
- **文件预览**: CodeMirror 6, react-pdf, MarkItDown, docx-preview (MIT/Apache)
- **UI 参考**: assistant-ui, Vercel AI Elements

---

*最后更新: 2026-06-15*