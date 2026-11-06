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
写一篇"把主题讲明白"的讲稿，按状态流推进，而不是概念清单。

推进语法：当前状态 → 缺口 → 为补缺口构造对象 → 对象角色 → 与已有对象的关系 → 约束/公式 → 校验 → 新状态。
每段回答：已知什么？还缺什么？为补缺口必须引入什么？引入后状态怎么变？

必守：
1. 先讲旧办法的失败画面，再引入新对象；不要"先定义再解释"。
2. 对象是被需要出来的名字：说明它来自哪个缺口、删掉会丢失什么信息。
3. 变量/函数/API 首次出现交代来源、角色、缺它会坏在哪。
4. 公式晚出现：先有目标与约束，让听众能猜到大致形状；解释"为什么只能长这样"，不解释"表示什么"。
5. 非平凡推导展开 3-5 步，每步说明用了什么条件、消掉哪个缺口；禁止"代入即得"。
6. 每推进 2-3 个新对象，回收一次状态：已知、未知、目标、障碍。
7. 代码是理论的实现状态：先说维护什么状态，再说语法；每个函数回指对应数学对象/状态转换。
8. 至少给：1 个对比对象、1 个边界/失败情形、1 个最小可运行例子、1 个非直觉但关键的结论。
9. 连续散文口播，短句判断句，不列提纲、不用"第一部分"、不堆项目符号。
10. 禁用空话："显然""其实很简单""大家都知道"；每个判断都要给可检查的理由。
11. 收尾用很短一段回收整条链：现在已知什么，下一步验证什么。

自检（内部执行，不输出）：开头是否先状态后定义；对象是否被需要出来；公式是否晚出现且强解释；
推导是否消缺口；是否无废话；是否有对比/边界/最小例；代码是否后置回指；每段是否引出下一个缺口。
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
