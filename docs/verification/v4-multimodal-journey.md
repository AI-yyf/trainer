# V4 多模态旅程 — 真实模型读取图表（2026-11-09）

**结论：PASS（真实 Provider + 真实图片附件）**

- Provider：`https://linksub.fun` / `deepseek-v4.1-flash`
- 图片：本地生成的 720×420 柱状图，Alpha=30、Beta=70
- 传输：`/session/message` 的 `attachments[]` base64 PNG
- 原始产物：`docs/verification/v4-multimodal-journey.json`
- 脚本：`scripts/record-v4-multimodal-journey.py`
- Key 仅通过 `TRAINER_TEST_API_KEY` 注入

## 结果

问题：

> 看这张柱状图：哪个队列的吞吐更高？只回答柱子标签。

真实回复：

> **Beta**（70）

| 断言 | 结果 |
| --- | --- |
| 识别较高的柱子 Beta | ✅ |
| 给出比较值 70 | ✅ |

## 边界

- 这是合成图表，不是真实扫描页/复杂图表；扫描 PDF 的本地 OCR 另见 `app/resources/ocr.py` 测试。
- 只验证一次真实视觉回合，不覆盖所有图像类型。
