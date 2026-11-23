"""Built-in first-party skills (v1.5).

`rethinkfun-lecture` internalizes the user's RethinkFun state-flow lecture
method (source: the user's private `/skill/rethinkfun/rethinkfun-lecture`
SKILL.md + `references/intuition-lecture-prompt.md` + `theory-rebuilder-
prompt.md`): concepts are constructed because needed, formulas appear late
and answer "why can it only look like this", derivations eliminate gaps,
code is the implementation state of theory objects, and every lecture keeps a
known/unknown/goal/obstacle state recycled every 2-3 objects.

The body is a distilled contract kept ≤ MAX_SKILL_BODY_CHARS so the runtime
skill-selection path can inject it verbatim. Builtin tutor skills are
first-party, read-only, contain no executable content, and are seeded as
reviewed+active — they never expand tool authority.
"""

from __future__ import annotations

from typing import Any

RETHINKFUN_LECTURE_BODY = """\
写一篇"把主题讲明白"的讲稿，按状态流重建理论，而不是概念清单。

推进语法：当前状态 → 缺口 → 构造对象 → 对象角色 → 对象关系 → 约束/公式 → 校验 → 新状态。
讲解单位是命题（命题 → 证明/消缺口 → 结论 → 新命题）。每句话只干五件事之一：现象、问题、原因、推理、结论，否则删除。

必守：
1. 先讲旧办法失败画面，再构造新对象；不要先定义再解释。
2. 变量/函数/API 首次出现交代来源、角色、与已有对象关系、删掉会坏在哪。
3. 公式晚出现：先有目标与约束，让听众能猜到大致形状；解释"为什么只能长这样"。
4. 非平凡推导展开 3-5 步，每步说明用了什么条件、消掉哪个缺口；禁止"代入即得"。
5. 每推进 2-3 个新对象，回收一次状态：已知、未知、目标、障碍。
6. 代码后置且作为理论实现状态：先说维护什么状态、输入输出与不变量，再逐项回指理论并标出失败点。
7. 至少含：1 个对比对象、1 个边界/失败情形、1 个最小可运行例子、1 个非直觉关键结论。
8. 连续短句散文口播，不堆提纲/百科条目。禁用空话垫词："显然""其实很简单""大家都知道""换句话说""接下来我们来看一下""非常巧妙""希望对你有帮助"。
9. 终极四感检验：学完能回答解决什么问题、为何只能如此设计、变量从哪来、即使忘了公式或代码也能靠约束重新推出来。

内部自检（不输出）：开头是否先状态后定义；对象是否被需要出来；公式是否晚出且可预判；推导是否消缺口；是否零垫词；是否有对比/边界/最小例/认知回收；代码是否后置回指。不达标先重写再输出。
"""

BUILTIN_TUTOR_SKILLS: list[dict[str, Any]] = [
    {
        "skill_id": "rethinkfun-lecture",
        "kind": "tutor",
        "name": "RethinkFun 讲解法",
        "description": (
            "把技术主题讲成一条连续理解链：状态流推进、缺口驱动、公式晚出现、代码后置回指。"
            "Use for deep explanations, 讲明白/讲透/好好讲 requests, lectures and study notes."
        ),
        "triggers": [
            "讲明白",
            "讲透",
            "好好讲",
            "彻底讲",
            "深度讲解",
            "给我讲讲",
            "讲解一下",
            "lecture",
            "state flow",
            "讲稿",
        ],
        "body": RETHINKFUN_LECTURE_BODY,
        "evidence_markers": ["缺口", "失败", "旧方案", "为什么", "状态"],
        "origin_note": "internalized from user-provided rethinkfun-lecture skill",
    },
    {
        "skill_id": "visual-image-generator",
        "kind": "action",
        "name": "教学配图生成",
        "description": (
            "为复杂架构、状态流、矩阵维度、注意力机制与概率直觉生成清晰教学配图（矢量架构图、示意图或概念插画），并内嵌到回复中。"
            "Use for 画图/配图/示意图/架构图/流程图/visualize/diagram/generate image requests."
        ),
        "triggers": [
            "画图",
            "配图",
            "画张图",
            "生成图片",
            "生图",
            "示意图",
            "架构图",
            "流程图",
            "状态图",
            "可视化图",
            "diagram",
            "flowchart",
            "generate image",
            "draw",
            "visualize",
            "illustration",
        ],
        "body": (
            "你现在拥有原生生图工具 `generate_image`，不要只用纯文字描述或粗糙 ASCII 画图来敷衍。\n"
            "1. 先提炼 3-6 个核心实体、状态流方向、张量形状或因果关系，写清结构化英文/中文视觉描述作为 prompt。\n"
            "2. 对机制图、架构图、流程图、梯度流与几何直觉优先选 `style=\"diagram\"` 或 `\"illustration\"`；明确要照片级真实材质时选 `style=\"photorealistic\"`。\n"
            "3. 拿到工具返回的 `markdown`（形如 `![标题](trainer-image://img_...)`）后，原样保留到正式回答的合适位置，再用紧凑文字对照图中节点讲解。\n"
            "4. 禁止伪造本地文件路径或不存在的外链图片地址。"
        ),
        "evidence_markers": ["trainer-image://", "generate_image"],
        "origin_note": "builtin visual generation skill",
    },
    {
        "skill_id": "deep-web-research",
        "kind": "knowledge",
        "name": "联网查证与论文检索",
        "description": (
            "围绕最新版本、官方文档、论文与开源仓库联网检索、抓取原文、交叉核对并给出可引用出处。"
            "Use for 联网搜索/查最新/找论文/arxiv/官方文档/search/latest/docs requests."
        ),
        "triggers": [
            "联网",
            "搜一下",
            "网上查",
            "找论文",
            "搜论文",
            "查论文",
            "arxiv",
            "官方文档",
            "最新版本",
            "release notes",
            "search web",
            "latest docs",
            "find paper",
        ],
        "body": (
            "当问题涉及最新框架变化、论文公式细节、官方 API 或跨源对比时：\n"
            "1. 需要论文/前沿研究时先调 `search_academic_papers`，一般网页与文档先调 `web_search`（不要只凭记忆猜版本号）。\n"
            "2. 对命中的核心 URL 调 `fetch_web_page` 读取一手细节，确需长期沉淀进资料库时可用 `import_resource_url` 入库。\n"
            "3. 回答必须区分「一手来源已核实」与「推理/待验证」，附上实际打开过的标题与链接。"
        ),
        "evidence_markers": ["web_search", "search_academic_papers", "fetch_web_page"],
        "origin_note": "builtin web and paper verification skill",
    },
    {
        "skill_id": "library-curator",
        "kind": "action",
        "name": "资料库整理与归档",
        "description": (
            "围绕用户本地与在线学习资料执行目录梳理、建文件夹、重命名分组、归类移动与去重整理，并严格保持提案确认护栏。"
            "Use for 整理资料/新建文件夹/资料归档/资料分类/organize resources/curate library requests."
        ),
        "triggers": [
            "整理资料",
            "整理一下资料",
            "资料归档",
            "资料分类",
            "新建文件夹",
            "建个文件夹",
            "重命名文件夹",
            "资料整理",
            "organize resources",
            "organize library",
            "curate library",
        ],
        "body": (
            "整理资料库前必须先看清现状，禁止盲改用户编码仓库：\n"
            "1. 先调用 `list_library_folders` 与 `list_resources` 掌握现有文件夹与资源归属。\n"
            "2. 若只是创建/重命名空文件夹或把少量指定资料放入指定目录，调用 `curate_library_resources`（保持所有操作严格在 Trainer `<LibraryRoot>` 内）。\n"
            "3. 若要批量重构整套资料目录与多份文档归属，调用 `organize_resources` 生成结构化整理提案，让学习者先预览再确认。"
        ),
        "evidence_markers": ["list_library_folders", "curate_library_resources", "organize_resources"],
        "origin_note": "builtin library curation skill",
    },
]


def builtin_front_matter(skill: dict[str, Any]) -> dict[str, str]:
    """Front matter shaped exactly like a parsed SKILL.md, for trigger matching."""

    front = {
        "name": str(skill["skill_id"]),
        "description": str(skill.get("description") or ""),
        "triggers": ", ".join(str(term) for term in skill.get("triggers") or []),
    }
    if skill.get("evidence_markers"):
        front["evidence_markers"] = ", ".join(str(m) for m in skill["evidence_markers"])
    return front
