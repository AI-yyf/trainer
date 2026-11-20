"""Ground Research Brief citations in versioned passages from the library."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..core.models import AssetSourceReference, ResourceRecord
from .service import _resolve_document_location

PASSAGE_LENGTH = 1800
PASSAGES_PER_RESOURCE = 3
PAGE_MENTION = re.compile(r"\bpage\s+(\d{1,5})\b|第\s*(\d{1,5})\s*页", re.IGNORECASE)
_PREPARATION_REQUEST = re.compile(
    r"(?:请(?:帮我)?|帮我|协助我)(?:完成|做好|做一次)?备课|"
    r"(?:请|帮我|请帮我)?(?:为|围绕)[^。！？\n]{1,90}(?:备课|准备(?:完整)?教学材料)|"
    r"\b(?:prepare|draft|create|help me (?:prepare|plan)) (?:a |the |my )?(?:lesson\b|teaching materials\b|research brief\b|lesson prep\b)|"
    r"\bprepara(?:r)? (?:una |la )?(?:clase|lección|material didáctico)\b|"
    r"\bprépare(?:r|z)? (?:un |le |une |la )?(?:cours|leçon|support pédagogique)\b|"
    r"\b(?:erstelle|bereite)\b[^.!?\n]{0,65}\b(?:unterricht|lehrmaterial)\b|"
    r"(?:授業|教材)を準備(?:して|してください)|(?:수업|교재)(?:을|를)?\s*준비해|"
    r"\b(?:prepare|preparar) (?:uma |a )?(?:aula|material didático)\b",
    re.IGNORECASE,
)
_PREPARATION_NEGATION = re.compile(
    r"(?:不要|不用|无需|别|如何|怎么)(?:帮我|完成)?备课|"
    r"\b(?:don't|do not|how (?:do i|to)) (?:prepare|draft|create)\b",
    re.IGNORECASE,
)


def preparation_requested(message: str) -> bool:
    """Recognize learner instructions, excluding quoted browser material."""
    text = "\n".join(line for line in message.splitlines() if not line.lstrip().startswith(">"))
    text = re.sub(r"[「『“\"][^\n]*?[」』”\"]|`[^`\n]+`", "", text)
    return not _PREPARATION_NEGATION.search(text) and bool(_PREPARATION_REQUEST.search(text))


def preparation_for_active_stage(message: str) -> bool:
    return preparation_requested(message) and bool(re.search(
        r"当前(?:的)?(?:学习)?阶段|\b(?:current|active) (?:learning )?stage\b|etapa actual|étape actuelle|"
        r"aktuell\w* (?:lern)?phase|現在の(?:学習)?段階|현재(?:의)? (?:학습 )?단계|etapa atual",
        message, re.IGNORECASE,
    ))


@dataclass(frozen=True, slots=True)
class BriefPassage:
    resource: ResourceRecord
    text: str
    first_line: int
    anchors: list[dict[str, Any]]

    def locate(self, quote: str, *, expected_line: int | None = None) -> AssetSourceReference | None:
        """Resolve a verbatim quote, allowing whitespace from copy/paste or extraction."""
        words = quote.split()
        if not 12 <= len(" ".join(words)) <= 500:
            return None
        matches = re.finditer(r"\s+".join(re.escape(word) for word in words), self.text)
        found: tuple[re.Match[str], int] | None = None
        for match in matches:
            start = self.first_line + self.text.count("\n", 0, match.start())
            if expected_line is not None and start != expected_line:
                continue
            if found is not None:
                return None
            found = (match, start)
        if found is None:
            return None
        match, start = found
        return self.reference(match.group(), start)

    def reference(self, excerpt: str, start: int) -> AssetSourceReference:
        location = _resolve_document_location(self.anchors, start)
        location["line_start"] = start
        location["line_end"] = start + excerpt.count("\n")
        location.setdefault("anchor_id", f"¶line@{start}")
        return AssetSourceReference(
            kind="resource",
            ref=self.resource.id,
            label=self.resource.name,
            metadata={
                "resource_id": self.resource.id,
                "version_id": self.resource.version_id,
                "content_hash": self.resource.content_hash,
                "location": location,
                "excerpt": excerpt,
            },
        )


def brief_passages(
    source: BriefPassage, query: str, *,
    passage_length: int = PASSAGE_LENGTH, limit: int = PASSAGES_PER_RESOURCE,
    use_page_hint: bool = True,
) -> list[BriefPassage]:
    """Pick a bounded set of original passages, favoring the research question."""
    terms = set(re.findall(r"[a-z0-9]{3,}|[\u3400-\u9fff]{2}", query.casefold()[:12_400]))
    section = (_requested_page(source, query) if use_page_hint else None) or source
    ranked: list[tuple[int, BriefPassage]] = []
    position = 0
    first_line = section.first_line
    while position < len(section.text):
        end = min(position + passage_length, len(section.text))
        if end < len(section.text):
            boundary = section.text.rfind("\n", position + passage_length // 2, end)
            if boundary >= 0:
                end = boundary + 1
        text = section.text[position:end]
        folded = text.casefold()
        score = sum(term in folded for term in terms)
        ranked.append((score, BriefPassage(source.resource, text, first_line, source.anchors)))
        first_line += text.count("\n")
        position = end
    featured = sorted(ranked, key=lambda entry: -entry[0])[:limit]
    return sorted((passage for _, passage in featured), key=lambda passage: passage.first_line)


def _requested_page(source: BriefPassage, query: str) -> BriefPassage | None:
    mentioned_pages = {int(first or second) for first, second in PAGE_MENTION.findall(query)}
    if len(mentioned_pages) != 1:
        return None
    pages = [
        (anchor.get("index"), anchor["line"])
        for anchor in source.anchors
        if anchor.get("kind") == "page" and type(anchor.get("line")) is int
    ]
    for position, (page, line) in enumerate(pages):
        if page not in mentioned_pages or line < source.first_line:
            continue
        lines = source.text.splitlines(keepends=True)
        start = line - source.first_line
        end = pages[position + 1][1] - source.first_line if position + 1 < len(pages) else len(lines)
        return BriefPassage(source.resource, "".join(lines[start:end]), line, source.anchors)
    return None
