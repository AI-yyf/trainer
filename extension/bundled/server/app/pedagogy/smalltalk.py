from __future__ import annotations

import re

_STRIP_EDGE_RE = re.compile(
    r"[\s`~!@#$%^&*()\-_=+\[\]{};:'\",.<>/?\\|，。！？、；：“”‘’（）【】《》~～·]+"
)

_CASUAL_GREETING_EXACT = frozenset(
    {
        "你好",
        "您好",
        "你好呀",
        "你好啊",
        "你好哦",
        "你好吗",
        "嗨",
        "哈喽",
        "哈罗",
        "早",
        "早安",
        "早上好",
        "上午好",
        "中午好",
        "下午好",
        "晚上好",
        "晚安",
        "在吗",
        "在不在",
        "谢谢",
        "多谢",
        "感谢",
        "谢谢你",
        "好的",
        "好",
        "嗯",
        "嗯嗯",
        "收到",
        "明白",
        "了解",
        "测试",
        "试试",
        "hi",
        "hello",
        "hey",
        "yo",
        "sup",
        "hi there",
        "hello there",
        "hey there",
        "hi trainer",
        "hello trainer",
        "hey trainer",
        "你好 trainer",
        "你好教练",
        "good morning",
        "good afternoon",
        "good evening",
        "thanks",
        "thank you",
        "thx",
        "ok",
        "okay",
        "got it",
        "ping",
        "test",
        "你是谁",
        "你叫什么",
        "你能做什么",
        "你是干嘛的",
        "who are you",
        "what can you do",
    }
)

_EXPLORATORY_OR_RESEARCH_TOKENS = (
    "讲解一下",
    "介绍一下",
    "讲讲这个",
    "讲一下这个",
    "看看这个项目",
    "看看这个文件夹",
    "解释一下这个项目",
    "解释一下这个文件夹",
    "整个项目",
    "项目结构",
    "目录结构",
    "仓库结构",
    "explain this project",
    "explain this repo",
    "explain this folder",
    "overview of this project",
    "what is this project",
    "walk me through",
    "研究进展",
    "最新进展",
    "前沿进展",
    "联网",
    "上网",
    "能联网",
    "可以联网",
    "联网搜索",
    "联网查",
    "能搜索",
    "可以搜索",
    "搜索功能",
    "在线搜索",
    "帮我查",
    "帮我找",
    "找找",
    "查一下",
    "搜一下",
    "搜索",
    "查找",
    "论文",
    "arxiv",
    "latest research",
    "research progress",
    "web search",
    "search online",
    "internet access",
    "can you search",
    "go online",
)

_RESCUE_OR_PATCH_TOKENS = (
    "stuck",
    "blocked",
    "frustrated",
    "error",
    "exception",
    "traceback",
    "fix",
    "patch",
    "bug",
    "报错",
    "卡住",
    "崩溃",
    "异常",
    "修复",
    "修一下",
    "打补丁",
    "补丁",
)


def _normalize_smalltalk_text(message: str) -> str:
    return _STRIP_EDGE_RE.sub(" ", str(message or "").strip().lower()).strip()


def is_casual_greeting_or_smalltalk(message: str) -> bool:
    """True only when the whole learner turn is casual greeting, ack, or smalltalk."""
    normalized = _normalize_smalltalk_text(message)
    return bool(normalized and normalized in _CASUAL_GREETING_EXACT)


def is_exploratory_or_research_query(message: str) -> bool:
    """True for project-tour / web-research queries that are not stuck-patch rescues."""
    raw = str(message or "").strip().lower()
    if not raw or any(token in raw for token in _RESCUE_OR_PATCH_TOKENS):
        return False
    return any(token in raw for token in _EXPLORATORY_OR_RESEARCH_TOKENS)


_BOGUS_SMALLTALK_STEP_PATTERNS = (
    re.compile(r"^先把\s+(.+?)\s+压成一个很小的补丁目标(?:[，,]?\s*再继续写[。.]?)?$"),
    re.compile(r"^先交付一个小而可复盘的\s+(.+?)\s+版本(?:[，,。.]|$)"),
    re.compile(r"^先找到\s+(.+?)\s+的第一处切口(?:[，,。.]|$)"),
    re.compile(r"^先用一句话重述\s+(.+?)\s+该表现成什么样[。.]?$"),
    re.compile(r"^先说出\s+(.+?)\s+的第一个可见行为(?:[，,。.]|$)"),
    re.compile(r"^围绕[「\"](.+?)[」\"]先做一个小动作"),
)


def is_bogus_smalltalk_step(text: str | None) -> bool:
    """True only when a learning step/task wraps a casual greeting instead of a technical topic."""
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return False
    for pattern in _BOGUS_SMALLTALK_STEP_PATTERNS:
        match = pattern.match(cleaned)
        if match and is_casual_greeting_or_smalltalk(match.group(1)):
            return True
    return False
