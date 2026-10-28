"""Language-integrity probes and corruption replies (§五十二 extraction)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...core.models import ProviderConfig
from ..coaching_recovery import _localized_text
from ..coaching_reply_drafts import _message_probe_variant
from .capability import _visible_probe_max_tokens
from .redaction import redact_provider_error
from .text import (
    _compact_visible_text,
    _contains_cjk,
    _looks_like_input_corruption_reply,
    _looks_like_mojibake_text,
    _mixed_script_reply_corruption_detail,
    _prefers_chinese,
)

_LANGUAGE_PROBE_VARIANTS = (
    (
        "\u4e0d\u8981\u76f4\u63a5\u8003\u8bd5\uff0c\u5148\u5b66\u518d\u6d4b\u3002\u8bf7\u5224\u65ad VS Code \u8fdc\u7a0b\u5de5\u4f5c\u533a\u8fb9\u754c\u3002ABC123",
        "\u4e0d\u8981\u76f4\u63a5\u8003\u8bd5\uff0c\u5148\u5b66\u518d\u6d4b\u3002\u8bf7\u5224\u65ad VS Code \u8fdc\u7a0b\u5de5\u4f5c\u533a\u8fb9\u754c\u3002ABC123",
    ),
    (
        "\u8bfb\u8fd9\u53e5\u8bdd\uff0c\u53ea\u56de\u590d\u6700\u540e\u56db\u4e2a\u6c49\u5b57\uff0c\u4e0d\u8981\u89e3\u91ca\uff1a\u4e0d\u8981\u76f4\u63a5\u8003\u8bd5\uff0c\u5148\u7528\u6700\u5c0f\u6559\u5b66\u6b65\u9aa4\u6559\u6211\u5982\u4f55\u5224\u65ad VS Code \u8fdc\u7a0b\u5de5\u4f5c\u533a\u8fb9\u754c\uff0c\u518d\u7ed9\u6211\u4e00\u4e2a\u5f88\u5c0f\u7684\u9a8c\u8bc1\u52a8\u4f5c",
        "\u9a8c\u8bc1\u52a8\u4f5c",
    ),
)
_NATURAL_LANGUAGE_PROBE_PROMPT = (
    "\u53ea\u7528\u7b80\u4f53\u4e2d\u6587\u56de\u7b54\u4e00\u53e5\u8bdd\uff0c\u5e76\u5b8c\u6574\u4fdd\u7559\u201c\u5148\u5b66\u518d\u6d4b\u201d\u548c\u201cVS Code\u201d\u3002\u4e0d\u8981\u89e3\u91ca\uff0c\u4e0d\u8981\u52a0\u5f15\u53f7\u3002"
)
_NATURAL_LANGUAGE_PROBE_FRAGMENTS = ("\u5148\u5b66\u518d\u6d4b", "VS Code")


class LanguageProbeMixin:
    if TYPE_CHECKING:
        _api_key: str | None
        _apply_request_defaults: Any
        _record_last_reply_failure: Any


    def _language_probe_result(
        self,
        *,
        client: Any,
        model: str,
        provider: ProviderConfig | None = None,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> dict[str, object]:
        probe_max_tokens = _visible_probe_max_tokens(provider)

        def natural_language_probe_result() -> dict[str, object]:
            if not _prefers_chinese(response_language):
                return {"ok": False}
            try:
                request_payload = self._apply_request_defaults(
                    {
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Reply in Chinese only. Keep required phrases exactly. Do not explain or add quotes.",
                            },
                            {
                                "role": "user",
                                "content": _NATURAL_LANGUAGE_PROBE_PROMPT,
                            },
                        ],
                        "temperature": 0,
                        "max_tokens": probe_max_tokens,
                    },
                    provider,
                )
                response = client.chat.completions.create(**request_payload)
            except Exception:  # pragma: no cover - network dependent
                return {"ok": False}
            content = response.choices[0].message.content if response.choices else None
            preview = _compact_visible_text(content)
            if not preview:
                return {"ok": False}
            if _looks_like_input_corruption_reply(preview):
                return {"ok": False}
            if not _contains_cjk(preview):
                return {"ok": False}
            if not all(fragment in preview for fragment in _NATURAL_LANGUAGE_PROBE_FRAGMENTS):
                return {"ok": False}
            return {
                "ok": True,
                "detail": _localized_text(
                    (
                        "Natural-language zh-CN probe succeeded after the strict echo probe was unstable. "
                        "Trainer can keep using this connection for Chinese coaching."
                    ),
                    "自然中文探测通过了：虽然严格回显探测不稳定，但这条连接仍能输出可用的中文教学句子。",
                    response_language,
                ),
                "preview": preview,
                "kind": "natural_language_fallback",
            }

        previews: list[str] = []
        probe_variants: list[tuple[str, str, str]] = []
        message_probe = _message_probe_variant(probe_message)
        if message_probe is not None:
            probe_variants.append((message_probe[0], message_probe[1], "message"))
        if _prefers_chinese(response_language):
            probe_variants.extend(
                (prompt_text, expected_output, "generic")
                for prompt_text, expected_output in _LANGUAGE_PROBE_VARIANTS
            )
        if not probe_variants:
            return {
                "ok": True,
                "detail": "Language integrity probe skipped for this English-only flow.",
                "preview": "",
                "skipped": True,
            }
        for _attempt in range(2):
            for prompt_text, expected_output, probe_kind in probe_variants:
                try:
                    request_payload = self._apply_request_defaults(
                        {
                            "model": model,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": "Return exactly the requested text. Do not explain or add quotes.",
                                },
                                {
                                    "role": "user",
                                    "content": prompt_text,
                                },
                            ],
                            "temperature": 0,
                            "max_tokens": probe_max_tokens,
                        },
                        provider,
                    )
                    response = client.chat.completions.create(**request_payload)
                except Exception as exc:  # pragma: no cover - network dependent
                    return {
                        "ok": False,
                        "category": "language_probe_inconclusive",
                        "detail": _localized_text(
                            (
                                "Language integrity probe could not complete after connectivity succeeded. "
                                f"Follow-up check failed: {redact_provider_error(exc, api_key=self._api_key)}"
                            ),
                            f"语言完整性探测在连通性成功后没能完成。后续检查失败：{redact_provider_error(exc, api_key=self._api_key)}",
                            response_language,
                        ),
                        "preview": "",
                    }

                content = response.choices[0].message.content if response.choices else None
                preview = _compact_visible_text(content)
                if not preview:
                    return {
                        "ok": False,
                        "category": "language_probe_inconclusive",
                        "detail": _localized_text(
                            (
                                "Language integrity probe returned no visible content after connectivity succeeded. "
                                "Trainer cannot verify non-English input on this connection."
                            ),
                            (
                                "语言完整性探测在连通性成功后没有拿到可见内容。"
                                "Trainer 现在还不能验证这条链路上的非 English 输入。"
                            ),
                            response_language,
                        ),
                        "preview": "",
                    }
                previews.append(preview)
                if expected_output in preview:
                    continue
                fallback_probe = natural_language_probe_result()
                if fallback_probe.get("ok") is True:
                    return fallback_probe
                if _looks_like_input_corruption_reply(preview, expected_probe=expected_output):
                    if probe_kind == "message":
                        detail = _localized_text(
                            (
                                "Provider reachable, but it corrupted the actual mixed-language coaching "
                                "message into question marks before the model saw it."
                            ),
                            "这个 provider 可达，但在模型看到之前就把当前这条混合语言教学消息变成了一串问号。",
                            response_language,
                        )
                    else:
                        detail = _localized_text(
                            (
                                "Provider reachable, but it corrupted Chinese input into question marks "
                                "before the model saw it."
                            ),
                            "这个 provider 可达，但在模型看到消息之前把中文输入变成了一串问号。",
                            response_language,
                        )
                    return {
                        "ok": False,
                        "category": "language_corruption",
                        "detail": detail,
                        "preview": preview,
                    }
                detail = _localized_text(
                    (
                        "Language integrity probe was inconclusive. The provider replied, but it did not preserve "
                        "the message-derived probe text exactly enough for Trainer to trust it."
                        if probe_kind == "message"
                        else (
                            "Language integrity probe was inconclusive. The provider replied, but it did not preserve "
                            "the mixed-language probe text exactly enough for Trainer to trust it."
                        )
                    ),
                    (
                        "语言完整性探测没有通过。provider 虽然回复了，"
                        "但没有把基于当前消息生成的探测文本完整保留下来，Trainer 还不能信任这条链路。"
                        if probe_kind == "message"
                        else (
                            "语言完整性探测没有通过。provider 虽然回复了，"
                            "但没有把混合语言探测文本完整保留下来，Trainer 还不能信任这条链路。"
                        )
                    ),
                    response_language,
                )
                return {
                    "ok": False,
                    "category": "language_probe_inconclusive",
                    "detail": detail,
                    "preview": preview,
                }

        final_detail = _localized_text(
            (
                "Language integrity probe preserved the message-derived and mixed CJK/ASCII probe text across all checks."
                if message_probe is not None or _prefers_chinese(response_language)
                else "Language integrity probe preserved the mixed CJK/ASCII probe text across all checks."
            ),
            (
                "语言完整性探测通过了：基于当前消息生成的探测文本和 mixed CJK/ASCII 探测文本都被完整保留下来了。"
                if message_probe is not None or _prefers_chinese(response_language)
                else "语言完整性探测通过了：mixed CJK/ASCII 探测文本在所有检查里都被完整保留下来了。"
            ),
            response_language,
        )
        return {
            "ok": True,
            "detail": final_detail,
            "preview": previews[-1] if previews else "",
            "kind": "strict_integrity",
        }

    def _language_probe_result_resilient(
        self,
        *,
        client: Any,
        model: str,
        provider: ProviderConfig | None = None,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> dict[str, object]:
        probe_max_tokens = _visible_probe_max_tokens(provider)
        zh_natural_success = (
            "\u81ea\u7136 zh-CN \u63a2\u6d4b\u5df2\u901a\u8fc7\uff1a"
            "\u867d\u7136\u4e25\u683c\u56de\u663e\u63a2\u6d4b\u4e0d\u7a33\u5b9a\uff0c"
            "Trainer \u4ecd\u7136\u80fd\u5728\u8fd9\u6761\u8fde\u63a5\u4e0a\u7ee7\u7eed zh-CN \u6559\u7ec3\u3002"
        )
        zh_probe_failed = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u5728\u8fde\u901a\u6027\u6210\u529f\u540e\u6ca1\u80fd\u5b8c\u6210\u3002"
            "\u540e\u7eed\u68c0\u67e5\u5931\u8d25\uff1a"
        )
        zh_no_visible = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u5728\u8fde\u901a\u6027\u6210\u529f\u540e\u6ca1\u6709\u62ff\u5230\u53ef\u89c1\u5185\u5bb9\u3002"
            "Trainer \u73b0\u5728\u8fd8\u4e0d\u80fd\u9a8c\u8bc1\u8fd9\u6761\u94fe\u8def\u4e0a\u7684\u975e English \u8f93\u5165\u3002"
        )
        zh_message_corruption = (
            "\u8fd9\u4e2a provider \u53ef\u8fbe\uff0c"
            "\u4f46\u5728\u6a21\u578b\u770b\u5230\u4e4b\u524d\u5c31\u628a\u5f53\u524d\u8fd9\u6761\u6df7\u5408\u8bed\u8a00\u6559\u7ec3\u6d88\u606f"
            "\u53d8\u6210\u4e86\u4e00\u4e32\u95ee\u53f7\u3002"
        )
        zh_generic_corruption = (
            "\u8fd9\u4e2a provider \u53ef\u8fbe\uff0c"
            "\u4f46\u5728\u6a21\u578b\u770b\u5230\u6d88\u606f\u4e4b\u524d\u628a\u4e2d\u6587\u8f93\u5165\u53d8\u6210\u4e86\u4e00\u4e32\u95ee\u53f7\u3002"
        )
        zh_message_inconclusive = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u6ca1\u6709\u901a\u8fc7\u3002provider \u867d\u7136\u56de\u590d\u4e86\uff0c"
            "\u4f46\u6ca1\u6709\u628a\u57fa\u4e8e\u5f53\u524d\u6d88\u606f\u751f\u6210\u7684\u63a2\u6d4b\u6587\u672c\u5b8c\u6574\u4fdd\u7559\u4e0b\u6765\uff0c"
            "Trainer \u8fd8\u4e0d\u80fd\u4fe1\u4efb\u8fd9\u6761\u94fe\u8def\u3002"
        )
        zh_generic_inconclusive = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u6ca1\u6709\u901a\u8fc7\u3002provider \u867d\u7136\u56de\u590d\u4e86\uff0c"
            "\u4f46\u6ca1\u6709\u628a mixed CJK/ASCII \u63a2\u6d4b\u6587\u672c\u5b8c\u6574\u4fdd\u7559\u4e0b\u6765\uff0c"
            "Trainer \u8fd8\u4e0d\u80fd\u4fe1\u4efb\u8fd9\u6761\u94fe\u8def\u3002"
        )
        zh_retry_success = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u5728\u91cd\u8bd5\u540e\u6062\u590d\u6210\u529f\uff1a"
            "\u81f3\u5c11\u6709\u4e00\u6761\u57fa\u4e8e\u5f53\u524d\u6d88\u606f\u6216 mixed CJK/ASCII \u7684\u63a2\u6d4b\u6587\u672c"
            "\u88ab\u53ef\u7528\u5730\u5b8c\u6574\u4fdd\u7559\u4e86\u3002"
        )
        zh_strict_success = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u901a\u8fc7\u4e86\uff1a"
            "\u57fa\u4e8e\u5f53\u524d\u6d88\u606f\u751f\u6210\u7684\u63a2\u6d4b\u6587\u672c\u548c mixed CJK/ASCII \u63a2\u6d4b\u6587\u672c"
            "\u90fd\u88ab\u5b8c\u6574\u4fdd\u7559\u4e0b\u6765\u4e86\u3002"
        )
        zh_generic_success = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u901a\u8fc7\u4e86\uff1a"
            "mixed CJK/ASCII \u63a2\u6d4b\u6587\u672c\u5728\u6240\u6709\u68c0\u67e5\u91cc\u90fd\u88ab\u5b8c\u6574\u4fdd\u7559\u4e0b\u6765\u4e86\u3002"
        )
        zh_no_signal = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u5728\u8fde\u901a\u6027\u6210\u529f\u540e\u4ecd\u6ca1\u6709\u62ff\u5230\u53ef\u7528\u4fe1\u53f7\u3002"
            "Trainer \u73b0\u5728\u8fd8\u4e0d\u80fd\u9a8c\u8bc1\u8fd9\u6761\u94fe\u8def\u4e0a\u7684\u975e English \u8f93\u5165\u3002"
        )

        def natural_language_probe_result() -> dict[str, object]:
            if not _prefers_chinese(response_language):
                return {"ok": False}
            try:
                request_payload = self._apply_request_defaults(
                    {
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Reply in Chinese only. Keep required phrases exactly. Do not explain or add quotes.",
                            },
                            {
                                "role": "user",
                                "content": _NATURAL_LANGUAGE_PROBE_PROMPT,
                            },
                        ],
                        "temperature": 0,
                        "max_tokens": probe_max_tokens,
                    },
                    provider,
                )
                response = client.chat.completions.create(**request_payload)
            except Exception:  # pragma: no cover - network dependent
                return {"ok": False}
            content = response.choices[0].message.content if response.choices else None
            preview = _compact_visible_text(content)
            if not preview:
                return {"ok": False}
            if _looks_like_input_corruption_reply(preview):
                return {"ok": False}
            if not _contains_cjk(preview):
                return {"ok": False}
            if not all(fragment in preview for fragment in _NATURAL_LANGUAGE_PROBE_FRAGMENTS):
                return {"ok": False}
            return {
                "ok": True,
                "detail": _localized_text(
                    (
                        "Natural-language zh-CN probe succeeded after the strict echo probe was unstable. "
                        "Trainer can keep using this connection for Chinese coaching."
                    ),
                    zh_natural_success,
                    response_language,
                ),
                "preview": preview,
                "kind": "natural_language_fallback",
            }

        previews: list[str] = []
        probe_variants: list[tuple[str, str, str]] = []
        message_probe = _message_probe_variant(probe_message)
        if message_probe is not None:
            probe_variants.append((message_probe[0], message_probe[1], "message"))
        if _prefers_chinese(response_language):
            probe_variants.extend(
                (prompt_text, expected_output, "generic")
                for prompt_text, expected_output in _LANGUAGE_PROBE_VARIANTS
            )
        if not probe_variants:
            return {
                "ok": True,
                "detail": "Language integrity probe skipped for this English-only flow.",
                "preview": "",
                "skipped": True,
            }

        last_inconclusive: dict[str, object] | None = None
        saw_blank_preview = False
        for _attempt in range(2):
            natural_fallback_attempted = False
            strict_successes = 0
            for prompt_text, expected_output, probe_kind in probe_variants:
                try:
                    request_payload = self._apply_request_defaults(
                        {
                            "model": model,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": "Return exactly the requested text. Do not explain or add quotes.",
                                },
                                {
                                    "role": "user",
                                    "content": prompt_text,
                                },
                            ],
                            "temperature": 0,
                            "max_tokens": probe_max_tokens,
                        },
                        provider,
                    )
                    response = client.chat.completions.create(**request_payload)
                except Exception as exc:  # pragma: no cover - network dependent
                    return {
                        "ok": False,
                        "category": "language_probe_inconclusive",
                        "detail": _localized_text(
                            (
                                "Language integrity probe could not complete after connectivity succeeded. "
                                f"Follow-up check failed: {redact_provider_error(exc, api_key=self._api_key)}"
                            ),
                            f"{zh_probe_failed}{redact_provider_error(exc, api_key=self._api_key)}",
                            response_language,
                        ),
                        "preview": "",
                    }

                content = response.choices[0].message.content if response.choices else None
                preview = _compact_visible_text(content)
                if not preview:
                    saw_blank_preview = True
                    last_inconclusive = {
                        "ok": False,
                        "category": "language_probe_inconclusive",
                        "detail": _localized_text(
                            (
                                "Language integrity probe returned no visible content after connectivity succeeded. "
                                "Trainer cannot verify non-English input on this connection."
                            ),
                            zh_no_visible,
                            response_language,
                        ),
                        "preview": "",
                    }
                    if not natural_fallback_attempted:
                        natural_fallback_attempted = True
                        fallback_probe = natural_language_probe_result()
                        if fallback_probe.get("ok") is True:
                            return fallback_probe
                    continue

                previews.append(preview)
                if expected_output in preview:
                    strict_successes += 1
                    continue

                if _looks_like_input_corruption_reply(preview, expected_probe=expected_output):
                    return {
                        "ok": False,
                        "category": "language_corruption",
                        "detail": _localized_text(
                            (
                                "Provider reachable, but it corrupted the actual mixed-language coaching "
                                "message into question marks before the model saw it."
                            )
                            if probe_kind == "message"
                            else (
                                "Provider reachable, but it corrupted Chinese input into question marks "
                                "before the model saw it."
                            ),
                            zh_message_corruption if probe_kind == "message" else zh_generic_corruption,
                            response_language,
                        ),
                        "preview": preview,
                    }

                if not natural_fallback_attempted:
                    natural_fallback_attempted = True
                    fallback_probe = natural_language_probe_result()
                    if fallback_probe.get("ok") is True:
                        return fallback_probe

                last_inconclusive = {
                    "ok": False,
                    "category": "language_probe_inconclusive",
                    "detail": _localized_text(
                        (
                            "Language integrity probe was inconclusive. The provider replied, but it did not preserve "
                            "the message-derived probe text exactly enough for Trainer to trust it."
                        )
                        if probe_kind == "message"
                        else (
                            "Language integrity probe was inconclusive. The provider replied, but it did not preserve "
                            "the mixed-language probe text exactly enough for Trainer to trust it."
                        ),
                        zh_message_inconclusive if probe_kind == "message" else zh_generic_inconclusive,
                        response_language,
                    ),
                    "preview": preview,
                }

            if strict_successes == len(probe_variants):
                recovered = saw_blank_preview or last_inconclusive is not None or _attempt > 0
                detail = _localized_text(
                    (
                        "Language integrity probe recovered after retry and preserved usable message-derived or mixed "
                        "CJK/ASCII text."
                        if recovered
                        else (
                            "Language integrity probe preserved the message-derived and mixed CJK/ASCII probe text across all checks."
                            if message_probe is not None or _prefers_chinese(response_language)
                            else "Language integrity probe preserved the mixed CJK/ASCII probe text across all checks."
                        )
                    ),
                    zh_retry_success
                    if recovered
                    else (
                        zh_strict_success
                        if message_probe is not None or _prefers_chinese(response_language)
                        else zh_generic_success
                    ),
                    response_language,
                )
                return {
                    "ok": True,
                    "detail": detail,
                    "preview": previews[-1] if previews else "",
                    "kind": "strict_integrity",
                }

        return last_inconclusive or {
            "ok": False,
            "category": "language_probe_inconclusive",
            "detail": _localized_text(
                (
                    "Language integrity probe returned no usable signal after connectivity succeeded. "
                    "Trainer cannot verify non-English input on this connection yet."
                ),
                zh_no_signal,
                response_language,
            ),
            "preview": previews[-1] if previews else "",
        }

    def detect_language_corruption(
        self,
        *,
        message: str,
        reply: str,
        response_language: str | None = None,
    ) -> bool:
        if (
            (_contains_cjk(message) or _prefers_chinese(response_language))
            and _looks_like_input_corruption_reply(reply)
        ):
            return True
        if _looks_like_mojibake_text(reply):
            return True
        return (
            _mixed_script_reply_corruption_detail(
                reply,
                message=message,
                response_language=response_language,
            )
            is not None
        )

    def _language_corruption_lane_note(
        self,
        scenario: str | None,
        response_language: str | None,
    ) -> str:
        normalized = str(scenario or "").strip().lower()
        if normalized == "remote_workspace":
            return _localized_text(
                "I am still keeping this turn in the VS Code remote lane.",
                "当前这轮我仍然保留在 VS Code remote 这条主线里。",
                response_language,
            )
        if normalized == "debug_loop":
            return _localized_text(
                "I am still keeping this turn in the VS Code debug lane.",
                "当前这轮我仍然保留在 VS Code debug 这条主线里。",
                response_language,
            )
        if normalized == "function_guidance":
            return _localized_text(
                "I am still keeping this turn in the function-guidance lane.",
                "当前这轮我仍然保留在 function-guidance 这条主线里。",
                response_language,
            )
        if normalized == "project_adaptation":
            return _localized_text(
                "I am still keeping this turn in the existing-project adaptation lane.",
                "当前这轮我仍然保留在 existing-project adaptation 这条主线里。",
                response_language,
            )
        return ""

    def language_corruption_summary(
        self,
        response_language: str | None,
        scenario: str | None = None,
    ) -> str:
        summary = _localized_text(
            "This provider is reachable, but it corrupted Chinese input into question marks before the model saw the message.",
            "模型服务可以连接，但中文内容在送到模型前变成了一串问号。",
            response_language,
        )
        if _prefers_chinese(response_language):
            summary = f"{summary} \u8bf7\u68c0\u67e5 provider \u662f\u5426\u652f\u6301\u4e2d\u6587\u3002"
        lane_note = self._language_corruption_lane_note(scenario, response_language)
        if lane_note:
            return f"{summary} {lane_note}"
        return summary

    def language_corruption_next_step(
        self,
        response_language: str | None,
        scenario: str | None = None,
    ) -> str:
        normalized = str(scenario or "").strip().lower()
        if normalized == "remote_workspace":
            return _localized_text(
                "Switch provider or gateway, or continue this remote lesson in English first. If you stay here, tell me whether the workspace is SSH, tunnels, dev container, WSL, or local, plus one real path or host label.",
                "先切换 provider 或 gateway，或者先用 English 继续这节 remote lesson。如果继续留在这里，请告诉我当前工作区是 SSH、tunnels、dev container、WSL 还是 local，并给我一个真实路径或 host label。",
                response_language,
            )
        if normalized == "debug_loop":
            return _localized_text(
                "Switch provider or gateway, or continue this debug lesson in English first. If you stay here, tell me where you will pause first and which single value, branch, or stack frame you expect to inspect.",
                "先切换 provider 或 gateway，或者先用 English 继续这节 debug lesson。如果继续留在这里，请告诉我你会先停在哪个断点，以及准备检查哪一个值、分支或 stack frame。",
                response_language,
            )
        if normalized == "function_guidance":
            return _localized_text(
                "Switch provider or gateway, or continue this function-guidance lesson in English first. If you stay here, give me the function name and one call site you can open right now.",
                "先切换 provider 或 gateway，或者先用 English 继续这节 function-guidance lesson。如果继续留在这里，请给我函数名，以及你现在就能打开的一个 call site。",
                response_language,
            )
        if normalized == "project_adaptation":
            return _localized_text(
                "Switch provider or gateway, or continue this project-adaptation lesson in English first. If you stay here, tell me what must stay stable, what must change, and the first boundary you want to adapt.",
                "先切换 provider 或 gateway，或者先用 English 继续这节 project-adaptation lesson。如果继续留在这里，请告诉我什么必须保持稳定、什么必须变化，以及你想先适配的第一条边界。",
                response_language,
            )
        return _localized_text(
            "Switch provider or gateway, or continue this test in English first, before resuming the coach thread.",
            "先切换 provider 或 gateway，或者先用 English 完成这次测试，再回来继续 coach thread。",
            response_language,
        )

    def language_corruption_reply(
        self,
        response_language: str | None,
        scenario: str | None = None,
    ) -> str:
        summary = self.language_corruption_summary(response_language, scenario=scenario)
        next_step = self.language_corruption_next_step(response_language, scenario=scenario)
        if _prefers_chinese(response_language):
            return (
                f"{summary}\n\n"
                "为了避免误导你，我不会把这段异常内容当成正常回答。"
                f"\n\n\u4e0b\u4e00\u6b65\uff1a{next_step}"
            )
        return (
            f"{summary}\n\n"
            "Trainer will not pretend this is a normal coaching turn, because the model never saw your actual sentence."
            f"\n\nNext step: {next_step}"
        )

    def _record_reply_language_corruption(self, detail: str) -> None:
        self._record_last_reply_failure(
            category="language_corruption",
            detail=detail,
            retryable=False,
            status_code=200,
            provider_reachable=True,
            model_supported=True,
            error=ValueError(detail),
        )

