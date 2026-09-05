"""Card generation service with LLM-backed content generation.

Generates TrainingCardCandidateSnapshot instances from different sources:
conversation_gap, plan_requirement, resource_knowledge, practice_feedback,
dependency_mastery, review_due.

Each source method attempts LLM generation first. On failure, it falls back
to a deterministic template.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from importlib.resources import files as resource_files
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from ..core.models import (
    CardGenerationContext,
    DependencyUsageEvidence,
    ResourceKnowledgeEvidence,
    TrainingCardCandidateSnapshot,
    TrainingCardCreatedFrom,
    TrainingCardTrustState,
    TrainingCardType,
)
from ..pedagogy.evidence_controls import PedagogyControls, apply_controls_to_card
from .subject_taxonomy import build_subject_blob, classify_learning_subject

try:
    from ..llm.prompts import CARD_FLASH_SYSTEM, CARD_PRACTICE_SYSTEM
except ImportError:
    CARD_PRACTICE_SYSTEM = (
        "Create one grounded practice card.\n"
        "Focus area: {focus_area}\n"
        "Target skill: {target_skill}\n"
        "Context: {context_hint}\n"
        "Source: {source}\n"
    )
    CARD_FLASH_SYSTEM = (
        "Create one grounded flash card.\n"
        "Focus area: {focus_area}\n"
        "Target skill: {target_skill}\n"
        "Context: {context_hint}\n"
        "Source: {source}\n"
    )

if TYPE_CHECKING:
    from ..core.event_ledger import EventLedgerService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CardGenerationStreamEvent:
    """One visible provider chunk or the completed generated card."""

    chunk: str | None = None
    card: TrainingCardCandidateSnapshot | None = None


class CardGenerationProviderFailure(RuntimeError):
    """A live provider did not produce a valid card; do not persist a template."""

    def __init__(self, reason: str, *, response_language: str | None = None) -> None:
        self.reason = str(reason or "invalid_card")
        self.detail = _localized_text(
            "The model-authored card was not accepted; retry generation to obtain a model card.",
            "模型生成的卡片未被接受；可以重试以获取模型卡片。",
            response_language,
        )
        super().__init__(self.detail)


class CardGenerationStreamError(RuntimeError):
    """A provider stream ended before a card could be validated.

    The route layer must surface this as a recoverable stream error.  In
    particular, this exception is intentionally distinct from malformed model
    JSON: an interrupted provider stream must never be converted into a
    deterministic card that looks like a completed model turn.
    """

    code = "card_generation_stream_interrupted"
    recoverable = True
    retryable = True
    provider_error_category = "stream_interrupted"
    provider_retryable = True

    def __init__(self, source: str, *, reason: str = "provider_stream_interrupted") -> None:
        self.source = source
        self.reason = reason
        detail = (
            f"{self.code}: source={source}; reason={reason}; "
            "recoverable=true; retryable=true"
        )
        self.safe_detail = detail
        super().__init__(detail)


def _apply_context_pedagogy_controls(
    card: TrainingCardCandidateSnapshot,
    context: CardGenerationContext,
) -> TrainingCardCandidateSnapshot:
    difficulty = str(context.difficulty or card.difficulty or "medium").strip().lower()
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = "medium"
    hint_count = context.hint_count
    if hint_count is None:
        hint_count = 3 if difficulty == "easy" else 1 if difficulty == "hard" else 2
    code_reveal = str(context.code_reveal or "").strip().lower()
    if code_reveal not in {"full", "scaffold", "withhold"}:
        code_reveal = "full" if difficulty == "easy" else "withhold" if difficulty == "hard" else "scaffold"
    practice_type = str(context.practice_type or "").strip().lower()
    if practice_type not in {"recover", "focused", "stretch"}:
        practice_type = "recover" if difficulty == "easy" else "stretch" if difficulty == "hard" else "focused"
    review_frequency = str(context.review_frequency or "").strip().lower()
    if review_frequency not in {"sooner", "normal", "later"}:
        review_frequency = "sooner" if difficulty == "easy" else "later" if difficulty == "hard" else "normal"
    material = str(context.material_recommendation or "").strip().lower()
    if material not in {"simpler", "current", "transfer"}:
        material = "simpler" if difficulty == "easy" else "current"
    next_step = str(context.next_plan_step or "").strip().lower()
    if next_step not in {"shrink", "hold", "widen"}:
        next_step = "shrink" if difficulty == "easy" else "widen" if difficulty == "hard" else "hold"
    should_reveal = context.should_reveal_code
    if should_reveal is None:
        should_reveal = code_reveal == "full"
    pedagogy_mode = str(context.pedagogy_mode or "").strip().lower()
    if pedagogy_mode not in {"socratic", "direct", "debug_guide"}:
        pedagogy_mode = "debug_guide" if difficulty == "easy" else "socratic" if difficulty == "hard" else "direct"
    controls = PedagogyControls(
        difficulty=difficulty,
        hint_count=max(1, min(5, int(hint_count))),
        explanation_depth="rebuild" if difficulty == "easy" else "grounded",
        code_reveal=code_reveal,
        practice_type=practice_type,
        review_frequency=review_frequency,
        material_recommendation=material,
        next_plan_step=next_step,
        should_reveal_code=bool(should_reveal),
        challenge_level="lower" if difficulty == "easy" else "raise" if difficulty == "hard" else "steady",
        hint_depth="direct" if difficulty == "easy" else "lighter" if difficulty == "hard" else "guided",
        review_urgency="high" if review_frequency == "sooner" else "low" if review_frequency == "later" else "normal",
        next_step_bias="shrink" if next_step == "shrink" else "widen" if next_step == "widen" else "steady",
        pedagogy_mode=pedagogy_mode,
    )
    return apply_controls_to_card(card, controls, language=context.response_language)


# Keep the name discoverable to callers that use the more explicit wording.
CardGenerationStreamInterrupted = CardGenerationStreamError

# Map the public source names used in the API to the TrainingCardCreatedFrom literals.
_SOURCE_MAP: dict[str, TrainingCardCreatedFrom] = {
    "conversation_gap": "conversation",
    "plan_requirement": "plan",
    "resource_knowledge": "resource",
    "practice_feedback": "practice_feedback",
    "dependency_mastery": "dependency_mastery",
    "review_due": "review_due",
}

# Deterministic cards must honor the learner's selected language even when an
# LLM is unavailable. Technical terms and user-provided topic names may stay
# in English, but the instructional contract around them must not silently
# fall back to English.
_EXPLICIT_CARD_FALLBACK_COPY: dict[str, dict[str, str]] = {
    "es-ES": {
        "practice_title": "Práctica: {topic}",
        "flash_title": "Tarjeta: {topic}",
        "why_now": "Esta tarjeta refuerza el siguiente paso antes de ampliar el tema.",
        "scenario": "Trabaja una parte pequeña y verificable de {topic}.",
        "problem": "Explica una regla, un ejemplo o un límite concreto de {topic}.",
        "action": "Aprende primero; después escribe una respuesta breve con una evidencia concreta.",
        "deliverable": "Una explicación breve de {topic} y una evidencia que la respalde.",
        "self_1": "¿La respuesta se mantiene en un alcance pequeño?",
        "self_2": "¿Puedes señalar una evidencia concreta en lugar de una suposición?",
        "validation": "Contrasta la respuesta con una fuente, un ejemplo o un resultado comprobable.",
        "rubric_1": "La explicación se mantiene precisa y acotada.",
        "rubric_2": "La evidencia comprueba la afirmación sin adivinar.",
        "deliverable_1": "La explicación o el resultado breve.",
        "deliverable_2": "Una frase que diga qué demuestra la evidencia.",
        "verify_1": "Comprueba la regla o el ejemplo exacto usado.",
        "verify_2": "Explica por qué esa evidencia respalda la respuesta.",
        "success": "Puedes explicar {topic} y respaldarlo con una evidencia concreta.",
        "stuck": "Reduce la respuesta a una regla y una evidencia.",
        "reflect": "¿Qué evidencia hizo que esta idea quedara clara?",
        "return": "Vuelve con tu respuesta, la comprobación y una breve reflexión.",
        "next": "Regresa con el resultado verificado y decide el siguiente paso.",
        "question": "¿Cuál es la explicación más pequeña y precisa de {topic}?",
        "flash_context": "Recupera la idea de memoria antes de revisar el material.",
        "expected": "Una explicación concisa de {topic}, con un ejemplo o un límite.",
        "hint_1": "Empieza por la definición o regla central.",
        "hint_2": "Añade un ejemplo, una condición límite o una aplicación.",
        "mistake": "Dar una definición vaga sin evidencia ni límite.",
        "correct": "Bien. La explicación tiene una base comprobable.",
        "incorrect": "Vuelve a la regla más pequeña y añade una evidencia concreta.",
    },
    "fr-FR": {
        "practice_title": "Exercice : {topic}",
        "flash_title": "Carte : {topic}",
        "why_now": "Cette carte consolide la prochaine étape avant d'élargir le sujet.",
        "scenario": "Travaillez une partie petite et vérifiable de {topic}.",
        "problem": "Expliquez une règle, un exemple ou une limite concrète de {topic}.",
        "action": "Apprenez d'abord, puis rédigez une réponse courte avec une preuve concrète.",
        "deliverable": "Une courte explication de {topic} accompagnée d'une preuve.",
        "self_1": "La réponse reste-t-elle dans un périmètre réduit ?",
        "self_2": "Pouvez-vous montrer une preuve concrète plutôt qu'une supposition ?",
        "validation": "Vérifiez la réponse avec une source, un exemple ou un résultat contrôlable.",
        "rubric_1": "L'explication reste précise et limitée.",
        "rubric_2": "La preuve valide l'affirmation sans deviner.",
        "deliverable_1": "La courte explication ou le résultat.",
        "deliverable_2": "Une phrase indiquant ce que la preuve établit.",
        "verify_1": "Vérifiez la règle ou l'exemple exact utilisé.",
        "verify_2": "Expliquez pourquoi cette preuve soutient la réponse.",
        "success": "Vous pouvez expliquer {topic} et le relier à une preuve concrète.",
        "stuck": "Réduisez la réponse à une règle et une preuve.",
        "reflect": "Quelle preuve a rendu cette idée claire ?",
        "return": "Revenez avec votre réponse, la vérification et une brève réflexion.",
        "next": "Revenez avec le résultat vérifié, puis choisissez la suite.",
        "question": "Quelle est l'explication la plus petite et la plus exacte de {topic} ?",
        "flash_context": "Rappelez-vous l'idée avant de rouvrir le matériel.",
        "expected": "Une explication concise de {topic}, avec un exemple ou une limite.",
        "hint_1": "Commencez par la définition ou la règle centrale.",
        "hint_2": "Ajoutez un exemple, une condition limite ou un usage.",
        "mistake": "Donner une définition vague sans preuve ni limite.",
        "correct": "Bien. L'explication est appuyée par une preuve vérifiable.",
        "incorrect": "Revenez à la règle la plus simple et ajoutez une preuve concrète.",
    },
    "de-DE": {
        "practice_title": "Uebung: {topic}",
        "flash_title": "Karte: {topic}",
        "why_now": "Diese Karte festigt den naechsten Schritt, bevor das Thema erweitert wird.",
        "scenario": "Bearbeite einen kleinen, pruefbaren Teil von {topic}.",
        "problem": "Erklaere eine konkrete Regel, ein Beispiel oder eine Grenze von {topic}.",
        "action": "Lerne zuerst und schreibe dann eine kurze Antwort mit einem konkreten Nachweis.",
        "deliverable": "Eine kurze Erklaerung von {topic} und ein Nachweis dafuer.",
        "self_1": "Bleibt die Antwort in einem kleinen Umfang?",
        "self_2": "Kannst du einen konkreten Nachweis statt einer Vermutung zeigen?",
        "validation": "Pruefe die Antwort an einer Quelle, einem Beispiel oder einem nachpruefbaren Ergebnis.",
        "rubric_1": "Die Erklaerung bleibt praezise und begrenzt.",
        "rubric_2": "Der Nachweis bestaetigt die Behauptung ohne Raten.",
        "deliverable_1": "Die kurze Erklaerung oder das Ergebnis.",
        "deliverable_2": "Ein Satz dazu, was der Nachweis belegt.",
        "verify_1": "Pruefe die verwendete Regel oder das genaue Beispiel.",
        "verify_2": "Erklaere, warum der Nachweis die Antwort stuetzt.",
        "success": "Du kannst {topic} erklaeren und mit einem konkreten Nachweis belegen.",
        "stuck": "Reduziere die Antwort auf eine Regel und einen Nachweis.",
        "reflect": "Welcher Nachweis hat diese Idee klar gemacht?",
        "return": "Komm mit deiner Antwort, der Pruefung und einer kurzen Reflexion zurueck.",
        "next": "Komm mit dem verifizierten Ergebnis zurueck und waehle dann den naechsten Schritt.",
        "question": "Was ist die kleinste praezise Erklaerung von {topic}?",
        "flash_context": "Rufe die Idee aus dem Gedächtnis ab, bevor du das Material wieder oeffnest.",
        "expected": "Eine knappe Erklaerung von {topic} mit einem Beispiel oder einer Grenze.",
        "hint_1": "Beginne mit der Kerndefinition oder der zentralen Regel.",
        "hint_2": "Fuege ein Beispiel, eine Grenzbedingung oder eine Anwendung hinzu.",
        "mistake": "Eine vage Definition ohne Nachweis oder Grenze geben.",
        "correct": "Gut. Die Erklaerung hat einen pruefbaren Anker.",
        "incorrect": "Kehre zur kleinsten Regel zurueck und fuege einen konkreten Nachweis hinzu.",
    },
    "ja-JP": {
        "practice_title": "練習: {topic}",
        "flash_title": "カード: {topic}",
        "why_now": "テーマを広げる前に、次の一歩を確実にするカードです。",
        "scenario": "{topic} の小さく検証可能な部分に取り組みます。",
        "problem": "{topic} の具体的な規則、例、または境界を説明してください。",
        "action": "先に学び、次に具体的な根拠を含む短い回答を書いてください。",
        "deliverable": "{topic} の短い説明と、それを支える一つの根拠。",
        "self_1": "回答は小さな範囲に収まっていますか。",
        "self_2": "推測ではなく具体的な根拠を示せますか。",
        "validation": "資料、例、または確認可能な結果と照らして回答を検証します。",
        "rubric_1": "説明は正確で、範囲が限定されています。",
        "rubric_2": "根拠が推測なしで主張を検証しています。",
        "deliverable_1": "短い説明または結果。",
        "deliverable_2": "根拠が何を示すかを説明する一文。",
        "verify_1": "使った規則または正確な例を確認します。",
        "verify_2": "その根拠が回答を支える理由を説明します。",
        "success": "{topic} を説明し、具体的な根拠に結び付けられます。",
        "stuck": "回答を一つの規則と一つの根拠まで小さくしてください。",
        "reflect": "どの根拠でこの考えが明確になりましたか。",
        "return": "回答、検証結果、短い振り返りを持って戻ってください。",
        "next": "検証済みの結果を持って戻り、次の一歩を選びます。",
        "question": "{topic} を最も小さく正確に説明すると何ですか。",
        "flash_context": "資料を開き直す前に、記憶から考えを取り出してください。",
        "expected": "{topic} の簡潔な説明と、一つの例または境界。",
        "hint_1": "中心となる定義または規則から始めてください。",
        "hint_2": "例、境界条件、または利用場面を一つ加えてください。",
        "mistake": "根拠や境界なしに曖昧な定義を述べること。",
        "correct": "よいです。説明に検証可能な根拠があります。",
        "incorrect": "最小の規則に戻り、具体的な根拠を一つ加えてください。",
    },
    "ko-KR": {
        "practice_title": "연습: {topic}",
        "flash_title": "카드: {topic}",
        "why_now": "주제를 넓히기 전에 다음 단계를 확실히 하기 위한 카드입니다.",
        "scenario": "{topic}의 작고 검증 가능한 한 부분을 다룹니다.",
        "problem": "{topic}의 구체적인 규칙, 예시 또는 경계를 설명하세요.",
        "action": "먼저 학습한 뒤 구체적인 근거를 포함한 짧은 답을 작성하세요.",
        "deliverable": "{topic}에 대한 짧은 설명과 이를 뒷받침하는 한 가지 근거.",
        "self_1": "답변이 작은 범위에 머물러 있나요?",
        "self_2": "추측 대신 구체적인 근거를 제시할 수 있나요?",
        "validation": "자료, 예시 또는 확인 가능한 결과와 비교하여 답변을 검증하세요.",
        "rubric_1": "설명이 정확하고 범위가 제한되어 있습니다.",
        "rubric_2": "근거가 추측 없이 주장을 검증합니다.",
        "deliverable_1": "짧은 설명 또는 결과.",
        "deliverable_2": "근거가 무엇을 증명하는지 말하는 한 문장.",
        "verify_1": "사용한 정확한 규칙 또는 예시를 확인하세요.",
        "verify_2": "그 근거가 답변을 뒷받침하는 이유를 설명하세요.",
        "success": "{topic}를 설명하고 구체적인 근거와 연결할 수 있습니다.",
        "stuck": "답을 하나의 규칙과 하나의 근거로 줄이세요.",
        "reflect": "어떤 근거가 이 생각을 분명하게 만들었나요?",
        "return": "답변, 검증 결과, 짧은 성찰을 가지고 돌아오세요.",
        "next": "검증한 결과를 가지고 돌아와 다음 단계를 선택하세요.",
        "question": "{topic}에 대한 가장 작고 정확한 설명은 무엇인가요?",
        "flash_context": "자료를 다시 열기 전에 기억에서 개념을 떠올리세요.",
        "expected": "{topic}에 대한 간결한 설명과 한 가지 예시 또는 경계.",
        "hint_1": "핵심 정의 또는 규칙부터 시작하세요.",
        "hint_2": "예시, 경계 조건 또는 사용 사례를 하나 추가하세요.",
        "mistake": "근거나 경계 없이 모호한 정의를 제시하는 것.",
        "correct": "좋습니다. 설명에 검증 가능한 근거가 있습니다.",
        "incorrect": "가장 작은 규칙으로 돌아가 구체적인 근거를 하나 추가하세요.",
    },
    "pt-BR": {
        "practice_title": "Prática: {topic}",
        "flash_title": "Cartão: {topic}",
        "why_now": "Este cartão consolida o próximo passo antes de ampliar o tema.",
        "scenario": "Trabalhe uma parte pequena e verificável de {topic}.",
        "problem": "Explique uma regra, um exemplo ou um limite concreto de {topic}.",
        "action": "Aprenda primeiro; depois escreva uma resposta curta com uma evidência concreta.",
        "deliverable": "Uma explicação curta de {topic} e uma evidência que a sustente.",
        "self_1": "A resposta permanece em um escopo pequeno?",
        "self_2": "Você consegue mostrar uma evidência concreta em vez de uma suposição?",
        "validation": "Confira a resposta com uma fonte, um exemplo ou um resultado verificável.",
        "rubric_1": "A explicação permanece precisa e limitada.",
        "rubric_2": "A evidência confirma a afirmação sem adivinhação.",
        "deliverable_1": "A explicação curta ou o resultado.",
        "deliverable_2": "Uma frase dizendo o que a evidência prova.",
        "verify_1": "Verifique a regra ou o exemplo exato usado.",
        "verify_2": "Explique por que a evidência sustenta a resposta.",
        "success": "Você consegue explicar {topic} e ligá-lo a uma evidência concreta.",
        "stuck": "Reduza a resposta a uma regra e uma evidência.",
        "reflect": "Qual evidência tornou esta ideia clara?",
        "return": "Volte com sua resposta, a verificação e uma reflexão curta.",
        "next": "Volte com o resultado verificado e escolha o próximo passo.",
        "question": "Qual é a explicação mais pequena e precisa de {topic}?",
        "flash_context": "Recupere a ideia da memória antes de abrir o material novamente.",
        "expected": "Uma explicação concisa de {topic}, com um exemplo ou um limite.",
        "hint_1": "Comece pela definição ou regra central.",
        "hint_2": "Acrescente um exemplo, uma condição de limite ou um uso.",
        "mistake": "Dar uma definição vaga sem evidência ou limite.",
        "correct": "Bom. A explicação tem uma base verificável.",
        "incorrect": "Volte à menor regra e acrescente uma evidência concreta.",
    },
}

_WHY_NOW_MESSAGES: dict[str, str] = {
    "conversation_gap": "Knowledge gap detected during conversation.",
    "plan_requirement": "Plan stage requires mastering this skill.",
    "resource_knowledge": "Extractable knowledge found in indexed resource.",
    "practice_feedback": "Feedback from recent practice session.",
    "dependency_mastery": "Prerequisite skill not yet mastered.",
    "review_due": "Scheduled review is due for this concept.",
}

_WHY_NOW_MESSAGES_ZH: dict[str, str] = {
    "conversation_gap": "对话中发现了知识缺口。",
    "plan_requirement": "计划阶段需要先掌握这个技能。",
    "resource_knowledge": "已索引的资料里发现了可提取的知识。",
    "practice_feedback": "来自最近练习反馈。",
    "dependency_mastery": "前置技能还没有掌握。",
    "review_due": "这个概念到了复习时间。",
}

_RESOURCE_BLOCKING_FLAGS = {
    "network_disabled",
    "fetch_failed",
    "blocked_source",
    "no_content",
    "source_conflict",
}

_GUIDED_SCENARIO_PACK_REMOTE = "remote_workspace"
_GUIDED_SCENARIO_PACK_DEBUG = "debug_loop"
_GUIDED_SCENARIO_PACK_FUNCTION = "function_guidance"
_GUIDED_SCENARIO_PACK_RESOURCE = "resource_knowledge"
_GUIDED_SCENARIO_PACK_DEPENDENCY = "dependency_mastery"
_GUIDED_SCENARIO_PACK_CATALOG = "guided_training_scenario_packs.json"


def _context_blob(context: CardGenerationContext) -> str:
    return build_subject_blob(
        context.focus_area,
        context.target_skill,
        context.context_hint,
        context.why_now,
    )


_WHY_NOW_MESSAGES_ZH.update(
    {
        "conversation_gap": "对话中发现了知识缺口。",
        "plan_requirement": "计划阶段需要先掌握这个技能。",
        "resource_knowledge": "已索引的资料里发现了可提取的知识。",
        "practice_feedback": "来自最近练习反馈。",
        "dependency_mastery": "前置技能还没有掌握。",
        "review_due": "这个概念到了复习时间。",
    }
)


def _match_guided_scenario_pack(
    context: CardGenerationContext,
    *,
    source: str | None = None,
) -> str | None:
    source_key = str(source or context.source or "").strip().lower()
    blob = _context_blob(context)
    if not blob:
        if source_key == "resource_knowledge":
            return _GUIDED_SCENARIO_PACK_RESOURCE
        if source_key == "dependency_mastery":
            return _GUIDED_SCENARIO_PACK_DEPENDENCY
        return None

    if any(
        token in blob
        for token in (
            "remote ssh",
            "remote_ssh",
            "remote workspace",
            "remote tunnels",
            "remote tunnel",
            "dev container",
            "devcontainer",
            "dev containers",
            "wsl",
            "vscode remote",
            "credential mode",
            "远程",
            "远程工作区",
            "凭据模式",
        )
    ):
        return _GUIDED_SCENARIO_PACK_REMOTE

    if any(
        token in blob
        for token in (
            "breakpoint",
            "launch.json",
            "debug console",
            "watch expression",
            "stack trace",
            "step into",
            "step over",
            "exception breakpoint",
            "debug",
            "调试",
            "断点",
        )
    ):
        return _GUIDED_SCENARIO_PACK_DEBUG

    if any(
        token in blob
        for token in (
            "signature help",
            "parameter hint",
            "function hint",
            "function guidance",
            "function contract",
            "call site",
            "call sites",
            "read function",
            "understand function",
            "hover",
            "peek definition",
            "go to definition",
            "find all references",
            "intellisense",
            "autocomplete",
            "function",
            "函数提示",
            "参数提示",
            "函数签名",
            "调用点",
            "函数契约",
            "看懂函数",
        )
    ):
        return _GUIDED_SCENARIO_PACK_FUNCTION

    # These sources own their governed pack only after the legacy keyword packs.
    # _apply_guided_workspace_facts then degrades incomplete facts before any LLM path.
    if source_key == "resource_knowledge":
        return _GUIDED_SCENARIO_PACK_RESOURCE
    if source_key == "dependency_mastery":
        return _GUIDED_SCENARIO_PACK_DEPENDENCY

    return None


def _guided_pack_focus(context: CardGenerationContext, fallback: str) -> str:
    return context.focus_area or context.target_skill or fallback


def _guided_pack_skill(context: CardGenerationContext, fallback: str) -> str:
    return context.target_skill or context.focus_area or fallback


@lru_cache(maxsize=1)
def _load_guided_scenario_pack_catalog() -> dict[str, dict[str, Any]]:
    try:
        raw = (
            resource_files("app.training")
            .joinpath(_GUIDED_SCENARIO_PACK_CATALOG)
            .read_text(encoding="utf-8")
        )
        data = json.loads(raw)
    except Exception:
        logger.warning("Failed to load guided scenario pack catalog", exc_info=True)
        return {}

    packs = data.get("packs")
    if not isinstance(packs, list):
        return {}

    catalog: dict[str, dict[str, Any]] = {}
    for pack in packs:
        pack_id = pack.get("id") if isinstance(pack, dict) else None
        if isinstance(pack_id, str):
            catalog[pack_id] = pack
    return catalog


def _pick_localized_value(value: Any, language: str = "en-US", default: Any = None) -> Any:
    if isinstance(value, dict):
        if language in value:
            return value[language]
        if language.lower().startswith("zh"):
            for candidate in ("zh-CN", "zh-Hans", "zh-TW", "zh"):
                if candidate in value:
                    return value[candidate]
        if "en-US" in value:
            return value["en-US"]
    return value if value is not None else default


def _localized_string(value: Any, language: str = "en-US") -> str:
    resolved = _pick_localized_value(value, language, "")
    return resolved.strip() if isinstance(resolved, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _localized_string_list(value: Any, language: str = "en-US") -> list[str]:
    return _string_list(_pick_localized_value(value, language, []))


def _feedback_dict(value: Any, language: str = "en-US") -> dict[str, str]:
    resolved = _pick_localized_value(value, language, {})
    if not isinstance(resolved, dict):
        return {}
    return {
        key: item
        for key, item in resolved.items()
        if isinstance(key, str) and isinstance(item, str) and key.strip()
    }


def _normalize_function_guidance_terms(text: str) -> str:
    replacements = (
        ("函数契约", "function contract"),
        ("调用点", "call site"),
        ("函数提示", "function guidance"),
        ("函数签名", "function signature"),
        ("签名提示", "signature help"),
        ("悬停", "hover"),
        ("查看定义", "definition"),
        ("跳转定义", "definition"),
        ("定义", "definition"),
        ("引用", "references"),
        ("参数提示", "signature help"),
        ("自动补全", "autocomplete"),
    )
    normalized = text
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])(?=[A-Za-z])", " ", normalized)
    normalized = re.sub(r"(?<=[A-Za-z])(?=[\u4e00-\u9fff])", " ", normalized)
    normalized = re.sub(r"\s{2,}", " ", normalized).strip()
    return normalized


def _normalize_function_guidance_card(
    card: TrainingCardCandidateSnapshot,
    language: str = "en-US",
) -> TrainingCardCandidateSnapshot:
    if not _prefers_chinese(language):
        return card

    text_fields = (
        "title",
        "why_now",
        "focus_area",
        "target_skill",
        "scenario",
        "problem_statement",
        "suggested_workspace_action",
        "deliverable",
        "validation_method",
        "stuck_recovery",
        "reflection_prompt",
        "return_with",
        "next_after_completion",
        "question",
        "context",
        "expected_answer",
        "success_signal",
    )
    update_payload: dict[str, Any] = {}
    for field in text_fields:
        value = getattr(card, field, "")
        if isinstance(value, str) and value.strip():
            update_payload[field] = _normalize_function_guidance_terms(value)

    list_fields = (
        "constraints",
        "self_check",
        "grading_rubric",
        "hint_ladder",
        "common_mistakes",
        "learner_deliverables",
        "verification_steps",
        "expected_symbols",
        "files_to_touch",
        "source_chain",
    )
    for field in list_fields:
        value = getattr(card, field, [])
        if isinstance(value, list) and value:
            update_payload[field] = [
                _normalize_function_guidance_terms(item) if isinstance(item, str) else item
                for item in value
            ]

    feedback = getattr(card, "feedback", {})
    if isinstance(feedback, dict) and feedback:
        update_payload["feedback"] = {
            key: _normalize_function_guidance_terms(item) if isinstance(item, str) else item
            for key, item in feedback.items()
        }

    return card.model_copy(update=update_payload) if update_payload else card


def _prefers_chinese(language: str | None) -> bool:
    return bool((language or "").strip().lower().startswith("zh"))


def _localized_text(english: str, chinese: str, language: str | None) -> str:
    return chinese if _prefers_chinese(language) else english


def _localized_why_now(source: str, why_now: str, language: str | None) -> str:
    if not _prefers_chinese(language):
        return why_now

    english = _WHY_NOW_MESSAGES.get(source)
    chinese = _WHY_NOW_MESSAGES_ZH.get(source)
    if english and chinese and why_now.startswith(english):
        return why_now.replace(english, chinese, 1)
    if english and chinese and why_now == english:
        return chinese
    return why_now


def _fallback_provenance_copy(
    reason: str,
    language: str | None,
) -> tuple[str, str]:
    """Return a machine-readable source marker and learner-facing explanation."""
    normalized_reason = reason.strip() or "unknown"
    reason_label = {
        "invalid_json": _localized_text("invalid JSON", "无效 JSON", language),
        "invalid_card": _localized_text("invalid card payload", "无效卡片内容", language),
        "missing_required_fields": _localized_text(
            "missing required fields",
            "缺少必需字段",
            language,
        ),
        "language_mismatch": _localized_text(
            "language mismatch",
            "语言不匹配",
            language,
        ),
    }.get(
        normalized_reason,
        _localized_text(normalized_reason, normalized_reason, language),
    )
    source_marker = f"generation_source=deterministic_fallback;reason={normalized_reason}"
    detail = _localized_text(
        f"Generation source: deterministic fallback ({reason_label}). "
        "The model-authored card was not accepted; retry generation to obtain a model card.",
        f"生成来源：确定性降级卡（{reason_label}）。模型生成的卡片未被接受；可以重试以获取模型卡片。",
        language,
    )
    return source_marker, detail


def _subject_taxonomy(context: CardGenerationContext):
    return classify_learning_subject(
        context.focus_area,
        context.target_skill,
        context.context_hint,
        context.why_now,
    )


def _subject_lane(context: CardGenerationContext) -> str:
    return _subject_taxonomy(context).family


def _practice_defaults(
    context: CardGenerationContext,
    language: str | None,
) -> dict[str, Any]:
    topic = context.focus_area or context.target_skill or _localized_text("this topic", "这个主题", language)
    taxonomy = _subject_taxonomy(context)

    if taxonomy.subtype == "derivation":
        return {
            "problem_statement": _localized_text(
                f"Turn {topic} into one short worked step or mini-derivation you can justify line by line.",
                f"把 {topic} 收成一个你能逐行说明理由的短步骤。",
                language,
            ),
            "suggested_workspace_action": _localized_text(
                "Work through one tiny transformation, example, or explanation by hand.",
                "先手工完成一个很小的变形、例题或解释。",
                language,
            ),
            "api_hints": [
                _localized_text("Name the starting form or known condition.", "先写清起始形式或已知条件。", language),
                _localized_text("Mark the key rule used in the crucial step.", "标出关键一步使用了哪条规则。", language),
                _localized_text("Do one final equivalence or substitution check.", "最后做一次等价或代入检查。", language),
            ],
            "deliverable": _localized_text(
                "One short derivation, proof step, or solved example that makes the move explicit.",
                "一段很短的推导、例题或解释，清楚写出这个数学步骤。",
                language,
            ),
            "self_check": [
                _localized_text("Can you name the exact rule used at the key step?", "你能说清关键一步用了哪条规则吗？", language),
                _localized_text("Could someone else follow the step without filling in gaps?", "别人不靠猜也能顺着你的步骤看懂吗？", language),
            ],
            "validation_method": _localized_text(
                "Check the step line by line or substitute the result back into the original form, then explain why it holds.",
                "逐行检查这个步骤，或把结果代回原式，再说明为什么它成立。",
                language,
            ),
            "grading_rubric": [
                _localized_text("The worked step stays short and correct.", "这个步骤保持简短且正确。", language),
                _localized_text("The final form is justified instead of guessed.", "最后的形式是被证明出来的，不是猜出来的。", language),
            ],
            "learner_deliverables": [
                _localized_text("The worked step or solved example.", "写好的步骤或例题。", language),
                _localized_text("One sentence naming the rule that justified the key move.", "一句话说明关键动作靠哪条规则成立。", language),
            ],
            "verification_steps": [
                _localized_text("Verify the key transformation line by line.", "逐行核对关键变形。", language),
                _localized_text("Check the final form by substitution or by explaining why it is equivalent.", "通过代入或等价说明，检查最后结果。", language),
            ],
            "success_signal": _localized_text(
                "One derivation move changed from pattern-matching into proof.",
                "有一个数学动作从“凭感觉”变成了“能证明”。",
                language,
            ),
            "stuck_recovery": _localized_text(
                "Go back to the first step you can justify and prove only that step.",
                "退回到第一个你能说清理由的步骤，先只证明那一步。",
                language,
            ),
            "reflection_prompt": _localized_text(
                "Which line was the first one you could truly justify instead of just imitate?",
                "哪一行是你第一次真正能说明理由，而不是照着做的？",
                language,
            ),
            "return_with": _localized_text(
                "Return with the worked step, the rule you used, and the final check.",
                "带着写好的步骤、使用的规则和最终检查结果回来。",
                language,
            ),
            "next_after_completion": _localized_text(
                "Return with the verified derivation step, then decide whether to practice one more example or switch to flash review.",
                "带着这个已验证的数学步骤回来，再决定继续做一个例子还是切到 flash 复习。",
                language,
            ),
        }

    if taxonomy.subtype == "writing":
        return {
            "problem_statement": _localized_text(
                f"Use one short phrase, sentence, or contrast to make your judgment about {topic} explicit.",
                f"用一个很短的短语、句子或对比，把你对 {topic} 的判断说清楚。",
                language,
            ),
            "suggested_workspace_action": _localized_text(
                "Rewrite, compare, or explain one short sentence, opening, tone, or reading signal.",
                "改写、对比或解释一个很短的句子、opening、tone 或阅读信号。",
                language,
            ),
            "api_hints": [
                _localized_text("Point to one exact phrase or sentence.", "先指向一个具体短语或句子。", language),
                _localized_text("Name one nearby alternative you are not choosing.", "说出一个你没有选的相邻表达。", language),
                _localized_text("State the meaning or tone difference it proves.", "说明它证明了什么语气或含义差别。", language),
            ],
            "deliverable": _localized_text(
                "One short rewrite, comparison, or explanation that makes the language choice visible.",
                "一个很短的改写、对比或解释，让这个语言选择清楚可见。",
                language,
            ),
            "self_check": [
                _localized_text("Can you point to the exact phrase carrying the meaning or tone?", "你能指出真正承载含义或语气的那几个词吗？", language),
                _localized_text("Did you keep the example short enough to inspect closely?", "你的例子够短，能被仔细检查吗？", language),
            ],
            "validation_method": _localized_text(
                "Read the result back against the intended tone or meaning and explain the one difference it proves.",
                "把结果对照目标语气或含义读一遍，并说明它证明了哪一个关键差别。",
                language,
            ),
            "grading_rubric": [
                _localized_text("The judgment stays tied to a real phrase or sentence.", "这个判断始终绑在真实短语或句子上。", language),
                _localized_text("The contrast or rewrite proves one specific language choice.", "改写或对比证明了一个具体的语言选择。", language),
            ],
            "learner_deliverables": [
                _localized_text("The rewritten sentence or short explanation.", "改写后的句子或简短解释。", language),
                _localized_text("One sentence stating the choice you made and why.", "一句话说明你做了什么选择，以及为什么。", language),
            ],
            "verification_steps": [
                _localized_text("Name the exact word, tone, or structure you changed or noticed.", "说出你改了或抓到的那个具体词、语气或结构。", language),
                _localized_text("Explain why it fits better than one nearby alternative.", "解释它为什么比另一个相近选项更合适。", language),
            ],
            "success_signal": _localized_text(
                "One language choice is now explicit and defensible.",
                "有一个语言选择现在已经清楚、而且说得出理由。",
                language,
            ),
            "stuck_recovery": _localized_text(
                "Shrink the task to one sentence, one phrase, or one contrast.",
                "把任务缩到一个句子、一个短语或一组对比上。",
                language,
            ),
            "reflection_prompt": _localized_text(
                "What signal made the tone or meaning easier to judge this time?",
                "这一次，是什么信号让你更容易判断语气或含义？",
                language,
            ),
            "return_with": _localized_text(
                "Return with the sentence, your judgment, and the reason.",
                "带着句子、你的判断和理由回来。",
                language,
            ),
            "next_after_completion": _localized_text(
                "Return with the verified language choice, then decide whether to expand to a second example or switch to flash review.",
                "带着这个已验证的语言选择回来，再决定要不要扩成第二个例子，还是切到 flash 复习。",
                language,
            ),
        }

    if taxonomy.subtype == "memorization":
        return {
            "problem_statement": _localized_text(
                f"Turn {topic} into one tiny fact cluster you can recall without looking.",
                f"把 {topic} 收成一个你能不看资料就回忆出来的小事实簇。",
                language,
            ),
            "suggested_workspace_action": _localized_text(
                "Group two or three facts, terms, or cues together, then do one closed-book recall.",
                "先把两三个事实、术语或提示词编成一小组，再做一次闭卷回忆。",
                language,
            ),
            "api_hints": [
                _localized_text("Keep the cluster tiny: two or three items only.", "把这一组压小，只留两到三个点。", language),
                _localized_text("Add one cue that helps you distinguish them.", "给这组内容加一个帮助区分的提示。", language),
                _localized_text("Recall before reopening the notes.", "先回忆，再重新打开资料核对。", language),
            ],
            "deliverable": _localized_text(
                "One tiny recall sheet, Q/A pair, or fact cluster with the misses marked.",
                "一张很小的回忆清单、问答对，或一组带错漏标记的事实簇。",
                language,
            ),
            "self_check": [
                _localized_text("Could you recall it before looking back at the notes?", "你是在看资料之前就回忆出来的吗？", language),
                _localized_text("Did you keep the cluster small enough to remember cleanly?", "这组内容够小，能被干净地记住吗？", language),
            ],
            "validation_method": _localized_text(
                "Hide the notes, recall the cluster, then compare what you remembered, missed, and confused.",
                "先遮住资料，回忆这一小组，再对比你记住了什么、漏了什么、混了什么。",
                language,
            ),
            "grading_rubric": [
                _localized_text("The cluster is small enough for real recall.", "这组内容足够小，适合真实回忆。", language),
                _localized_text("The final check clearly shows what was remembered versus missed.", "最终核对能清楚区分记住了什么、漏了什么。", language),
            ],
            "learner_deliverables": [
                _localized_text("The tiny fact cluster or Q/A pair.", "这一小组事实或问答对。", language),
                _localized_text("One note about what you missed or confused.", "一句说明你漏掉或混淆了什么。", language),
            ],
            "verification_steps": [
                _localized_text("Recall the cluster without looking.", "不看资料先回忆这一组内容。", language),
                _localized_text("Compare the recall against the source and mark one gap.", "对照原资料核对，并标出一个缺口。", language),
            ],
            "success_signal": _localized_text(
                "One fact cluster moved from recognition into recall.",
                "有一小组知识点从“眼熟”变成了“能回忆”。",
                language,
            ),
            "stuck_recovery": _localized_text(
                "Shrink to two items and one contrast before trying recall again.",
                "先缩到两个点和一个对比，再重做一次回忆。",
                language,
            ),
            "reflection_prompt": _localized_text(
                "Which cue actually helped you retrieve the right fact this time?",
                "这一次，真正帮助你提取正确事实的是哪一个提示？",
                language,
            ),
            "return_with": _localized_text(
                "Return with the recall result, the misses, and the cue that helped.",
                "带着回忆结果、错漏点和真正有用的提示回来。",
                language,
            ),
            "next_after_completion": _localized_text(
                "Return with the checked recall, then decide whether to add one more cluster or switch to flash review.",
                "带着这次已核对的回忆结果回来，再决定继续补一组还是切到 flash 复习。",
                language,
            ),
        }

    if taxonomy.subtype == "reading":
        return {
            "problem_statement": _localized_text(
                f"Make one narrow claim about {topic} and support it with one real excerpt, scene, or detail.",
                f"围绕 {topic} 提出一个很窄的判断，并用一个真实片段、场景或细节支撑它。",
                language,
            ),
            "suggested_workspace_action": _localized_text(
                "Use one short excerpt, scene, or claim from the book and make one evidence-based judgment.",
                "抓住书里的一个短片段、一个场景或一个判断，做一次有证据支撑的分析。",
                language,
            ),
            "api_hints": [
                _localized_text("Pick one short excerpt or scene.", "先选一个短片段或小场景。", language),
                _localized_text("State one claim instead of a whole-book summary.", "只说一个判断，不要概括整本书。", language),
                _localized_text("Point to the exact detail that supports the claim.", "指出支撑这个判断的那个具体细节。", language),
            ],
            "deliverable": _localized_text(
                "One short reading note that states a claim and the exact evidence supporting it.",
                "一则很短的阅读笔记，写出一个判断和支撑它的明确证据。",
                language,
            ),
            "self_check": [
                _localized_text("Can you show the exact line, image, or detail your claim rests on?", "你能指出这个判断真正依赖的句子、意象或细节吗？", language),
                _localized_text("Did you separate the claim from the evidence clearly?", "你把“判断”和“证据”分清了吗？", language),
            ],
            "validation_method": _localized_text(
                "Check that the claim comes from a real excerpt and that the evidence truly supports it, then explain the link.",
                "检查这个判断是否来自真实片段，证据是否真的支撑它，然后把两者的联系说清楚。",
                language,
            ),
            "grading_rubric": [
                _localized_text("The claim stays narrow and readable.", "这个判断保持得足够窄，也足够清楚。", language),
                _localized_text("The evidence is explicit and relevant.", "证据明确，而且和判断真的相关。", language),
            ],
            "learner_deliverables": [
                _localized_text("One claim about the passage or theme.", "关于片段或主题的一个判断。", language),
                _localized_text("One concrete excerpt or detail supporting that claim.", "支撑这个判断的一个具体片段或细节。", language),
            ],
            "verification_steps": [
                _localized_text("Point to the exact excerpt, scene, or detail.", "指出那个确切的片段、场景或细节。", language),
                _localized_text("Explain how the evidence supports the claim instead of only retelling the plot.", "解释证据怎样支撑判断，而不是只复述情节。", language),
            ],
            "success_signal": _localized_text(
                "One reading judgment is now supported by visible evidence.",
                "有一个阅读判断现在已经能被看得见的证据支撑起来。",
                language,
            ),
            "stuck_recovery": _localized_text(
                "Shrink to one sentence, one image, or one scene before deciding the theme.",
                "先缩到一句话、一个意象或一个场景，再去判断主题。",
                language,
            ),
            "reflection_prompt": _localized_text(
                "What made this piece of evidence feel trustworthy to you?",
                "这次是哪一点让你觉得这条证据真的站得住？",
                language,
            ),
            "return_with": _localized_text(
                "Return with the claim, the evidence, and the link between them.",
                "带着判断、证据，以及二者之间的联系回来。",
                language,
            ),
            "next_after_completion": _localized_text(
                "Return with the verified reading note, then decide whether to deepen the same passage or switch to flash review.",
                "带着这条已验证的阅读笔记回来，再决定继续深挖同一片段，还是切到 flash 复习。",
                language,
            ),
        }

    if taxonomy.family == "code":
        return {
            "problem_statement": _localized_text(
                f"Turn {topic} into one real code or tool move you can prove.",
                f"把 {topic} 收成一个你能真正证明的代码或工具动作。",
                language,
            ),
            "suggested_workspace_action": _localized_text(
                "Inspect, change, or run one small thing that proves the concept in real project context.",
                "在真实项目上下文里检查、修改或运行一个很小的对象，证明这个概念。",
                language,
            ),
            "api_hints": [
                _localized_text("Name the exact file, boundary, or output first.", "先说清具体文件、边界或输出。", language),
                _localized_text("Choose one command, API, or call site to check.", "选择一个命令、API 或 call site 去检查。", language),
                _localized_text("Use the smallest verification move available.", "使用当前最小的验证动作。", language),
            ],
            "deliverable": _localized_text(
                "One patch, checked output, or short explanation that proves the concept.",
                "一个补丁、一段已检查的输出，或一段能证明概念的简短解释。",
                language,
            ),
            "self_check": [
                _localized_text("Did you keep the slice small enough for one pass?", "你把范围压到一遍能看完了吗？", language),
                _localized_text("Can you point to one concrete proof instead of a guess?", "你能指出一个具体证据，而不是靠猜吗？", language),
            ],
            "validation_method": _localized_text(
                "Run the smallest relevant check or inspect one real artifact and explain what it proves.",
                "运行最小相关检查，或检查一个真实产物，并说明它证明了什么。",
                language,
            ),
            "grading_rubric": [
                _localized_text("The move stayed tightly bounded.", "这个动作保持得很窄。", language),
                _localized_text("The result can be verified without extra guesswork.", "这个结果不用额外猜测就能验证。", language),
            ],
            "learner_deliverables": [
                _localized_text("The exact file, output, or boundary you checked.", "你检查的那个具体文件、输出或边界。", language),
                _localized_text("One sentence explaining what the result proved.", "一句话说明这个结果证明了什么。", language),
            ],
            "verification_steps": [
                _localized_text("Check the exact behavior around the focus area.", "检查焦点附近的那个具体行为。", language),
                _localized_text("Confirm the result matches the claimed boundary.", "确认结果和你声称的边界一致。", language),
            ],
            "success_signal": _localized_text(
                "One real code or tool fact moved from guesswork to proof.",
                "有一个真实的代码或工具事实，从猜测变成了证据。",
                language,
            ),
            "stuck_recovery": _localized_text(
                "Reduce scope to one file, one boundary, or one output and prove only that.",
                "把范围缩到一个文件、一个边界或一个输出，先只证明它。",
                language,
            ),
            "reflection_prompt": _localized_text(
                "Which concrete fact changed from assumption into proof?",
                "哪一个具体事实，是从“我以为”变成“我能证明”的？",
                language,
            ),
            "return_with": _localized_text(
                "Return with the checked artifact, the result, and one sentence of explanation.",
                "带着已检查的产物、结果和一句解释回来。",
                language,
            ),
            "next_after_completion": _localized_text(
                "Return with the verified result, then decide whether to continue practice or switch to flash review.",
                "带着已验证的结果回来，再决定继续 practice 还是切到 flash 复习。",
                language,
            ),
        }

    return {
        "problem_statement": _localized_text(
            f"Turn {topic} into one small, verifiable move grounded in a real object, excerpt, or explanation.",
            f"把 {topic} 收成一个很小、可验证，而且绑在真实对象、片段或解释上的动作。",
            language,
        ),
        "suggested_workspace_action": _localized_text(
            "Make the smallest observable explanation, comparison, or artifact that proves understanding.",
            "做出最小、可观察的解释、对比或产出，来证明你真的理解了。",
            language,
        ),
        "api_hints": [
            _localized_text("Choose one concrete object, excerpt, or example.", "先选一个具体对象、片段或例子。", language),
            _localized_text("State the exact gap you are trying to close.", "说清你现在要补的是哪一个缺口。", language),
            _localized_text("Use one visible check instead of a vague feeling.", "用一个看得见的检查，替代“我感觉差不多”。", language),
        ],
        "deliverable": _localized_text(
            "A small learner-produced artifact that demonstrates progress on the current focus.",
            "一个很小的学习产出，能证明你在当前焦点上真的有推进。",
            language,
        ),
        "self_check": [
            _localized_text("Did you keep the slice small?", "你有没有把这一步压得足够小？", language),
            _localized_text("Can you show one concrete proof that the work is correct?", "你能给出一个具体证据，说明这一步是对的吗？", language),
        ],
        "validation_method": _localized_text(
            "Use the smallest truthful verification method available for this card.",
            "使用这张卡当前最小、最诚实的验证方式。",
            language,
        ),
        "grading_rubric": [
            _localized_text("The action stayed tightly bounded.", "这个动作保持得足够聚焦。", language),
            _localized_text("The result can be verified without extra guesswork.", "这个结果不用额外猜测就能验证。", language),
        ],
        "learner_deliverables": [
            _localized_text("The small artifact, excerpt, or explanation you produced.", "你产出的那条小结果、片段或解释。", language),
            _localized_text("One sentence stating what it proves.", "一句话说明它证明了什么。", language),
        ],
        "verification_steps": [
            _localized_text("Point to the exact object, excerpt, or move you used.", "指出你实际使用的那个对象、片段或动作。", language),
            _localized_text("Explain why it proves the claimed boundary or idea.", "解释它为什么能证明你声称的边界或观点。", language),
        ],
        "success_signal": _localized_text(
            "One vague topic became one visible, checked result.",
            "一个模糊主题，变成了一个看得见、能检查的结果。",
            language,
        ),
        "stuck_recovery": _localized_text(
            "Return to the smallest boundary you can state and verify only that boundary first.",
            "退回到你能说清的最小边界，先只验证这个边界。",
            language,
        ),
        "reflection_prompt": _localized_text(
            "What did you prove, and what did you deliberately leave out?",
            "你证明了什么，又刻意先没做什么？",
            language,
        ),
        "return_with": _localized_text(
            "Return with the result, the check, and one sentence of explanation.",
            "带着结果、检查方式和一句解释回来。",
            language,
        ),
        "next_after_completion": _localized_text(
            "Return with the verified result, then decide whether to continue practice or switch to flash review.",
            "带着已验证的结果回来，再决定继续 practice 还是切到 flash 复习。",
            language,
        ),
    }


def _flash_defaults(
    context: CardGenerationContext,
    source_key: str,
    language: str | None,
    scenario_pack: str = "",
) -> dict[str, Any]:
    topic = context.focus_area or context.target_skill or _localized_text("this concept", "这个概念", language)
    taxonomy = _subject_taxonomy(context)
    is_code_subject = taxonomy.family == "code"
    scenario = context.context_hint or _localized_text(
        f"Keep {topic} grounded in one stable rule before widening the thread.",
        f"先把 {topic} 压成一条稳定规则，再继续扩展当前主线。",
        language,
    )

    if scenario_pack == _GUIDED_SCENARIO_PACK_REMOTE or taxonomy.subtype == "remote":
        return {
            "scenario": scenario,
            "problem_statement": _localized_text(
                "State the one remote-boundary rule that keeps host ownership and credential placement honest before deeper coaching continues.",
                "先说清远程边界规则：主机归属和凭据放置为什么成立，然后再继续更深的教学。",
                language,
            ),
            "suggested_workspace_action": _localized_text(
                "Answer first, then name the workspace type and one real path or storage fact.",
                "先作答，再说出工作区类型和一个真实路径或存储事实。",
                language,
            ),
            "deliverable": _localized_text(
                "One sentence naming the workspace type, owning host, and safe credential mode.",
                "一句话说清工作区类型、文件归属主机和安全凭据模式。",
                language,
            ),
            "validation_method": _localized_text(
                "Check the rule against one real workspace fact instead of answering from habit.",
                "不要凭习惯作答，要用一个真实工作区事实来核对这条规则。",
                language,
            ),
            "learner_deliverables": [
                _localized_text(
                    "One sentence stating the remote type and owning host.",
                    "一句话说出远程类型和真正拥有文件的主机。",
                    language,
                ),
                _localized_text(
                    "One credential decision tied to that boundary.",
                    "给出一个和这个边界对应的凭据决策。",
                    language,
                ),
            ],
            "verification_steps": [
                _localized_text(
                    "Name the remote surface first: SSH, tunnels, dev container, WSL, or local.",
                    "先说出远程表面类型：SSH、tunnels、dev container、WSL 或 local。",
                    language,
                ),
                _localized_text(
                    "Tie the answer to one real path, mount point, or storage boundary.",
                    "再把答案绑定到一个真实路径、挂载点或存储边界。",
                    language,
                ),
            ],
            "success_signal": _localized_text(
                "You can restate the remote boundary rule and support it with one real host or path fact.",
                "你能复述远程边界规则，并用一个真实主机或路径事实支撑它。",
                language,
            ),
            "stuck_recovery": _localized_text(
                "Shrink the answer to one judgment: which host owns the workspace files?",
                "先把问题缩成一个判断：到底是哪台主机拥有工作区文件？",
                language,
            ),
            "reflection_prompt": _localized_text(
                "Which boundary fact made the remote credential rule feel trustworthy this time?",
                "这次是哪条边界事实让远程凭据规则终于变得可信了？",
                language,
            ),
            "return_with": _localized_text(
                "Return with the boundary rule, the owning host, and the credential decision.",
                "带着边界规则、文件归属主机和凭据决策回来。",
                language,
            ),
            "next_after_completion": _localized_text(
                "Return with the boundary rule, then continue the paired remote practice step.",
                "带着这条边界规则回来，然后继续配套的远程实践卡。",
                language,
            ),
        }

    if scenario_pack == _GUIDED_SCENARIO_PACK_DEBUG or taxonomy.subtype == "debug":
        return {
            "scenario": scenario,
            "problem_statement": _localized_text(
                "State the smallest trustworthy debug loop before you touch code again.",
                "先说清最小可信 debug loop，再决定要不要继续改代码。",
                language,
            ),
            "suggested_workspace_action": _localized_text(
                "Answer first, then point to the repro step, pause point, or bad-state observation it governs.",
                "先作答，再指出它对应的复现步骤、暂停点或坏状态观察。",
                language,
            ),
            "deliverable": _localized_text(
                "One sentence naming the repro, the pause point, and the first wrong state.",
                "一句话说出复现、暂停点和第一个错误状态。",
                language,
            ),
            "validation_method": _localized_text(
                "Check whether the answer still forces reproduce -> pause -> observe, rather than guess -> edit.",
                "检查这条答案是否仍然逼着你先复现、再暂停、再观察，而不是先猜再改。",
                language,
            ),
            "learner_deliverables": [
                _localized_text(
                    "The smallest debug rule in your own words.",
                    "用你自己的话说出最小 debug 规则。",
                    language,
                ),
                _localized_text(
                    "One concrete repro or breakpoint anchor.",
                    "给出一个具体的复现点或断点锚点。",
                    language,
                ),
            ],
            "verification_steps": [
                _localized_text(
                    "Make sure the answer includes one repro, one pause point, and one observed bad state.",
                    "确认答案同时包含一次复现、一个暂停点和一个被观察到的坏状态。",
                    language,
                ),
                _localized_text(
                    "Reject answers that jump straight from symptom to code edit.",
                    "排除那种从症状直接跳到改代码的答案。",
                    language,
                ),
            ],
            "success_signal": _localized_text(
                "You can restate the debug loop without skipping the first trustworthy observation.",
                "你能复述这条 debug loop，而且不会跳过第一个可信观察点。",
                language,
            ),
            "stuck_recovery": _localized_text(
                "Reduce the answer to one repro and one pause point, then rebuild from there.",
                "先把答案缩成一次复现和一个暂停点，再从那里重新搭起来。",
                language,
            ),
            "reflection_prompt": _localized_text(
                "What part of the loop keeps you from editing on instinct?",
                "这条 loop 里哪一部分最能防止你靠直觉乱改？",
                language,
            ),
            "return_with": _localized_text(
                "Return with the debug rule, the pause point, and the first wrong state.",
                "带着 debug 规则、暂停点和第一个错误状态回来。",
                language,
            ),
            "next_after_completion": _localized_text(
                "Return with the debug rule, then open the paired practice card in the real failure path.",
                "带着这条 debug 规则回来，然后在真实故障路径里打开配套的实践卡。",
                language,
            ),
        }

    if scenario_pack == _GUIDED_SCENARIO_PACK_FUNCTION or taxonomy.subtype == "function":
        return {
            "scenario": scenario,
            "problem_statement": _localized_text(
                "State the editor-signal rule that lets you recover one function contract without guessing.",
                "说清一条编辑器信号规则，让你能不靠猜测恢复一个 function contract。",
                language,
            ),
            "suggested_workspace_action": _localized_text(
                "Answer first, then name one hover, signature help, definition, or call-site anchor.",
                "先作答，再指出一个 hover、signature help、definition 或 call site 锚点。",
                language,
            ),
            "deliverable": _localized_text(
                "One sentence separating quick hints from the source of truth.",
                "一句话区分“快速提示”和“真正的事实来源”。",
                language,
            ),
            "validation_method": _localized_text(
                "Check that the answer distinguishes editor hints from definition and live call sites.",
                "检查答案是否把编辑器提示和 definition、真实 call site 区分开了。",
                language,
            ),
            "learner_deliverables": [
                _localized_text(
                    "The one rule that separates hint from proof.",
                    "那条把“提示”和“证明”分开的规则。",
                    language,
                ),
                _localized_text(
                    "One real function or call-site anchor where it applies.",
                    "一个它真正适用的函数或 call site 锚点。",
                    language,
                ),
            ],
            "verification_steps": [
                _localized_text(
                    "Make sure the answer names what hover or signature help can suggest.",
                    "确认答案说清了 hover 或 signature help 能提示什么。",
                    language,
                ),
                _localized_text(
                    "Make sure it also names what definition or a real caller must still prove.",
                    "同时确认它也说清了 definition 或真实调用者还必须证明什么。",
                    language,
                ),
            ],
            "success_signal": _localized_text(
                "You can explain the function-contract rule and tie it to one real call site.",
                "你能解释 function contract 规则，并把它绑到一个真实 call site 上。",
                language,
            ),
            "stuck_recovery": _localized_text(
                "Shrink the answer to one distinction: quick hint versus actual contract proof.",
                "先把答案缩成一个区分：快速提示 vs 真正的 contract 证明。",
                language,
            ),
            "reflection_prompt": _localized_text(
                "Which editor signal gave a hint, and which signal actually proved the contract?",
                "哪个编辑器信号只是给了提示，哪个信号才真正证明了 contract？",
                language,
            ),
            "return_with": _localized_text(
                "Return with the contract rule and one checked call-site anchor.",
                "带着 contract 规则和一个已核对的 call site 锚点回来。",
                language,
            ),
            "next_after_completion": _localized_text(
                "Return with the contract rule, then recover one real call site in the paired practice step.",
                "带着这条 contract 规则回来，然后在配套实践卡里恢复一个真实 call site。",
                language,
            ),
        }

    if is_code_subject:
        return {
            "scenario": scenario,
            "problem_statement": _localized_text(
                f"State the one rule or boundary that keeps {topic} safe before you widen the live workspace task again.",
                f"先说清一条规则或边界，让 {topic} 在重新回到真实工作区任务前保持安全。",
                language,
            ),
            "suggested_workspace_action": _localized_text(
                "Answer first, then name one file, symbol, API, or boundary where the rule applies.",
                "先作答，再说出一个它真正适用的文件、符号、API 或边界。",
                language,
            ),
            "deliverable": _localized_text(
                "One short rule plus one concrete code anchor.",
                "一条简短规则，加上一个具体的代码锚点。",
                language,
            ),
            "validation_method": _localized_text(
                "Check the answer against one real symbol, API contract, or failure boundary.",
                "用一个真实符号、API contract 或失败边界来核对这条答案。",
                language,
            ),
            "learner_deliverables": [
                _localized_text("The rule in one or two sentences.", "用一两句话写出这条规则。", language),
                _localized_text("One real code anchor where it applies.", "指出一个真实代码锚点。", language),
            ],
            "verification_steps": [
                _localized_text(
                    "Keep the answer tied to one boundary, role, or failure mode.",
                    "让答案始终绑在一个边界、角色或失败模式上。",
                    language,
                ),
                _localized_text(
                    "Name the code anchor that makes the answer trustworthy.",
                    "说出那个让答案可信的代码锚点。",
                    language,
                ),
            ],
            "success_signal": _localized_text(
                "You can restate the rule and connect it to one real code anchor without guessing.",
                "你能复述这条规则，并把它连到一个真实代码锚点上，而不是靠猜。",
                language,
            ),
            "stuck_recovery": _localized_text(
                "Shrink the answer to one rule and one code anchor.",
                "把答案缩成一条规则和一个代码锚点。",
                language,
            ),
            "reflection_prompt": _localized_text(
                "Which boundary or signal finally made this code concept feel solid?",
                "这次到底是哪条边界或信号让这个代码概念真正稳住了？",
                language,
            ),
            "return_with": _localized_text(
                "Return with the rule and the code anchor you used.",
                "带着这条规则和你使用的代码锚点回来。",
                language,
            ),
            "next_after_completion": _localized_text(
                "Return with the checked rule, then open one small practice step in the live workspace.",
                "带着已核对的规则回来，然后在真实工作区里开启一个更小的实践步骤。",
                language,
            ),
        }

    return {
        "scenario": scenario,
        "problem_statement": _localized_text(
            f"State the one rule, contrast, or proof step that makes {topic} precise before you widen the topic again.",
            f"先说清一条规则、对比点或证明步骤，让 {topic} 在继续扩展前保持精确。",
            language,
        ),
        "suggested_workspace_action": _localized_text(
            "Answer first, then name one example, sentence, passage, or proof step where the idea applies.",
            "先作答，再指出一个它真正适用的例子、句子、片段或证明步骤。",
            language,
        ),
        "deliverable": _localized_text(
            "One short rule plus one concrete anchor.",
            "一条简短规则，加上一个具体锚点。",
            language,
        ),
        "validation_method": _localized_text(
            "Check the answer against one example, contrast, or proof step instead of memorizing empty wording.",
            "不要背空话，要用一个例子、对比点或证明步骤来核对答案。",
            language,
        ),
        "learner_deliverables": [
            _localized_text("The rule in one or two sentences.", "用一两句话写出这条规则。", language),
            _localized_text("One concrete anchor that keeps the rule honest.", "给出一个让这条规则保持诚实的具体锚点。", language),
        ],
        "verification_steps": [
            _localized_text(
                "Keep the answer tied to one contrast, example, or proof step.",
                "让答案始终绑在一个对比点、例子或证明步骤上。",
                language,
            ),
            _localized_text(
                "State why that anchor really supports the answer.",
                "说明为什么这个锚点真的支撑了答案。",
                language,
            ),
        ],
        "success_signal": _localized_text(
            "You can restate the rule and attach it to one concrete anchor without drifting into vague wording.",
            "你能复述这条规则，并把它绑到一个具体锚点上，而不会漂成空泛表述。",
            language,
        ),
        "stuck_recovery": _localized_text(
            "Shrink the answer to one rule and one anchor.",
            "先把答案缩成一条规则和一个锚点。",
            language,
        ),
        "reflection_prompt": _localized_text(
            "Which contrast or proof step made this answer finally click?",
            "这次到底是哪一个对比点或证明步骤让答案真正卡住了？",
            language,
        ),
        "return_with": _localized_text(
            "Return with the rule and the concrete anchor you used.",
            "带着这条规则和你使用的具体锚点回来。",
            language,
        ),
        "next_after_completion": _localized_text(
            "Return with the checked rule, then decide whether to try one example or continue flash review.",
            "带着已核对的规则回来，然后决定是做一个例子，还是继续 flash 复习。",
            language,
        ),
    }


def _ensure_flash_contract(
    card: TrainingCardCandidateSnapshot,
    context: CardGenerationContext,
    source_key: str,
) -> TrainingCardCandidateSnapshot:
    if card.card_type != "flash":
        return card

    language = context.response_language
    defaults = _flash_defaults(context, source_key, language, card.scenario_pack)
    special_pack = card.scenario_pack in {
        _GUIDED_SCENARIO_PACK_REMOTE,
        _GUIDED_SCENARIO_PACK_DEBUG,
        _GUIDED_SCENARIO_PACK_FUNCTION,
    }

    card.scenario = card.scenario or card.context or defaults["scenario"]
    card.problem_statement = card.problem_statement or defaults["problem_statement"]
    card.suggested_workspace_action = card.suggested_workspace_action or defaults["suggested_workspace_action"]
    card.deliverable = card.deliverable or defaults["deliverable"]
    card.validation_method = card.validation_method or defaults["validation_method"]
    if not card.learner_deliverables:
        card.learner_deliverables = list(defaults["learner_deliverables"])
    if not card.verification_steps:
        card.verification_steps = list(defaults["verification_steps"])
    card.success_signal = card.success_signal or defaults["success_signal"]
    card.stuck_recovery = card.stuck_recovery or defaults["stuck_recovery"]
    card.reflection_prompt = card.reflection_prompt or defaults["reflection_prompt"]
    card.return_with = card.return_with or defaults["return_with"]
    if special_pack or not card.next_after_completion.strip():
        card.next_after_completion = defaults["next_after_completion"]
    return card


def _ensure_practice_contract(
    card: TrainingCardCandidateSnapshot,
    context: CardGenerationContext,
) -> TrainingCardCandidateSnapshot:
    """Fill the visible loop fields when an otherwise usable practice card omits them.

    Provider output is intentionally treated as a draft. A practice card is not
    routable as a learning unit until it names a try, a check, a reflection, and
    a return path. Filling only absent fields keeps successful provider output
    intact while retaining a deterministic fallback when the provider is vague.
    """
    if card.card_type != "practice":
        return card

    defaults = _practice_defaults(context, context.response_language)
    card.scenario = card.scenario or context.context_hint or defaults["problem_statement"]
    card.problem_statement = card.problem_statement or defaults["problem_statement"]
    card.suggested_workspace_action = (
        card.suggested_workspace_action or defaults["suggested_workspace_action"]
    )
    card.api_hints = card.api_hints or list(defaults["api_hints"])
    card.deliverable = card.deliverable or defaults["deliverable"]
    card.self_check = card.self_check or list(defaults["self_check"])
    card.validation_method = card.validation_method or defaults["validation_method"]
    card.grading_rubric = card.grading_rubric or list(defaults["grading_rubric"])
    card.learner_deliverables = card.learner_deliverables or list(defaults["learner_deliverables"])
    card.verification_steps = card.verification_steps or list(defaults["verification_steps"])
    card.success_signal = card.success_signal or defaults["success_signal"]
    card.stuck_recovery = card.stuck_recovery or defaults["stuck_recovery"]
    card.reflection_prompt = card.reflection_prompt or defaults["reflection_prompt"]
    card.return_with = card.return_with or defaults["return_with"]
    card.next_after_completion = card.next_after_completion or defaults["next_after_completion"]
    return card


_MULTI_SCOPE_SEPARATOR = re.compile(
    r"\s*(?:,|;|\band\b|\bthen\b|\balso\b|\u3001|\uff0c|\uff1b|\u548c|\u4ee5\u53ca|\u5e76\u4e14)\s*",
    re.IGNORECASE,
)
_UNVERIFIED_COMPLETION_CLAIM = re.compile(
    r"\b(?:master(?:ed|y)|fully\s+understood|complete(?:d|ion)?|ready\s+to\s+advance)\b|\u638c\u63e1|\u5df2\u5b8c\u6210",
    re.IGNORECASE,
)


def _single_problem_focus(*values: str) -> str:
    """Return the first explicit learning target from a potentially broad request."""
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        parts = [part.strip(" .:-") for part in _MULTI_SCOPE_SEPARATOR.split(cleaned) if part.strip(" .:-")]
        return parts[0] if parts else cleaned
    return "current learning target"


def _truthful_completion_copy(topic: str, language: str | None) -> str:
    return _localized_text(
        f"This card counts only after verifiable evidence confirms one result for {topic}; it does not establish long-term retention.",
        f"\u8fd9\u5f20\u5361\u53ea\u6709\u5728\u53ef\u9a8c\u8bc1\u8bc1\u636e\u786e\u8ba4 {topic} \u7684\u4e00\u4e2a\u7ed3\u679c\u540e\u624d\u80fd\u8ba1\u5165\u5b8c\u6210\uff1b\u5b83\u4e0d\u4ee3\u8868\u957f\u671f\u638c\u63e1\u3002",
        language,
    )


def _enforce_learning_loop_contract(
    card: TrainingCardCandidateSnapshot,
    context: CardGenerationContext,
) -> TrainingCardCandidateSnapshot:
    """Attach one-problem, evidence-first semantics without changing the public model.

    ``TrainingCardCandidateSnapshot`` deliberately allows extension fields. The
    metadata below is therefore backward compatible with existing consumers,
    while the visible fields continue to drive older webviews and API clients.
    """
    language = context.response_language
    original_focus = card.target_skill or card.focus_area or context.target_skill or context.focus_area
    focus = _single_problem_focus(card.target_skill, card.focus_area, context.target_skill, context.focus_area)

    if card.target_skill:
        card.target_skill = focus
    elif card.focus_area:
        card.focus_area = focus
    else:
        card.target_skill = focus

    if card.focus_area and _MULTI_SCOPE_SEPARATOR.search(card.focus_area):
        card.focus_area = focus
    if original_focus and original_focus != focus and card.title:
        card.title = card.title.replace(original_focus, focus)

    if _UNVERIFIED_COMPLETION_CLAIM.search(card.success_signal or ""):
        card.success_signal = _truthful_completion_copy(focus, language)
    if _UNVERIFIED_COMPLETION_CLAIM.search(card.next_after_completion or ""):
        card.next_after_completion = _localized_text(
            f"Return with the verification output for {focus}; decide the next step after the evidence is reviewed.",
            f"\u5e26\u7740 {focus} \u7684\u9a8c\u8bc1\u8f93\u51fa\u56de\u6765\uff0c\u5728\u5ba1\u67e5\u8bc1\u636e\u540e\u518d\u51b3\u5b9a\u4e0b\u4e00\u6b65\u3002",
            language,
        )
    feedback = dict(card.feedback)
    if _UNVERIFIED_COMPLETION_CLAIM.search(str(feedback.get("correct", ""))):
        feedback["correct"] = _localized_text(
            "The answer is a useful attempt. Verify it against the stated check before counting the card as complete.",
            "\u8fd9\u4e2a\u7b54\u6848\u662f\u4e00\u6b21\u6709\u4ef7\u503c\u7684\u5c1d\u8bd5\u3002\u5728\u5c06\u5361\u7247\u8ba1\u5165\u5b8c\u6210\u524d\uff0c\u8bf7\u5148\u6309\u58f0\u660e\u7684\u68c0\u67e5\u8fdb\u884c\u9a8c\u8bc1\u3002",
            language,
        )
        card.feedback = feedback

    learn = card.problem_statement or card.question or card.scenario
    try_step = card.suggested_workspace_action or card.deliverable
    verify = list(card.verification_steps) or ([card.validation_method] if card.validation_method else [])
    return card.model_copy(
        update={
            "learning_loop": {
                "learn": learn,
                "try": try_step,
                "verify": verify,
                "reflect": card.reflection_prompt,
                "return": card.return_with,
                "single_problem_focus": focus,
                "completion_requires_verification": True,
                "durable_mastery_claimed": False,
            },
            "single_problem_focus": focus,
            "completion_requires_verification": True,
        }
    )


def _make_guided_scenario_pack_card_from_catalog(
    pack: str,
    context: CardGenerationContext,
    card_type: str,
    language: str = "en-US",
) -> TrainingCardCandidateSnapshot | None:
    raw_pack = _load_guided_scenario_pack_catalog().get(pack)
    if not raw_pack:
        return None

    raw_card = raw_pack.get(card_type)
    if not isinstance(raw_card, dict):
        return None

    def _fallback_pack_focus_label(pack_name: str, language_name: str) -> str:
        is_chinese = language_name == "zh-CN"
        if pack_name == _GUIDED_SCENARIO_PACK_REMOTE:
            return "VS Code 远程工作区" if is_chinese else "VS Code remote workspace"
        if pack_name == _GUIDED_SCENARIO_PACK_DEBUG:
            return "VS Code 调试闭环" if is_chinese else "VS Code debug loop"
        if pack_name == _GUIDED_SCENARIO_PACK_FUNCTION:
            return "\u51fd\u6570\u5951\u7ea6\u5224\u65ad" if is_chinese else "function contract reading"
        if pack_name == _GUIDED_SCENARIO_PACK_RESOURCE:
            return "\u8d44\u6e90\u5230\u53ef\u4fe1\u77e5\u8bc6" if is_chinese else "resource to trusted knowledge"
        if pack_name == _GUIDED_SCENARIO_PACK_DEPENDENCY:
            return "\u4f9d\u8d56\u4e0e API \u638c\u63e1" if is_chinese else "dependency and API mastery"
        return pack_name.replace("_", " ")

    current_focus = _localized_string(raw_pack.get("currentFocus"), language) or _fallback_pack_focus_label(
        pack,
        language,
    )
    target_skill = _localized_string(raw_card.get("targetSkill"), language) or current_focus
    scenario = context.context_hint or _localized_string(raw_card.get("scenario"), language)
    next_step_key = "practiceNextStep" if card_type == "practice" else "flashNextStep"

    card = TrainingCardCandidateSnapshot(
        card_type=cast(TrainingCardType, card_type),
        scenario_pack=pack,
        title=_localized_string(raw_card.get("title"), language),
        why_now=_localized_string(raw_card.get("whyNow"), language),
        focus_area=_guided_pack_focus(context, current_focus),
        target_skill=_guided_pack_skill(context, target_skill),
        scenario=scenario,
        problem_statement=_localized_string(raw_card.get("problemStatement"), language),
        suggested_workspace_action=_localized_string(
            raw_card.get("suggestedWorkspaceAction"),
            language,
        ),
        api_hints=_string_list(raw_card.get("apiHints")),
        constraints=_localized_string_list(raw_card.get("constraints"), language),
        deliverable=_localized_string(raw_card.get("deliverable"), language),
        self_check=_localized_string_list(raw_card.get("selfCheck"), language),
        validation_method=_localized_string(raw_card.get("validationMethod"), language),
        learner_deliverables=_localized_string_list(raw_card.get("learnerDeliverables"), language),
        verification_steps=_localized_string_list(raw_card.get("verificationSteps"), language),
        success_signal=_localized_string(raw_card.get("successSignal"), language),
        hint_ladder=_localized_string_list(raw_card.get("hintLadder"), language),
        common_mistakes=_localized_string_list(raw_card.get("commonMistakes"), language),
        stuck_recovery=_localized_string(raw_card.get("stuckRecovery"), language),
        reflection_prompt=_localized_string(raw_card.get("reflectionPrompt"), language),
        return_with=_localized_string(raw_card.get("returnWith"), language),
        next_after_completion=
            _localized_string(raw_pack.get(next_step_key), language)
            or _localized_string(raw_card.get("returnWith"), language),
        expected_symbols=_string_list(raw_card.get("expectedSymbols")),
        files_to_touch=_string_list(raw_card.get("filesToTouch")),
        source_chain=_localized_string_list(raw_pack.get("sourceChain"), language),
        difficulty=context.difficulty or "medium",
    )

    if pack == _GUIDED_SCENARIO_PACK_FUNCTION:
        card = _normalize_function_guidance_card(card, language)

    if card_type == "flash":
        card.knowledge_type = _localized_string(raw_card.get("knowledgeType"), language)
        card.question = _localized_string(raw_card.get("question"), language)
        card.context = context.context_hint or _localized_string(raw_card.get("context"), language)
        card.answer_mode = _localized_string(raw_card.get("answerMode"), language) or "text"
        card.expected_answer = _localized_string(raw_card.get("expectedAnswer"), language)
        card.feedback = _feedback_dict(raw_card.get("feedback"), language)

    return card


def _guided_fact_text(value: object, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip()


def _guided_fact_path(value: object) -> str:
    path = _guided_fact_text(value, limit=480).replace("\\", "/")
    if path.startswith("<") and path.endswith(">"):
        return ""
    return path


_DEPENDENCY_GENERIC_IDENTIFIERS = frozenset(
    {
        "api",
        "dependency",
        "dependencies",
        "library",
        "package",
        "sdk",
        "usage",
        "use",
    }
)


def _dependency_identifier_candidates(dependency: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for raw_identifier in re.findall(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*", dependency):
        parts = [part.casefold() for part in raw_identifier.split(".")]
        if not parts or all(part in _DEPENDENCY_GENERIC_IDENTIFIERS for part in parts):
            continue
        for end in range(len(parts), 0, -1):
            candidate = ".".join(parts[:end])
            if (
                len(candidate) >= 3
                and candidate not in _DEPENDENCY_GENERIC_IDENTIFIERS
                and candidate not in seen
            ):
                candidates.append(candidate)
                seen.add(candidate)
    return candidates


def _matches_dependency_usage(dependency: str, identifier: str) -> bool:
    evidence_identifier = _guided_fact_text(identifier, limit=240).casefold().strip(".")
    if not evidence_identifier:
        return False
    return any(
        evidence_identifier == candidate
        or candidate.startswith(f"{evidence_identifier}.")
        or evidence_identifier.startswith(f"{candidate}.")
        for candidate in _dependency_identifier_candidates(dependency)
    )


def _verified_dependency_usage(
    context: CardGenerationContext,
    dependency: str,
) -> DependencyUsageEvidence | None:
    for evidence in context.dependency_usage_evidence:
        kind = _guided_fact_text(evidence.kind, limit=40).lower()
        identifier = _guided_fact_text(evidence.identifier, limit=240)
        summary = _guided_fact_text(evidence.summary, limit=320)
        path = _guided_fact_path(evidence.file_path)
        if not identifier or not summary or not _matches_dependency_usage(dependency, identifier):
            continue
        if kind in {"import", "call"} and path:
            return evidence
        if kind == "declaration" and _guided_fact_text(evidence.summary, limit=320):
            return evidence
    return None


def _resource_knowledge_evidence(
    context: CardGenerationContext,
) -> tuple[ResourceKnowledgeEvidence | None, str, str, str, str]:
    evidence = context.resource_knowledge_evidence
    if evidence is None:
        return None, "", "", "", ""
    resource_id = _guided_fact_text(evidence.resource_id, limit=160)
    fragment_id = _guided_fact_text(evidence.fragment_id, limit=160)
    source_type = _guided_fact_text(evidence.source_type, limit=120)
    focus = _guided_fact_text(evidence.focus_area, limit=240)
    summary = _guided_fact_text(evidence.summary, limit=480)
    if not resource_id or not fragment_id or not source_type or not focus or not summary:
        return evidence, "", "", "", ""
    return evidence, fragment_id, source_type, focus, summary


def _guided_unique_items(*groups: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            cleaned = _guided_fact_text(value)
            if cleaned and cleaned not in seen:
                result.append(cleaned)
                seen.add(cleaned)
    return result


def _guided_remote_name(context: CardGenerationContext) -> str:
    direct_name = _guided_fact_text(context.remote_workspace_name)
    if direct_name:
        return direct_name
    for fact in context.remote_workspace_facts:
        cleaned = _guided_fact_text(fact)
        lowered = cleaned.lower()
        for prefix in ("remote identity:", "remote_name:", "remote:"):
            if lowered.startswith(prefix):
                return cleaned[len(prefix) :].strip()
    return ""


def _guided_function_anchor(context: CardGenerationContext, path: str) -> str:
    source = _guided_fact_text(
        context.current_file_selection
        or context.current_file_excerpt
        or context.current_file_content,
        limit=2400,
    )
    if not source:
        return ""
    for pattern in (
        r"\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)",
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>",
    ):
        match = re.search(pattern, source)
        if match:
            return _localized_text(
                f"function `{match.group(1)}` in `{path}`",
                f"\u51fd\u6570`{match.group(1)}`\u4f4d\u4e8e`{path}`",
                context.response_language,
            )
    selection_range = _guided_fact_text(context.current_file_selection_range, limit=120)
    if context.current_file_selection:
        range_label = _localized_text(
            selection_range or "range not supplied",
            selection_range or "\u672a\u63d0\u4f9b\u8303\u56f4",
            context.response_language,
        )
        return _localized_text(
            f"selected code ({range_label}) in `{path}`",
            f"`{path}`\u4e2d\u7684\u9009\u4e2d\u4ee3\u7801\uff08{range_label}\uff09",
            context.response_language,
        )
    return _localized_text(
        f"current code in `{path}`",
        f"`{path}`\u4e2d\u7684\u5f53\u524d\u4ee3\u7801",
        context.response_language,
    )


def _guided_text(context: CardGenerationContext, english: str, chinese: str) -> str:
    return _localized_text(english, chinese, context.response_language)


def _guided_pack_label(pack: str, language: str | None) -> str:
    labels = {
        _GUIDED_SCENARIO_PACK_FUNCTION: ("function guidance", "\u51fd\u6570\u63d0\u793a"),
        _GUIDED_SCENARIO_PACK_DEBUG: ("debug loop", "\u8c03\u8bd5\u95ed\u73af"),
        _GUIDED_SCENARIO_PACK_REMOTE: ("remote workspace", "\u8fdc\u7a0b\u5de5\u4f5c\u533a"),
        _GUIDED_SCENARIO_PACK_RESOURCE: ("resource knowledge", "\u8d44\u6e90\u77e5\u8bc6"),
        _GUIDED_SCENARIO_PACK_DEPENDENCY: ("dependency and API mastery", "\u4f9d\u8d56\u4e0e API \u638c\u63e1"),
    }
    english, chinese = labels.get(pack, (pack.replace("_", " "), pack.replace("_", " ")))
    return _localized_text(english, chinese, language)


def _guided_scenario_skeleton_source(context: CardGenerationContext) -> str:
    return _guided_text(
        context,
        "Guided scenario skeleton",
        "\u5f15\u5bfc\u573a\u666f\u9aa8\u67b6",
    )


def _guided_missing_fact_card(
    card: TrainingCardCandidateSnapshot,
    *,
    pack: str,
    missing: str,
    missing_chinese: str,
    context: CardGenerationContext,
) -> TrainingCardCandidateSnapshot:
    missing_display = _guided_text(context, missing, missing_chinese)
    label = _guided_pack_label(pack, context.response_language)
    note = _guided_text(
        context,
        f"Grounding unavailable: {missing_display}.",
        f"\u7f3a\u5c11\u53ef\u9a8c\u8bc1\u4e8b\u5b9e\uff1a{missing_display}\u3002",
    )
    return card.model_copy(
        update={
            "status": "needs_primer",
            "files_to_touch": [],
            "why_now": (
                f"{card.why_now} {note} "
                + _guided_text(
                    context,
                    "Trainer will not treat catalog examples or placeholders as workspace facts.",
                    "Trainer \u4e0d\u4f1a\u628a\u76ee\u5f55\u793a\u4f8b\u6216\u5360\u4f4d\u7b26\u5f53\u4f5c\u5de5\u4f5c\u533a\u4e8b\u5b9e\u3002",
                )
            ).strip(),
            "suggested_workspace_action": _guided_text(
                context,
                f"Provide {missing_display}; then regenerate this {label} card from those facts.",
                f"\u8bf7\u63d0\u4f9b{missing_display}\uff0c\u518d\u7528\u8fd9\u4e9b\u4e8b\u5b9e\u91cd\u65b0\u751f\u6210\u8fd9\u5f20{label}\u5361\u3002",
            ),
            "constraints": _guided_unique_items(
                card.constraints,
                [
                    note,
                    _guided_text(
                        context,
                        "Do not treat catalog paths or placeholders as current workspace facts.",
                        "\u4e0d\u8981\u628a\u76ee\u5f55\u8def\u5f84\u6216\u5360\u4f4d\u7b26\u5f53\u4f5c\u5f53\u524d\u5de5\u4f5c\u533a\u4e8b\u5b9e\u3002",
                    ),
                ],
            ),
            "learner_deliverables": [
                _guided_text(
                    context,
                    f"Provide {missing_display}.",
                    f"\u8bf7\u63d0\u4f9b{missing_display}\u3002",
                ),
                _guided_text(
                    context,
                    "Name the supplied fact that will anchor the next card.",
                    "\u8bf4\u660e\u54ea\u6761\u63d0\u4f9b\u7684\u4e8b\u5b9e\u5c06\u9501\u5b9a\u4e0b\u4e00\u5f20\u5361\u3002",
                ),
            ],
            "verification_steps": [
                _guided_text(
                    context,
                    f"Provide {missing_display}.",
                    f"\u8bf7\u63d0\u4f9b{missing_display}\u3002",
                ),
                _guided_text(
                    context,
                    "Regenerate the card only after the facts can be verified.",
                    "\u53ea\u5728\u8fd9\u4e9b\u4e8b\u5b9e\u53ef\u9a8c\u8bc1\u540e\u518d\u91cd\u65b0\u751f\u6210\u5361\u7247\u3002",
                ),
            ],
            "validation_method": _guided_text(
                context,
                f"Validate the supplied {missing_display} before attempting the exercise.",
                f"\u5f00\u59cb\u7ec3\u4e60\u524d\uff0c\u5148\u9a8c\u8bc1\u63d0\u4f9b\u7684{missing_display}\u3002",
            ),
            "success_signal": _guided_text(
                context,
                f"Verified workspace facts are available for this {label} card.",
                f"\u8fd9\u5f20{label}\u5361\u5df2\u5177\u5907\u53ef\u9a8c\u8bc1\u7684\u5de5\u4f5c\u533a\u4e8b\u5b9e\u3002",
            ),
            "return_with": _guided_text(
                context,
                f"Return with {missing_display}.",
                f"\u8bf7\u5e26\u56de{missing_display}\u3002",
            ),
            "source_chain": [
                _guided_scenario_skeleton_source(context),
                note,
            ],
        }
    )


def _apply_guided_workspace_facts(
    card: TrainingCardCandidateSnapshot,
    *,
    pack: str,
    context: CardGenerationContext,
) -> TrainingCardCandidateSnapshot:
    if pack not in {
        _GUIDED_SCENARIO_PACK_REMOTE,
        _GUIDED_SCENARIO_PACK_DEBUG,
        _GUIDED_SCENARIO_PACK_FUNCTION,
        _GUIDED_SCENARIO_PACK_RESOURCE,
        _GUIDED_SCENARIO_PACK_DEPENDENCY,
    }:
        return card

    if pack == _GUIDED_SCENARIO_PACK_RESOURCE:
        resource_id = _guided_fact_text(context.resource_id, limit=160)
        evidence, fragment_id, source_type, knowledge_focus, source_context = _resource_knowledge_evidence(
            context
        )
        trust_state = _derive_resource_trust_state(context)
        evidence_resource_id = _guided_fact_text(
            evidence.resource_id if evidence is not None else "",
            limit=160,
        )
        if (
            not resource_id
            or evidence_resource_id != resource_id
            or not fragment_id
            or not source_type
            or not knowledge_focus
            or not source_context
        ):
            return _guided_missing_fact_card(
                card,
                pack=pack,
                missing="a trusted indexed resource fragment and knowledge atom",
                missing_chinese="\u53ef\u4fe1\u5df2\u7d22\u5f15\u8d44\u6599\u7684\u7247\u6bb5\u4e0e\u77e5\u8bc6\u539f\u5b50",
                context=context,
            ).model_copy(update={"trust_state": trust_state})
        if trust_state != "trusted":
            return _guided_missing_fact_card(
                card,
                pack=pack,
                missing="a trusted indexed resource",
                missing_chinese="\u4e00\u4efd\u53ef\u4fe1\u4e14\u5df2\u7d22\u5f15\u7684\u8d44\u6599",
                context=context,
            ).model_copy(update={"trust_state": trust_state})
        return card.model_copy(
            update={
                "status": "candidate",
                "trust_state": trust_state,
                "files_to_touch": [],
                "why_now": _guided_text(
                    context,
                    f"{card.why_now} Coach confirmed trusted resource `{resource_id}` for `{knowledge_focus}`.",
                    f"{card.why_now} Coach \u5df2\u786e\u8ba4\u53ef\u4fe1\u8d44\u6599`{resource_id}`\u53ef\u7528\u4e8e`{knowledge_focus}`\u3002",
                ).strip(),
                "suggested_workspace_action": _guided_text(
                    context,
                    f"Read trusted resource `{resource_id}`, state one knowledge atom about `{knowledge_focus}`, then queue one next card.",
                    f"\u9605\u8bfb\u53ef\u4fe1\u8d44\u6599`{resource_id}`\uff0c\u8bf4\u660e\u4e00\u4e2a\u5173\u4e8e`{knowledge_focus}`\u7684\u77e5\u8bc6\u539f\u5b50\uff0c\u518d\u6392\u5165\u4e00\u5f20\u4e0b\u4e00\u6b65\u5361\u7247\u3002",
                ),
                "verification_steps": _guided_unique_items(
                    card.verification_steps,
                    [
                        _guided_text(
                            context,
                            f"Confirm that `{resource_id}` remains trusted before extracting `{knowledge_focus}`.",
                            f"\u63d0\u53d6`{knowledge_focus}`\u524d\uff0c\u786e\u8ba4`{resource_id}`\u4ecd\u5904\u4e8e\u53ef\u4fe1\u72b6\u6001\u3002",
                        ),
                        _guided_text(
                            context,
                            "Return one knowledge atom and the next card it should create.",
                            "\u5e26\u56de\u4e00\u4e2a\u77e5\u8bc6\u539f\u5b50\u53ca\u5176\u5e94\u751f\u6210\u7684\u4e0b\u4e00\u5f20\u5361\u7247\u3002",
                        ),
                    ],
                ),
                "source_chain": [
                    _guided_text(context, f"Resource ID: {resource_id}", f"\u8d44\u6599 ID\uff1a{resource_id}"),
                    _guided_text(context, f"Fragment ID: {fragment_id}", f"\u7247\u6bb5 ID\uff1a{fragment_id}"),
                    _guided_text(context, f"Source type: {source_type}", f"\u6765\u6e90\u7c7b\u578b\uff1a{source_type}"),
                    _guided_text(context, f"Trust state: {trust_state}", f"\u53ef\u4fe1\u72b6\u6001\uff1a{trust_state}"),
                    _guided_text(context, f"Knowledge atom: {knowledge_focus}", f"\u77e5\u8bc6\u539f\u5b50\uff1a{knowledge_focus}"),
                    _guided_text(context, f"Evidence: {source_context}", f"\u8bc1\u636e\uff1a{source_context}"),
                ],
            }
        )

    if pack == _GUIDED_SCENARIO_PACK_DEPENDENCY:
        dependency = _guided_fact_text(context.target_skill or context.focus_area, limit=240)
        usage_evidence = _verified_dependency_usage(context, dependency)
        if not dependency or usage_evidence is None:
            return _guided_missing_fact_card(
                card,
                pack=pack,
                missing="a dependency/API name and a verified import, call, or declaration",
                missing_chinese="\u4f9d\u8d56/API \u540d\u79f0\u53ca\u5df2\u9a8c\u8bc1\u7684\u5bfc\u5165\u3001\u8c03\u7528\u6216\u58f0\u660e",
                context=context,
            )
        evidence_path = _guided_fact_path(usage_evidence.file_path)
        evidence_kind = _guided_fact_text(usage_evidence.kind, limit=40).lower()
        evidence_identifier = _guided_fact_text(usage_evidence.identifier, limit=240)
        evidence_summary = _guided_fact_text(usage_evidence.summary, limit=320)
        if evidence_kind == "declaration":
            context_source = _guided_text(
                context,
                f"Verified declaration: {evidence_summary}",
                f"\u5df2\u9a8c\u8bc1\u58f0\u660e\uff1a{evidence_summary}",
            )
        else:
            context_source = _guided_text(
                context,
                f"Verified {evidence_kind}: {evidence_summary} in {evidence_path}",
                f"\u5df2\u9a8c\u8bc1{evidence_kind}\uff1a{evidence_summary}\uff0c\u4f4d\u4e8e{evidence_path}",
            )
        return card.model_copy(
            update={
                "status": "candidate",
                "files_to_touch": [evidence_path] if evidence_path else [],
                "why_now": _guided_text(
                    context,
                    f"{card.why_now} Coach verified `{dependency}` through {evidence_kind} `{evidence_identifier}`.",
                    f"{card.why_now} Coach \u901a\u8fc7{evidence_kind}\u9a8c\u8bc1\u4e86`{dependency}`\uff08`{evidence_identifier}`\uff09\u3002",
                ).strip(),
                "suggested_workspace_action": _guided_text(
                    context,
                    f"Use `{dependency}` through the verified usage, then record one output before claiming mastery.",
                    f"\u901a\u8fc7\u5df2\u9a8c\u8bc1\u7684\u4f7f\u7528\u65b9\u5f0f\u4f7f\u7528`{dependency}`\uff0c\u5e76\u5728\u58f0\u79f0\u638c\u63e1\u524d\u8bb0\u5f55\u4e00\u4e2a\u8f93\u51fa\u3002",
                ),
                "verification_steps": _guided_unique_items(
                    card.verification_steps,
                    [
                        _guided_text(
                            context,
                            f"Exercise one real capability of `{dependency}` through the verified usage.",
                            f"\u901a\u8fc7\u5df2\u9a8c\u8bc1\u7684\u4f7f\u7528\u65b9\u5f0f\u7ec3\u4e60`{dependency}`\u7684\u4e00\u9879\u771f\u5b9e\u80fd\u529b\u3002",
                        ),
                        _guided_text(
                            context,
                            "Return one verified output, response, or assertion and one sharp edge you checked.",
                            "\u5e26\u56de\u4e00\u4e2a\u5df2\u9a8c\u8bc1\u7684\u8f93\u51fa\u3001\u54cd\u5e94\u6216\u65ad\u8a00\uff0c\u4ee5\u53ca\u4e00\u4e2a\u5df2\u68c0\u67e5\u7684\u8fb9\u7f18\u6761\u4ef6\u3002",
                        ),
                    ],
                ),
                "source_chain": [
                    _guided_text(context, f"Dependency/API: {dependency}", f"\u4f9d\u8d56/API\uff1a{dependency}"),
                    context_source,
                    _guided_text(
                        context,
                        "Verification target: one real output",
                        "\u9a8c\u8bc1\u76ee\u6807\uff1a\u4e00\u4e2a\u771f\u5b9e\u8f93\u51fa",
                    ),
                ],
            }
        )

    path = _guided_fact_path(context.current_file_path)
    workspace_root = _guided_fact_path(context.workspace_root_path)

    if pack == _GUIDED_SCENARIO_PACK_FUNCTION:
        anchor = _guided_function_anchor(context, path) if path else ""
        if not anchor:
            return _guided_missing_fact_card(
                card,
                pack=pack,
                missing="a code-file path and selected code or file content",
                missing_chinese="\u4ee3\u7801\u6587\u4ef6\u8def\u5f84\u4e0e\u9009\u4e2d\u4ee3\u7801\u6216\u6587\u4ef6\u5185\u5bb9",
                context=context,
            )
        return card.model_copy(
            update={
                "files_to_touch": [path],
                "why_now": _guided_text(
                    context,
                    f"{card.why_now} Coach supplied {anchor}; use that real code instead of a template call site.",
                    f"{card.why_now} Coach \u5df2\u63d0\u4f9b{anchor}\uff1b\u8bf7\u4f7f\u7528\u8fd9\u6bb5\u771f\u5b9e\u4ee3\u7801\uff0c\u800c\u4e0d\u662f\u6a21\u677f\u8c03\u7528\u70b9\u3002",
                ).strip(),
                "suggested_workspace_action": _guided_text(
                    context,
                    f"Open `{path}`, inspect {anchor} with Hover or Signature Help, then state its contract before editing.",
                    f"\u6253\u5f00`{path}`\uff0c\u7528 Hover \u6216 Signature Help \u68c0\u67e5{anchor}\uff0c\u518d\u5728\u7f16\u8f91\u524d\u8bf4\u6e05\u5176 contract\u3002",
                ),
                "constraints": _guided_unique_items(
                    card.constraints,
                    [
                        _guided_text(
                            context,
                            f"Keep the investigation anchored to {anchor}.",
                            f"\u5c06\u8c03\u67e5\u9501\u5b9a\u5728{anchor}\u3002",
                        )
                    ],
                ),
                "verification_steps": _guided_unique_items(
                    card.verification_steps,
                    [
                        _guided_text(
                            context,
                            f"Inspect {anchor} in `{path}` with editor guidance.",
                            f"\u5728`{path}`\u4e2d\u7528\u7f16\u8f91\u5668\u63d0\u793a\u68c0\u67e5{anchor}\u3002",
                        ),
                        _guided_text(
                            context,
                            f"Record the parameter and return contract supported by the current code in `{path}`.",
                            f"\u8bb0\u5f55`{path}`\u5f53\u524d\u4ee3\u7801\u652f\u6301\u7684\u53c2\u6570\u548c return contract\u3002",
                        ),
                    ],
                ),
                "source_chain": [
                    _guided_scenario_skeleton_source(context),
                    _guided_text(context, f"Current file: {path}", f"\u5f53\u524d\u6587\u4ef6\uff1a{path}"),
                    _guided_text(context, f"Code anchor: {anchor}", f"\u4ee3\u7801\u951a\u70b9\uff1a{anchor}"),
                ],
            }
        )

    if pack == _GUIDED_SCENARIO_PACK_DEBUG:
        diagnostics = [
            _guided_fact_text(item, limit=360)
            for item in context.current_file_diagnostics
            if _guided_fact_text(item, limit=360)
        ]
        if not path or not diagnostics:
            return _guided_missing_fact_card(
                card,
                pack=pack,
                missing="a current file path and at least one diagnostic",
                missing_chinese="\u5f53\u524d\u6587\u4ef6\u8def\u5f84\u4e0e\u81f3\u5c11\u4e00\u6761\u8bca\u65ad",
                context=context,
            )
        diagnostic = diagnostics[0]
        return card.model_copy(
            update={
                "files_to_touch": [path],
                "why_now": _guided_text(
                    context,
                    f"{card.why_now} Coach supplied a diagnostic for `{path}`: `{diagnostic}`.",
                    f"{card.why_now} Coach \u5df2\u63d0\u4f9b`{path}`\u7684\u8bca\u65ad\uff1a`{diagnostic}`\u3002",
                ).strip(),
                "suggested_workspace_action": _guided_text(
                    context,
                    f"Reproduce the diagnostic in `{path}` before editing, then pause at the first useful state boundary.",
                    f"\u7f16\u8f91\u524d\u5148\u5728`{path}`\u4e2d\u590d\u73b0\u8bca\u65ad\uff0c\u7136\u540e\u5728\u7b2c\u4e00\u4e2a\u6709\u7528\u7684\u72b6\u6001\u8fb9\u754c\u6682\u505c\u3002",
                ),
                "constraints": _guided_unique_items(
                    card.constraints,
                    [
                        _guided_text(
                            context,
                            f"Keep the debug loop anchored to the reported diagnostic in `{path}`.",
                            f"\u5c06\u8c03\u8bd5\u95ed\u73af\u9501\u5b9a\u5728`{path}`\u4e2d\u5df2\u62a5\u544a\u7684\u8bca\u65ad\u3002",
                        )
                    ],
                ),
                "verification_steps": _guided_unique_items(
                    card.verification_steps,
                    [
                        _guided_text(
                            context,
                            f"Reproduce the reported diagnostic in `{path}`: `{diagnostic}`.",
                            f"\u5728`{path}`\u4e2d\u590d\u73b0\u5df2\u62a5\u544a\u7684\u8bca\u65ad\uff1a`{diagnostic}`\u3002",
                        ),
                        _guided_text(
                            context,
                            f"Record the first verified bad state before changing `{path}`.",
                            f"\u4fee\u6539`{path}`\u524d\uff0c\u8bb0\u5f55\u7b2c\u4e00\u4e2a\u5df2\u9a8c\u8bc1\u7684\u9519\u8bef\u72b6\u6001\u3002",
                        ),
                    ],
                ),
                "source_chain": [
                    _guided_scenario_skeleton_source(context),
                    _guided_text(context, f"Current file: {path}", f"\u5f53\u524d\u6587\u4ef6\uff1a{path}"),
                    _guided_text(context, f"Diagnostic: {diagnostic}", f"\u8bca\u65ad\uff1a{diagnostic}"),
                ],
            }
        )

    remote_name = _guided_remote_name(context)
    boundary = workspace_root or path
    if not remote_name or not boundary:
        return _guided_missing_fact_card(
            card,
            pack=pack,
            missing="a remote identity and a current workspace path or file path",
            missing_chinese="\u8fdc\u7a0b\u8eab\u4efd\u4e0e\u5f53\u524d\u5de5\u4f5c\u533a\u8def\u5f84\u6216\u6587\u4ef6\u8def\u5f84",
            context=context,
        )
    files_to_touch = [path] if path else []
    return card.model_copy(
        update={
            "files_to_touch": files_to_touch,
            "why_now": _guided_text(
                context,
                f"{card.why_now} Coach supplied remote identity `{remote_name}` and boundary `{boundary}`.",
                f"{card.why_now} Coach \u5df2\u63d0\u4f9b\u8fdc\u7a0b\u8eab\u4efd`{remote_name}`\u548c\u8fb9\u754c`{boundary}`\u3002",
            ).strip(),
            "suggested_workspace_action": _guided_text(
                context,
                f"Inspect remote identity `{remote_name}` against workspace boundary `{boundary}` before making a credential decision.",
                f"\u5728\u505a\u51ed\u636e\u51b3\u7b56\u524d\uff0c\u5148\u5bf9\u7167\u8fdc\u7a0b\u8eab\u4efd`{remote_name}`\u4e0e\u5de5\u4f5c\u533a\u8fb9\u754c`{boundary}`\u3002",
            ),
            "constraints": _guided_unique_items(
                card.constraints,
                [
                    _guided_text(
                        context,
                        f"Use only the reported remote identity `{remote_name}` and boundary `{boundary}`.",
                        f"\u53ea\u4f7f\u7528\u5df2\u62a5\u544a\u7684\u8fdc\u7a0b\u8eab\u4efd`{remote_name}`\u548c\u8fb9\u754c`{boundary}`\u3002",
                    )
                ],
            ),
            "verification_steps": _guided_unique_items(
                card.verification_steps,
                [
                    _guided_text(
                        context,
                        f"Confirm remote identity `{remote_name}` for workspace boundary `{boundary}`.",
                        f"\u786e\u8ba4\u5de5\u4f5c\u533a\u8fb9\u754c`{boundary}`\u5bf9\u5e94\u7684\u8fdc\u7a0b\u8eab\u4efd`{remote_name}`\u3002",
                    ),
                    _guided_text(
                        context,
                        f"State the credential decision for `{remote_name}` before touching project code.",
                        f"\u89e6\u78b0\u9879\u76ee\u4ee3\u7801\u524d\uff0c\u8bf4\u660e`{remote_name}`\u7684\u51ed\u636e\u51b3\u7b56\u3002",
                    ),
                ],
            ),
            "source_chain": [
                _guided_scenario_skeleton_source(context),
                _guided_text(
                    context,
                    f"Remote identity: {remote_name}",
                    f"\u8fdc\u7a0b\u8eab\u4efd\uff1a{remote_name}",
                ),
                _guided_text(
                    context,
                    f"Workspace boundary: {boundary}",
                    f"\u5de5\u4f5c\u533a\u8fb9\u754c\uff1a{boundary}",
                ),
            ],
        }
    )


def _build_guided_scenario_pack_card(
    pack: str,
    context: CardGenerationContext,
    card_type: str,
    language: str = "en-US",
) -> TrainingCardCandidateSnapshot:
    catalog_card = _make_guided_scenario_pack_card_from_catalog(pack, context, card_type, language)
    if catalog_card is not None:
        if card_type == "practice":
            catalog_card = catalog_card.model_copy(update={"status": "needs_primer"})
        return catalog_card

    if pack == _GUIDED_SCENARIO_PACK_RESOURCE:
        focus = _guided_pack_focus(context, _guided_text(context, "resource knowledge", "\u8d44\u6599\u77e5\u8bc6"))
        if card_type == "flash":
            return TrainingCardCandidateSnapshot(
                card_type="flash",
                scenario_pack=pack,
                title=_guided_text(context, "Flash: Resource provenance", "\u95ea\u8bb0\uff1a\u8d44\u6599\u6eaf\u6e90"),
                why_now=_guided_text(
                    context,
                    "Recall the source and concept before treating resource content as learned knowledge.",
                    "\u5728\u5c06\u8d44\u6599\u5185\u5bb9\u5f53\u4f5c\u5df2\u638c\u63e1\u77e5\u8bc6\u524d\uff0c\u5148\u56de\u5fc6\u6765\u6e90\u4e0e\u6982\u5ff5\u3002",
                ),
                focus_area=focus,
                target_skill=_guided_pack_skill(context, focus),
                knowledge_type="resource_knowledge",
                question=_guided_text(
                    context,
                    "What provenance and concept must a trusted resource knowledge atom retain?",
                    "\u4e00\u4e2a\u53ef\u4fe1\u8d44\u6599\u77e5\u8bc6\u539f\u5b50\u5fc5\u987b\u4fdd\u7559\u54ea\u4e9b\u6765\u6e90\u548c\u6982\u5ff5\u4fe1\u606f\uff1f",
                ),
                context=_guided_text(context, "Tie the answer to the indexed resource, not a generic summary.", "\u5c06\u7b54\u6848\u7ed1\u5b9a\u5230\u5df2\u7d22\u5f15\u8d44\u6599\uff0c\u4e0d\u8981\u53ea\u7ed9\u51fa\u6cdb\u5316\u6458\u8981\u3002"),
                answer_mode="text",
                expected_answer=_guided_text(
                    context,
                    "Name the resource, its trust state, the extracted concept, and the next card it supports.",
                    "\u8bf4\u660e\u8d44\u6599\u3001\u5176\u53ef\u4fe1\u72b6\u6001\u3001\u63d0\u53d6\u6982\u5ff5\u548c\u5b83\u652f\u6301\u7684\u4e0b\u4e00\u5f20\u5361\u3002",
                ),
                validation_method=_guided_text(context, "Check the indexed resource and its trust state.", "\u6838\u5bf9\u5df2\u7d22\u5f15\u8d44\u6599\u53ca\u5176\u53ef\u4fe1\u72b6\u6001\u3002"),
                status="needs_primer",
            )
        return TrainingCardCandidateSnapshot(
            card_type="practice",
            scenario_pack=pack,
            title=_guided_text(context, "Practice: Turn a resource into trusted knowledge", "\u7ec3\u4e60\uff1a\u628a\u8d44\u6599\u53d8\u6210\u53ef\u4fe1\u77e5\u8bc6"),
            why_now=_guided_text(context, "A resource becomes useful only when its provenance and one concept are explicit.", "\u53ea\u6709\u6765\u6e90\u548c\u4e00\u4e2a\u6982\u5ff5\u660e\u786e\u65f6\uff0c\u8d44\u6599\u624d\u80fd\u771f\u6b63\u7528\u4e8e\u5b66\u4e60\u3002"),
            focus_area=focus,
            target_skill=_guided_pack_skill(context, focus),
            problem_statement=_guided_text(context, "Extract one trusted knowledge atom and queue its next card.", "\u63d0\u53d6\u4e00\u4e2a\u53ef\u4fe1\u77e5\u8bc6\u539f\u5b50\uff0c\u5e76\u6392\u5165\u5b83\u7684\u4e0b\u4e00\u5f20\u5361\u3002"),
            suggested_workspace_action=_guided_text(context, "Read the resource before extracting one precise concept.", "\u63d0\u53d6\u4e00\u4e2a\u7cbe\u786e\u6982\u5ff5\u524d\uff0c\u5148\u9605\u8bfb\u8d44\u6599\u3002"),
            deliverable=_guided_text(context, "One knowledge atom with provenance and one next card.", "\u4e00\u4e2a\u5e26\u6765\u6e90\u7684\u77e5\u8bc6\u539f\u5b50\u548c\u4e00\u5f20\u4e0b\u4e00\u6b65\u5361\u3002"),
            validation_method=_guided_text(context, "Confirm the resource is trusted before using it.", "\u4f7f\u7528\u524d\u786e\u8ba4\u8d44\u6599\u53ef\u4fe1\u3002"),
            status="needs_primer",
        )

    if pack == _GUIDED_SCENARIO_PACK_DEPENDENCY:
        focus = _guided_pack_focus(context, _guided_text(context, "dependency and API mastery", "\u4f9d\u8d56\u4e0e API \u638c\u63e1"))
        if card_type == "flash":
            return TrainingCardCandidateSnapshot(
                card_type="flash",
                scenario_pack=pack,
                title=_guided_text(context, "Flash: Dependency/API safe usage", "\u95ea\u8bb0\uff1a\u4f9d\u8d56/API \u5b89\u5168\u4f7f\u7528"),
                why_now=_guided_text(context, "Recall a capability, sharp edge, and safe rule before relying on the API.", "\u4f9d\u8d56 API \u524d\uff0c\u5148\u56de\u5fc6\u4e00\u9879\u80fd\u529b\u3001\u4e00\u4e2a\u8fb9\u7f18\u4e0e\u4e00\u6761\u5b89\u5168\u89c4\u5219\u3002"),
                focus_area=focus,
                target_skill=_guided_pack_skill(context, focus),
                knowledge_type="dependency_mastery",
                question=_guided_text(context, "What capability, sharp edge, and safe usage rule matter for this dependency/API?", "\u8fd9\u4e2a\u4f9d\u8d56/API \u7684\u54ea\u9879\u80fd\u529b\u3001\u8fb9\u7f18\u548c\u5b89\u5168\u4f7f\u7528\u89c4\u5219\u6700\u91cd\u8981\uff1f"),
                context=_guided_text(context, "Answer from one declared dependency/API context.", "\u4ece\u4e00\u4e2a\u5df2\u58f0\u660e\u7684\u4f9d\u8d56/API \u4e0a\u4e0b\u6587\u4f5c\u7b54\u3002"),
                answer_mode="text",
                expected_answer=_guided_text(context, "State one capability, one sharp edge, and one safe rule tied to the real context.", "\u8bf4\u660e\u4e00\u9879\u80fd\u529b\u3001\u4e00\u4e2a\u8fb9\u7f18\u548c\u4e00\u6761\u7ed1\u5b9a\u771f\u5b9e\u4e0a\u4e0b\u6587\u7684\u5b89\u5168\u89c4\u5219\u3002"),
                validation_method=_guided_text(context, "Check the answer against one real usage context.", "\u7528\u4e00\u4e2a\u771f\u5b9e\u4f7f\u7528\u4e0a\u4e0b\u6587\u6838\u5bf9\u7b54\u6848\u3002"),
                hint_ladder=[
                    _guided_text(
                        context,
                        "Start with the verified import, call, or declaration.",
                        "\u5148\u4ece\u5df2\u9a8c\u8bc1\u7684\u5bfc\u5165\u3001\u8c03\u7528\u6216\u58f0\u660e\u5f00\u59cb\u3002",
                    ),
                    _guided_text(
                        context,
                        "Name one observable output before describing an edge case.",
                        "\u5148\u8bf4\u660e\u4e00\u4e2a\u53ef\u89c2\u5bdf\u8f93\u51fa\uff0c\u518d\u63cf\u8ff0\u8fb9\u7f18\u60c5\u51b5\u3002",
                    ),
                ],
                common_mistakes=[
                    _guided_text(
                        context,
                        "Treating a package name or free-form hint as proof of usage.",
                        "\u628a\u5305\u540d\u6216\u81ea\u7531\u63d0\u793a\u5f53\u4f5c\u4f7f\u7528\u8bc1\u636e\u3002",
                    ),
                    _guided_text(
                        context,
                        "Claiming mastery without one checked output.",
                        "\u6ca1\u6709\u4e00\u4e2a\u5df2\u68c0\u67e5\u8f93\u51fa\u5c31\u58f0\u79f0\u5df2\u638c\u63e1\u3002",
                    ),
                ],
                feedback={
                    "correct": _guided_text(
                        context,
                        "Good. The API claim is tied to a verified use and output.",
                        "\u5f88\u597d\u3002\u8fd9\u4e2a API \u5224\u65ad\u5df2\u7ed1\u5b9a\u5230\u53ef\u9a8c\u8bc1\u7684\u4f7f\u7528\u4e0e\u8f93\u51fa\u3002",
                    ),
                    "incorrect": _guided_text(
                        context,
                        "Return to the verified usage and record one observable output.",
                        "\u56de\u5230\u5df2\u9a8c\u8bc1\u7684\u4f7f\u7528\u5904\uff0c\u8bb0\u5f55\u4e00\u4e2a\u53ef\u89c2\u5bdf\u8f93\u51fa\u3002",
                    ),
                },
                next_after_completion=_guided_text(
                    context,
                    "Return with the verified output and one checked edge case.",
                    "\u5e26\u56de\u5df2\u9a8c\u8bc1\u8f93\u51fa\u548c\u4e00\u4e2a\u5df2\u68c0\u67e5\u7684\u8fb9\u7f18\u60c5\u51b5\u3002",
                ),
                status="needs_primer",
            )
        return TrainingCardCandidateSnapshot(
            card_type="practice",
            scenario_pack=pack,
            title=_guided_text(context, "Practice: Verify one dependency/API capability", "\u7ec3\u4e60\uff1a\u9a8c\u8bc1\u4e00\u9879\u4f9d\u8d56/API \u80fd\u529b"),
            why_now=_guided_text(context, "Mastery needs one verified output in the real API context.", "\u638c\u63e1\u9700\u8981\u5728\u771f\u5b9e API \u4e0a\u4e0b\u6587\u4e2d\u4ea7\u751f\u4e00\u4e2a\u5df2\u9a8c\u8bc1\u8f93\u51fa\u3002"),
            focus_area=focus,
            target_skill=_guided_pack_skill(context, focus),
            problem_statement=_guided_text(context, "Use one real dependency/API capability and verify one output.", "\u4f7f\u7528\u4e00\u9879\u771f\u5b9e\u4f9d\u8d56/API \u80fd\u529b\u5e76\u9a8c\u8bc1\u4e00\u4e2a\u8f93\u51fa\u3002"),
            suggested_workspace_action=_guided_text(context, "Keep the exercise to one API call and one check.", "\u5c06\u7ec3\u4e60\u9650\u5b9a\u4e3a\u4e00\u6b21 API \u8c03\u7528\u548c\u4e00\u6b21\u68c0\u67e5\u3002"),
            deliverable=_guided_text(context, "One verified output and one safe usage note.", "\u4e00\u4e2a\u5df2\u9a8c\u8bc1\u8f93\u51fa\u548c\u4e00\u6761\u5b89\u5168\u4f7f\u7528\u7b14\u8bb0\u3002"),
            validation_method=_guided_text(context, "Run one focused check against the dependency/API output.", "\u9488\u5bf9\u4f9d\u8d56/API \u8f93\u51fa\u8fd0\u884c\u4e00\u6b21\u805a\u7126\u68c0\u67e5\u3002"),
            status="needs_primer",
        )

    if card_type == "flash":
        if pack == _GUIDED_SCENARIO_PACK_REMOTE:
            return TrainingCardCandidateSnapshot(
                card_type="flash",
                scenario_pack=pack,
                title="Flash: Remote workspace boundary",
                focus_area=_guided_pack_focus(context, "VS Code remote workspace"),
                target_skill=_guided_pack_skill(context, "remote workspace boundary"),
                knowledge_type="engineering_concept",
                question="When should Trainer keep the API key local instead of storing it in the workspace for a remote VS Code session?",
                context=context.context_hint or "Use the remote workspace boundary before trusting deeper coaching.",
                answer_mode="text",
                expected_answer=(
                    "Keep the key local with ui_proxy when the remote host is shared or not fully trusted. "
                    "Use workspace_secret only when the remote machine and file boundary are understood and trustworthy."
                ),
                hint_ladder=[
                    "Start with the workspace type: SSH, tunnels, dev container, WSL, or local.",
                    "Then ask which host owns the files and secret storage.",
                    "Only after that decide whether credentials should stay local or remote.",
                ],
                common_mistakes=[
                    "Assuming every remote machine should store the API key remotely.",
                    "Treating the resource sandbox like the project workspace boundary.",
                ],
                feedback={
                    "correct": "Good. You tied credential mode to trust and host ownership.",
                    "incorrect": "Decide the host and trust boundary first, then choose the credential mode.",
                },
                next_after_completion="Return with the boundary rule, then continue the paired remote practice step.",
                difficulty="medium",
            )
        if pack == _GUIDED_SCENARIO_PACK_DEBUG:
            return TrainingCardCandidateSnapshot(
                card_type="flash",
                scenario_pack=pack,
                title="Flash: Minimal debug loop",
                focus_area=_guided_pack_focus(context, "VS Code debugging"),
                target_skill=_guided_pack_skill(context, "debug loop design"),
                knowledge_type="engineering_concept",
                question="What is the smallest trustworthy debug loop before you change code?",
                context=context.context_hint or "The goal is to prove where the bad state begins, not to tour the whole stack.",
                answer_mode="text",
                expected_answer=(
                    "Reproduce the failure, pause at the first useful breakpoint or exception boundary, "
                    "and record the first verified wrong value or branch before editing."
                ),
                hint_ladder=[
                    "Start with a failing repro you can repeat.",
                    "Then pause where the state first changes, not where the symptom ends.",
                    "Only after that record the first wrong value or branch.",
                ],
                common_mistakes=[
                    "Changing code before the failure is reproducible.",
                    "Putting breakpoints after the state is already corrupted.",
                ],
                feedback={
                    "correct": "Nice. The loop is small enough to trust.",
                    "incorrect": "Shrink the loop to one repro, one pause, and one verified finding.",
                },
                next_after_completion="Return with the debug rule, then open the paired practice card in the real failure path.",
                difficulty="medium",
            )
        return TrainingCardCandidateSnapshot(
            card_type="flash",
            scenario_pack=pack,
            title="Flash: Function guidance contract",
            focus_area=_guided_pack_focus(context, "function guidance"),
            target_skill=_guided_pack_skill(context, "function contract recovery"),
            knowledge_type="engineering_concept",
            question="What do hover, signature help, and go-to-definition each prove about a function?",
            context=context.context_hint or "Use editor guidance to verify a contract before you edit a live call site.",
            answer_mode="text",
            expected_answer=(
                "Hover gives the quick summary, signature help confirms parameters at the call site, "
                "and go-to-definition plus real references prove the actual implementation boundary."
            ),
            hint_ladder=[
                "Hover is the fast summary, not the final proof.",
                "Signature help is strongest when you are inside a real call site.",
                "Definition and references confirm what really owns the contract.",
            ],
            common_mistakes=[
                "Treating autocomplete as a verified contract.",
                "Reading the hover text without checking a real caller or definition.",
            ],
            feedback={
                "correct": "Good. You separated quick hints from the real source of truth.",
                "incorrect": "Distinguish quick editor hints from the definition and live call sites that prove the contract.",
            },
            next_after_completion="Return with the contract rule, then recover one real call site in the paired practice step.",
            difficulty="medium",
        )

    if pack == _GUIDED_SCENARIO_PACK_REMOTE:
        return TrainingCardCandidateSnapshot(
            card_type="practice",
            status="needs_primer",
            scenario_pack=pack,
            title="Practice: Verify the remote workspace boundary",
            focus_area=_guided_pack_focus(context, "VS Code remote workspace"),
            target_skill=_guided_pack_skill(context, "remote workspace boundary"),
            scenario=(
                context.context_hint
                or "You are coaching through Remote SSH, WSL, tunnels, or a dev container and need one honest boundary check before deeper work."
            ),
            problem_statement=(
                "Prove which machine owns the workspace files, which credential mode is safe, "
                "and how Trainer should explain that boundary before any deeper coaching continues."
            ),
            suggested_workspace_action=(
                "Inspect one real workspace URI or path, then explain the safe credential mode in one sentence before touching code."
            ),
            api_hints=[
                "detectRemoteWorkspaceType(uri)",
                "getRecommendedCredentialMode(workspaceType)",
                "isCredentialModeSecureForWorkspace(mode, workspaceType)",
            ],
            constraints=[
                "Do not patch project files just to test the remote boundary.",
                "Keep the proof to one workspace path, one credential decision, and one recovery note.",
            ],
            deliverable="A short remote-boundary judgment with one confirmed workspace path and one credential-mode decision.",
            self_check=[
                "Can you name which host owns the workspace files?",
                "Can you explain whether the API key should stay local or remote here?",
                "Did you verify one real path or storage boundary without changing project code?",
            ],
            validation_method="Read the current workspace metadata, name the remote type, and confirm one concrete path or credential boundary.",
            learner_deliverables=[
                "Name the remote workspace type and the host that owns the files.",
                "Confirm whether the API key should stay local or remote for this workspace.",
                "Bring back one concrete path or setting that proves the boundary.",
            ],
            verification_steps=[
                "Capture the current remote surface (SSH / tunnels / dev container / WSL / local).",
                "Confirm one resolved workspace path or mount point.",
                "Explain the safe credential mode and why Trainer should use it here.",
            ],
            expected_symbols=[
                "detectRemoteWorkspaceType",
                "getRecommendedCredentialMode",
                "isCredentialModeSecureForWorkspace",
            ],
            hint_ladder=[
                "Start with the workspace URI or remote name.",
                "Then decide whether credentials should stay local or remote.",
                "Finally prove the boundary with one real path or storage fact.",
            ],
            common_mistakes=[
                "Assuming every remote machine should store the API key remotely.",
                "Treating the resource sandbox like the project workspace boundary.",
            ],
            stuck_recovery="If the path story is fuzzy, stop and prove only one thing: which host owns the workspace files.",
            reflection_prompt="Which part of the remote boundary was unclear before you checked a real path?",
            success_signal="You can explain the remote boundary in one sentence and support it with one real path or credential fact.",
            return_with="Return with the remote type, the confirmed path, and the credential decision.",
            next_after_completion="Return with the remote boundary proof",
            difficulty="medium",
        )
    if pack == _GUIDED_SCENARIO_PACK_DEBUG:
        return TrainingCardCandidateSnapshot(
            card_type="practice",
            status="needs_primer",
            scenario_pack=pack,
            title="Practice: Narrow the debug loop",
            focus_area=_guided_pack_focus(context, "VS Code debugging"),
            target_skill=_guided_pack_skill(context, "debug loop design"),
            scenario=context.context_hint or "A file is failing and you need one minimal VS Code debug loop before changing more code.",
            problem_statement=(
                "Build one minimal debug loop that reproduces the issue, stops where the state first changes, "
                "and returns one verified finding."
            ),
            suggested_workspace_action="Pick one failing command or file, set the first useful breakpoint at the state boundary, and run the smallest repro.",
            api_hints=[
                "launch.json configurations",
                "Conditional breakpoints and exception breakpoints",
                "Watch expressions or Debug Console for the first bad value",
            ],
            constraints=[
                "Do not refactor while you still cannot reproduce the bug.",
                "Prefer one breakpoint and one failing path over a full debug tour.",
            ],
            deliverable="A reproducible failing step plus one verified explanation of where the state diverges.",
            self_check=[
                "Can you reproduce the failure on demand?",
                "Did at least one breakpoint or exception pause at the right boundary?",
                "Can you name the first wrong value or branch, not just the final symptom?",
            ],
            validation_method="Reproduce once, pause at the boundary, and record the first verified bad state.",
            learner_deliverables=[
                "Write down the smallest repro step.",
                "Pause at the first useful breakpoint or exception boundary.",
                "Record the first verified wrong value, branch, or missing state.",
            ],
            verification_steps=[
                "Run the smallest failing repro.",
                "Pause at the first useful breakpoint or exception.",
                "Write down the first verified wrong value or branch.",
            ],
            expected_symbols=["launch.json", "breakpoint", "Debug Console"],
            hint_ladder=[
                "Start by making the failure repeat on demand.",
                "Then move the breakpoint earlier until the state first changes.",
                "Only after that record the first wrong value or branch.",
            ],
            common_mistakes=[
                "Changing code before the failure is reproducible.",
                "Setting breakpoints after the state is already corrupted.",
            ],
            stuck_recovery="If every breakpoint feels noisy, move it earlier and choose the first state transition you can explain.",
            reflection_prompt="What did the debugger prove that logs or guesswork did not?",
            success_signal="You can state where the bad state first appears and what evidence proved it.",
            return_with="Return with the repro step, the pause location, and the first wrong value.",
            next_after_completion="Return with the debug evidence",
            difficulty="medium",
        )
    return TrainingCardCandidateSnapshot(
        card_type="practice",
        status="needs_primer",
        scenario_pack=pack,
        title="Practice: Recover a function contract with editor guidance",
        focus_area=_guided_pack_focus(context, "function guidance"),
        target_skill=_guided_pack_skill(context, "function contract recovery"),
        scenario=context.context_hint or "You need to understand an unfamiliar function using hover, signature help, definition, and one real call site.",
        problem_statement=(
            "Use VS Code function guidance to recover one function's contract: what it expects, "
            "what it returns, and which call site proves it."
        ),
        suggested_workspace_action="Start from one live call site, then inspect hover, signature help, and definition before editing anything.",
        api_hints=[
            "Hover / Peek Definition",
            "Signature Help (parameter hints)",
            "Go to Definition / Find All References",
        ],
        constraints=[
            "Do not copy an implementation before you understand the contract.",
            "Keep the investigation to one function and one call site.",
        ],
        deliverable="A short function-contract note plus one learner-authored change or explanation that respects it.",
        self_check=[
            "Can you name the parameters and return shape?",
            "Did you inspect at least one real caller?",
            "Can you explain one common misuse before editing?",
        ],
        validation_method="Cross-check hover, signature help, and one real reference until the contract is stable.",
        learner_deliverables=[
            "Open one real call site.",
            "Confirm the parameter and return contract from editor guidance or definition.",
            "Explain one misuse or edge case before editing.",
        ],
        verification_steps=[
            "Check hover or signature help from a live call site.",
            "Open the definition or a real caller/reference.",
            "Write down the contract and one safe next edit.",
        ],
        expected_symbols=["Hover", "Signature Help", "Go to Definition"],
        hint_ladder=[
            "Hover is the fast summary, not the final proof.",
            "Signature help is strongest when you are inside a real call site.",
            "Definition and references confirm what really owns the contract.",
        ],
        common_mistakes=[
            "Treating autocomplete as a verified contract.",
            "Reading the hover text without checking a real caller or definition.",
        ],
        stuck_recovery="If the signature is still vague, stop editing and inspect one more real caller or type definition.",
        reflection_prompt="Which editor hint gave the missing piece: hover, signature help, definition, or references?",
        success_signal="You can explain the function contract and make one small safe change without guessing.",
        return_with="Return with the function contract, one checked call site, and the safe next edit.",
        next_after_completion="Return with the function contract",
        difficulty="medium",
    )


def _guided_context_for_pack(
    pack: str,
    context: CardGenerationContext,
) -> CardGenerationContext:
    if pack == _GUIDED_SCENARIO_PACK_DEPENDENCY:
        # A free-form hint must never masquerade as dependency usage evidence.
        return context.model_copy(update={"context_hint": ""})
    if pack != _GUIDED_SCENARIO_PACK_RESOURCE:
        return context
    evidence, _, _, focus, summary = _resource_knowledge_evidence(context)
    if evidence is None or _guided_fact_text(evidence.resource_id, limit=160) != _guided_fact_text(
        context.resource_id,
        limit=160,
    ):
        focus = ""
        summary = ""
    return context.model_copy(
        update={
            # Resource focus and prose must come from the indexed evidence projection,
            # never from the client-supplied card fields.
            "focus_area": focus,
            "target_skill": focus,
            "context_hint": summary,
        }
    )


def _make_guided_scenario_pack_card(
    pack: str,
    context: CardGenerationContext,
    card_type: str,
    language: str = "en-US",
) -> TrainingCardCandidateSnapshot:
    """Build the teaching skeleton, then project only verified workspace facts into it."""
    grounded_context = _guided_context_for_pack(pack, context)
    card = _build_guided_scenario_pack_card(pack, grounded_context, card_type, language)
    return _apply_guided_workspace_facts(card, pack=pack, context=grounded_context)


def _derive_resource_trust_state(context: CardGenerationContext) -> str:
    explicit = str(context.resource_trust_state or "").strip().lower()
    if explicit:
        return explicit
    flags = {str(flag or "").strip().lower() for flag in context.resource_quality_flags}
    if context.resource_missing:
        return "untrusted"
    if flags & _RESOURCE_BLOCKING_FLAGS:
        return "untrusted"
    if "stale" in flags or str(context.resource_freshness or "").strip().lower() == "stale":
        return "stale"
    if context.resource_trust_score >= 0.75:
        return "trusted"
    if context.resource_trust_score >= 0.45:
        return "unknown"
    return "untrusted"


def _resource_reliability_note(context: CardGenerationContext, language: str | None = None) -> str:
    if context.resource_missing:
        return _localized_text(
            context.resource_missing_reason or "The requested resource could not be found in the current workspace memory.",
            context.resource_missing_reason or "当前 workspace memory 里找不到请求的资料。",
            language,
        )
    flags = [str(flag or "").strip() for flag in context.resource_quality_flags if str(flag or "").strip()]
    if flags:
        return _localized_text(
            f"Resource reliability warning: {', '.join(flags[:3])}.",
            f"资料可信度提醒：{', '.join(flags[:3])}。",
            language,
        )
    freshness = str(context.resource_freshness or "").strip()
    if freshness:
        return _localized_text(
            f"Resource freshness: {freshness}.",
            f"资料新鲜度：{freshness}。",
            language,
        )
    return ""

# Required fields for structural validation of LLM responses.
_PRACTICE_REQUIRED_FIELDS = (
    "title", "focus_area", "target_skill", "scenario", "problem_statement",
    "api_hints", "deliverable", "self_check", "grading_rubric",
    "stuck_recovery", "reflection_prompt",
)

_FLASH_REQUIRED_FIELDS = (
    "title", "why_now", "focus_area", "target_skill", "knowledge_type", "question",
    "answer_mode", "expected_answer", "problem_statement", "learner_deliverables",
    "verification_steps", "success_signal", "reflection_prompt", "return_with",
    "next_after_completion", "hint_ladder", "common_mistakes", "feedback",
)

# Fields copied verbatim from a validated LLM JSON payload onto the card
# candidate snapshot.
_LLM_CARD_FIELD_MAP = frozenset(
    {
        "title", "why_now", "focus_area", "target_skill", "difficulty",
        "scenario", "problem_statement", "suggested_workspace_action",
        "api_hints", "constraints", "deliverable", "self_check",
        "expected_answer_shape", "validation_method", "grading_rubric",
        "trainer_review_input", "stuck_recovery", "reflection_prompt",
        "knowledge_type", "question", "context", "answer_mode",
        "options", "correct_option_index", "expected_answer", "rubric", "hint_ladder",
        "feedback", "common_mistakes", "review_schedule",
        "expected_symbols", "scenario_pack", "source_chain", "next_after_completion",
        "files_to_touch", "learner_deliverables", "verification_steps",
        "success_signal", "return_with", "acceptance_criteria",
    }
)

# Acceptance criteria must be machine-checkable: the training-acceptance check
# in the sidecar evaluator accepts a criterion only when it names at least one
# "verifiable code symbol" — a backticked literal (e.g. `asyncio.gather`) or a
# snake_case/camelCase identifier — and that symbol appears in the learner's
# submitted code. The helpers below mirror the signal rule from
# ``app/evaluator/service.py`` (``_normalize_code_symbol`` /
# ``_criterion_code_signals``) so generated criteria structurally always pass.
_CARD_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*")
_CARD_CODE_SYMBOL_PATTERN = re.compile(
    rf"{_CARD_IDENTIFIER_PATTERN.pattern}(?:\s*\.\s*{_CARD_IDENTIFIER_PATTERN.pattern})*"
)
_ACCEPTANCE_BACKTICK_PATTERN = re.compile(r"`([^`]+)`")
_ACCEPTANCE_DOTTED_SYMBOL_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]+(?:\.[A-Za-z_][A-Za-z0-9_]+)+"
)
_ACCEPTANCE_EXTRACTION_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ACCEPTANCE_KNOWN_SYMBOL_TOKENS = frozenset(
    {
        "asyncio", "await", "async", "def", "class", "import", "return", "yield",
        "main", "python", "pytest", "unittest", "json", "os", "sys", "re", "math",
        "typing", "list", "dict", "set", "tuple", "str", "int", "float", "bool",
        "print", "len", "range", "open", "http", "https", "api", "url", "sql",
        "git", "docker", "npm", "node", "test", "tests", "init", "run", "gather",
    }
)
_ACCEPTANCE_MIN_CRITERIA = 3
_ACCEPTANCE_MAX_CRITERIA = 5
_ACCEPTANCE_MAX_SYMBOLS = 6


def _normalize_card_code_symbol(value: str) -> str | None:
    """Mirror ``app/evaluator/service.py::_normalize_code_symbol``."""
    normalized = value.strip().strip("`").strip()
    normalized = re.sub(r"\(\s*\)$", "", normalized)
    if not normalized or _CARD_CODE_SYMBOL_PATTERN.fullmatch(normalized) is None:
        return None
    return re.sub(r"\s*\.\s*", ".", normalized)


def _criterion_has_code_signal(criterion: str) -> bool:
    """True when a criterion names at least one verifiable code symbol.

    Mirrors the evaluator's ``_criterion_code_signals`` rule: a backticked
    literal or a bare snake_case/camelCase identifier counts; free-form prose
    without any code symbol never does.
    """
    for literal in _ACCEPTANCE_BACKTICK_PATTERN.findall(criterion):
        if _normalize_card_code_symbol(literal) is not None:
            return True
    for token in _CARD_IDENTIFIER_PATTERN.findall(criterion):
        if "_" in token or (
            token[0].islower() and any(character.isupper() for character in token[1:])
        ):
            return True
    return False


def _extract_acceptance_symbols(
    deliverable: str,
    grading_rubric: list[str],
    target_skill: str,
) -> list[str]:
    """Collect identifier-like code symbols from the deliverable, rubric, and skill."""
    symbols: list[str] = []

    def _add(candidate: str) -> None:
        normalized = _normalize_card_code_symbol(candidate)
        if normalized and normalized not in symbols:
            symbols.append(normalized)

    for source_text in (deliverable, *grading_rubric, target_skill):
        text = source_text if isinstance(source_text, str) else ""
        if not text:
            continue
        for literal in _ACCEPTANCE_BACKTICK_PATTERN.findall(text):
            _add(literal)
        for dotted in _ACCEPTANCE_DOTTED_SYMBOL_PATTERN.findall(text):
            _add(dotted)
        for token in _ACCEPTANCE_EXTRACTION_IDENTIFIER.findall(text):
            if any(token in symbol.split(".") for symbol in symbols):
                continue
            if "_" in token or (
                token[0].islower() and any(character.isupper() for character in token[1:])
            ) or token.lower() in _ACCEPTANCE_KNOWN_SYMBOL_TOKENS:
                _add(token)
        if len(symbols) >= _ACCEPTANCE_MAX_SYMBOLS:
            break
    return symbols[:_ACCEPTANCE_MAX_SYMBOLS]


def derive_acceptance_criteria(
    deliverable: str,
    grading_rubric: list[str],
    target_skill: str,
    *,
    language: str | None = None,
) -> list[str]:
    """Build 3-5 symbol-anchored acceptance criteria from card inputs.

    Every returned item quotes at least one backticked code symbol so the
    training-acceptance check in the evaluator can match it against the
    learner's submitted code. Used by the deterministic fallback templates and
    as the synthesizer when an LLM omits or degrades ``acceptance_criteria``.
    """
    chinese = _prefers_chinese(language)
    step_templates = (
        (
            "使用 `{symbol}` 完成交付物中的关键一步",
            "定义 `{symbol}` 并让它出现在提交的代码里",
            "通过 `{symbol}` 验证最终结果",
        )
        if chinese
        else (
            "Use `{symbol}` for the key step of the deliverable",
            "Define `{symbol}` so it appears in the submitted code",
            "Verify the final result via `{symbol}`",
        )
    )
    generic_criteria = (
        (
            "定义 `main` 入口并通过 `python` 运行提交的内容",
            "使用 `pytest` 或 `python` 运行一次并保留输出",
            "运行时无 `SyntaxError` 或 `RuntimeError`",
        )
        if chinese
        else (
            "Define a `main` entry point and run the submission via `python`",
            "Run the submission once via `pytest` or `python` and keep the output",
            "Run without `SyntaxError` or `RuntimeError`",
        )
    )
    error_criterion = generic_criteria[-1]

    criteria: list[str] = []
    symbols = _extract_acceptance_symbols(deliverable, grading_rubric, target_skill)
    if symbols:
        for index, template in enumerate(step_templates):
            candidate = template.format(symbol=symbols[index % len(symbols)])
            if candidate not in criteria:
                criteria.append(candidate)
    else:
        for candidate in generic_criteria:
            if candidate not in criteria:
                criteria.append(candidate)
    if error_criterion not in criteria:
        criteria.append(error_criterion)
    return criteria[:_ACCEPTANCE_MAX_CRITERIA]


def _synthesize_acceptance_criteria(
    raw: object,
    context: CardGenerationContext,
    *,
    deliverable: str = "",
    grading_rubric: list[str] | None = None,
) -> list[str]:
    """Keep only verifiable LLM criteria and top up to >=3 deterministic ones.

    Model items without any verifiable code symbol are dropped, then
    ``derive_acceptance_criteria`` fills the gap so the final card always
    carries at least three symbol-anchored items.
    """
    valid: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, str):
                continue
            candidate = item.strip()
            if not candidate or candidate in valid:
                continue
            if not _criterion_has_code_signal(candidate):
                continue
            valid.append(candidate)
            if len(valid) >= _ACCEPTANCE_MAX_CRITERIA:
                return valid
    if len(valid) >= _ACCEPTANCE_MIN_CRITERIA:
        return valid
    for candidate in derive_acceptance_criteria(
        deliverable,
        grading_rubric or [],
        context.target_skill or context.focus_area or "",
        language=context.response_language,
    ):
        if candidate in valid:
            continue
        valid.append(candidate)
        if len(valid) >= _ACCEPTANCE_MAX_CRITERIA:
            break
    return valid


def _acceptance_criteria_for_payload(
    data: dict[str, Any],
    context: CardGenerationContext,
) -> list[str]:
    """Normalize the ``acceptance_criteria`` field of one LLM card payload."""
    return _synthesize_acceptance_criteria(
        data.get("acceptance_criteria"),
        context,
        deliverable=str(data.get("deliverable") or ""),
        grading_rubric=_string_list(data.get("grading_rubric")),
    )

# Card prompts contain a comparatively large structured contract (especially
# flash cards, which carry the answer, hints, feedback, and return path).  A
# 1024-token ceiling frequently cuts otherwise valid JSON at the final fields.
# Keep this request-local budget independent of the coach reply budget; the
# provider's configured maximum still caps it in ``ProviderService``.
_CARD_GENERATION_MAX_TOKENS = 2048


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _build_prompt(context: CardGenerationContext, source: str, card_type: str) -> str:
    """Build the system prompt for card generation."""
    template = CARD_PRACTICE_SYSTEM if card_type == "practice" else CARD_FLASH_SYSTEM
    prompt = template.format(
        context_hint=context.context_hint or "general practice",
        focus_area=context.focus_area or "unspecified",
        target_skill=context.target_skill or "unspecified",
        source=source,
    )
    if _prefers_chinese(context.response_language):
        prompt += (
            "\n\nLanguage: Respond in zh-CN. Keep technical terms like API, protocol, VS Code, "
            "launch.json, Debug Console, and return value in English when that keeps the card clearer."
        )
    elif context.response_language:
        prompt += f"\n\nLanguage: Respond in {context.response_language}. Keep technical terms like API and protocol in English when helpful."
    prompt += (
        "\n\nAcceptance criteria: the JSON must include an \"acceptance_criteria\" array of "
        "exactly 3-5 short items derived from the deliverable and grading rubric. Every item MUST "
        "quote at least one code symbol in backticks and follow one of the patterns: "
        "\"使用 `symbol` …\" / \"定义 `symbol` …\" / \"通过 `symbol` …\" "
        "(English: \"Use `symbol` ...\" / \"Define `symbol` ...\" / \"Via `symbol` ...\"). "
        "Items without a backticked symbol are discarded and replaced."
    )
    return prompt


def _parse_llm_json(raw: str) -> dict[str, Any] | None:
    """Parse JSON from LLM response, tolerating think blocks, prose, and fences."""

    def _try_json(candidate: str) -> dict[str, Any] | None:
        try:
            result = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            return None
        return result if isinstance(result, dict) else None

    def _strip_fence(candidate: str) -> str:
        text = candidate.strip()
        if not text.startswith("```"):
            return text
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()

    def _extract_first_object(candidate: str) -> str | None:
        start = candidate.find("{")
        if start < 0:
            return None
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(candidate)):
            char = candidate[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return candidate[start : index + 1]
        return None

    text = raw.strip()
    if not text:
        return None

    normalized = re.sub(r"<think\b[^>]*>.*?</think\s*>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    normalized = re.sub(r"</?think\b[^>]*>", " ", normalized, flags=re.IGNORECASE | re.DOTALL).strip()

    direct = _try_json(normalized)
    if direct is not None:
        return direct

    unfenced = _strip_fence(normalized)
    fenced = _try_json(unfenced)
    if fenced is not None:
        return fenced

    if "```" in normalized:
        for block in re.findall(r"```(?:json)?\s*([\s\S]*?)```", normalized, flags=re.IGNORECASE):
            parsed = _try_json(block.strip())
            if parsed is not None:
                return parsed

    first_object = _extract_first_object(unfenced)
    if first_object:
        parsed = _try_json(first_object)
        if parsed is not None:
            return parsed

    return None


def _validate_fields(data: dict[str, Any], required: tuple[str, ...]) -> bool:
    """Check that all required fields are present and non-empty."""
    for field in required:
        value = data.get(field)
        if value is None:
            return False
        if isinstance(value, str) and not value.strip():
            return False
        if isinstance(value, (list, dict)) and not value:
            return False
    return True


_ZH_CARD_PROSE_FIELDS = frozenset(
    {
        "title",
        "why_now",
        "scenario",
        "problem_statement",
        "suggested_workspace_action",
        "deliverable",
        "self_check",
        "grading_rubric",
        "learner_deliverables",
        "verification_steps",
        "success_signal",
        "stuck_recovery",
        "reflection_prompt",
        "question",
        "expected_answer",
        "expected_answer_shape",
        "validation_method",
        "trainer_review_input",
        "rubric",
        "feedback",
        "common_mistakes",
        "return_with",
        "next_after_completion",
        "constraints",
    }
)

_ZH_CARD_TECHNICAL_WORDS = frozenset(
    {
        "api",
        "protocol",
        "remote",
        "debug",
        "function",
        "hover",
        "signature",
        "definition",
        "references",
        "call",
        "site",
        "workspace",
        "file",
        "path",
        "vscode",
        "ssh",
        "wsl",
        "http",
        "https",
        "json",
        "python",
        "typescript",
        "javascript",
        "node",
        "terminal",
        "breakpoint",
        "exception",
        "stack",
        "trace",
    }
)


def _contains_chinese_text(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value))


def _is_short_technical_card_text(value: str) -> bool:
    normalized = value.strip()
    if not normalized or len(normalized) > 64:
        return False
    if re.fullmatch(r"[A-Za-z0-9_./:\\#@()[\]{}<>=+*,'\"`| -]+", normalized):
        if re.search(r"[.!?]", normalized):
            return False
        words = re.findall(r"[A-Za-z]+(?:[-/][A-Za-z0-9]+)*", normalized.lower())
        return bool(words) and len(words) <= 6 and all(
            word in _ZH_CARD_TECHNICAL_WORDS or any(char.isdigit() for char in word)
            for word in words
        )
    return False


def _is_zh_card_prose(value: object) -> bool:
    if not isinstance(value, str):
        return True
    normalized = value.strip()
    return bool(normalized) and (
        _contains_chinese_text(normalized) or _is_short_technical_card_text(normalized)
    )


_CARD_LANGUAGE_MARKERS: dict[str, tuple[str, ...]] = {
    "es-ES": (" el ", " la ", " los ", " las ", " una ", " para ", " con ", " que ", " del ", " por "),
    "fr-FR": (" le ", " la ", " les ", " une ", " des ", " pour ", " avec ", " dans ", " est ", " que "),
    "de-DE": (" der ", " die ", " das ", " eine ", " einen ", " und ", " mit ", " fuer ", " ist ", " nicht "),
    "pt-BR": (" uma ", " para ", " com ", " que ", " dos ", " das ", " nao ", " sobre ", " este ", " por "),
}


def _iter_card_prose(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _iter_card_prose(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _iter_card_prose(item)]
    return []


def _has_requested_locale_prose(data: dict[str, Any], language: str) -> bool:
    prose = " ".join(
        value.strip()
        for field in _ZH_CARD_PROSE_FIELDS
        for value in _iter_card_prose(data.get(field))
        if value.strip()
    ).lower()
    if not prose:
        return False
    if language == "ja-JP":
        return bool(re.search(r"[\u3040-\u30ff]", prose))
    if language == "ko-KR":
        return bool(re.search(r"[\uac00-\ud7af]", prose))
    normalized = f" {prose.replace('ä', 'a').replace('ö', 'o').replace('ü', 'u').replace('ß', 'ss').replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u').replace('ã', 'a').replace('ç', 'c')} "
    markers = _CARD_LANGUAGE_MARKERS.get(language, ())
    return sum(marker in normalized for marker in markers) >= 2


def _has_expected_card_language(data: dict[str, Any], response_language: str | None) -> bool:
    """Reject learner-facing prose that contradicts the selected UI language."""
    if not response_language or response_language == "en-US":
        return True

    if response_language in _EXPLICIT_CARD_FALLBACK_COPY:
        return _has_requested_locale_prose(data, response_language)

    if not _prefers_chinese(response_language):
        return True

    for field in _ZH_CARD_PROSE_FIELDS:
        value = data.get(field)
        if value is None:
            continue
        if isinstance(value, str) and not _is_zh_card_prose(value):
            return False
        if isinstance(value, list) and any(not _is_zh_card_prose(item) for item in value):
            return False
        if isinstance(value, dict) and any(not _is_zh_card_prose(item) for item in value.values()):
            return False
    return True


def _localized_fallback_value(copy: dict[str, str], key: str, topic: str) -> str:
    return copy[key].format(topic=topic)


def _replace_mismatched_card_prose(
    card: TrainingCardCandidateSnapshot,
    context: CardGenerationContext,
) -> TrainingCardCandidateSnapshot:
    """Keep a deterministic card usable when an LLM ignores a selected locale."""
    language = context.response_language
    copy = _EXPLICIT_CARD_FALLBACK_COPY.get(language or "")
    if not copy or _has_expected_card_language(card.model_dump(), language):
        return card

    topic = card.focus_area or card.target_skill or context.focus_area or context.target_skill or "topic"
    shared = {
        "why_now": _localized_fallback_value(copy, "why_now", topic),
        "scenario": _localized_fallback_value(copy, "scenario", topic),
        "problem_statement": _localized_fallback_value(copy, "problem", topic),
        "suggested_workspace_action": _localized_fallback_value(copy, "action", topic),
        "api_hints": [
            _localized_fallback_value(copy, "hint_1", topic),
            _localized_fallback_value(copy, "hint_2", topic),
        ],
        "constraints": [
            _localized_fallback_value(copy, "self_1", topic),
            _localized_fallback_value(copy, "self_2", topic),
        ],
        "deliverable": _localized_fallback_value(copy, "deliverable", topic),
        "self_check": [
            _localized_fallback_value(copy, "self_1", topic),
            _localized_fallback_value(copy, "self_2", topic),
        ],
        "validation_method": _localized_fallback_value(copy, "validation", topic),
        "grading_rubric": [
            _localized_fallback_value(copy, "rubric_1", topic),
            _localized_fallback_value(copy, "rubric_2", topic),
        ],
        "learner_deliverables": [
            _localized_fallback_value(copy, "deliverable_1", topic),
            _localized_fallback_value(copy, "deliverable_2", topic),
        ],
        "verification_steps": [
            _localized_fallback_value(copy, "verify_1", topic),
            _localized_fallback_value(copy, "verify_2", topic),
        ],
        "success_signal": _localized_fallback_value(copy, "success", topic),
        "stuck_recovery": _localized_fallback_value(copy, "stuck", topic),
        "reflection_prompt": _localized_fallback_value(copy, "reflect", topic),
        "return_with": _localized_fallback_value(copy, "return", topic),
        "next_after_completion": _localized_fallback_value(copy, "next", topic),
        "common_mistakes": [_localized_fallback_value(copy, "mistake", topic)],
        "feedback": {
            "correct": _localized_fallback_value(copy, "correct", topic),
            "incorrect": _localized_fallback_value(copy, "incorrect", topic),
        },
    }
    if card.card_type == "flash":
        return card.model_copy(
            update={
                **shared,
                "title": _localized_fallback_value(copy, "flash_title", topic),
                "question": _localized_fallback_value(copy, "question", topic),
                "context": _localized_fallback_value(copy, "flash_context", topic),
                "expected_answer": _localized_fallback_value(copy, "expected", topic),
                "hint_ladder": [
                    _localized_fallback_value(copy, "hint_1", topic),
                    _localized_fallback_value(copy, "hint_2", topic),
                ],
            }
        )
    return card.model_copy(
        update={
            **shared,
            "title": _localized_fallback_value(copy, "practice_title", topic),
            "question": "",
            "context": "",
            "expected_answer": "",
            "hint_ladder": [],
        }
    )


class CardGenerationService:
    """Generates training card candidates from various sources.

    When a ProviderService is supplied, each source handler attempts to use
    the LLM to generate richer content. On failure (LLM unavailable, parse
    error, missing fields), the handler falls back to a deterministic template.
    """

    def __init__(self, provider_service: Any | None = None, event_ledger: EventLedgerService | None = None) -> None:
        self._provider = provider_service
        self._event_ledger = event_ledger
        self._pending_llm_failure_reasons: dict[tuple[int, str, str], str] = {}

    def generate_card(
        self,
        source: str,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
        fallback_reason: str | None = None,
    ) -> TrainingCardCandidateSnapshot:
        """Main entry point — dispatches to the appropriate source handler."""
        guided_pack = _match_guided_scenario_pack(context, source=source)
        if guided_pack:
            # Guided cards must never let a successful provider response replace the
            # verified-workspace-facts gate. This includes legacy conversation sources.
            card = _make_guided_scenario_pack_card(
                guided_pack,
                context,
                context.card_type or "practice",
                context.response_language or "en-US",
            )
            if source == "plan_requirement" and context.plan_stage_id:
                card.plan_links = [context.plan_stage_id]
        else:
            handler = {
                "conversation_gap": self._generate_from_conversation_gap,
                "plan_requirement": self._generate_from_plan_requirement,
                "resource_knowledge": self._generate_from_resource_knowledge,
                "practice_feedback": self._generate_from_practice_feedback,
                "dependency_mastery": self._generate_from_dependency_mastery,
                "review_due": self._generate_from_review_due,
            }.get(source)
            if handler is None:
                if allow_llm and self._provider is not None:
                    raise CardGenerationProviderFailure(
                        "unknown_source",
                        response_language=context.response_language,
                    )
                card = self._generate_stub(context, allow_llm=False)
            else:
                card = handler(context, allow_llm=allow_llm)
        pending_fallback_reason = self._take_llm_failure(
            context,
            source,
            context.card_type or "practice",
        )
        if allow_llm and not guided_pack and pending_fallback_reason and self._provider is not None:
            raise CardGenerationProviderFailure(
                pending_fallback_reason,
                response_language=context.response_language,
            )
        return self._finalize_card(
            card,
            source,
            context,
            fallback_reason=fallback_reason or pending_fallback_reason,
        )

    def _finalize_card(
        self,
        card: TrainingCardCandidateSnapshot,
        source: str,
        context: CardGenerationContext,
        *,
        fallback_reason: str | None = None,
        generation_source: str | None = None,
    ) -> TrainingCardCandidateSnapshot:
        """Apply shared card contracts and record the creation event."""
        # Ensure card_id is a full UUID (36 chars), not the model default short id
        if not card.card_id or len(card.card_id) < 36:
            card.card_id = str(uuid4())
        card.status = card.status or "candidate"
        card.created_from = _SOURCE_MAP.get(source, "conversation")
        if not card.source_chain:
            card.source_chain = ["card_generation_router"]
        card = _ensure_flash_contract(card, context, source)
        card = _ensure_practice_contract(card, context)
        card = _replace_mismatched_card_prose(card, context)
        card = _enforce_learning_loop_contract(card, context)
        card.why_now = card.why_now or _WHY_NOW_MESSAGES.get(source, f"Fallback card generated from {source or 'conversation_gap'}.")
        card.why_now = _localized_why_now(source, card.why_now, context.response_language)
        creation_payload: dict[str, Any] = {
            "card_id": card.card_id,
            "card_type": card.card_type,
            "created_from": card.created_from,
            "title": card.title,
            "focus_area": card.focus_area,
            "target_skill": card.target_skill,
        }
        if fallback_reason:
            source_marker, detail = _fallback_provenance_copy(
                fallback_reason,
                context.response_language,
            )
            source_chain = list(card.source_chain)
            if source_marker not in source_chain:
                source_chain.append(source_marker)
            card = card.model_copy(
                update={
                    "generation_source": "deterministic_fallback",
                    "generation_status": "degraded",
                    "generation_fallback_reason": fallback_reason,
                    "generation_recoverable": True,
                    "provider_attempted": True,
                    "model_output_valid": False,
                    "source_chain": source_chain,
                    "why_now": f"{card.why_now} {detail}".strip(),
                }
            )
            creation_payload.update(
                {
                    "generation_source": "deterministic_fallback",
                    "generation_status": "degraded",
                    "generation_fallback_reason": fallback_reason,
                    "generation_recoverable": True,
                }
            )
        elif generation_source:
            card = card.model_copy(
                update={
                    "generation_source": generation_source,
                    "generation_status": "complete",
                    "generation_recoverable": False,
                }
            )
            creation_payload.update(
                {
                    "generation_source": generation_source,
                    "generation_status": "complete",
                    "generation_recoverable": False,
                }
            )
        now = _utc_now_iso()
        if not card.created_at:
            card.created_at = now
        if not card.updated_at:
            card.updated_at = now
        card = _apply_context_pedagogy_controls(card, context)
        # Goal F2 guarantee: every card leaves the generator with symbol-anchored
        # acceptance criteria. Paths that never set them (governed scenario-pack
        # templates, catalog cards, unknown sources) are backfilled here; cards
        # that already carry criteria (LLM field map, deterministic templates)
        # are never overwritten.
        if not card.acceptance_criteria:
            card = card.model_copy(
                update={
                    "acceptance_criteria": derive_acceptance_criteria(
                        card.deliverable,
                        card.grading_rubric,
                        context.target_skill or context.focus_area or card.target_skill or "",
                        language=context.response_language,
                    )
                }
            )
        if not card.project_id and context.workspace_id:
            card = card.model_copy(update={"project_id": context.workspace_id})

        # §13.21 Record card creation event in unified event ledger
        if self._event_ledger is not None:
            self._event_ledger.record_event(
                "card_candidate_created",
                actor="system",
                scope="card",
                project_id=context.workspace_id,
                source_chain=["card_generation_router", source],
                payload_ref=creation_payload,
                before_state_ref={},
                after_state_ref={
                    "card_id": card.card_id,
                    "status": card.status,
                },
                reversibility="reversible",
                audit_note=f"Card candidate '{card.card_id}' created from '{source}'",
            )

        return card

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_card(
        self,
        card: TrainingCardCandidateSnapshot,
        learner_state: dict,
    ) -> float:
        """Priority scoring in [0.0, 1.0].

        Skeleton heuristic: base 0.5, boost for explicit target_skill, boost
        for review_due source, penalise cards without a focus area.
        """
        score = 0.5
        if card.target_skill:
            score += 0.15
        if card.created_from == "review_due":
            score += 0.2
        if not card.focus_area:
            score -= 0.15
        # Boost if learner has prior weakness in this area.
        weaknesses = learner_state.get("weaknesses", [])
        if isinstance(weaknesses, list) and card.focus_area in weaknesses:
            score += 0.15
        return max(0.0, min(1.0, score))

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    def _try_llm_generation(
        self,
        context: CardGenerationContext,
        source: str,
        card_type: str,
    ) -> TrainingCardCandidateSnapshot | None:
        """Try generating a card via LLM. Returns None on any failure.

        Reasoning-first providers frequently spend the response budget on
        hidden reasoning and return malformed JSON or field-incomplete cards,
        so each request gets exactly one silent synchronous retry at a higher
        temperature before any failure is recorded or surfaced.
        """
        if self._provider is None:
            return None

        def _invoke_provider(temperature: float) -> str:
            """Run one async chat completion synchronously (thread off a live loop)."""
            import asyncio
            import concurrent.futures

            # Run the async LLM call synchronously.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            request = self._provider.chat_completion(
                messages,
                temperature=temperature,
                max_tokens=_CARD_GENERATION_MAX_TOKENS,
            )
            if loop and loop.is_running():
                # We're already in an async context — use nest_asyncio or
                # run in a thread. For simplicity, use thread.
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, request).result()
            return asyncio.run(request)

        try:
            messages = self._llm_messages(context, source, card_type)
            required = (
                _PRACTICE_REQUIRED_FIELDS
                if card_type == "practice"
                else _FLASH_REQUIRED_FIELDS
            )
            failure_reason = "exception"
            for attempt, temperature in enumerate((0.7, 0.9), start=1):
                try:
                    raw = _invoke_provider(temperature)
                except Exception:
                    logger.debug(
                        "LLM card generation failed for source=%s (attempt %d)",
                        source,
                        attempt,
                        exc_info=True,
                    )
                    failure_reason = "exception"
                    continue

                data = _parse_llm_json(raw)
                if data is None:
                    logger.warning(
                        "LLM response was not valid JSON for source=%s (attempt %d)", source, attempt,
                    )
                    failure_reason = "invalid_json"
                    continue

                if not _validate_fields(data, required):
                    logger.warning(
                        "LLM response missing required fields for source=%s (attempt %d)",
                        source,
                        attempt,
                    )
                    failure_reason = "missing_required_fields"
                    continue

                if not _has_expected_card_language(data, context.response_language):
                    logger.warning(
                        "LLM response does not match requested card language for source=%s (attempt %d)",
                        source,
                        attempt,
                    )
                    failure_reason = "language_mismatch"
                    continue

                try:
                    card_kwargs: dict[str, Any] = {"card_type": card_type}
                    for key in _LLM_CARD_FIELD_MAP:
                        if key in data:
                            card_kwargs[key] = data[key]
                    card_kwargs["acceptance_criteria"] = _acceptance_criteria_for_payload(
                        data,
                        context,
                    )
                    return TrainingCardCandidateSnapshot(**card_kwargs)
                except Exception:
                    logger.warning(
                        "LLM response could not be converted to a card for source=%s (attempt %d)",
                        source,
                        attempt,
                    )
                    failure_reason = "invalid_card"
                    continue

            self._record_llm_generation_failure(context, source, card_type, failure_reason)
            return None

        except Exception:
            logger.debug("LLM card generation failed for source=%s", source, exc_info=True)
            self._record_llm_generation_failure(
                context,
                source,
                card_type,
                "exception",
            )
            return None

    def _llm_failure_key(
        self,
        context: CardGenerationContext,
        source: str,
        card_type: str,
    ) -> tuple[int, str, str]:
        return (id(context), source, card_type)

    def _remember_llm_failure(
        self,
        context: CardGenerationContext,
        source: str,
        card_type: str,
        reason: str,
    ) -> None:
        self._pending_llm_failure_reasons[self._llm_failure_key(context, source, card_type)] = reason

    def _take_llm_failure(
        self,
        context: CardGenerationContext,
        source: str,
        card_type: str,
    ) -> str | None:
        return self._pending_llm_failure_reasons.pop(
            self._llm_failure_key(context, source, card_type),
            None,
        )

    def _record_llm_generation_failure(
        self,
        context: CardGenerationContext,
        source: str,
        card_type: str,
        reason: str,
    ) -> None:
        self._remember_llm_failure(context, source, card_type, reason)
        if self._event_ledger is not None:
            self._event_ledger.record_event(
                "card_generation_failed",
                actor="system",
                scope="card",
                project_id=context.workspace_id,
                payload_ref={"source": source, "card_type": card_type, "reason": reason},
                reversibility="irreversible",
                audit_note=f"Card generation failed ({reason}) for source='{source}'",
            )

    def _build_card_from_llm_data(
        self,
        data: dict[str, Any] | None,
        context: CardGenerationContext,
        source: str,
        card_type: str,
    ) -> TrainingCardCandidateSnapshot | None:
        """Validate one provider payload and convert it into a card candidate."""
        if data is None:
            logger.warning("LLM response was not valid JSON for source=%s", source)
            self._record_llm_generation_failure(context, source, card_type, "invalid_json")
            return None

        required = _PRACTICE_REQUIRED_FIELDS if card_type == "practice" else _FLASH_REQUIRED_FIELDS
        if not _validate_fields(data, required):
            logger.warning("LLM response missing required fields for source=%s", source)
            self._record_llm_generation_failure(context, source, card_type, "missing_required_fields")
            return None
        if not _has_expected_card_language(data, context.response_language):
            logger.warning("LLM response does not match requested card language for source=%s", source)
            self._record_llm_generation_failure(context, source, card_type, "language_mismatch")
            return None

        card_kwargs: dict[str, Any] = {"card_type": card_type}
        for key in _LLM_CARD_FIELD_MAP:
            if key in data:
                card_kwargs[key] = data[key]
        card_kwargs["acceptance_criteria"] = _acceptance_criteria_for_payload(data, context)
        try:
            return TrainingCardCandidateSnapshot(**card_kwargs)
        except Exception:
            logger.warning("LLM response could not be converted to a card for source=%s", source)
            self._record_llm_generation_failure(context, source, card_type, "invalid_card")
            return None

    def _llm_messages(
        self,
        context: CardGenerationContext,
        source: str,
        card_type: str,
    ) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": _build_prompt(context, source, card_type)},
            {"role": "user", "content": "Generate the training card now."},
        ]

    async def generate_card_stream(
        self,
        source: str,
        context: CardGenerationContext,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[CardGenerationStreamEvent]:
        """Stream provider chunks and finish with one validated card candidate."""
        guided_pack = _match_guided_scenario_pack(context, source=source)
        if guided_pack:
            yield CardGenerationStreamEvent(
                card=self.generate_card(source, context, allow_llm=False)
            )
            return
        if source not in _SOURCE_MAP:
            raise CardGenerationStreamError(source, reason="unknown_source")
        if self._provider is None:
            raise RuntimeError("Card generation provider is not configured.")

        card_type = context.card_type or "practice"
        raw_parts: list[str] = []
        stream_kwargs: dict[str, object] = {
            "temperature": 0.7,
            "max_tokens": _CARD_GENERATION_MAX_TOKENS,
        }
        if cancel_event is not None:
            stream_kwargs["cancel_event"] = cancel_event
        try:
            async for chunk in self._provider.chat_completion_stream(
                self._llm_messages(context, source, card_type),
                **stream_kwargs,
            ):
                if not isinstance(chunk, str) or not chunk:
                    continue
                raw_parts.append(chunk)
                yield CardGenerationStreamEvent(chunk=chunk)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._event_ledger is not None:
                self._event_ledger.record_event(
                    "card_generation_failed",
                    actor="system",
                    scope="card",
                    project_id=context.workspace_id,
                    payload_ref={
                        "source": source,
                        "card_type": card_type,
                        "reason": "stream_interrupted",
                        "retryable": True,
                        "recoverable": True,
                    },
                    reversibility="irreversible",
                    audit_note=(
                        "Card generation stream interrupted before validation; "
                        f"source='{source}' can be retried."
                    ),
                )
            raise CardGenerationStreamError(source) from exc

        raw_payload = "".join(raw_parts)
        parsed_payload = _parse_llm_json(raw_payload)
        card = self._build_card_from_llm_data(
            parsed_payload,
            context,
            source,
            card_type,
        )
        if card is None:
            # Stream parsing failures use the deterministic source handler without
            # invoking the provider a second time.
            if parsed_payload is None:
                fallback_reason = "invalid_json"
            elif not _validate_fields(
                parsed_payload,
                _PRACTICE_REQUIRED_FIELDS
                if card_type == "practice"
                else _FLASH_REQUIRED_FIELDS,
            ):
                fallback_reason = "missing_required_fields"
            elif not _has_expected_card_language(
                parsed_payload,
                context.response_language,
            ):
                fallback_reason = "language_mismatch"
            else:
                fallback_reason = "invalid_card"
            if guided_pack:
                card = self.generate_card(
                    source,
                    context,
                    allow_llm=False,
                    fallback_reason=fallback_reason,
                )
            else:
                raise CardGenerationStreamError(source, reason=fallback_reason)
        else:
            card = self._finalize_card(
                card,
                source,
                context,
                generation_source="model",
            )
            if guided_pack:
                # Build governed facts only after the provider has completed.
                # Otherwise an interrupted stream would create a misleading
                # candidate event for a card that was never returned.
                guided_guardrail = self.generate_card(source, context, allow_llm=False)
                card = self._merge_guided_guardrail(card, guided_guardrail)
        yield CardGenerationStreamEvent(card=card)

    @staticmethod
    def _merge_guided_guardrail(
        model_card: TrainingCardCandidateSnapshot,
        guardrail: TrainingCardCandidateSnapshot,
    ) -> TrainingCardCandidateSnapshot:
        """Keep governed pack facts while accepting useful model-authored copy."""
        forced_fields = {
            "scenario_pack": guardrail.scenario_pack,
            "status": guardrail.status,
            "requires_project_context": guardrail.requires_project_context,
            "project_context_ready": guardrail.project_context_ready,
            "trust_state": guardrail.trust_state,
            "trust_acknowledged": guardrail.trust_acknowledged,
            "source_chain": guardrail.source_chain,
            "plan_links": guardrail.plan_links,
        }
        for field in (
            "verification_steps",
            "learner_deliverables",
            "expected_symbols",
            "constraints",
            "self_check",
            "hint_ladder",
            "common_mistakes",
        ):
            model_value = getattr(model_card, field, None)
            guardrail_value = getattr(guardrail, field, None)
            if not model_value and guardrail_value:
                forced_fields[field] = guardrail_value
        return model_card.model_copy(update=forced_fields)

    # ------------------------------------------------------------------
    # Fully implemented sources (enhanced with LLM)
    # ------------------------------------------------------------------

    def _generate_from_conversation_gap(
        self,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
    ) -> TrainingCardCandidateSnapshot:
        """Generate a practice or flash card from a detected conversation gap."""
        card_type = context.card_type or "practice"
        guided_pack = _match_guided_scenario_pack(context, source="conversation_gap")
        if guided_pack:
            return _make_guided_scenario_pack_card(
                guided_pack,
                context,
                card_type,
                context.response_language or "en-US",
            )
        llm_card = (
            self._try_llm_generation(context, "conversation_gap", card_type)
            if allow_llm
            else None
        )
        if llm_card is not None:
            return llm_card
        if card_type == "flash":
            return self._make_fallback_card("conversation_gap", context)

        language = context.response_language
        practice_defaults = _practice_defaults(context, language)
        return TrainingCardCandidateSnapshot(
            card_type="practice",
            title=_localized_text(
                f"Practice: {context.focus_area or context.target_skill or 'unspecified area'}",
                f"练习：{context.focus_area or context.target_skill or '未指定领域'}",
                language,
            ),
            focus_area=context.focus_area or context.target_skill,
            target_skill=context.target_skill,
            scenario=_localized_text(
                context.context_hint or "Address a knowledge gap identified during coaching.",
                context.context_hint or "围绕教练发现的知识缺口做一次聚焦练习。",
                language,
            ),
            problem_statement=practice_defaults["problem_statement"],
            suggested_workspace_action=practice_defaults["suggested_workspace_action"],
            api_hints=practice_defaults["api_hints"],
            deliverable=practice_defaults["deliverable"],
            self_check=practice_defaults["self_check"],
            validation_method=practice_defaults["validation_method"],
            grading_rubric=practice_defaults["grading_rubric"],
            acceptance_criteria=derive_acceptance_criteria(
                practice_defaults["deliverable"],
                practice_defaults["grading_rubric"],
                context.target_skill or context.focus_area or "",
                language=language,
            ),
            learner_deliverables=practice_defaults["learner_deliverables"],
            verification_steps=practice_defaults["verification_steps"],
            success_signal=practice_defaults["success_signal"],
            stuck_recovery=practice_defaults["stuck_recovery"],
            reflection_prompt=practice_defaults["reflection_prompt"],
            return_with=practice_defaults["return_with"],
            next_after_completion=practice_defaults["next_after_completion"],
            difficulty="medium",
        )

    def _generate_from_plan_requirement(
        self,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
    ) -> TrainingCardCandidateSnapshot:
        """Generate a training card targeting a plan stage skill."""
        card_type = context.card_type or "flash"
        llm_card = (
            self._try_llm_generation(context, "plan_requirement", card_type)
            if allow_llm
            else None
        )
        if llm_card is not None:
            if context.plan_stage_id:
                llm_card.plan_links = [context.plan_stage_id]
            return llm_card
        guided_pack = _match_guided_scenario_pack(context, source="plan_requirement")
        if guided_pack:
            card = _make_guided_scenario_pack_card(
                guided_pack,
                context,
                card_type,
                context.response_language or "en-US",
            )
            if context.plan_stage_id:
                card.plan_links = [context.plan_stage_id]
            return card

        language = context.response_language
        if card_type == "practice":
            skill = context.target_skill or context.focus_area or "plan skill"
            is_code_subject = _subject_lane(context) == "code"
            plan_deliverable = _localized_text(
                "One small patch or learner-authored artifact tied to the current plan stage."
                if is_code_subject
                else "One small learner-authored artifact tied to the current plan stage.",
                "一个与当前计划阶段直接相关的小补丁或学习产物。"
                if is_code_subject
                else "一个与当前计划阶段直接相关的小型学习产出。",
                language,
            )
            plan_rubric = [
                _localized_text(
                    "The action stayed tightly bounded.",
                    "行动边界保持得很紧。",
                    language,
                ),
                _localized_text(
                    "The result can be verified without extra guesswork.",
                    "结果可以在没有额外猜测的情况下验证。",
                    language,
                ),
            ]
            card = TrainingCardCandidateSnapshot(
                card_type="practice",
                title=_localized_text(
                    f"Practice: {skill}",
                    f"练习：{skill}",
                    language,
                ),
                focus_area=context.focus_area or context.target_skill,
                target_skill=context.target_skill,
                scenario=_localized_text(
                    context.context_hint or "This plan stage needs one small, verifiable move.",
                    context.context_hint or "当前 plan stage 需要一个小而可验证的推进动作。",
                    language,
                ),
                problem_statement=_localized_text(
                    f"Turn {skill} into one narrow implementation slice you can review in one pass."
                    if is_code_subject
                    else f"Turn {skill} into one narrow learning move you can review in one pass.",
                    f"把 {skill} 收窄成一个可以一遍评审完的小实现切片。"
                    if is_code_subject
                    else f"把 {skill} 收成一个范围很窄、可以快速复盘的学习动作。",
                    language,
                ),
                suggested_workspace_action=_localized_text(
                    "Make one narrow change that proves the current plan step is real."
                    if is_code_subject
                    else "Take one narrow action or produce one short artifact that proves the current plan step is real.",
                    "做一个很窄的改动，证明当前计划这一步是真的落地了。"
                    if is_code_subject
                    else "做一个很窄的动作，或产出一个很短的结果，证明当前计划这一步是真的落地了。",
                    language,
                ),
                deliverable=plan_deliverable,
                learner_deliverables=[
                    _localized_text(
                        "One focused patch on the current plan thread."
                        if is_code_subject
                        else "One focused artifact on the current plan thread.",
                        "当前计划主线上的一个聚焦补丁。"
                        if is_code_subject
                        else "当前计划主线上的一个聚焦产出。",
                        language,
                    ),
                    _localized_text(
                        "One short note explaining why this move is the right next step.",
                        "一段简短说明，解释为什么这一步是当前最合适的下一步。",
                        language,
                    ),
                ],
                validation_method=_localized_text(
                    "Run the smallest relevant check and explain why the result now holds.",
                    "运行最小相关检查，并说明为什么这次结果已经成立。",
                    language,
                ),
                verification_steps=[
                    _localized_text(
                        f"Check the exact behavior around {skill}.",
                        f"先检查 {skill} 附近的具体行为。",
                        language,
                    ),
                    _localized_text(
                        "Confirm the move still fits in one short review pass.",
                        "确认这一步仍然可以在一次很短的检查里看完。",
                        language,
                    ),
                ],
                self_check=[
                    _localized_text(
                        "Did you keep the slice tight enough to review quickly?",
                        "你有没有把切片保持得足够紧，能被快速评审？",
                        language,
                    ),
                    _localized_text(
                        "Can you point to one concrete proof that the move works?",
                        "你能不能指出一个具体证据，来证明这一步有效？",
                        language,
                    ),
                ],
                grading_rubric=plan_rubric,
                acceptance_criteria=derive_acceptance_criteria(
                    plan_deliverable,
                    plan_rubric,
                    context.target_skill or context.focus_area or "",
                    language=language,
                ),
                common_mistakes=[
                    _localized_text(
                        "Turning the plan step into a refactor instead of a narrow proof."
                        if is_code_subject
                        else "Turning one small plan step into a broad rewrite instead of a narrow proof.",
                        "把这一步做成重构，而不是一个范围很窄的证明动作。"
                        if is_code_subject
                        else "把一个很小的计划步骤做成大改写，而不是一个范围很窄的证明动作。",
                        language,
                    ),
                    _localized_text(
                        "Only explaining the plan without landing a visible artifact.",
                        "只讲计划，不落成一个可见的结果。",
                        language,
                    ),
                ],
                stuck_recovery=_localized_text(
                    "Return to the smallest boundary you can state, then prove only that boundary first.",
                    "回到你能说清楚的最小边界，先只证明这个边界。",
                    language,
                ),
                reflection_prompt=_localized_text(
                    "What did this step prove, and what did you deliberately leave out?",
                    "这一步证明了什么，又刻意没有包含什么？",
                    language,
                ),
                success_signal=_localized_text(
                    "One narrow plan step landed with a concrete check.",
                    "一个很窄的计划步骤已经落地，并带着具体验证结果。",
                    language,
                ),
                return_with=_localized_text(
                    "Return with the patch, the check result, and one sentence of reflection."
                    if is_code_subject
                    else "Return with the artifact, the check result, and one sentence of reflection.",
                    "带着补丁、验证结果和一句复盘说明回来。"
                    if is_code_subject
                    else "带着产出、验证结果和一句复盘说明回来。",
                    language,
                ),
                next_after_completion=_localized_text(
                    "Update evidence, then decide whether the next move should stay in practice or switch to flash review.",
                    "更新 evidence，然后决定下一步继续 practice 还是切回 flash 复习。",
                    language,
                ),
                difficulty="medium",
            )
            if context.plan_stage_id:
                card.plan_links = [context.plan_stage_id]
            return card

        card = TrainingCardCandidateSnapshot(
            card_type="flash",
            title=_localized_text(
                f"Flash: {context.target_skill or context.focus_area or 'plan skill'}",
                f"闪记：{context.target_skill or context.focus_area or '计划技能'}",
                language,
            ),
            focus_area=context.focus_area or context.target_skill,
            target_skill=context.target_skill,
            knowledge_type="engineering_concept",
            question=_localized_text(
                f"What is the core idea behind {context.target_skill or 'this skill'}?",
                f"{context.target_skill or '这个技能'} 的核心概念是什么？",
                language,
            ),
            context=_localized_text(
                context.context_hint or "This skill is required by your current plan stage.",
                context.context_hint or "这是你当前 plan stage 需要的技能。",
                language,
            ),
            answer_mode="text",
            expected_answer=_localized_text(
                "A concise explanation of the concept.",
                "对这个概念的简洁说明。",
                language,
            ),
            hint_ladder=[
                _localized_text("Think about what problem this technique solves.", "想一想这个技术解决了什么问题。", language),
                _localized_text("Consider the data flow or control flow involved.", "再想它涉及怎样的数据流或控制流。", language),
            ],
            difficulty="medium",
        )
        if context.plan_stage_id:
            card.plan_links = [context.plan_stage_id]
        return card

    # ------------------------------------------------------------------
    # Previously stub sources — now LLM-backed with template fallback
    # ------------------------------------------------------------------

    def _generate_from_resource_knowledge(
        self,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
    ) -> TrainingCardCandidateSnapshot:
        """Generate a flash card from indexed resource knowledge."""
        card_type = context.card_type or "flash"
        guided_pack = _match_guided_scenario_pack(context, source="resource_knowledge")
        if guided_pack:
            return _make_guided_scenario_pack_card(
                guided_pack,
                context,
                card_type,
                context.response_language or "en-US",
            )
        trust_state = _derive_resource_trust_state(context)
        reliability_note = _resource_reliability_note(context, context.response_language)
        llm_card = (
            self._try_llm_generation(context, "resource_knowledge", card_type)
            if allow_llm
            else None
        )
        if llm_card is not None:
            llm_card.trust_state = cast(TrainingCardTrustState, trust_state)
            if reliability_note:
                llm_card.why_now = (
                    f"{llm_card.why_now} {reliability_note}".strip()
                    if llm_card.why_now
                    else reliability_note
                )
            return llm_card

        # Template fallback
        if card_type == "flash":
            language = context.response_language
            question = (
                _localized_text(
                    f"What key concept from the resource relates to {context.focus_area or 'this topic'}?",
                    f"资料里与 {context.focus_area or '这个主题'} 相关的关键概念是什么？",
                    language,
                )
                if not context.resource_missing
                else _localized_text(
                    f"Why can't the coach safely turn {context.focus_area or 'this topic'} into a grounded flash card yet?",
                    f"为什么 coach 现在还不能把 {context.focus_area or '这个主题'} 安全地做成 grounded flash card？",
                    language,
                )
            )
            expected_answer = (
                _localized_text(
                    "The core concept explained in the resource.",
                    "资料里解释的核心概念。",
                    language,
                )
                if trust_state not in {"untrusted", "stale"}
                else _localized_text(
                    "State the trust or content problem first, then name what evidence is still missing.",
                    "先说明资料可信度或内容问题，再说还缺什么证据。",
                    language,
                )
            )
            hint_ladder = (
                [
                    _localized_text("Review the resource section on this topic.", "先看资料里这个主题对应的部分。", language),
                    _localized_text("Identify the key definition or pattern.", "找出关键定义或模式。", language),
                ]
                if trust_state not in {"untrusted", "stale"}
                else [
                    _localized_text("Check whether the resource was actually indexed successfully.", "先确认资料是不是已经成功索引。", language),
                    _localized_text("Name the missing proof before trying to memorize content from it.", "先说清楚缺的证据，再去记内容。", language),
                ]
            )
            feedback = (
                {
                    "correct": _localized_text("Well done! You've grasped the resource content.", "做得好，你已经抓住资料内容了。", language),
                    "incorrect": _localized_text("Review the resource again and focus on the key definition.", "再回去看一遍资料，重点放在关键定义上。", language),
                }
                if trust_state not in {"untrusted", "stale"}
                else {
                    "correct": _localized_text("Good catch. You noticed the coach still lacks a trustworthy source to teach from.", "发现得好。你注意到 coach 现在还没有足够可信的资料可教。", language),
                    "incorrect": _localized_text("Do not memorize from this yet. Resolve the resource trust or content gap first.", "现在先别记这个。先把资料可信度或内容缺口处理掉。", language),
                }
            )
            card = TrainingCardCandidateSnapshot(
                card_type="flash",
                title=_localized_text(
                    f"Flash: {context.focus_area or context.target_skill or 'resource concept'}",
                    f"闪记：{context.focus_area or context.target_skill or '资料概念'}",
                    language,
                ),
                focus_area=context.focus_area or context.target_skill,
                target_skill=context.target_skill,
                knowledge_type="engineering_concept",
                question=question,
                context=_localized_text(
                    context.context_hint or "Extracted from an indexed learning resource.",
                    context.context_hint or "从已索引的学习资料中提取。",
                    language,
                ),
                answer_mode="text",
                expected_answer=expected_answer,
                hint_ladder=hint_ladder,
                common_mistakes=[
                    _localized_text("Confusing the concept with a related but different idea.", "把这个概念和相近但不同的概念混在一起。", language),
                ],
                feedback=feedback,
                difficulty="medium",
            )
            card.trust_state = cast(TrainingCardTrustState, trust_state)
            if reliability_note:
                card.why_now = (
                    f"{card.why_now} {reliability_note}".strip()
                    if card.why_now
                    else reliability_note
                )
            return card
        card = self._make_fallback_card("resource_knowledge", context)
        card.trust_state = cast(TrainingCardTrustState, trust_state)
        if reliability_note:
            card.why_now = f"{card.why_now} {reliability_note}".strip()
        return card

    def _generate_from_practice_feedback(
        self,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
    ) -> TrainingCardCandidateSnapshot:
        """Generate a practice card from recent practice feedback."""
        card_type = context.card_type or "practice"
        llm_card = (
            self._try_llm_generation(context, "practice_feedback", card_type)
            if allow_llm
            else None
        )
        if llm_card is not None:
            return llm_card
        guided_pack = _match_guided_scenario_pack(context, source="practice_feedback")
        if guided_pack and card_type == "practice":
            return _make_guided_scenario_pack_card(
                guided_pack,
                context,
                "practice",
                context.response_language or "en-US",
            )

        # Template fallback
        if card_type == "practice":
            language = context.response_language
            skill = context.focus_area or context.target_skill or "this skill"
            is_code_subject = _subject_lane(context) == "code"
            revised_deliverable = _localized_text(
                "An improved implementation addressing the feedback."
                if is_code_subject
                else "A revised artifact or explanation that addresses the feedback.",
                "一个针对反馈完成改进的实现。"
                if is_code_subject
                else "一个已经回应反馈的修订结果或解释。",
                language,
            )
            revised_rubric = [
                _localized_text("Feedback points addressed", "反馈点已处理", language),
                _localized_text(
                    "Quality or clarity maintained or improved",
                    "质量或清晰度保持住了，或者更好了",
                    language,
                ),
            ]
            return TrainingCardCandidateSnapshot(
                card_type="practice",
                title=_localized_text(
                    f"Practice: Improve {skill}",
                    f"练习：改进 {skill}",
                    language,
                ),
                focus_area=context.focus_area or context.target_skill,
                target_skill=context.target_skill,
                scenario=_localized_text(
                    context.context_hint or "Address feedback from a recent practice session.",
                    context.context_hint or "根据最近一次练习反馈来改进。",
                    language,
                ),
                problem_statement=_localized_text(
                    f"Based on recent feedback, improve your {skill} implementation."
                    if is_code_subject
                    else f"Based on recent feedback, improve your work on {skill}.",
                    f"根据最近反馈，改进你的 {skill} 实现。"
                    if is_code_subject
                    else f"根据最近反馈，改进你在 {skill} 上的这一步。",
                    language,
                ),
                suggested_workspace_action=_localized_text(
                    "Review feedback and refactor your code."
                    if is_code_subject
                    else "Review the feedback and revise one small part of the work.",
                    "回看反馈并重构代码。"
                    if is_code_subject
                    else "回看反馈，并只修改这份工作里很小的一处。",
                    language,
                ),
                api_hints=[
                    _localized_text(
                        "Review the most relevant note, example, or reference for this skill area.",
                        "回看这个技能最相关的一条笔记、例子或参考材料。",
                        language,
                    ),
                ],
                deliverable=revised_deliverable,
                self_check=[
                    _localized_text(
                        "Does the revision address the feedback points?",
                        "这次修订有回应反馈点吗？",
                        language,
                    ),
                    _localized_text(
                        "Is the improvement specific and visible?",
                        "这次改进是否足够具体，而且看得见？",
                        language,
                    ),
                ],
                grading_rubric=revised_rubric,
                acceptance_criteria=derive_acceptance_criteria(
                    revised_deliverable,
                    revised_rubric,
                    context.target_skill or context.focus_area or "",
                    language=language,
                ),
                stuck_recovery=_localized_text(
                    "Re-read the original feedback carefully and implement one fix at a time.",
                    "重新仔细阅读原始反馈，一次只做一个修复。",
                    language,
                ),
                reflection_prompt=_localized_text(
                    "What did the feedback reveal about your understanding?",
                    "这次反馈暴露了你理解里的什么问题？",
                    language,
                ),
                difficulty="medium",
            )
        return self._make_fallback_card("practice_feedback", context)

    def _generate_from_dependency_mastery(
        self,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
    ) -> TrainingCardCandidateSnapshot:
        """Generate a flash card for a prerequisite skill not yet mastered."""
        card_type = context.card_type or "flash"
        guided_pack = _match_guided_scenario_pack(context, source="dependency_mastery")
        if guided_pack:
            return _make_guided_scenario_pack_card(
                guided_pack,
                context,
                card_type,
                context.response_language or "en-US",
            )
        llm_card = (
            self._try_llm_generation(context, "dependency_mastery", card_type)
            if allow_llm
            else None
        )
        if llm_card is not None:
            return llm_card

        # Template fallback
        if card_type == "flash":
            language = context.response_language
            skill = context.target_skill or context.focus_area or "prerequisite skill"
            return TrainingCardCandidateSnapshot(
                card_type="flash",
                title=_localized_text(
                    f"Flash: Prerequisite {skill}",
                    f"闪记：前置技能 {skill}",
                    language,
                ),
                focus_area=context.focus_area or context.target_skill,
                target_skill=context.target_skill,
                knowledge_type="engineering_concept",
                question=_localized_text(
                    f"What is {skill} and why is it a prerequisite for your current work?",
                    f"{skill} 是什么，为什么它是你当前工作的前置技能？",
                    language,
                ),
                context=_localized_text(
                    context.context_hint or "This prerequisite skill needs mastery before advancing.",
                    context.context_hint or "这个前置技能需要先掌握，才能继续往下推进。",
                    language,
                ),
                answer_mode="text",
                expected_answer=_localized_text(
                    f"A clear explanation of {skill} and its role as a foundation.",
                    f"对 {skill} 及其作为基础能力的作用给出清晰解释。",
                    language,
                ),
                hint_ladder=[
                    _localized_text(f"Think about what {skill} enables.", f"先想想 {skill} 能让你做什么。", language),
                    _localized_text(
                        "Consider how this concept connects to what you're currently learning.",
                        "再考虑它和你现在学习的内容如何连接。",
                        language,
                    ),
                ],
                common_mistakes=[
                    _localized_text("Confusing this prerequisite with more advanced concepts.", "把这个前置技能和更高级的概念混淆。", language),
                    _localized_text("Skipping fundamentals too quickly.", "太快跳过基础。", language),
                ],
                feedback={
                    "correct": _localized_text("Great! You have the foundation needed to move forward.", "很好，你已经具备继续往前的基础了。", language),
                    "incorrect": _localized_text("Spend more time on this foundation before advancing.", "先把这个基础学稳，再继续往下。", language),
                },
                difficulty="easy",
            )
        return self._make_fallback_card("dependency_mastery", context)

    def _generate_from_review_due(
        self,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
    ) -> TrainingCardCandidateSnapshot:
        """Generate a flash card for a concept due for review."""
        card_type = context.card_type or "flash"
        llm_card = (
            self._try_llm_generation(context, "review_due", card_type)
            if allow_llm
            else None
        )
        if llm_card is not None:
            return llm_card
        guided_pack = _match_guided_scenario_pack(context, source="review_due")
        if guided_pack and card_type == "flash":
            return _make_guided_scenario_pack_card(
                guided_pack,
                context,
                "flash",
                context.response_language or "en-US",
            )

        # Template fallback
        if card_type == "flash":
            language = context.response_language
            skill = context.focus_area or context.target_skill or "review concept"
            return TrainingCardCandidateSnapshot(
                card_type="flash",
                title=_localized_text(
                    f"Review: {skill}",
                    f"复习：{skill}",
                    language,
                ),
                focus_area=context.focus_area or context.target_skill,
                target_skill=context.target_skill,
                knowledge_type="engineering_concept",
                question=_localized_text(
                    f"Explain the key aspects of {skill} from memory.",
                    f"请从记忆中说明 {skill} 的关键点。",
                    language,
                ),
                context=_localized_text(
                    context.context_hint or "Scheduled review - recall and reinforce this concept.",
                    context.context_hint or "计划中的复习 - 回忆并巩固这个概念。",
                    language,
                ),
                answer_mode="text",
                expected_answer=_localized_text(
                    f"A complete explanation of {skill} covering the main points.",
                    f"对 {skill} 的完整说明，覆盖主要要点。",
                    language,
                ),
                hint_ladder=[
                    _localized_text("Start with the core definition.", "先从核心定义开始。", language),
                    _localized_text("Think about when and why you would use this.", "想想你会在什么情况下、为什么使用它。", language),
                ],
                common_mistakes=[
                    _localized_text("Forgetting edge cases or limitations.", "遗漏边界情况或限制。", language),
                    _localized_text("Confusing with similar concepts.", "把它和相似概念混淆。", language),
                ],
                feedback={
                    "correct": _localized_text("Your recall is solid - this concept is well-reinforced.", "很好，你的回忆很稳，这个概念已经被巩固。", language),
                    "incorrect": _localized_text("This needs more reinforcement. Review the original material.", "这里还需要更多巩固。请回到原始材料。", language),
                },
                difficulty="medium",
            )
        return self._make_fallback_card("review_due", context)

    def _generate_stub(
        self,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
    ) -> TrainingCardCandidateSnapshot:
        """Fallback for unknown source types."""
        return self._make_fallback_card("conversation_gap", context)

    def _make_fallback_card(
        self,
        source_key: str,
        context: CardGenerationContext,
    ) -> TrainingCardCandidateSnapshot:
        """Create a truthful fallback card when the source is unknown or underspecified."""
        topic = context.focus_area or context.target_skill or "current work"
        language = context.response_language
        if context.card_type == "flash":
            return TrainingCardCandidateSnapshot(
                card_type="flash",
                title=_localized_text(
                    f"Flash: {topic}",
                    f"闪记：{topic}",
                    language,
                ),
                focus_area=context.focus_area or context.target_skill,
                target_skill=context.target_skill,
                knowledge_type="engineering_concept",
                question=_localized_text(
                    f"What is the smallest truthful explanation of {topic}?",
                    f"{topic} 的最小真实解释是什么？",
                    language,
                ),
                context=_localized_text(
                    context.context_hint or f"Fallback card generated from {source_key}.",
                    context.context_hint or f"来自 {source_key} 的回退卡片。",
                    language,
                ),
                answer_mode="text",
                expected_answer=_localized_text(
                    f"A concise explanation of {topic} and the boundary it sits within.",
                    f"对 {topic} 的简洁说明，以及它所处的边界。",
                    language,
                ),
                hint_ladder=[
                    _localized_text("Name the core idea first.", "先说核心概念。", language),
                    _localized_text("Add one concrete example or boundary condition.", "再举一个具体例子或边界条件。", language),
                ],
                common_mistakes=[
                    _localized_text("Jumping straight to implementation details without defining the concept.", "还没定义概念就直接讲实现细节。", language),
                ],
                feedback={
                    "correct": _localized_text("Good. You kept the explanation grounded.", "很好，你把解释控制在了真实边界内。", language),
                    "incorrect": _localized_text("Return to the smallest truthful explanation and name the boundary.", "回到最小真实解释，并说清楚边界。", language),
                },
                difficulty=context.difficulty,
            )

        practice_defaults = _practice_defaults(context, language)
        return TrainingCardCandidateSnapshot(
            card_type="practice",
            title=_localized_text(
                f"Practice: {topic}",
                f"练习：{topic}",
                language,
            ),
            focus_area=context.focus_area or context.target_skill,
            target_skill=context.target_skill,
            scenario=_localized_text(
                context.context_hint or f"Fallback card generated from {source_key}.",
                context.context_hint or f"来自 {source_key} 的回退卡片。",
                language,
            ),
            problem_statement=practice_defaults["problem_statement"],
            suggested_workspace_action=practice_defaults["suggested_workspace_action"],
            api_hints=practice_defaults["api_hints"],
            deliverable=practice_defaults["deliverable"],
            self_check=practice_defaults["self_check"],
            validation_method=practice_defaults["validation_method"],
            grading_rubric=practice_defaults["grading_rubric"],
            acceptance_criteria=derive_acceptance_criteria(
                practice_defaults["deliverable"],
                practice_defaults["grading_rubric"],
                context.target_skill or context.focus_area or "",
                language=language,
            ),
            learner_deliverables=practice_defaults["learner_deliverables"],
            verification_steps=practice_defaults["verification_steps"],
            success_signal=practice_defaults["success_signal"],
            stuck_recovery=practice_defaults["stuck_recovery"],
            reflection_prompt=practice_defaults["reflection_prompt"],
            return_with=practice_defaults["return_with"],
            next_after_completion=practice_defaults["next_after_completion"],
            difficulty=context.difficulty,
        )
