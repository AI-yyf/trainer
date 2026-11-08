"""Localized provider failure summaries and next steps (§五十二 extraction).

Pure copy only: no transport, no provider config, no credentials. The service
keeps the public methods and delegates here so callers and tests keep the same
surface.
"""

from __future__ import annotations

from ..coaching_recovery import _localized_text
from .quota_copy import provider_quota_copy

_SUMMARIES: dict[str, tuple[str, str]] = {
    "invalid_key_or_permission": (
        "The provider rejected this turn's API key or permissions.",
        "这个 provider 拒绝了这轮请求使用的 API key 或 permission。",
    ),
    "model_unsupported": (
        "The provider reached the endpoint, but this model name is not accepted there.",
        "这个 provider 可以连通，但当前 model name 不被这个 endpoint 接受。",
    ),
    "model_not_found": (
        "The provider reached the gateway, but no available channel matched this model.",
        "这个 provider 可以连通，但 gateway 里没有可用 channel 能匹配当前 model。",
    ),
    "language_corruption": (
        "The provider returned a visibly corrupted coaching reply on this turn.",
        "这个 provider 可达，但这一轮返回了肉眼可见的乱码回复。",
    ),
    "malformed_response": (
        "The endpoint responded, but the payload was not a valid OpenAI-compatible response.",
        "这个 endpoint 有响应，但返回 payload 不是有效的 OpenAI-compatible response。",
    ),
    "truncated_or_empty": (
        "The provider ended the visible stream before a complete answer was available.",
        "provider 在完整返回之前就结束了流，这一轮没有可信的完整答案。",
    ),
    "streaming_unavailable": (
        "The configured provider has no verified native streaming path for this turn.",
        "当前 provider 没有通过验证的原生流式路径，这一轮不能继续。",
    ),
    "rate_limit": (
        "The provider rate-limited this turn before Trainer could continue.",
        "这个 provider 对这轮请求触发了 rate limit，Trainer 暂时无法继续。",
    ),
    "timeout": (
        "Trainer could not get a response from the provider before the timeout.",
        "Trainer 在超时前没有从 provider 收到响应。",
    ),
    "network": (
        "Trainer could not reach the provider over the network.",
        "Trainer 目前无法通过 network 连到这个 provider。",
    ),
}

_NEXT_STEPS: dict[str, tuple[str, str]] = {
    "invalid_key_or_permission": (
        "Check the API key or provider permissions, retest the connection, and resend this exact turn.",
        "先检查 API key 或 provider permission，重新测试连接后再重发这一轮。",
    ),
    "model_unsupported": (
        "Switch to a model name that this provider actually supports, retest, and resend this exact turn.",
        "先换成这个 provider 真的支持的 model name，重新测试后再重发这一轮。",
    ),
    "model_not_found": (
        "Pick a channel-backed model at this gateway, retest, and resend this exact turn.",
        "先换成这个 gateway 里真的有 channel 的 model，重新测试后再重发这一轮。",
    ),
    "language_corruption": (
        "Switch provider or gateway first, then resend this same turn after the visible corruption disappears.",
        "先切换 provider 或 gateway，确认乱码消失后再重发这一轮。",
    ),
    "malformed_response": (
        "Check that the endpoint really speaks the OpenAI-compatible protocol, then retest and resend this exact turn.",
        "先确认这个 endpoint 真的返回 OpenAI-compatible protocol，再测试并重发这一轮。",
    ),
    "truncated_or_empty": (
        "Retry with a shorter visible answer or raise the provider output limit, then resend this exact turn.",
        "先缩短可见答案或提高 provider 的输出限制，然后重新发送这一轮。",
    ),
    "streaming_unavailable": (
        "Choose a provider and model with verified native streaming in Settings, retest it, and resend this exact turn.",
        "先在设置里选择已验证支持原生流式的 provider 和 model，重新测试后再重发这一轮。",
    ),
    "rate_limit": (
        "Wait briefly, then retry this same turn once the rate limit clears.",
        "先等一会儿，等 rate limit 过去后再重试这一轮。",
    ),
    "timeout": (
        "Retry once after checking provider latency or gateway load.",
        "先检查 provider 延迟或 gateway 负载，再重试这一轮。",
    ),
    "network": (
        "Check the network path or proxy settings, then resend this exact turn.",
        "先检查 network 路径或 proxy 设置，再重发这一轮。",
    ),
}

_FALLBACK_SUMMARY = (
    "Trainer is blocked on the provider path for this turn.",
    "Trainer 这轮被 provider path 卡住了。",
)
_FALLBACK_NEXT_STEP = (
    "Repair the provider path, then resend this exact coaching turn.",
    "先修好 provider path，再重发这一轮 coaching。",
)


def provider_failure_summary_text(category: str, response_language: str | None) -> str:
    if category == "quota_exhausted":
        return provider_quota_copy(response_language)[0]
    english, chinese = _SUMMARIES.get(category, _FALLBACK_SUMMARY)
    return _localized_text(english, chinese, response_language)


def provider_failure_next_step_text(category: str, response_language: str | None) -> str:
    if category == "quota_exhausted":
        return provider_quota_copy(response_language)[1]
    english, chinese = _NEXT_STEPS.get(category, _FALLBACK_NEXT_STEP)
    return _localized_text(english, chinese, response_language)
