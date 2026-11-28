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
        "当前模型服务拒绝了这轮请求使用的 API 密钥或访问权限。",
    ),
    "model_unsupported": (
        "The provider reached the endpoint, but this model name is not accepted there.",
        "模型连接可以连通，但当前服务地址不接受这个模型名称。",
    ),
    "model_not_found": (
        "The provider reached the gateway, but no available channel matched this model.",
        "模型连接可以连通，但当前服务地址下没有可用通道匹配这个模型。",
    ),
    "language_corruption": (
        "The provider returned a visibly corrupted coaching reply on this turn.",
        "模型服务可达，但这一轮返回了肉眼可见的乱码回复。",
    ),
    "malformed_response": (
        "The endpoint responded, but the payload was not a valid OpenAI-compatible response.",
        "当前服务地址有响应，但返回内容不符合 OpenAI 兼容接口格式。",
    ),
    "truncated_or_empty": (
        "The provider ended the visible stream before a complete answer was available.",
        "模型服务在完整返回前就结束了输出，这一轮没有得到完整回答。",
    ),
    "streaming_unavailable": (
        "The configured provider has no verified native streaming path for this turn.",
        "当前模型连接没有通过验证的原生流式输出能力，这一轮不能继续。",
    ),
    "rate_limit": (
        "The provider rate-limited this turn before Trainer could continue.",
        "当前模型服务对这轮请求触发了频率限制，Trainer 暂时无法继续。",
    ),
    "timeout": (
        "Trainer could not get a response from the provider before the timeout.",
        "Trainer 在超时前没有从模型服务收到响应。",
    ),
    "network": (
        "Trainer could not reach the provider over the network.",
        "Trainer 目前无法通过网络连到这个模型服务。",
    ),
}

_NEXT_STEPS: dict[str, tuple[str, str]] = {
    "invalid_key_or_permission": (
        "Check the API key or provider permissions, retest the connection, and resend this exact turn.",
        "先在设置里检查 API 密钥或访问权限，重新测试连接后再重发这一轮。",
    ),
    "model_unsupported": (
        "Switch to a model name that this provider actually supports, retest, and resend this exact turn.",
        "先换成当前模型连接真正支持的模型名称，重新测试后再重发这一轮。",
    ),
    "model_not_found": (
        "Pick a channel-backed model at this gateway, retest, and resend this exact turn.",
        "先换成当前服务地址下真实可用的模型，重新测试后再重发这一轮。",
    ),
    "language_corruption": (
        "Switch provider or gateway first, then resend this same turn after the visible corruption disappears.",
        "先切换模型连接或服务地址，确认乱码消失后再重发这一轮。",
    ),
    "malformed_response": (
        "Check that the endpoint really speaks the OpenAI-compatible protocol, then retest and resend this exact turn.",
        "先确认当前服务地址支持 OpenAI 兼容接口协议，再测试并重发这一轮。",
    ),
    "truncated_or_empty": (
        "Retry with a shorter visible answer or raise the provider output limit, then resend this exact turn.",
        "先缩短回答长度或提高模型输出上限，然后重新发送这一轮。",
    ),
    "streaming_unavailable": (
        "Choose a provider and model with verified native streaming in Settings, retest it, and resend this exact turn.",
        "先在设置里选择已验证支持原生流式的模型连接和模型，重新测试后再重发这一轮。",
    ),
    "rate_limit": (
        "Wait briefly, then retry this same turn once the rate limit clears.",
        "先稍等片刻，等频率限制解除后再重试这一轮。",
    ),
    "timeout": (
        "Retry once after checking provider latency or gateway load.",
        "先检查模型服务延迟或服务地址负载，再重试这一轮。",
    ),
    "network": (
        "Check the network path or proxy settings, then resend this exact turn.",
        "先检查网络连接或代理设置，再重发这一轮。",
    ),
}

_FALLBACK_SUMMARY = (
    "Trainer is blocked on the provider path for this turn.",
    "Trainer 这一轮在模型连接上受阻。",
)
_FALLBACK_NEXT_STEP = (
    "Repair the provider path, then resend this exact coaching turn.",
    "先检查并修复模型连接，再重发这一轮对话。",
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
