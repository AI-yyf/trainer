from __future__ import annotations

import json
import ipaddress
import os
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from typing import Any


CJK_RE = re.compile(r"[\u3400-\u9fff]")
GENERIC_INTERRUPTION_MARKERS = (
    "教练服务在中途断开了",
    "沿着同一条主线续回去",
    "provider stopped mid-turn",
    "thread can still resume",
)

DEFAULT_REMOTE_PROMPT = (
    "\u8bf7\u521b\u5efa\u4e00\u5f20 learn-first practice card\uff0c\u4e3b\u9898\u662f VS Code Remote SSH\u3002"
    "\u5148\u8ba9\u6211\u7ec3\u4e60\u4e00\u4e2a\u5f88\u5c0f\u4e14\u53ef\u9a8c\u8bc1\u7684\u6b65\u9aa4\uff0c\u518d\u5e2e\u6211\u9a8c\u8bc1\u7ed3\u679c\u3002"
)
DEFAULT_DEBUG_PROMPT = (
    "\u8bf7\u521b\u5efa\u4e00\u5f20 learn-first practice card\uff0c\u4e3b\u9898\u662f\u5728 VS Code \u91cc debug Python\u3002"
    "\u5148\u8ba9\u6211\u7ec3\u4e60\u4e00\u4e2a breakpoint \u548c\u4e00\u4e2a\u53ef\u9a8c\u8bc1\u7684 value\uff0c\u518d\u5e2e\u6211\u9a8c\u8bc1\u3002"
)
DEFAULT_FUNCTION_PROMPT = (
    "\u8bf7\u521b\u5efa\u4e00\u5f20 learn-first practice card\uff0c\u4e3b\u9898\u662f TypeScript fetch options \u7684\u4e00\u4e2a\u771f\u5b9e call site\u3002"
    "\u5148\u8ba9\u6211\u7ec3\u4e60\u4e00\u4e2a\u53ef\u9a8c\u8bc1\u7684\u5c0f\u6b65\uff0c\u518d\u5e2e\u6211\u9a8c\u8bc1\u3002"
)

OPENAI_LIKE_PROTOCOLS = {
    "openai_chat_completions_compatible",
    "openai_chat_completions",
    "openai_responses",
}


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _load_cases() -> list[dict[str, Any]]:
    raw = _require_env("TRAINER_LIVE_PROTOCOL_CASES_JSON")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("TRAINER_LIVE_PROTOCOL_CASES_JSON must be valid JSON.") from exc
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("TRAINER_LIVE_PROTOCOL_CASES_JSON must be a non-empty JSON array.")
    cases: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise RuntimeError("Each protocol case must be a JSON object.")
        protocol = str(item.get("protocol") or "").strip()
        base_url = str(item.get("baseUrl") or item.get("base_url") or "").strip()
        model = str(item.get("model") or "").strip()
        if not protocol or not base_url or not model:
            raise RuntimeError("Each protocol case requires protocol, baseUrl, and model.")
        if "apiKey" in item or "api_key" in item:
            raise RuntimeError(
                "TRAINER_LIVE_PROTOCOL_CASES_JSON must not contain apiKey; "
                "use TRAINER_LIVE_PROTOCOL_API_KEY."
            )
        cases.append(
            {
                "protocol": protocol,
                "baseUrl": base_url,
                "model": model,
            }
        )

    return cases


def _post_json(
    sidecar_url: str,
    path: str,
    payload: dict[str, Any],
    *,
    timeout: int = 120,
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"{sidecar_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with _urlopen_sidecar(request, sidecar_url, timeout=timeout) as response:
            text = response.read().decode("utf-8")
            body = json.loads(text)
            if not isinstance(body, dict):
                raise RuntimeError(f"{path} returned a non-object JSON payload.")
            return response.status, body
    except urllib.error.HTTPError as exc:
        # Upstream bodies can contain request context or provider diagnostics. The live
        # probe only needs the endpoint and status to make its pass/fail decision.
        raise RuntimeError(f"{path} HTTP {exc.code}") from exc


def _is_loopback_sidecar(sidecar_url: str) -> bool:
    """Keep local probe traffic off ambient HTTP proxies."""
    hostname = (urlsplit(sidecar_url).hostname or "").strip().lower()
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _urlopen_sidecar(
    request: urllib.request.Request,
    sidecar_url: str,
    *,
    timeout: int,
):
    if not _is_loopback_sidecar(sidecar_url):
        return urllib.request.urlopen(request, timeout=timeout)

    # urllib honors HTTP(S)_PROXY before it considers a loopback host unless
    # NO_PROXY is present. Scope the bypass to this synchronous local request
    # so provider traffic and the caller's environment remain unchanged.
    previous = {name: os.environ.get(name) for name in ("NO_PROXY", "no_proxy")}
    try:
        entries = {"localhost", "127.0.0.1", "::1"}
        for value in previous.values():
            if value:
                entries.update(part.strip() for part in value.split(",") if part.strip())
        bypass = ",".join(sorted(entries))
        os.environ["NO_PROXY"] = bypass
        os.environ["no_proxy"] = bypass
        return urllib.request.urlopen(request, timeout=timeout)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _post_json_with_retries(
    sidecar_url: str,
    path: str,
    payload: dict[str, Any],
    *,
    timeout: int = 120,
    attempts: int = 3,
) -> tuple[int, dict[str, Any]]:
    """Retry transient gateway/transport failures without masking contract failures."""
    last_error: RuntimeError | None = None
    for attempt in range(max(1, attempts)):
        try:
            return _post_json(sidecar_url, path, payload, timeout=timeout)
        except RuntimeError as exc:
            last_error = exc
            detail = str(exc).lower()
            transient = any(
                marker in detail
                for marker in (
                    "http 408",
                    "http 429",
                    "http 502",
                    "http 503",
                    "http 504",
                    "timeout",
                    "timed out",
                    "temporar",
                    "connection reset",
                    "connection refused",
                )
            )
            if not transient:
                raise
            if attempt + 1 >= max(1, attempts):
                raise
            time.sleep(0.75 * (attempt + 1))
    raise last_error or RuntimeError(f"{path} failed")


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise RuntimeError(detail)


def _has_cjk(value: str) -> bool:
    return bool(CJK_RE.search(value))


def _provider_payload(case: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": f"live-{case['protocol']}",
        "baseUrl": case["baseUrl"],
        "apiKeyRef": "trainer.live-protocol",
        "model": case["model"],
        "protocol": case["protocol"],
    }
    if case["protocol"] in OPENAI_LIKE_PROTOCOLS:
        payload["requestDefaults"] = {
            "extra_body": {
                "thinking": {
                    "type": "disabled",
                }
            }
        }
    return payload


def _resolve_case_api_key(case: dict[str, Any], default_api_key: str | None) -> str:
    api_key = str(default_api_key or "").strip()
    if not api_key:
        raise RuntimeError(
            f"{case.get('protocol') or 'protocol case'} requires TRAINER_LIVE_PROTOCOL_API_KEY."
        )
    return api_key


def _selected_card(snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    memory = snapshot.get("memory") if isinstance(snapshot, dict) else None
    memory_record = memory if isinstance(memory, dict) else {}
    routing = memory_record.get("active_training_card_routing") or memory_record.get(
        "activeTrainingCardRouting"
    )
    routing_record = routing if isinstance(routing, dict) else {}
    card = routing_record.get("selected_card") or routing_record.get("selectedCard")
    card_record = card if isinstance(card, dict) else {}
    return routing_record, card_record


def _model_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    direct_models = payload.get("models")
    if isinstance(direct_models, list):
        resolved: list[str] = []
        for item in direct_models:
            if isinstance(item, str):
                candidate = item.strip()
            elif isinstance(item, dict):
                candidate = str(item.get("id") or item.get("name") or "").strip()
            else:
                candidate = ""
            if candidate:
                resolved.append(candidate)
        if resolved:
            return resolved

    available_models = payload.get("available_models")
    if isinstance(available_models, list):
        return [str(item).strip() for item in available_models if str(item).strip()]

    return []


def _provider_result_summary(payload: dict[str, Any]) -> str:
    """Return only stable, non-secret fields when a provider probe fails."""

    fields = (
        ("status", payload.get("status")),
        ("error_category", payload.get("error_category") or payload.get("errorCategory")),
        ("status_code", payload.get("status_code") or payload.get("statusCode")),
        ("retryable", payload.get("retryable")),
    )
    return ", ".join(f"{name}={value}" for name, value in fields if value is not None) or "no status"


def _assert_turn(
    *,
    case_protocol: str,
    payload: dict[str, Any],
    expected_scenario: str,
    expected_pack: str | None = None,
    label: str,
) -> dict[str, str]:
    reply_record = payload.get("reply")
    reply = str(reply_record.get("content") if isinstance(reply_record, dict) else "").strip()
    coach_turn = payload.get("coach_turn")
    scenario = str(coach_turn.get("scenario") if isinstance(coach_turn, dict) else "").strip()
    _require(
        scenario == expected_scenario,
        f"{case_protocol} {label}: expected scenario {expected_scenario}, got {scenario or '(missing)'}",
    )
    _require(reply, f"{case_protocol} {label}: missing visible reply")
    _require(_has_cjk(reply), f"{case_protocol} {label}: reply is not zh-CN enough")
    _require(
        not any(marker in reply for marker in GENERIC_INTERRUPTION_MARKERS),
        f"{case_protocol} {label}: reply degraded into generic interruption copy",
    )
    result = {"scenario": scenario}
    if expected_pack is not None:
        snapshot = payload.get("snapshot")
        routing, card = _selected_card(snapshot if isinstance(snapshot, dict) else {})
        card_type = str(card.get("card_type") or card.get("type") or "").strip()
        scenario_pack = str(card.get("scenario_pack") or card.get("scenarioPack") or "").strip()
        title = str(card.get("title") or "").strip()
        problem = str(card.get("problem_statement") or card.get("problemStatement") or "").strip()
        _require(routing, f"{case_protocol} {label}: missing active_training_card_routing")
        _require(card_type == "practice", f"{case_protocol} {label}: expected practice card")
        _require(scenario_pack == expected_pack, f"{case_protocol} {label}: expected scenario_pack {expected_pack}")
        _require(_has_cjk(title), f"{case_protocol} {label}: title is not localized")
        _require(_has_cjk(problem), f"{case_protocol} {label}: problem statement is not localized")
        result["scenarioPack"] = scenario_pack
    return result


def _assert_generated_card(
    *,
    case_protocol: str,
    payload: dict[str, Any],
    expected_pack: str,
    label: str,
) -> dict[str, str]:
    card_record = payload.get("card") if isinstance(payload, dict) else None
    card = card_record if isinstance(card_record, dict) else {}
    card_type = str(card.get("card_type") or card.get("cardType") or card.get("type") or "").strip()
    scenario_pack = str(card.get("scenario_pack") or card.get("scenarioPack") or "").strip()
    title = str(card.get("title") or "").strip()
    problem = str(card.get("problem_statement") or card.get("problemStatement") or "").strip()
    card_id = str(card.get("card_id") or card.get("cardId") or "").strip()
    _require(bool(card), f"{case_protocol} {label}: missing generated card")
    _require(card_type == "practice", f"{case_protocol} {label}: expected practice card")
    _require(scenario_pack == expected_pack, f"{case_protocol} {label}: expected scenario_pack {expected_pack}")
    _require(bool(card_id), f"{case_protocol} {label}: missing durable card id")
    _require(_has_cjk(title), f"{case_protocol} {label}: title is not localized")
    _require(_has_cjk(problem), f"{case_protocol} {label}: problem statement is not localized")
    return {"scenarioPack": scenario_pack, "cardId": card_id}


def _training_card_payload(
    *,
    workspace_id: str,
    message: str,
    provider: dict[str, Any],
    api_key: str,
    scenario: str,
) -> dict[str, Any]:
    defaults = {
        "remote_workspace": ("VS Code remote workspace", "name the remote boundary"),
        "debug_loop": ("VS Code debug loop", "stop at one meaningful state change"),
        "function_guidance": ("function contract", "read one real call site"),
    }
    focus_area, target_skill = defaults[scenario]
    return {
        "workspace_id": workspace_id,
        "source": "conversation_gap",
        "card_type": "practice",
        "focus_area": focus_area,
        "target_skill": target_skill,
        "context_hint": f"Coach request: {message}",
        "why_now": "学习者请求先学后练的一个最小训练动作。",
        "response_language": "zh-CN",
        "provider": provider,
        "api_key": api_key,
    }


def _assert_chat_turn(
    *,
    case_protocol: str,
    payload: dict[str, Any],
    expected_scenario: str,
    label: str,
) -> dict[str, str]:
    result = _assert_turn(
        case_protocol=case_protocol,
        payload=payload,
        expected_scenario=expected_scenario,
        label=label,
    )
    snapshot = payload.get("snapshot")
    routing, _card = _selected_card(snapshot if isinstance(snapshot, dict) else {})
    _require(
        not routing,
        f"{case_protocol} {label}: composer chat unexpectedly minted a training card",
    )
    return result


def main() -> int:
    sidecar_url = _require_env("TRAINER_LIVE_PROTOCOL_SIDECAR_URL").rstrip("/")
    default_api_key = os.environ.get("TRAINER_LIVE_PROTOCOL_API_KEY", "").strip() or None
    cases = _load_cases()

    remote_prompt = os.environ.get("TRAINER_LIVE_PROTOCOL_REMOTE_PROMPT", DEFAULT_REMOTE_PROMPT).strip()
    debug_prompt = os.environ.get("TRAINER_LIVE_PROTOCOL_DEBUG_PROMPT", DEFAULT_DEBUG_PROMPT).strip()
    function_prompt = os.environ.get(
        "TRAINER_LIVE_PROTOCOL_FUNCTION_PROMPT",
        DEFAULT_FUNCTION_PROMPT,
    ).strip()

    summary: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        api_key = _resolve_case_api_key(case, default_api_key)
        provider = _provider_payload(case)
        status, test_payload = _post_json_with_retries(
            sidecar_url,
            "/provider/test",
            {
                "provider": provider,
                "api_key": api_key,
                "response_language": "zh-CN",
                "probe_message": remote_prompt,
            },
        )
        _require(
            status == 200 and bool(test_payload.get("ok")),
            f"{case['protocol']}: /provider/test failed: {_provider_result_summary(test_payload)}",
        )

        status, models_payload = _post_json_with_retries(
            sidecar_url,
            "/provider/models",
            {
                "provider": provider,
                "api_key": api_key,
            },
        )
        _require(
            status == 200 and bool(models_payload.get("listed")),
            f"{case['protocol']}: /provider/models failed: {_provider_result_summary(models_payload)}",
        )
        model_ids = _model_ids_from_payload(models_payload)
        _require(
            case["model"] in model_ids,
            f"{case['protocol']}: expected model {case['model']} in {model_ids}",
        )

        workspace_id = f"live-protocol-{index}-{int(time.time() * 1000)}"
        status, start_payload = _post_json(
            sidecar_url,
            "/session/start",
            {
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Verify real provider protocols and learn-first coaching continuity.",
                    "weekly_hours": 4,
                    "teaching_style": "auto",
                    "answer_policy": "auto",
                },
            },
        )
        _require(status == 200, f"{case['protocol']}: /session/start returned HTTP {status}")
        session_id = str(start_payload.get("session_id") or "").strip()
        _require(session_id, f"{case['protocol']}: missing session_id")

        def run_turn(message: str) -> dict[str, Any]:
            turn_status, turn_payload = _post_json_with_retries(
                sidecar_url,
                "/turn",
                {
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "intent": "coach",
                    "message": message,
                    "response_language": "zh-CN",
                    "answer_mode": "auto",
                    "use_agent_loop": True,
                    "provider": provider,
                    "api_key": api_key,
                },
                timeout=180,
            )
            _require(
                turn_status == 200,
                f"{case['protocol']}: /turn returned HTTP {turn_status}",
            )
            return turn_payload

        remote_result = _assert_chat_turn(
            case_protocol=case["protocol"],
            payload=run_turn(remote_prompt),
            expected_scenario="remote_workspace",
            label="remote",
        )
        debug_result = _assert_chat_turn(
            case_protocol=case["protocol"],
            payload=run_turn(debug_prompt),
            expected_scenario="debug_loop",
            label="debug",
        )
        function_result = _assert_chat_turn(
            case_protocol=case["protocol"],
            payload=run_turn(function_prompt),
            expected_scenario="function_guidance",
            label="function",
        )

        generated_cards: dict[str, dict[str, str]] = {}
        for label, message, scenario in (
            ("remote", remote_prompt, "remote_workspace"),
            ("debug", debug_prompt, "debug_loop"),
            ("function", function_prompt, "function_guidance"),
        ):
            card_status, card_payload = _post_json_with_retries(
                sidecar_url,
                "/training/generate-card",
                _training_card_payload(
                    workspace_id=f"{workspace_id}-{scenario}",
                    message=message,
                    provider=provider,
                    api_key=api_key,
                    scenario=scenario,
                ),
                timeout=180,
            )
            _require(
                card_status == 200 and bool(card_payload.get("success", True)),
                f"{case['protocol']} {label}: explicit card generation failed",
            )
            generated_cards[label] = _assert_generated_card(
                case_protocol=case["protocol"],
                payload=card_payload,
                expected_pack=scenario,
                label=f"{label}-card",
            )

        summary.append(
            {
                "protocol": case["protocol"],
                "providerTest": "passed",
                "providerModels": len(model_ids),
                "remote": remote_result,
                "debug": debug_result,
                "functionGuidance": function_result,
                "generatedCards": generated_cards,
            }
        )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)
