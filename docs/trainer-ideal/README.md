# Trainer 理想文档中心

这个文件夹是 Trainer 的理想态产品文档入口，不是运行时事实的唯一来源。这里放的是已经收敛后的长期目标说明，用来约束方向，而不是覆盖当前已发货契约。

## 文件夹职责

- `trainer-product-design-spec.md` 是最终版产品设计说明书。
- `assets/` 保存当前视图截图和设计证据，方便和正文对照。
- `output/doc/` 下的 `docx` 和 `pdf` 是渲染产物，不是新的需求来源。

## 使用规则

- 先看当前事实，再看理想态。已发货五视图契约和运行行为以 `docs/ui-contract.md`、`docs/architecture.md`、`docs/developer-workflows.md`、`docs/verification.md` 与当前实现/测试为准。
- 以后讨论 Trainer 的产品定义、视图职责、使用场景和验收口径，优先看这个文件夹。
- `docs/plans/2026-05-07-trainer-teaching-quality-closure-checklist.md` 与 `docs/verification/2026-05-09-trainer-closure-status-matrix.md` 仍然是事实来源，但它们是来源，不是日常阅读入口。
- 早期过渡稿、临时脚本、缓存、测试垃圾、资源叉文件都不应再参与产品判断。

## 这个文件夹解决什么问题

- 把五个一级视图的职责一次性说清楚。
- 把训练子视图、资源闭环、计划闭环、设置闭环统一到一个口径。
- 把“Trainer 是教练，不是代写器”这个边界固定下来。
- 把当前截图和理想态规范放在一起，避免只看代码或只看文档造成误判。

## 推荐阅读顺序

1. 先看 `trainer-product-design-spec.md` 的总览和产品定位。
2. 再看五个一级视图和训练子视图的详细章节。
3. 再看最后的场景闭环、文件夹设计和清理策略。
