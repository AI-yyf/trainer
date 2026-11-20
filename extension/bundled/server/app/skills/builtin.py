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
    }
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
