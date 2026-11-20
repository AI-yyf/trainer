from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .review_intervention import (
    REVIEW_INTERVENTION_KEY,
    derive_review_budget,
    review_refusal_signal,
)

PROACTIVE_BUDGET_KEY = "proactive_budget"
DAILY_PROACTIVE_BUDGET = 2
MIN_NUDGE_SPACING_MINUTES = 45

_IGNORED_DIAGNOSTIC_SEVERITIES = {"info", "information", "hint"}
_LATIN_STOPWORDS = {
    "error",
    "warning",
    "line",
    "file",
    "code",
    "type",
    "value",
    "name",
    "function",
    "method",
    "class",
    "module",
    "import",
    "return",
    "variable",
    "undefined",
    "expected",
    "missing",
    "invalid",
    "failed",
    "check",
    "with",
    "from",
    "that",
    "this",
}
_LATIN_TOKEN_RE = re.compile(r"[a-z0-9_]{4,}", re.IGNORECASE)
_CJK_SPAN_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]{2,}")

_DIAGNOSTIC_WHISPER_TEMPLATES: dict[str, str] = {
    "zh": "注意到 {diagnostic}，这正好踩到你之前标记过容易混的「{concept}」，先小步看一眼这里？",
    "en": "Noticed {diagnostic} — that touches \"{concept}\", a spot you flagged earlier. Want to look closely at this line first?",
    "es": "Se detectó {diagnostic}; toca «{concept}», un punto que antes costó. ¿Lo revisamos paso a paso?",
    "fr": "Repéré : {diagnostic} — cela touche « {concept} », un point déjà fragile. On regarde cette ligne ensemble ?",
    "de": "Auffällig: {diagnostic} — das berührt „{concept}“, wo es neulich hakte. Wollen wir diese Stelle kurz prüfen?",
    "ja": "{diagnostic} が出ています。以前つまずきやすかった「{concept}」と重なるので、ここを先に確認しますか？",
    "ko": "{diagnostic} 경고가 보입니다. 예전에 헷갈렸던 '{concept}'와 이어지는데, 이 부분부터 잠깐 볼까요?",
    "pt": "Apareceu {diagnostic} — isso toca em \"{concept}\", um ponto que já deu dúvida antes. Quer olhar essa linha primeiro?",
}

_REVIEW_WHISPER_TEMPLATES: dict[str, str] = {
    "zh": "「{concept}」之前练过但到点该回头过一眼了；趁现在手感还在，要不要 2 分钟自测确认一下？",
    "en": "\"{concept}\" is ready for a quick recall check while the context is fresh. Want a 2-minute check?",
    "es": "«{concept}» está listo para un repaso breve mientras lo tienes fresco. ¿Hacemos una comprobación rápida?",
    "fr": "« {concept} » est prêt pour un court rappel tant que c'est frais. On fait une vérification rapide ?",
    "de": "„{concept}“ eignet sich gerade für einen kurzen Rückblick, solange der Kontext frisch ist. Kurz prüfen?",
    "ja": "「{concept}」を軽く思い出すタイミングです。覚えているうちに2分だけ確認しませんか？",
    "ko": "'{concept}' 개념을 가볍게 떠올려 볼 때가 되었습니다. 감이 남아 있을 때 잠깐 확인해 볼까요?",
    "pt": "\"{concept}\" está no ponto para uma checagem rápida enquanto o contexto está fresco. Vamos revisar em 2 minutos?",
}


@dataclass(frozen=True)
class ProactiveWhisper:
    """Single-whisper proactive decision constrained by learner budget and focus."""

    should_nudge: bool
    kind: str
    reason: str
    concept: str = ""
    message: str = ""
    remaining_daily_budget: int = DAILY_PROACTIVE_BUDGET
    dedup_key: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "should_nudge": self.should_nudge,
            "kind": self.kind,
            "reason": self.reason,
            "concept": self.concept,
            "message": self.message,
            "remaining_daily_budget": self.remaining_daily_budget,
            "dedup_key": self.dedup_key,
        }


def _ensure_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _parse_iso(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return _ensure_utc(parsed)


def _lang_bucket(language: str | None) -> str:
    lowered = str(language or "").strip().lower()
    if lowered.startswith("zh"):
        return "zh"
    if lowered.startswith("en"):
        return "en"
    if lowered.startswith("es"):
        return "es"
    if lowered.startswith("fr"):
        return "fr"
    if lowered.startswith("de"):
        return "de"
    if lowered.startswith("ja"):
        return "ja"
    if lowered.startswith("ko"):
        return "ko"
    if lowered.startswith("pt"):
        return "pt"
    return "en"


def _budget_state(workspace: dict[str, Any] | None, *, now: datetime) -> dict[str, Any]:
    now_utc = _ensure_utc(now)
    today = now_utc.date().isoformat()
    raw = (workspace or {}).get(PROACTIVE_BUDGET_KEY)
    state = dict(raw) if isinstance(raw, dict) else {}
    stored_date = str(state.get("date") or "")
    last_nudge_at = state.get("last_nudge_at")
    if stored_date != today:
        return {
            "date": today,
            "count": 0,
            "seen_keys": [],
            "last_nudge_at": last_nudge_at,
            "last_kind": state.get("last_kind") or "",
            "last_session_id": state.get("last_session_id") or "",
        }
    seen_keys = [
        str(item).strip()
        for item in (state.get("seen_keys") or [])
        if str(item).strip()
    ]
    return {
        "date": today,
        "count": max(0, int(state.get("count") or 0)),
        "seen_keys": seen_keys,
        "last_nudge_at": last_nudge_at,
        "last_kind": str(state.get("last_kind") or ""),
        "last_session_id": str(state.get("last_session_id") or ""),
    }


def _diagnostic_text_and_severity(item: Any) -> tuple[str, str]:
    if isinstance(item, str):
        text = item.strip()
        lowered = text.lower()
        for sev in _IGNORED_DIAGNOSTIC_SEVERITIES:
            if lowered.startswith(f"{sev}:") or lowered.startswith(f"[{sev}]"):
                return text, sev
        return text, ""
    if isinstance(item, dict):
        severity = str(item.get("severity") or item.get("level") or "").strip().lower()
        text = str(item.get("message") or item.get("text") or item.get("detail") or "").strip()
        return text, severity
    return str(getattr(item, "message", "") or getattr(item, "text", "") or "").strip(), str(
        getattr(item, "severity", "") or ""
    ).strip().lower()


def _extract_tokens(text: str) -> tuple[set[str], set[str]]:
    lowered = text.lower()
    latin = {
        tok
        for tok in _LATIN_TOKEN_RE.findall(lowered)
        if tok not in _LATIN_STOPWORDS
    }
    cjk_ngrams: set[str] = set()
    for span in _CJK_SPAN_RE.findall(lowered):
        cjk_ngrams.add(span)
        for size in (2, 3):
            if len(span) >= size:
                for idx in range(len(span) - size + 1):
                    cjk_ngrams.add(span[idx : idx + size])
    return latin, cjk_ngrams


def _latin_root_overlap(left: set[str], right: set[str]) -> bool:
    if left & right:
        return True
    for a in left:
        prefix = a[:5] if len(a) >= 5 else a
        for b in right:
            b_prefix = b[:5] if len(b) >= 5 else b
            if len(prefix) >= 5 and prefix == b_prefix:
                return True
            if (len(a) >= 4 and a in b) or (len(b) >= 4 and b in a):
                return True
    return False


def _weakness_concept_and_text(item: Any) -> tuple[str, str]:
    if isinstance(item, str):
        raw = item.strip()
        if ":" in raw:
            head, _tail = raw.split(":", 1)
            return head.strip() or raw, raw
        if "：" in raw:
            head, _tail = raw.split("：", 1)
            return head.strip() or raw, raw
        return raw, raw
    if isinstance(item, dict):
        concept = str(item.get("concept") or item.get("name") or "").strip()
        reason = str(item.get("reason") or item.get("latest_example") or "").strip()
        return concept, f"{concept} {reason}".strip()
    concept = str(getattr(item, "concept", "") or "").strip()
    reason = str(getattr(item, "reason", "") or getattr(item, "latest_example", "") or "").strip()
    return concept, f"{concept} {reason}".strip()


def match_diagnostic_to_weakness(
    diagnostics: Iterable[Any] | None,
    weaknesses: Iterable[Any] | None,
) -> tuple[str, str] | None:
    """Return ``(weakness_concept, diagnostic_text)`` when a live diagnostic hits a recorded weakness."""
    diag_entries: list[str] = []
    for raw_diag in diagnostics or []:
        text, severity = _diagnostic_text_and_severity(raw_diag)
        if not text or severity in _IGNORED_DIAGNOSTIC_SEVERITIES:
            continue
        diag_entries.append(text)
    if not diag_entries:
        return None

    weak_entries: list[tuple[str, set[str], set[str]]] = []
    for raw_weak in weaknesses or []:
        concept, full_text = _weakness_concept_and_text(raw_weak)
        if not concept:
            continue
        latin, cjk = _extract_tokens(full_text)
        if latin or cjk:
            weak_entries.append((concept, latin, cjk))
    if not weak_entries:
        return None

    for diag_text in diag_entries:
        diag_latin, diag_cjk = _extract_tokens(diag_text)
        for concept, weak_latin, weak_cjk in weak_entries:
            if (diag_cjk & weak_cjk) or _latin_root_overlap(diag_latin, weak_latin):
                return concept, diag_text
    return None


def _due_review_concept(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("concept") or item.get("title") or "").strip()
    return str(getattr(item, "concept", "") or getattr(item, "title", "") or "").strip()


def evaluate_proactive_opportunity(
    workspace: dict[str, Any] | None,
    *,
    now: datetime,
    diagnostics: Iterable[Any] | None = None,
    weaknesses: Iterable[Any] | None = None,
    due_reviews: Iterable[Any] | None = None,
    due_count: int = 0,
    session_id: str = "",
    message: str = "",
    response_language: str = "zh",
    learner_actively_typing: bool = False,
) -> ProactiveWhisper:
    """Decide whether to emit a single calm proactive whisper under daily/spacing/typing budgets."""
    now_utc = _ensure_utc(now)
    budget = _budget_state(workspace, now=now_utc)
    used_today = int(budget["count"])
    remaining = max(0, DAILY_PROACTIVE_BUDGET - used_today)
    lang = _lang_bucket(response_language)

    def blocked(reason: str, *, rem: int | None = None) -> ProactiveWhisper:
        return ProactiveWhisper(
            should_nudge=False,
            kind="",
            reason=reason,
            remaining_daily_budget=remaining if rem is None else rem,
        )

    if learner_actively_typing:
        return blocked("learner_typing")

    if review_refusal_signal(message):
        return blocked("message_refusal")

    intervention = (workspace or {}).get(REVIEW_INTERVENTION_KEY)
    if isinstance(intervention, dict):
        refused_until = _parse_iso(intervention.get("refused_until"))
        if refused_until is not None and refused_until > now_utc:
            return blocked("refused")

    active_thread = (workspace or {}).get("active_thread")
    if isinstance(active_thread, dict) and str(active_thread.get("blocker") or "").strip():
        return blocked("focused_activity")

    if used_today >= DAILY_PROACTIVE_BUDGET:
        return blocked("daily_budget_exhausted", rem=0)

    last_nudge_dt = _parse_iso(budget.get("last_nudge_at"))
    if last_nudge_dt is not None and now_utc - last_nudge_dt < timedelta(minutes=MIN_NUDGE_SPACING_MINUTES):
        return blocked("nudge_spacing_cooldown")

    seen_keys = set(budget.get("seen_keys") or [])
    saw_duplicate_only = False

    diagnostic_hit = match_diagnostic_to_weakness(diagnostics, weaknesses)
    if diagnostic_hit is not None:
        concept, diag_text = diagnostic_hit
        dedup_key = f"diagnostic:{concept.lower()}"
        if dedup_key not in seen_keys:
            trimmed_diag = diag_text[:120].rstrip()
            text = _DIAGNOSTIC_WHISPER_TEMPLATES[lang].format(
                diagnostic=trimmed_diag,
                concept=concept,
            )
            return ProactiveWhisper(
                should_nudge=True,
                kind="diagnostic_weakness",
                reason="diagnostic_matches_weakness",
                concept=concept,
                message=text,
                remaining_daily_budget=max(0, remaining - 1),
                dedup_key=dedup_key,
            )
        saw_duplicate_only = True

    review_list = list(due_reviews or [])
    effective_due_count = max(int(due_count or 0), len(review_list))
    if effective_due_count > 0:
        review_budget = derive_review_budget(
            workspace,
            due_count=effective_due_count,
            now=now_utc,
            session_id=session_id,
            message=message,
            learner_actively_typing=learner_actively_typing,
        )
        if review_budget.allowed:
            concept = next((_due_review_concept(item) for item in review_list if _due_review_concept(item)), "")
            concept_label = concept or ("待回顾内容" if lang == "zh" else "a recent skill")
            dedup_key = f"review:{concept_label.lower()}"
            if dedup_key not in seen_keys:
                text = _REVIEW_WHISPER_TEMPLATES[lang].format(concept=concept_label)
                return ProactiveWhisper(
                    should_nudge=True,
                    kind="review_gap",
                    reason=review_budget.reason,
                    concept=concept_label,
                    message=text,
                    remaining_daily_budget=max(0, remaining - 1),
                    dedup_key=dedup_key,
                )
            saw_duplicate_only = True
        elif not saw_duplicate_only:
            return blocked(review_budget.reason)

    if saw_duplicate_only:
        return blocked("already_nudged_today")
    return blocked("no_nudge_candidate")


def record_proactive_nudge(
    state: dict[str, Any] | None,
    *,
    now: datetime,
    kind: str,
    dedup_key: str,
    session_id: str = "",
) -> dict[str, Any]:
    """Advance the persisted per-workspace proactive whisper budget after surfacing a whisper."""
    now_utc = _ensure_utc(now)
    today = now_utc.date().isoformat()
    current = dict(state or {}) if isinstance(state, dict) else {}
    if str(current.get("date") or "") != today:
        count = 0
        seen_keys: list[str] = []
    else:
        count = max(0, int(current.get("count") or 0))
        seen_keys = [str(item).strip() for item in (current.get("seen_keys") or []) if str(item).strip()]
    normalized_key = str(dedup_key or "").strip()
    if normalized_key and normalized_key not in seen_keys:
        seen_keys.append(normalized_key)
    seen_keys = seen_keys[-24:]
    return {
        "date": today,
        "count": count + 1,
        "seen_keys": seen_keys,
        "last_nudge_at": now_utc.isoformat(),
        "last_kind": str(kind or "").strip(),
        "last_session_id": str(session_id or "").strip(),
    }
