# Trainer UX Enhancement Roadmap
**Generated**: 2025-06-15  
**Based on**: `docs/open-source-fit-and-provider-strategy.md`

## Recently Completed (2025-06-15)

### 1. Quick Actions Labels ✅
**File**: `extension/webview/src/components/composer/CoachComposer.tsx`
- Changed to more action-oriented labels
- "代码" → "看代码"
- "解释" → "解释原理"
- "计划" → "制定计划"
- "复习" → "回顾复习"

### 2. Composer Placeholder Text ✅
**File**: `extension/webview/src/app/AppRecovered.tsx`
- Changed to more guiding text
- "输入问题或任务，按 Enter 发送..." → "告诉我你现在卡在哪里，或者想学什么，按 Enter 发送"
- "输入你想实现的计划，按 Enter 生成..." → "描述你想实现的目标，按 Enter 生成计划"

### 3. Toast Notification System ✅
**File**: `extension/webview/src/components/Toast.tsx`
- Lightweight, non-intrusive notifications
- 4 levels: info, pass, warn, error
- Auto-dismiss with progress bar
- Convenience helpers: toastPass(), toastError(), toastWarn(), toastInfo()
- Context-based + global showToast()

### 4. CSS UX Enhancements ✅
**File**: `extension/webview/src/styles.css` (+~300 lines)
- FadeIn animation for empty states
- Pulse animation for empty state icons
- SlideInUp staggered animation for quick action buttons
- Hover lift effect for quick action buttons
- Hint ladder tier indicators with numbered badges
- Training card hover effects and active state styling
- Training progress bar styling
- Practice checkbox improvements
- Memory layer indicators
- File tree node improvements
- Settings section styling
- Provider status indicators
- Tab navigation styling
- Toast notification system styles
- Focus management improvements
- Keyboard shortcut hints on send button

### 5. Shortcut Hint Display ✅
**File**: `extension/webview/src/components/composer/CoachComposer.tsx`
- Shows keyboard shortcut hint on send button hover
- Localized labels

---

## Next Priority Improvements

### High Impact, Low Effort

#### 1. Missing Chinese Translations
**File**: `extension/webview/src/lib/i18n/copy.ts`
Check and fill missing zh-CN translations for:
- New provider features
- Training card actions
- Workspace authority labels
- Search result labels

#### 2. Empty State Illustrations
**File**: Various components
Add friendly empty states with guidance:
- Conversation: "问我一个问题，或者选择一个快速操作"
- Resources: "导入资料、链接或笔记，开始积累知识"
- Training: "根据你的学习目标，我会为你生成训练卡"
- Plan: "我们一起制定一个可执行的计划"

#### 3. Loading State Skeletons
**Files**: Various components
Add skeleton loaders for:
- Message loading
- Resource tree loading
- Training card loading
- Search results loading

### Medium Effort Improvements

#### 4. Keyboard Navigation
- Add keyboard shortcuts for main actions
- Tab navigation through panels
- Focus trap in modals
- Skip links for accessibility

#### 5. Responsive Design
- Mobile/tablet layout for web preview
- Collapsible sidebar on smaller screens
- Touch-friendly tap targets

#### 6. Search Result Enhancements
- Teaching signals (skill level, last practiced)
- "Inject to training card" toggle
- Recency weighting visualization

### Lower Priority (Future)

#### 7. Advanced Features
- react-arborist for file tree
- MarkItDown for universal conversion
- Video quick preview
- Semantic search enhancement

---

## Implementation Checklist

### Must Have
- [x] Quick actions labels improved
- [x] Composer placeholder text
- [x] Toast notification system
- [x] CSS animations and transitions
- [x] Keyboard shortcut hints
- [ ] Missing Chinese translations
- [ ] Empty state illustrations
- [ ] Loading skeletons

### Should Have
- [ ] Keyboard navigation
- [ ] Focus management polish
- [ ] Search result enhancements
- [ ] Training progress visualization

### Nice to Have
- [ ] react-arborist integration
- [ ] MarkItDown integration
- [ ] Video preview
- [ ] Responsive design

---

## Files Modified (2025-06-15)
- `extension/webview/src/app/AppRecovered.tsx`
- `extension/webview/src/components/composer/CoachComposer.tsx`
- `extension/webview/src/components/Toast.tsx` (new)
- `extension/webview/src/styles.css`

## Verification
- Typecheck: ✅ Passes
- Build: ✅ Succeeds

---

## Strategy Alignment

All UX improvements align with the strategy document's principles:

1. **Coach-first**: Quick actions guide students toward learning, not just answers
2. **Memory-rich**: Training and memory indicators help students understand their progress
3. **Resource-grounded**: Search improvements will make resources more accessible
4. **Training-native**: Training card UI enhancements support the training workflow
5. **Humanized**: Better empty states, loading states, and notifications reduce friction