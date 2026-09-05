# Trainer UX 优化总结

**日期**: 2026-06-15
**版本**: v1.0.x

## 1. 已完成的改进

### 1.1 TrainingCardRenderer 全语言支持 (8种语言)

**文件**: `extension/webview/src/components/parts/TrainingCardRenderer.tsx`

**改进**:
- 从简单的 zh/en 二元翻译升级为完整的 8 语言支持系统
- 支持语言: `zh-CN`, `en-US`, `es-ES`, `fr-FR`, `de-DE`, `ja-JP`, `ko-KR`, `pt-BR`
- 使用模板变量系统支持复数和动态数值
- 所有 UI 标签完全本地化:
  - 卡片类型 (闪卡/练习卡)
  - 难度级别 (简单/中等/困难)
  - 提示阶梯 (提示可用数量、显示提示、已使用提示)
  - 证据提交 (提交证据、描述框、取消、提交并评分)
  - 评分按钮 (重试/困难/良好/简单)
  - FSRS 指标 (掌握度、R值、S值、D值、状态)
  - 时间信息 (到期、间隔、天数、来源)
  - 验证步骤
  - 完成后下一步、如果卡住、来源链

### 1.2 CSS 动画与微交互增强

**文件**: `extension/webview/src/styles.css`

**新增动画**:
- `fadeSlideIn`: 淡入+上移进入动画
- `scaleIn`: 缩放进入动画
- `shimmer`: 加载时的闪烁效果
- `typingBounce`: 打字指示器三点跳动
- `pulse`: 脉冲动画 (用于连胜指示器火焰图标)

**微交互**:
- `.hover-lift`: 悬停时轻微上浮+阴影效果
- 按钮按下时 `scale(0.97)` 反馈
- 卡片交错进入动画 (50ms 延迟递增)
- 消息气泡进入动画
- 滚动容器淡出边缘效果
- 聚焦状态 `focus-visible` 高亮

**Coach Conversation 增强**:
- 消息气泡入场动画
- 交错动画 (40ms 延迟递增)
- 流式消息状态指示器
- 平滑滚动行为

### 1.3 会话视图流畅度提升

**文件**: `extension/webview/src/components/coach/CoachConversationView.tsx`

**改进**:
- 自动滚动逻辑优化: 仅当用户在底部附近时自动滚动
- 用户发送消息时强制滚动到底部
- 平滑滚动行为 (`behavior: "smooth"`)
- `overscroll-behavior: contain` 防止滚动穿透

## 2. 架构改进

### 2.1 Typed Parts Registry 完整实现

**文件**: `shared/src/partsRendererRegistry.ts`

**支持的消息部分类型**:
| 类型 | 描述 | CSS 类 |
|------|------|--------|
| `markdown` | 富文本内容 | `.trainer-markdown` |
| `code` | 代码块 (含语言高亮) | `.trainer-code-block` |
| `diff` | 差异对比视图 | `.trainer-diff-block` |
| `math` | 数学公式 (KaTeX) | `.trainer-math` |
| `mermaid` | Mermaid 图表 | `.trainer-mermaid` |
| `table` | 表格数据 | `.trainer-table` |
| `citation` | 资源引用 | `.trainer-citation` |
| `tool_call` | 工具调用 | `.trainer-tool-call` |
| `tool_result` | 工具结果 | `.trainer-tool-result` |
| `reasoning` | 推理摘要 | `.trainer-reasoning` |
| `training_card` | 训练卡 | `.trainer-training-card` |
| `plan_update` | 计划更新 | `.trainer-plan-update` |
| `test_result` | 测试结果 | `.trainer-test-result` |
| `file_preview` | 文件预览 | `.trainer-file-preview` |
| `checklist` | 清单 | `.trainer-checklist` |
| `alert` | 警告提示 | `.trainer-alert` |

### 2.2 i18n 翻译系统

**文件**: `extension/webview/src/lib/i18n/copy.ts`

**翻译键覆盖范围**:
- 核心角色 (coach/trainer/you/plan/settings/chat/workspace)
- 视图标签 (currentFocus/currentTask/latestReview 等)
- 计划相关 (goals/constraints/acceptance/nextMove 等)
- 设置-界面 (language/answerMode/teachingStyle 等)
- 设置-Provider (provider/baseUrl/apiKey 等)
- 训练相关 (startTraining/markAgain/markHard/markGood/markEasy 等)
- 强化学习概念 (Q-learning/DQN/PPO/MCTS 等)
- 会话相关 (newConversation/regenerate/copyMessage 等)
- 快捷操作 (suggestedActions/generatePlan/runReview 等)

## 3. 体验优化亮点

### 3.1 首次使用体验
- 设置页面清晰的状态引导
- 阻塞状态明确提示需要配置项
- 就绪状态展示教练能力概述

### 3.2 训练卡片交互
- 渐进式提示揭示 (Hint Ladder)
- 证据提交与评分流程
- FSRS 指标可视化 (掌握度条、R值条)
- 项目交接提示

### 3.3 会话流畅度
- 消息入场动画不阻塞交互
- 流式输出时的视觉反馈
- 自动滚动智能判断
- 平滑的滚动体验

### 3.4 记忆层级可视化
- 分层展示 (Master/Project/Session/Resource/Review/Provider)
- 状态指示器 (活跃/轻量/空)
- 资源信号和教学资产展示
- 可注入训练卡指示

## 4. 技术实现细节

### 4.1 CSS 变量系统
```css
:root {
  --animation-duration-fast: 120ms;
  --animation-duration-normal: 200ms;
  --animation-duration-slow: 350ms;
  --animation-ease-out: cubic-bezier(0.25, 0.46, 0.45, 0.94);
  --animation-ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
}
```

### 4.2 主题系统
- 深色主题 (默认)
- 浅色主题
- 系统主题跟随

### 4.3 响应式断点
- `768px`: 双列网格
- `480px`: 单列堆叠

## 5. 下一步优化建议

### 5.1 高优先级
1. **Provider v2 配置系统**: 实现多 profile、多协议、多模型别名
2. **文件预览三层能力梯**: Tier A 富预览、Tier B 转换预览、Tier C metadata 兜底
3. **Workspace Authority**: 实现 activeWorkspaceRoot 和 folder sovereignty

### 5.2 中优先级
4. **搜索系统**: 升级为 SQLite FTS5 + metadata filter + optional rerank
5. **Memory 分层**: 完善 Master/Project/Session/Resource/Review 分层体系
6. **Remote Workspace**: 完善远程访问支持

### 5.3 低优先级
7. **更丰富的卡片类型**: Recall/Explain/Predict/Drill/Debug/Transfer/Review
8. **成就系统**: 展示学习里程碑和连胜记录
9. **数据分析**: 训练进度和能力提升可视化

## 6. 验证证据

```bash
npm run build  # ✓ built in 22.31s
npm run check  # TypeScript 检查通过
```

## 7. 参考文档

- [docs/open-source-fit-and-provider-strategy.md](./open-source-fit-and-provider-strategy.md)
- [docs/architecture.md](./architecture.md)
- FSRS 算法: `ts-fsrs` / `py-fsrs`
- UI 组件: `assistant-ui` / `Vercel AI Elements`
