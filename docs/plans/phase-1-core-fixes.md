# Trainer 实施子计划 - 阶段 1: 核心修复

版本：v1.0  
创建时间：2026-06-18  
前置条件：完成主计划阅读

## 当前状态

### 已完成 ✅
1. i18n 系统 - 已识别并修复 `streakMessage` 重复键
2. TypeScript 编译 - 通过
3. Webview 构建 - 成功
4. Training 视图 - 2651 行完整实现
5. CoachConversationView - 完整实现
6. CoachPlanView - 完整实现

### 已识别问题 ⚠️

#### 问题 1: App.tsx 过大 (6948 行)
**现状**: App.tsx 是单一巨型文件
**影响**: 维护困难，模块边界不清晰
**建议**: 按视图拆分组件，提取常量

#### 问题 2: i18n 翻译缺失
**现状**: 部分语言缺少部分翻译键
- es-ES: 缺少 `streakMessage` 相关键
- fr-FR, de-DE, ja-JP, ko-KR, pt-BR: 缺少大量 `settings*` 键

**影响**: 非首选语言可能显示不完整
**建议**: 补充缺失翻译或完善回退机制

#### 问题 3: 样式文件过大 (13812 行)
**现状**: styles.css 包含所有样式
**影响**: 维护困难
**建议**: 按组件拆分 CSS

## 立即行动项

### 行动 1: 验证 App.tsx 中的翻译回退

检查 App.tsx 是否有内联翻译（应该全部使用 copy.ts）：

```bash
# 搜索 App.tsx 中的硬编码中文
grep -n "教练\|对话\|设置" extension/webview/src/app/App.tsx | head -20
```

### 行动 2: 检查 shared/src 中的翻译

```bash
# 检查 shared/src 中是否有独立的翻译管理
ls -la shared/src/
```

### 行动 3: 验证 Training 视图的激励系统

Training 视图已包含：
- `getHumanizedMetrics()` - 人性化指标
- `calculateStreak()` - 连胜计算
- `getNextActionHint()` - 下一步提示
- `renderLearningJourney()` - 学习旅程渲染

需要验证这些功能是否与 copy.ts 正确集成。

## 下一阶段任务

### 阶段 2: 模块化重构

1. **拆分 App.tsx**
   - 提取视图组件到独立文件
   - 提取常量到 `lib/constants.ts`
   - 提取内联函数到 `lib/helpers.ts`

2. **拆分 styles.css**
   - 提取 `training.css`
   - 提取 `settings.css`
   - 提取 `coach.css`

3. **完善 i18n**
   - 补充缺失翻译
   - 或确保回退机制完善

## 验证清单

- [x] TypeScript 编译通过
- [x] Webview 构建成功
- [ ] App.tsx 模块化完成
- [ ] styles.css 拆分完成
- [ ] i18n 翻译完整

## 依赖关系

```
阶段 1 (核心修复)
    ↓
阶段 2 (模块化重构)
    ↓
阶段 3 (Workspace Authority)
    ↓
阶段 4 (File Preview)
```
