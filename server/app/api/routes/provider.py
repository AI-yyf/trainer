from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter

from ...core.models import (
    ProviderConfig,
    ProviderModelsResponse,
    ProviderTestResponse,
)
from ...llm.provider_gateway import NEWAPI_CONNECTION_TYPE
from ...llm.provider_protocols import provider_protocol_family
from .._helpers import contains_cjk_text, localized_text, prefers_chinese
from ..runtime import TrainerRuntime
from ._deps import RouterDeps


def build_provider_router(runtime: TrainerRuntime, deps: RouterDeps) -> APIRouter:
    router = APIRouter(tags=["provider"])

    operation_reliability_record = deps.operation_reliability_record
    provider_api_key_from_payload = deps.provider_api_key_from_payload
    provider_capabilities_from_payload = deps.provider_capabilities_from_payload
    provider_config_from_payload = deps.provider_config_from_payload
    provider_connection_type_from_payload = deps.provider_connection_type_from_payload
    provider_model_policy_detail = deps.provider_model_policy_detail
    provider_model_policy_violation = deps.provider_model_policy_violation
    provider_protocol_from_payload = deps.provider_protocol_from_payload

    def provider_declared_window_payload(
        provider: ProviderConfig | None,
    ) -> dict[str, object]:
        if provider is None:
            return {
                "context_window_tokens": None,
                "max_output_tokens": None,
                "model_token_limits": {},
                "capabilities": {},
                "model_capabilities": {},
            }

        limits: dict[str, object] = {}
        raw_limits = getattr(provider, "model_token_limits", None) or {}
        if isinstance(raw_limits, dict):
            for model_name, limit in raw_limits.items():
                key = str(model_name).strip()
                if not key:
                    continue
                if hasattr(limit, "model_dump"):
                    dumped = limit.model_dump(by_alias=True)
                elif isinstance(limit, dict):
                    dumped = dict(limit)
                else:
                    dumped = {}
                limits[key] = dumped

        window = provider.context_window_tokens
        max_output = provider.max_output_tokens
        model = str(provider.model or "").strip()
        if model and window and model not in limits:
            entry: dict[str, object] = {
                "contextWindowTokens": window,
                "context_window_tokens": window,
            }
            if max_output:
                entry["maxOutputTokens"] = max_output
                entry["max_output_tokens"] = max_output
            limits[model] = entry

        capabilities: dict[str, object] = {}
        flags = getattr(provider, "capabilities", None)
        flags_dump = getattr(flags, "model_dump", None)
        if callable(flags_dump):
            capabilities = cast("dict[str, object]", flags_dump(by_alias=True))
        elif isinstance(flags, dict):
            capabilities = dict(flags)

        serialized_model_capabilities: dict[str, object] = {}
        raw_model_capabilities = getattr(provider, "model_capabilities", None) or {}
        if isinstance(raw_model_capabilities, dict):
            for cap_model, cap_flags in raw_model_capabilities.items():
                cap_key = str(cap_model).strip()
                if not cap_key:
                    continue
                if hasattr(cap_flags, "model_dump"):
                    serialized_model_capabilities[cap_key] = cap_flags.model_dump(by_alias=True)
                elif isinstance(cap_flags, dict):
                    serialized_model_capabilities[cap_key] = dict(cap_flags)
        if model and capabilities and model not in serialized_model_capabilities:
            serialized_model_capabilities[model] = capabilities

        return {
            "context_window_tokens": window,
            "max_output_tokens": max_output,
            "model_token_limits": limits,
            "capabilities": capabilities,
            "model_capabilities": serialized_model_capabilities,
        }

    def empty_provider_test_capability_payload(
        provider: ProviderConfig | None = None,
    ) -> dict[str, object]:
        return {
            "capability_evidence": [],
            "tools_ready": False,
            "tool_probe_status": "unverified",
            "streaming_ready": False,
            "stream_probe_status": "unverified",
            "vision_ready": False,
            "vision_probe_status": "unverified",
            "thinking_ready": False,
            "thinking_probe_status": "unverified",
            "base_url": (provider.base_url if provider is not None else None) or None,
            "model": (provider.model if provider is not None else None) or None,
            "available_models": [],
            "resolved_model": None,
            "warnings": [],
            **provider_declared_window_payload(provider),
        }

    def provider_test_capability_payload(
        provider: ProviderConfig,
        result: ProviderTestResponse | None = None,
    ) -> dict[str, object]:
        if result is None or result.ok is not True:
            return empty_provider_test_capability_payload(provider)
        evidence = list(result.capability_evidence) if result.capability_evidence else []
        serialized = [
            {
                "name": item.name,
                "declared": item.declared,
                "observed": item.observed,
                "state": item.state,
            }
            for item in evidence
        ]

        def verified_ready(name: str, ready_flag: bool) -> bool:
            match = next(
                (item for item in serialized if str(item.get("name") or "").strip().lower() == name),
                None,
            )
            return bool(
                ready_flag
                and match
                and match.get("state") == "verified"
                and match.get("observed") is True
            )

        tools_ready = verified_ready("tools", bool(result.tools_ready))
        streaming_ready = verified_ready("streaming", bool(result.streaming_ready))
        vision_ready = verified_ready("vision", bool(result.vision_ready))
        thinking_ready = verified_ready("thinking", bool(result.thinking_ready))
        tools = next((item for item in serialized if item["name"] == "tools"), None)
        streaming = next((item for item in serialized if item["name"] == "streaming"), None)
        vision = next((item for item in serialized if item["name"] == "vision"), None)
        thinking = next((item for item in serialized if item["name"] == "thinking"), None)
        return {
            "capability_evidence": serialized,
            "tools_ready": tools_ready,
            "tool_probe_status": "verified" if tools_ready else str(tools.get("state") if tools else "unverified"),
            "streaming_ready": streaming_ready,
            "stream_probe_status": "verified" if streaming_ready else str(
                streaming.get("state") if streaming else "unverified"
            ),
            "vision_ready": vision_ready,
            "vision_probe_status": "verified" if vision_ready else str(
                vision.get("state") if vision else "unverified"
            ),
            "thinking_ready": thinking_ready,
            "thinking_probe_status": "verified" if thinking_ready else str(
                thinking.get("state") if thinking else "unverified"
            ),
            "base_url": provider.base_url or None,
            "model": provider.model or None,
            "available_models": [],
            "resolved_model": None,
            "warnings": [],
            **provider_declared_window_payload(provider),
        }


    def _provider_test_upstream_excerpt(detail: str | None) -> str | None:
        if not isinstance(detail, str):
            return None
        raw_detail = detail.strip()
        if not raw_detail:
            return None
        for pattern in (
            r"""["']message["']\s*:\s*["']([^"']+)["']""",
            r"""["']detail["']\s*:\s*["']([^"']+)["']""",
        ):
            match = re.search(pattern, raw_detail)
            if not match:
                continue
            excerpt = match.group(1).strip()
            excerpt = re.sub(r"\s*\(request id: [^)]+\)", "", excerpt, flags=re.IGNORECASE).strip()
            return excerpt or None
        return None

    def _provider_test_route_detail(
        base_detail: str,
        raw_detail: str | None,
        error_category: str | None = None,
    ) -> str:
        if error_category == "invalid_key_or_permission":
            return base_detail
        upstream_excerpt = _provider_test_upstream_excerpt(raw_detail)
        if not upstream_excerpt:
            return base_detail
        if upstream_excerpt.lower() in base_detail.lower():
            return base_detail
        return f"{base_detail} Upstream: {upstream_excerpt}"

    def _provider_test_clean_base_detail(
        error_category: str | None,
        provider: ProviderConfig,
        response_language: str | None,
    ) -> str:
        if error_category == "invalid_key_or_permission":
            return localized_text(
                "Provider rejected the API key or permissions. Check the key, scope, and model access.",
                "provider 拒绝了 API key 或 permission。请检查 key、scope 和 model access。",
                response_language,
            )
        if error_category == "language_corruption":
            return localized_text(
                "Provider reachable, but Chinese input or reply text was visibly corrupted on this connection.",
                "provider 可达，但这条连接上的中文输入或回复文本出现了可见乱码。",
                response_language,
            )
        if error_category == "language_probe_inconclusive":
            return localized_text(
                "Provider reachable, but Trainer could not fully verify zh-CN input integrity on this connection yet.",
                "provider 可达，但 Trainer 还不能完整验证这条连接的 zh-CN 输入保真度。",
                response_language,
            )
        if error_category == "empty_response":
            return localized_text(
                "Provider reachable, but the reply was unusable or contained no visible text.",
                "provider 可达，但这次回复不可用，或没有可见文本。",
                response_language,
            )
        if error_category == "rate_limit":
            return localized_text(
                "Provider rate limited the request. Wait briefly and try again.",
                "provider 触发了 rate limit。稍等一下再试。",
                response_language,
            )
        if error_category == "timeout":
            return localized_text(
                "Provider request timed out. Check latency or retry the connection.",
                "provider request timeout。请检查延迟，或重新测试这条连接。",
                response_language,
            )
        if error_category == "network":
            return localized_text(
                "Trainer could not reach the provider endpoint. Check the base URL and network path.",
                "Trainer 还连不到 provider endpoint。请检查 base URL 和 network path。",
                response_language,
            )
        if error_category == "malformed_response":
            return localized_text(
                "Provider returned an unexpected response. Check that the endpoint matches the configured protocol.",
                "provider 返回了不符合预期的响应。请确认 endpoint 和当前配置的 protocol 匹配。",
                response_language,
            )
        if error_category == "model_unsupported":
            return localized_text(
                f"Provider reached, but the configured chat model '{provider.model}' is not supported.",
                f"provider 已连通，但当前配置的 chat model 「{provider.model}」不受支持。",
                response_language,
            )
        if error_category == "model_not_found":
            return localized_text(
                f"Provider reached, but there is currently no available channel for chat model '{provider.model}'.",
                f"provider 已连通，但当前没有可用于 chat model 「{provider.model}」的 channel。",
                response_language,
            )
        return localized_text(
            "Provider test failed. Check the base URL, model, API key, and protocol, then try again.",
            "provider 测试失败。请检查 base URL、model、API key 和 protocol，然后再试一次。",
            response_language,
        )

    def _provider_test_clean_route_detail(
        error_category: str | None,
        provider: ProviderConfig,
        response_language: str | None,
        raw_detail: str | None,
    ) -> str:
        return _provider_test_route_detail(
            _provider_test_clean_base_detail(error_category, provider, response_language),
            raw_detail,
            error_category,
        )

    def _provider_route_localized_diagnostic_line(
        line: str,
        provider: ProviderConfig,
        response_language: str | None,
    ) -> str:
        text = str(line or "").strip()
        if not text or not prefers_chinese(response_language) or contains_cjk_text(text):
            return text

        if text.startswith("provider: "):
            return f"provider：{text.split(':', 1)[1].strip()}"
        if text.startswith("base URL: "):
            return f"base URL：{text.split(':', 1)[1].strip()}"
        if text.startswith("model: "):
            return f"model：{text.split(':', 1)[1].strip()}"
        if text == "configuration incomplete: a live provider test needs name, base URL, and model":
            return "配置不完整：live provider test 需要 provider name、base URL 和 model。"
        if text == "No API key supplied for provider test.":
            return "provider test 还没有可用的 API key。"
        if text == "No API key supplied for model listing.":
            return "models 列表还没有可用的 API key。"
        if (
            text
            == "Provider config is saved, but no API key is available. Trainer cannot work until you add one."
        ):
            return "provider 设置已经保存，但还没有可用的 API key。补上之后 Trainer 才能继续工作。"
        if (
            text
            == "Provider config is saved, but no API key is available. Trainer cannot fetch models until you add one."
        ):
            return "provider 设置已经保存，但还没有可用的 API key。补上之后 Trainer 才能获取 models。"
        if text == "live connectivity check skipped: no API key supplied":
            return "已跳过 live connectivity check：还没有 API key。"
        if text == "live connectivity check succeeded":
            return "live connectivity check 已通过。"
        if text == "live connectivity check failed":
            return "live connectivity check 失败。"
        if text == "Chat probe failed, but model listing succeeded.":
            return "chat probe 失败了，但 model listing 已通过。"
        if text == "Chat probe failed.":
            return "chat probe 失败了。"
        if text == "Model listing request failed.":
            return "model listing 请求失败了。"
        if text == "Compact chat probe returned no visible text, so Trainer retried with a visible-text probe.":
            return "compact chat probe 没拿到可见文本，所以 Trainer 改用 visible-text probe 重试。"
        if text == "Visible-text probe also returned no usable text.":
            return "visible-text probe 也没有拿到可用文本。"
        if text == "Language integrity probe failed: the mixed CJK/ASCII probe text was corrupted.":
            return "language integrity probe 失败：混合 CJK/ASCII 的 probe 文本被破坏了。"
        if (
            text
            == "Language integrity probe was inconclusive: the mixed CJK/ASCII probe text was not preserved clearly enough."
        ):
            return "language integrity probe 结果不确定：混合 CJK/ASCII 的 probe 文本没有被足够清晰地保留下来。"

        attempt_match = re.fullmatch(
            r"Trainer retried the compact chat probe after blank visible text \(attempt (\d+)\)\.",
            text,
        )
        if attempt_match:
            return f"compact chat probe 先返回了空白可见文本，Trainer 已重试（第 {attempt_match.group(1)} 次）。"

        chat_probe_match = re.fullmatch(r"Chat probe succeeded with model (.+?)\.", text)
        if chat_probe_match:
            return f"chat probe 已通过，使用的 model 是 {chat_probe_match.group(1)}。"

        probe_preview_match = re.fullmatch(r"Probe response preview:\s*(.+)", text)
        if probe_preview_match:
            return f"probe 响应预览：{probe_preview_match.group(1)}"

        language_probe_preview_match = re.fullmatch(r"Language probe preview:\s*(.+)", text)
        if language_probe_preview_match:
            return f"language probe 预览：{language_probe_preview_match.group(1)}"

        gemini_gateway_match = re.fullmatch(
            r"Using OpenAI-compatible chat probe for a Gemini-compatible non-Google gateway\.",
            text,
        )
        if gemini_gateway_match:
            return "当前是 Gemini-compatible 的非 Google gateway，所以改用 OpenAI-compatible chat probe。"

        openai_models_match = re.fullmatch(
            r"Using OpenAI-compatible model listing for provider (.+?)\.",
            text,
        )
        if openai_models_match:
            return f"对 provider {openai_models_match.group(1)} 使用 OpenAI-compatible model listing。"

        listed_models_match = re.fullmatch(r"Listed (\d+) models from provider (.+?)\.", text)
        if listed_models_match:
            return f"已从 provider {listed_models_match.group(2)} 列出 {listed_models_match.group(1)} 个 models。"

        resolved_model_match = re.fullmatch(r"Resolved configured model to (.+?)\.", text)
        if resolved_model_match:
            return f"当前配置的 model 对应到 {resolved_model_match.group(1)}。"

        tried_candidates_match = re.fullmatch(r"Tried model candidates:\s*(.+)", text)
        if tried_candidates_match:
            return f"尝试过的 model candidates：{tried_candidates_match.group(1)}"

        success_detail_match = re.fullmatch(
            r"Provider reachable\. Chat probe succeeded with model (.+?)\. Response:\s*(.+)",
            text,
        )
        if success_detail_match:
            return (
                f"provider 已连通，chat probe 已通过，当前 model「{success_detail_match.group(1)}」"
                f"可以返回可见内容。 响应预览：{success_detail_match.group(2)}"
            )

        empty_visible_reply_match = re.fullmatch(
            r"Provider reachable, but the chat probe returned no usable visible reply for model (.+?)\.",
            text,
        )
        if empty_visible_reply_match:
            return (
                f"provider 已连通，但当前 model「{empty_visible_reply_match.group(1)}」"
                "这次没有返回可用的可见文本。"
            )

        listed_detail_match = re.fullmatch(
            r"Provider reachable\. Listed (\d+) models\.(?: Resolved configured model to (.+?)\.)?",
            text,
        )
        if listed_detail_match:
            resolved = (listed_detail_match.group(2) or "").strip()
            resolved_suffix = f" 当前配置的 model 对应到「{resolved}」。" if resolved else ""
            return f"provider 已连通，并成功列出了 {listed_detail_match.group(1)} 个 models。{resolved_suffix}".strip()

        native_probe_match = re.fullmatch(r"Using native ([a-z_]+) probe\.", text)
        if native_probe_match:
            return f"当前使用原生 {native_probe_match.group(1)} probe。"

        native_models_match = re.fullmatch(r"Using native ([a-z_]+) model listing\.", text)
        if native_models_match:
            return f"当前使用原生 {native_models_match.group(1)} model listing。"

        native_probe_success_match = re.fullmatch(
            r"Provider reachable\. Native ([a-z_]+) probe succeeded with model (.+?)\. Response:\s*(.+)",
            text,
        )
        if native_probe_success_match:
            return (
                f"provider 已连通，原生 {native_probe_success_match.group(1)} probe 已通过，"
                f"当前 model「{native_probe_success_match.group(2)}」可以返回可见内容。"
                f" 响应预览：{native_probe_success_match.group(3)}"
            )

        native_probe_empty_attempt_match = re.fullmatch(
            r"Anthropic Messages probe returned no visible text on attempt (\d+)\.",
            text,
        )
        if native_probe_empty_attempt_match:
            return f"Anthropic Messages probe 在第 {native_probe_empty_attempt_match.group(1)} 次尝试时没有返回可见文本。"

        native_probe_recovered_match = re.fullmatch(
            r"Anthropic Messages probe returned visible text after empty first attempt\.",
            text,
        )
        if native_probe_recovered_match:
            return "Anthropic Messages probe 在第一次空回复之后拿到了可见文本。"

        native_probe_endpoint_match = re.fullmatch(
            r"Anthropic Messages probe reached /v1/messages\.",
            text,
        )
        if native_probe_endpoint_match:
            return "Anthropic Messages probe 已经命中 /v1/messages。"

        if (
            text
            == "Provider reachable, but Trainer could not fully verify zh-CN input integrity on this connection yet."
        ):
            return "provider 可达，但 Trainer 还不能完整验证这条连接的 zh-CN 输入保真度。"
        if (
            text
            == "Provider reachable, but it corrupted Chinese input into question marks before the model saw it. Trainer cannot safely coach in zh-CN on this connection yet."
        ):
            return "provider 可达，但它会在模型看到内容前把中文输入破坏成问号；这条连接暂时不能安全地做 zh-CN 教练。"

        no_channel_match = re.fullmatch(r"No available channel for model (.+)", text)
        if no_channel_match:
            return f"当前没有可用于 model {no_channel_match.group(1)} 的 channel。"

        not_supported_match = re.fullmatch(r"Not supported model (.+)", text)
        if not_supported_match:
            return f"当前不支持 model {not_supported_match.group(1)}。"

        return text

    def _provider_route_localized_diagnostics(
        diagnostics: object,
        provider: ProviderConfig,
        response_language: str | None,
    ) -> list[str]:
        if not isinstance(diagnostics, list):
            return []
        localized: list[str] = []
        seen: set[str] = set()
        for item in diagnostics:
            text = _provider_route_localized_diagnostic_line(
                str(item or ""),
                provider,
                response_language,
            )
            if not text or text in seen:
                continue
            seen.add(text)
            localized.append(text)
        return localized

    def _provider_test_success_detail(
        provider: ProviderConfig,
        response_language: str | None,
        raw_detail: str | None,
    ) -> str:
        detail = str(raw_detail or "").strip()
        if not detail:
            return localized_text(
                f"Provider reachable. Chat probe succeeded with model {provider.model}.",
                f"provider 已连通，chat probe 已通过，当前 model「{provider.model}」可以返回可见内容。",
                response_language,
            )
        if not prefers_chinese(response_language) or contains_cjk_text(detail):
            return detail

        success_match = re.fullmatch(
            r"Provider reachable\. Chat probe succeeded with model (.+?)\. Response:\s*(.+)",
            detail,
        )
        if success_match:
            model_name = success_match.group(1).strip()
            preview = success_match.group(2).strip()
            return (
                f"provider 已连通，chat probe 已通过，当前 model「{model_name}」可以返回可见内容。"
                f" 响应预览：{preview}"
            )

        listed_match = re.fullmatch(
            r"Provider reachable\. Listed (\d+) models\.(?: Resolved configured model to (.+?)\.)?",
            detail,
        )
        if listed_match:
            count = listed_match.group(1)
            resolved_model = (listed_match.group(2) or "").strip()
            suffix = (
                f" 当前配置的 model 对应到「{resolved_model}」。"
                if resolved_model
                else ""
            )
            return f"provider 已连通，并成功列出了 {count} 个 models。{suffix}".strip()

        if detail.startswith("Provider reachable."):
            return f"provider 已连通，当前 model「{provider.model}」已经通过 live probe。"

        return detail

    def _provider_models_visible_detail(
        provider: ProviderConfig,
        response_language: str | None,
        response: dict[str, object],
    ) -> str:
        detail = str(response.get("detail") or "").strip()
        if not detail:
            return detail
        if not prefers_chinese(response_language) or contains_cjk_text(detail):
            return detail

        error_category = str(response.get("error_category") or "").strip() or None
        if error_category == "missing_api_key":
            return "provider 设置已经保存，但还没有可用的 API key。补上之后 Trainer 才能获取 models。"
        if error_category:
            return _provider_test_clean_base_detail(error_category, provider, response_language)

        available_models = response.get("available_models")
        model_count = len(available_models) if isinstance(available_models, list) else 0
        resolved_model = str(response.get("resolved_model") or "").strip()
        if model_count > 0:
            suffix = (
                f" 当前配置的 model 对应到「{resolved_model}」。"
                if resolved_model
                else ""
            )
            return f"已获取 {model_count} 个 models。{suffix}".strip()
        return "provider 已响应，但没有返回可见的 models。"

    def persist_provider_last_test_recovery(
        payload: dict,
        response: dict[str, object],
        provider: ProviderConfig | None = None,
    ) -> None:
        outcome = "success" if response.get("ok") is True else "failure"
        response["reliability"] = operation_reliability_record(
            phase="acked",
            outcome=outcome,
        )
        workspace_id = str(payload.get("workspace_id") or payload.get("workspaceId") or "").strip()
        if not workspace_id:
            return
        raw_provider_payload = payload.get("provider")
        provider_payload: dict[str, object] = (
            raw_provider_payload if isinstance(raw_provider_payload, dict) else {}
        )
        body = {
            **response,
            "checked_at": datetime.now(UTC).isoformat(),
            "workspace_id": workspace_id,
            "provider_profile_id": (
                (getattr(provider, "profile_id", None) if provider is not None else None)
                or payload.get("profile_id")
                or payload.get("profileId")
                or provider_payload.get("profile_id")
                or provider_payload.get("profileId")
                or ""
            ),
            "provider_name": (provider.name if provider is not None else response.get("provider_name")),
            "base_url": (
                provider.base_url
                if provider is not None
                else response.get("base_url") or response.get("baseUrl")
            ),
            "model": (provider.model if provider is not None else response.get("model")),
            "protocol": (provider.protocol if provider is not None else response.get("protocol")),
        }
        runtime.memory_service.persist_provider_capability_recovery(workspace_id, body)


    @router.post("/provider/test")
    def provider_test(payload: dict) -> dict[str, object]:
        provider_payload = payload.get("provider", {})
        if not isinstance(provider_payload, dict):
            provider_payload = {}
        api_key = provider_api_key_from_payload(payload)
        provider_protocol = provider_protocol_from_payload(provider_payload)
        connection_type = provider_connection_type_from_payload(provider_payload)
        probe_message_raw = payload.get("probe_message") or payload.get("probeMessage")
        probe_message = probe_message_raw.strip() if isinstance(probe_message_raw, str) else None
        response_language_raw = payload.get("response_language") or payload.get("responseLanguage")
        response_language = (
            response_language_raw.strip() if isinstance(response_language_raw, str) else None
        )
        declared_protocol_raw = provider_payload.get("protocol") or provider_payload.get("api")
        declared_unknown_protocol = (
            isinstance(declared_protocol_raw, str)
            and bool(str(declared_protocol_raw).strip())
            and provider_protocol is None
        )
        if declared_unknown_protocol or (
            provider_protocol is None and connection_type == NEWAPI_CONNECTION_TYPE
        ):
            detail = localized_text(
                "This connection type is not a protocol. Select OpenAI Chat Completions, Responses, Anthropic Messages, Gemini, or OpenAI-compatible after a live test. Unknown gateways are not assumed compatible.",
                "这是网关连接类型，不是协议。请在 live test 之后选择 OpenAI Chat Completions、Responses、Anthropic Messages、Gemini 或 OpenAI-compatible。未知网关不会被默认成 compatible。",
                response_language,
            )
            diagnostics = [
                f"connection type: {connection_type or 'unknown'}",
                "newapi_channel_conn is a gateway connection type, not a protocol.",
                "Unknown gateways are not assumed OpenAI-compatible.",
            ]
            unknown_protocol_response = {
                **empty_provider_test_capability_payload(),
                "ok": False,
                "configured": bool(
                    str(provider_payload.get("name") or "").strip()
                    and str(provider_payload.get("base_url") or provider_payload.get("baseUrl") or "").strip()
                    and str(provider_payload.get("model") or "").strip()
                ),
                "api_key_supplied": bool(api_key),
                "reachable": False,
                "success": False,
                "status": "unknown_protocol",
                "provider_name": str(provider_payload.get("name") or "").strip() or None,
                "base_url": str(
                    provider_payload.get("base_url") or provider_payload.get("baseUrl") or ""
                ).strip()
                or None,
                "model": str(provider_payload.get("model") or "").strip() or None,
                "protocol": None,
                "protocol_family": None,
                "connection_type": connection_type,
                "detail": detail,
                "diagnostics": diagnostics,
                "error_category": "unknown_protocol",
                "retryable": False,
            }
            persist_provider_last_test_recovery(payload, unknown_protocol_response)
            unknown_provider = provider_config_from_payload(payload)
            if unknown_provider is None:
                fallback_url = str(
                    provider_payload.get("base_url") or provider_payload.get("baseUrl") or ""
                ).strip()
                fallback_model = str(provider_payload.get("model") or "").strip()
                if fallback_url and fallback_model:
                    unknown_provider = ProviderConfig(
                        name=str(provider_payload.get("name") or "").strip()
                        or "custom-openai-compatible",
                        baseUrl=fallback_url,
                        apiKeyRef=str(
                            provider_payload.get("api_key_ref")
                            or provider_payload.get("apiKeyRef")
                            or "trainer.default"
                        ),
                        model=fallback_model,
                    )
            if unknown_provider is not None:
                runtime.remember_provider_capability_test(
                    unknown_provider,
                    api_key,
                    unknown_protocol_response,
                )
                transport_url = (unknown_provider.base_url or "").strip().rstrip("/")
                transport_model = (unknown_provider.model or "").strip()
                if transport_url and transport_model:
                    for cache_key in list(runtime.provider_capability_cache):
                        if transport_url in cache_key and transport_model in cache_key:
                            runtime.provider_capability_cache[cache_key] = {
                                "connection": "unverified",
                            }
            return unknown_protocol_response
        if provider_protocol is None:
            provider_protocol = "openai_chat_completions_compatible"
        provider_protocol_family_value = provider_protocol_family(provider_protocol)
        provider = provider_config_from_payload(payload) or ProviderConfig(
            name=(provider_payload.get("name", "custom-openai-compatible") or "custom-openai-compatible").strip(),
            baseUrl=(provider_payload.get("base_url") or provider_payload.get("baseUrl", "")).strip(),
            apiKeyRef=provider_payload.get("api_key_ref")
            or provider_payload.get("apiKeyRef", "trainer.default"),
            model=(provider_payload.get("model", "") or "").strip(),
            protocol=provider_protocol,
            embeddingModel=provider_payload.get("embedding_model") or provider_payload.get("embeddingModel"),
            requestDefaults=provider_payload.get("request_defaults")
            or provider_payload.get("requestDefaults")
            or {},
            capabilities=provider_capabilities_from_payload(provider_payload),
        )
        configured = bool(provider.name and provider.base_url and provider.model)
        api_key_supplied = bool(api_key)
        diagnostics = [
            f"provider: {provider.name}",
            f"base URL: {provider.base_url or '(missing)'}",
            f"model: {provider.model or '(missing)'}",
        ]

        if not configured:
            detail = localized_text(
                "Provider config is incomplete. Save a provider name, base URL, and model before testing.",
                "\u0070\u0072\u006f\u0076\u0069\u0064\u0065\u0072 \u914d\u7f6e\u8fd8\u4e0d\u5b8c\u6574\u3002\u5f00\u59cb\u6d4b\u8bd5\u524d\uff0c\u8bf7\u5148\u4fdd\u5b58 provider name\u3001base URL \u548c model\u3002",
                response_language,
            )
            diagnostics.append(
                "configuration incomplete: a live provider test needs name, base URL, and model"
            )
            incomplete_response = {
                "ok": False,
                "configured": False,
                "api_key_supplied": api_key_supplied,
                "reachable": False,
                "success": False,
                "status": "incomplete",
                "provider_name": provider.name,
                "protocol": provider.protocol,
                "protocol_family": provider_protocol_family_value,
                "detail": detail,
                "diagnostics": _provider_route_localized_diagnostics(
                    diagnostics,
                    provider,
                    response_language,
                ),
                **empty_provider_test_capability_payload(provider),
            }
            persist_provider_last_test_recovery(payload, incomplete_response, provider)
            runtime.remember_provider_capability_test(provider, api_key, incomplete_response)
            return incomplete_response

        policy_violation = provider_model_policy_violation(provider)
        if policy_violation is not None:
            detail = provider_model_policy_detail(provider, policy_violation, response_language)
            diagnostics.append(detail)
            policy_response = {
                "ok": False,
                "configured": True,
                "api_key_supplied": api_key_supplied,
                "reachable": False,
                "success": False,
                "status": policy_violation,
                "provider_name": provider.name,
                "protocol": provider.protocol,
                "protocol_family": provider_protocol_family_value,
                "detail": detail,
                "diagnostics": _provider_route_localized_diagnostics(
                    diagnostics,
                    provider,
                    response_language,
                ),
                "error_category": policy_violation,
                "retryable": False,
                "status_code": 400,
                "model_supported": False,
                **empty_provider_test_capability_payload(provider),
            }
            persist_provider_last_test_recovery(payload, policy_response, provider)
            runtime.remember_provider_capability_test(provider, api_key, policy_response)
            return policy_response

        provider_service = runtime.provider_service_for(provider, api_key)
        result = provider_service.test(
            provider,
            api_key,
            probe_message=probe_message,
            response_language=response_language,
        )
        runtime.remember_provider_capability_test(provider, api_key, result)
        result_status = result.error_category or "failed"

        if not api_key_supplied:
            detail = localized_text(
                (
                    "Provider settings are saved, but no API key is stored. "
                    "Trainer cannot work until you add one."
                ),
                "\u0070\u0072\u006f\u0076\u0069\u0064\u0065\u0072 \u8bbe\u7f6e\u5df2\u7ecf\u4fdd\u5b58\uff0c\u4f46\u8fd8\u6ca1\u6709\u53ef\u7528\u7684 API key\u3002\u8865\u4e0a\u4e4b\u540e Trainer \u624d\u80fd\u7ee7\u7eed\u5de5\u4f5c\u3002",
                response_language,
            )
            diagnostics.append("live connectivity check skipped: no API key supplied")
            if result.detail:
                diagnostics.append(result.detail)
            missing_key_response = {
                "ok": False,
                "configured": True,
                "api_key_supplied": False,
                "reachable": False,
                "success": False,
                "status": "missing_api_key",
                "error_category": "missing_api_key",
                "provider_name": provider.name,
                "protocol": provider.protocol,
                "protocol_family": provider_protocol_family_value,
                "detail": detail,
                "diagnostics": _provider_route_localized_diagnostics(
                    diagnostics,
                    provider,
                    response_language,
                ),
                **provider_test_capability_payload(provider, result),
            }
            persist_provider_last_test_recovery(payload, missing_key_response, provider)
            runtime.remember_provider_capability_test(provider, api_key, missing_key_response)
            return missing_key_response

        if result.ok:
            diagnostics.append("live connectivity check succeeded")
            diagnostics.extend(result.diagnostics)
            if result.detail and result.detail not in diagnostics:
                diagnostics.append(result.detail)
            success_response = {
                "ok": True,
                "configured": True,
                "api_key_supplied": True,
                "reachable": True,
                "success": True,
                "status": "connected",
                "provider_name": provider.name,
                "protocol": provider.protocol,
                "protocol_family": provider_protocol_family_value,
                "detail": _provider_test_success_detail(
                    provider,
                    response_language,
                    result.detail,
                ),
                "diagnostics": _provider_route_localized_diagnostics(
                    diagnostics,
                    provider,
                    response_language,
                ),
                "error_category": result.error_category,
                "retryable": result.retryable,
                "status_code": result.status_code,
                "model_supported": result.model_supported,
                **provider_test_capability_payload(provider, result),
            }
            persist_provider_last_test_recovery(payload, success_response, provider)
            return success_response

        # Failed protocol probes share one normalized, localized detail path.
        detail = _provider_test_clean_route_detail(
            result.error_category,
            provider,
            response_language,
            result.detail,
        )
        diagnostics.append("live connectivity check failed")
        diagnostics.extend(result.diagnostics)
        if result.detail and result.detail not in diagnostics:
            diagnostics.append(result.detail)
        failed_response = {
            "ok": False,
            "configured": True,
            "api_key_supplied": True,
            "reachable": result.provider_reachable,
            "success": False,
            "status": result_status,
            "provider_name": provider.name,
            "protocol": provider.protocol,
            "protocol_family": provider_protocol_family_value,
            "detail": detail,
            "diagnostics": _provider_route_localized_diagnostics(
                diagnostics,
                provider,
                response_language,
            ),
            "error_category": result.error_category,
            "retryable": result.retryable,
            "status_code": result.status_code,
            "model_supported": result.model_supported,
            **provider_test_capability_payload(provider, result),
        }
        persist_provider_last_test_recovery(payload, failed_response, provider)
        return failed_response

    @router.post("/provider/models")
    def provider_models(payload: dict) -> dict[str, object]:
        provider_payload = payload.get("provider", {})
        if not isinstance(provider_payload, dict):
            provider_payload = {}
        api_key = provider_api_key_from_payload(payload)
        response_language_raw = payload.get("response_language") or payload.get("responseLanguage")
        response_language = (
            response_language_raw.strip() if isinstance(response_language_raw, str) else None
        )
        provider_protocol = provider_protocol_from_payload(provider_payload)
        connection_type = provider_connection_type_from_payload(provider_payload)
        declared_protocol_raw = provider_payload.get("protocol") or provider_payload.get("api")
        if provider_protocol is None and (
            (isinstance(declared_protocol_raw, str) and declared_protocol_raw.strip())
            or connection_type == NEWAPI_CONNECTION_TYPE
        ):
            detail = localized_text(
                "This connection type is not a protocol. Select a real protocol before listing models. Unknown gateways are not assumed compatible.",
                "这是网关连接类型，不是协议。列出 models 前请先选择真实协议。未知网关不会被默认成 compatible。",
                response_language,
            )
            return {
                "ok": False,
                "detail": detail,
                "available_models": [],
                "resolved_model": None,
                "listed": False,
                "error_category": "unknown_protocol",
                "retryable": False,
                "diagnostics": [
                    f"connection type: {connection_type or 'unknown'}",
                    "Unknown gateways are not assumed OpenAI-compatible.",
                ],
                "protocol": None,
                "protocol_family": None,
            }
        if provider_protocol is None:
            provider_protocol = "openai_chat_completions_compatible"
        provider_protocol_family_value = provider_protocol_family(provider_protocol)
        provider = provider_config_from_payload(payload) or ProviderConfig(
            name=(provider_payload.get("name", "custom-openai-compatible") or "custom-openai-compatible").strip(),
            baseUrl=(provider_payload.get("base_url") or provider_payload.get("baseUrl", "")).strip(),
            apiKeyRef=provider_payload.get("api_key_ref")
            or provider_payload.get("apiKeyRef", "trainer.default"),
            model=(provider_payload.get("model", "") or "").strip(),
            protocol=provider_protocol,
            embeddingModel=provider_payload.get("embedding_model") or provider_payload.get("embeddingModel"),
            requestDefaults=provider_payload.get("request_defaults")
            or provider_payload.get("requestDefaults")
            or {},
            capabilities=provider_capabilities_from_payload(provider_payload),
        )

        if not provider.base_url:
            response = ProviderModelsResponse(
                ok=False,
                detail=localized_text(
                    "Add a service root address before fetching models.",
                    "\u83b7\u53d6\u6a21\u578b\u524d\uff0c\u8bf7\u5148\u586b\u5199\u670d\u52a1\u6839\u5730\u5740\u3002",
                    response_language,
                ),
            ).model_dump()
            response["protocol"] = provider.protocol
            response["protocol_family"] = provider_protocol_family_value
            return response

        provider_service = runtime.provider_service_for(provider, api_key)
        response = provider_service.list_models(provider, api_key).model_dump()
        response["detail"] = _provider_models_visible_detail(
            provider,
            response_language,
            response,
        )
        response["diagnostics"] = _provider_route_localized_diagnostics(
            response.get("diagnostics"),
            provider,
            response_language,
        )
        response["protocol"] = provider.protocol
        response["protocol_family"] = provider_protocol_family_value
        return response
    return router
