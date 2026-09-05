from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LearningFamily = Literal["code", "theory"]
LearningSubtype = Literal[
    "remote",
    "debug",
    "function",
    "implementation",
    "derivation",
    "writing",
    "memorization",
    "reading",
    "concept",
]


@dataclass(frozen=True)
class LearningSubject:
    family: LearningFamily
    subtype: LearningSubtype

    @property
    def is_code(self) -> bool:
        return self.family == "code"

    @property
    def is_theory(self) -> bool:
        return self.family == "theory"


_REMOTE_MARKERS = (
    "remote ssh",
    "remote workspace",
    "remote tunnel",
    "remote tunnels",
    "dev container",
    "devcontainer",
    "wsl",
    "ssh",
    "port forwarding",
    "port forward",
    "tunnel",
    "credential mode",
    "host label",
    "workspace boundary",
    "远程",
    "工作区边界",
)

_DEBUG_MARKERS = (
    "debug loop",
    "debugger",
    "debug",
    "breakpoint",
    "launch.json",
    "stack frame",
    "stack trace",
    "traceback",
    "watch expression",
    "step into",
    "step over",
    "exception filter",
    "变量",
    "调试",
    "断点",
    "调用栈",
    "堆栈",
)

_FUNCTION_MARKERS = (
    "function guidance",
    "signature help",
    "call site",
    "hover",
    "go to definition",
    "definition",
    "parameter hint",
    "function contract",
    "type hint",
    "intellisense",
    "函数提示",
    "签名提示",
    "调用点",
    "定义跳转",
    "函数契约",
)

_CODE_MARKERS = (
    "api",
    "protocol",
    "repo",
    "repository",
    "workspace",
    "endpoint",
    "schema",
    "python",
    "typescript",
    "javascript",
    "java",
    "rust",
    "golang",
    "sql",
    "json",
    "yaml",
    "git",
    "patch",
    "refactor",
    "bug",
    "test case",
    "pytest",
    "fastapi",
    "code change",
    "engineering practice",
    "engineering workflow",
    "event stream",
    "eventsource",
    "implementation",
    "server sent events",
    "server-sent event",
    "server-sent events",
    "streaming response",
    "工程实践",
    "工程实现",
    "流式响应",
    "code",
    "代码",
    "文件",
    "接口",
    "函数",
)

_DERIVATION_MARKERS = (
    "math",
    "algebra",
    "geometry",
    "calculus",
    "equation",
    "integral",
    "derivative",
    "matrix",
    "probability",
    "statistics",
    "proof",
    "theorem",
    "derive",
    "derivation",
    "physics",
    "推导",
    "证明",
    "方程",
    "导数",
    "积分",
    "矩阵",
    "概率",
    "统计",
    "物理",
    "数学",
    "定理",
)

_WRITING_MARKERS = (
    "writing",
    "email",
    "essay",
    "paragraph",
    "sentence",
    "tone",
    "rewrite",
    "revise",
    "grammar",
    "translation",
    "vocabulary",
    "word choice",
    "opening",
    "closing",
    "summary sentence",
    "英语写作",
    "英文写作",
    "写作",
    "改写",
    "润色",
    "语气",
    "语法",
    "翻译",
    "词汇",
    "单词",
    "句子",
    "段落",
    "作文",
)

_MEMORIZATION_MARKERS = (
    "memorize",
    "memorization",
    "recall",
    "spaced repetition",
    "flash card",
    "flashcard",
    "closed-book",
    "facts",
    "terms",
    "anatomy",
    "medicine",
    "medical",
    "politics",
    "history dates",
    "背记",
    "背诵",
    "记忆",
    "默写",
    "回忆",
    "术语",
    "医学",
    "病理",
    "政治",
    "考点",
)

_READING_MARKERS = (
    "book",
    "novel",
    "chapter",
    "passage",
    "excerpt",
    "quote",
    "theme",
    "character",
    "plot",
    "article",
    "paper",
    "reading comprehension",
    "poem",
    "literature",
    "阅读",
    "阅读理解",
    "书",
    "文章",
    "论文",
    "章节",
    "片段",
    "引文",
    "主题",
    "人物",
    "情节",
    "古诗",
)


def build_subject_blob(*parts: object) -> str:
    return " ".join(
        str(part).strip().lower()
        for part in parts
        if isinstance(part, str) and part.strip()
    )


def _has_exact_token(blob: str, token: str) -> bool:
    return f" {token} " in f" {blob} "


def classify_learning_subject(*parts: object) -> LearningSubject:
    blob = build_subject_blob(*parts)
    if not blob:
        return LearningSubject("theory", "concept")

    if _has_exact_token(blob, "sse"):
        return LearningSubject("code", "implementation")
    if any(marker in blob for marker in _REMOTE_MARKERS):
        return LearningSubject("code", "remote")
    if any(marker in blob for marker in _DEBUG_MARKERS):
        return LearningSubject("code", "debug")
    if any(marker in blob for marker in _FUNCTION_MARKERS):
        return LearningSubject("code", "function")
    if any(marker in blob for marker in _CODE_MARKERS):
        return LearningSubject("code", "implementation")
    if any(marker in blob for marker in _DERIVATION_MARKERS):
        return LearningSubject("theory", "derivation")
    if any(marker in blob for marker in _WRITING_MARKERS):
        return LearningSubject("theory", "writing")
    if any(marker in blob for marker in _MEMORIZATION_MARKERS):
        return LearningSubject("theory", "memorization")
    if any(marker in blob for marker in _READING_MARKERS):
        return LearningSubject("theory", "reading")
    return LearningSubject("theory", "concept")
