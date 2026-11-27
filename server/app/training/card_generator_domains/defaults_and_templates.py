"""Card generation service with LLM-backed content generation.

Generates TrainingCardCandidateSnapshot instances from different sources:
conversation_gap, plan_requirement, resource_knowledge, practice_feedback,
dependency_mastery, review_due.

Each source method attempts LLM generation first. On failure, it falls back
to a deterministic template.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files as resource_files
from typing import TYPE_CHECKING, Any, cast

from ...core.models import (
    CardGenerationContext,
    ResourceKnowledgeEvidence,
    TrainingCardCandidateSnapshot,
    TrainingCardCreatedFrom,
)
from ...llm.provider.errors import provider_error_quota_exhausted
from ...pedagogy.evidence_controls import (
    CodeReveal,
    Difficulty,
    MaterialRecommendation,
    NextPlanStep,
    PedagogyControls,
    PedagogyMode,
    PracticeType,
    ReviewFrequency,
    apply_controls_to_card,
)
from ..subject_taxonomy import build_subject_blob, classify_learning_subject

try:
    from ...llm.prompts import CARD_FLASH_SYSTEM, CARD_PRACTICE_SYSTEM
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
    pass


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CardGenerationStreamEvent:
    """One visible provider chunk or the completed generated card."""

    chunk: str | None = None
    card: TrainingCardCandidateSnapshot | None = None


_CARD_STREAM_IDLE_TIMEOUT_SECONDS = 45.0


_CARD_GENERATION_ATTEMPT_TIMEOUT_SECONDS = 300.0


def _normalize_card_locale(language: str | None) -> str:
    raw = str(language or "").strip().lower().replace("_", "-")
    if raw.startswith("zh"):
        return "zh-CN"
    if raw.startswith("es"):
        return "es-ES"
    if raw.startswith("fr"):
        return "fr-FR"
    if raw.startswith("de"):
        return "de-DE"
    if raw.startswith("ja"):
        return "ja-JP"
    if raw.startswith("ko"):
        return "ko-KR"
    if raw.startswith("pt"):
        return "pt-BR"
    return "en-US"


def _localized_8(copy_by_locale: dict[str, str], language: str | None) -> str:
    locale = _normalize_card_locale(language)
    return copy_by_locale.get(locale) or copy_by_locale["en-US"]


_PROVIDER_FAILURE_DETAIL_BY_LOCALE: dict[str, str] = {
    "en-US": "The model-authored card was not accepted; retry generation to obtain a model card.",
    "zh-CN": "模型生成的卡片未被接受；可以重试以获取模型卡片。",
    "es-ES": "No se aceptó la tarjeta generada por el modelo; vuelve a intentar la generación para obtener una tarjeta del modelo.",
    "fr-FR": "La carte générée par le modèle n'a pas été acceptée ; relance la génération pour obtenir une carte du modèle.",
    "de-DE": "Die vom Modell erstellte Karte wurde nicht akzeptiert; starte die Generierung erneut, um eine Modellkarte zu erhalten.",
    "ja-JP": "モデルが生成したカードが受け入れられませんでした。モデルカードを取得するには再生成してください。",
    "ko-KR": "모델이 생성한 카드가 수락되지 않았습니다. 모델 카드를 받으려면 생성을 다시 시도하세요.",
    "pt-BR": "O cartão gerado pelo modelo não foi aceito; tente gerar novamente para obter um cartão do modelo.",
}


_PROVIDER_UNAVAILABLE_DETAIL_BY_LOCALE: dict[str, str] = {
    "en-US": "The model provider is temporarily unavailable; retry card generation in a moment.",
    "zh-CN": "模型提供方暂时不可用；请稍等片刻后重试生成卡片。",
    "es-ES": "El proveedor del modelo no está disponible temporalmente; vuelve a generar la tarjeta en unos instantes.",
    "fr-FR": "Le fournisseur du modèle est temporairement indisponible ; relance la génération dans un instant.",
    "de-DE": "Der Modellanbieter ist vorübergehend nicht erreichbar; starte die Kartengenerierung gleich erneut.",
    "ja-JP": "モデル提供元が一時的に利用できません。しばらくしてからカード生成を再試行してください。",
    "ko-KR": "모델 제공자가 일시적으로 사용할 수 없습니다. 잠시 후 카드 생성을 다시 시도하세요.",
    "pt-BR": "O provedor do modelo está temporariamente indisponível; tente gerar o cartão novamente em instantes.",
}


_PROVIDER_QUOTA_DETAIL_BY_LOCALE: dict[str, str] = {
    "en-US": "The model provider account quota is exhausted; top up the account before generating a card.",
    "zh-CN": "模型提供方的账户额度已用尽；补充额度后再生成卡片。",
    "es-ES": "La cuota de la cuenta del proveedor del modelo está agotada; recarga la cuenta antes de generar una tarjeta.",
    "fr-FR": "Le quota du compte du fournisseur est épuisé ; recharge le compte avant de générer une carte.",
    "de-DE": "Das Kontingent des Modellanbieter-Kontos ist aufgebraucht; lade das Konto auf, bevor du eine Karte erzeugst.",
    "ja-JP": "モデル提供元アカウントの利用枠が上限に達しました。残高を追加してからカードを生成してください。",
    "ko-KR": "모델 제공자 계정의 사용 한도가 소진되었습니다. 충전 후 카드를 생성하세요.",
    "pt-BR": "A cota da conta do provedor do modelo esgotou; recarregue a conta antes de gerar um cartão.",
}


def _provider_failure_reason(error: BaseException) -> str:
    """Classify transport failures in a provider exception chain.

    ``ProviderService.chat_completion`` wraps every transport error in a plain
    ``RuntimeError`` and keeps the original as ``__cause__``, so the status
    code and retryable marker live one or more links down the chain.
    """
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        category = str(getattr(current, "provider_error_category", "") or "").strip().lower()
        status = getattr(current, "status_code", None)
        if not isinstance(status, int):
            response = getattr(current, "response", None)
            status = getattr(response, "status_code", None)
        if category == "quota_exhausted" or status == 402:
            return "provider_quota_exhausted"
        if (
            status == 429
            and isinstance(current, Exception)
            and provider_error_quota_exhausted(current)
        ):
            # A rate limit and an exhausted account both arrive as 429; only
            # the latter is pointless to retry.
            return "provider_quota_exhausted"
        if isinstance(status, int) and (status >= 500 or status in {408, 429}):
            return "provider_unavailable"
        if getattr(current, "provider_retryable", None) is True:
            return "provider_unavailable"
        if isinstance(current, TimeoutError) or type(current).__name__ in {
            "APIConnectionError", "APITimeoutError", "ConnectError", "ConnectTimeout",
            "ReadTimeout", "RemoteProtocolError",
        }:
            return "provider_unavailable"
        current = current.__cause__ or current.__context__
    return ""


class CardGenerationProviderFailure(RuntimeError):
    """A live provider did not produce a valid card; do not persist a template."""

    def __init__(self, reason: str, *, response_language: str | None = None) -> None:
        self.reason = str(reason or "invalid_card")
        copy = _PROVIDER_FAILURE_DETAIL_BY_LOCALE
        if self.reason == "provider_unavailable":
            copy = _PROVIDER_UNAVAILABLE_DETAIL_BY_LOCALE
        elif self.reason == "provider_quota_exhausted":
            copy = _PROVIDER_QUOTA_DETAIL_BY_LOCALE
        self.detail = _localized_8(copy, response_language)
        # Only a real outage is worth retrying as-is; quota and malformed
        # model output need a different learner action.
        self.retryable = self.reason == "provider_unavailable"
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
        # The whitelist normalization above guarantees each value is a member
        # of its Literal; the casts only recover that fact for the typechecker.
        difficulty=cast(Difficulty, difficulty),
        hint_count=max(1, min(5, int(hint_count))),
        explanation_depth="rebuild" if difficulty == "easy" else "grounded",
        code_reveal=cast(CodeReveal, code_reveal),
        practice_type=cast(PracticeType, practice_type),
        review_frequency=cast(ReviewFrequency, review_frequency),
        material_recommendation=cast(MaterialRecommendation, material),
        next_plan_step=cast(NextPlanStep, next_step),
        should_reveal_code=bool(should_reveal),
        challenge_level="lower" if difficulty == "easy" else "raise" if difficulty == "hard" else "steady",
        hint_depth="direct" if difficulty == "easy" else "lighter" if difficulty == "hard" else "guided",
        review_urgency="high" if review_frequency == "sooner" else "low" if review_frequency == "later" else "normal",
        next_step_bias="shrink" if next_step == "shrink" else "widen" if next_step == "widen" else "steady",
        pedagogy_mode=cast(PedagogyMode, pedagogy_mode),
    )
    return apply_controls_to_card(card, controls, language=context.response_language)


CardGenerationStreamInterrupted = CardGenerationStreamError


_SOURCE_MAP: dict[str, TrainingCardCreatedFrom] = {
    "conversation_gap": "conversation",
    "plan_requirement": "plan",
    "resource_knowledge": "resource",
    "practice_feedback": "practice_feedback",
    "dependency_mastery": "dependency_mastery",
    "review_due": "review_due",
}


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


_WHY_NOW_MESSAGES_BY_LOCALE: dict[str, dict[str, str]] = {
    "en-US": _WHY_NOW_MESSAGES,
    "zh-CN": _WHY_NOW_MESSAGES_ZH,
    "es-ES": {
        "conversation_gap": "Se detectó una brecha de conocimiento durante la conversación.",
        "plan_requirement": "Esta etapa del plan requiere dominar esta habilidad.",
        "resource_knowledge": "Se encontró conocimiento extraíble en un recurso indexado.",
        "practice_feedback": "Comentarios de una sesión de práctica reciente.",
        "dependency_mastery": "Una habilidad previa aún no está dominada.",
        "review_due": "Este concepto ya tiene pendiente su repaso programado.",
    },
    "fr-FR": {
        "conversation_gap": "Une lacune a été détectée pendant la conversation.",
        "plan_requirement": "Cette étape du plan exige de maîtriser cette compétence.",
        "resource_knowledge": "Des connaissances exploitables ont été trouvées dans une ressource indexée.",
        "practice_feedback": "Retour d'une séance de pratique récente.",
        "dependency_mastery": "Une compétence prérequise n'est pas encore maîtrisée.",
        "review_due": "La révision planifiée de ce concept est arrivée à échéance.",
    },
    "de-DE": {
        "conversation_gap": "Im Gespräch wurde eine Wissenslücke erkannt.",
        "plan_requirement": "Dieser Planschritt erfordert das Beherrschen dieser Fähigkeit.",
        "resource_knowledge": "In einer indexierten Quelle wurden verwertbare Inhalte gefunden.",
        "practice_feedback": "Rückmeldung aus einer kürzlichen Übungseinheit.",
        "dependency_mastery": "Eine vorausgesetzte Fähigkeit ist noch nicht sicher beherrscht.",
        "review_due": "Für dieses Konzept steht die geplante Wiederholung an.",
    },
    "ja-JP": {
        "conversation_gap": "会話の中で知識の抜けが見つかりました。",
        "plan_requirement": "プランのこの段階では、このスキルの習得が必要です。",
        "resource_knowledge": "インデックス済み資料から抽出できる知識が見つかりました。",
        "practice_feedback": "直近の練習セッションからのフィードバックです。",
        "dependency_mastery": "前提となるスキルがまだ習得できていません。",
        "review_due": "この概念の予定復習タイミングになりました。",
    },
    "ko-KR": {
        "conversation_gap": "대화 중에 지식 공백이 발견되었습니다.",
        "plan_requirement": "계획 단계에서 이 기술을 먼저 익혀야 합니다.",
        "resource_knowledge": "색인된 자료에서 추출할 수 있는 지식을 찾았습니다.",
        "practice_feedback": "최근 연습 세션의 피드백에서 이어졌습니다.",
        "dependency_mastery": "선행 기술이 아직 충분히 숙달되지 않았습니다.",
        "review_due": "이 개념의 예정된 복습 시점이 되었습니다.",
    },
    "pt-BR": {
        "conversation_gap": "Uma lacuna de conhecimento foi detectada durante a conversa.",
        "plan_requirement": "Esta etapa do plano exige dominar esta habilidade.",
        "resource_knowledge": "Conhecimento extraível encontrado em um recurso indexado.",
        "practice_feedback": "Feedback de uma sessão de prática recente.",
        "dependency_mastery": "Uma habilidade pré-requisito ainda não foi dominada.",
        "review_due": "A revisão programada deste conceito está no prazo.",
    },
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
    allow_resource_content: bool = False,
) -> str | None:
    source_key = str(source or context.source or "").strip().lower()
    if source_key == "resource_knowledge" and allow_resource_content:
        evidence, fragment_id, source_type, focus, summary = _resource_knowledge_evidence(context)
        if (evidence is not None and evidence.resource_id == context.resource_id
                and fragment_id and source_type and focus and summary
                and _derive_resource_trust_state(context) == "trusted"
                and not context.resource_missing and context.resource_freshness != "stale"):
            # Once the source is verified, teach its content rather than replacing
            # every subject with the same provenance quiz. Missing evidence still
            # takes the deterministic, governed path below.
            return None
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


_FALLBACK_REASON_BY_LOCALE: dict[str, dict[str, str]] = {
    "invalid_json": {
        "en-US": "invalid JSON",
        "zh-CN": "无效 JSON",
        "es-ES": "JSON no válido",
        "fr-FR": "JSON invalide",
        "de-DE": "ungültiges JSON",
        "ja-JP": "無効な JSON",
        "ko-KR": "유효하지 않은 JSON",
        "pt-BR": "JSON inválido",
    },
    "invalid_card": {
        "en-US": "invalid card payload",
        "zh-CN": "无效卡片内容",
        "es-ES": "contenido de tarjeta no válido",
        "fr-FR": "contenu de carte invalide",
        "de-DE": "ungültige Kartendaten",
        "ja-JP": "無効なカード内容",
        "ko-KR": "유효하지 않은 카드 데이터",
        "pt-BR": "conteúdo de cartão inválido",
    },
    "missing_required_fields": {
        "en-US": "missing required fields",
        "zh-CN": "缺少必需字段",
        "es-ES": "faltan campos obligatorios",
        "fr-FR": "champs obligatoires manquants",
        "de-DE": "fehlende Pflichtfelder",
        "ja-JP": "必須フィールドが不足しています",
        "ko-KR": "필수 필드가 누락되었습니다",
        "pt-BR": "campos obrigatórios ausentes",
    },
    "language_mismatch": {
        "en-US": "language mismatch",
        "zh-CN": "语言不匹配",
        "es-ES": "idioma no coincidente",
        "fr-FR": "langue incohérente",
        "de-DE": "Sprache stimmt nicht überein",
        "ja-JP": "言語が一致しません",
        "ko-KR": "언어가 일치하지 않습니다",
        "pt-BR": "idioma incompatível",
    },
    "provider_stalled": {
        "en-US": "provider stalled",
        "zh-CN": "provider 无响应",
        "es-ES": "el proveedor no respondió",
        "fr-FR": "le fournisseur ne répond plus",
        "de-DE": "Anbieter reagiert nicht",
        "ja-JP": "プロバイダーが応答しません",
        "ko-KR": "공급자가 응답하지 않습니다",
        "pt-BR": "provedor sem resposta",
    },
}


_FALLBACK_PROVENANCE_TEMPLATE_BY_LOCALE: dict[str, str] = {
    "en-US": "Generation source: deterministic fallback ({reason_label}). The model-authored card was not accepted; retry generation to obtain a model card.",
    "zh-CN": "生成来源：确定性降级卡（{reason_label}）。模型生成的卡片未被接受；可以重试以获取模型卡片。",
    "es-ES": "Origen de generación: respaldo determinista ({reason_label}). No se aceptó la tarjeta del modelo; vuelve a intentarlo para obtener una tarjeta generada por el modelo.",
    "fr-FR": "Source de génération : repli déterministe ({reason_label}). La carte du modèle n'a pas été acceptée ; relance la génération pour obtenir une carte du modèle.",
    "de-DE": "Erstellungsquelle: deterministischer Rückfall ({reason_label}). Die Modellkarte wurde nicht akzeptiert; wiederhole die Generierung für eine Modellkarte.",
    "ja-JP": "生成元: 決定論的フォールバック（{reason_label}）。モデルが生成したカードが受け入れられませんでした。モデルカードを取得するには再生成してください。",
    "ko-KR": "생성 출처: 결정론적 대체 카드({reason_label}). 모델이 생성한 카드가 수락되지 않았습니다. 모델 카드를 받으려면 다시 생성하세요.",
    "pt-BR": "Origem da geração: fallback determinístico ({reason_label}). O cartão gerado pelo modelo não foi aceito; tente gerar novamente para obter um cartão do modelo.",
}


def _localized_why_now(source: str, why_now: str, language: str | None) -> str:
    locale = _normalize_card_locale(language)
    if locale == "en-US":
        return why_now

    english = _WHY_NOW_MESSAGES.get(source)
    localized = _WHY_NOW_MESSAGES_BY_LOCALE.get(locale, {}).get(source)
    if english and localized and why_now.startswith(english):
        return why_now.replace(english, localized, 1)
    if english and localized and why_now == english:
        return localized
    return why_now


def _fallback_provenance_copy(
    reason: str,
    language: str | None,
) -> tuple[str, str]:
    """Return a machine-readable source marker and learner-facing explanation."""
    normalized_reason = reason.strip() or "unknown"
    locale = _normalize_card_locale(language)
    reason_table = _FALLBACK_REASON_BY_LOCALE.get(normalized_reason)
    reason_label = (
        reason_table.get(locale) or reason_table["en-US"]
        if reason_table is not None
        else normalized_reason
    )
    source_marker = f"generation_source=deterministic_fallback;reason={normalized_reason}"
    template = _FALLBACK_PROVENANCE_TEMPLATE_BY_LOCALE.get(
        locale,
        _FALLBACK_PROVENANCE_TEMPLATE_BY_LOCALE["en-US"],
    )
    return source_marker, template.format(reason_label=reason_label)


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


def _guided_fact_text(value: object, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip()


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
