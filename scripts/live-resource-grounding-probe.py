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
from pathlib import Path
from typing import Any

CJK_RE = re.compile(r"[\u3400-\u9fff]")

DEFAULT_GROUNDING_PROMPT = (
    "\u6211\u521a\u5bfc\u5165\u4e86\u4e00\u4efd\u8bbe\u8ba1\u6587\u6863\u3002"
    "\u8bf7\u76f4\u63a5\u544a\u8bc9\u6211 Resources \u89c6\u56fe\u7684 first viewport "
    "promise\uff0c\u4ee5\u53ca\u5b83\u7edd\u4e0d\u80fd\u53d8\u6210\u4ec0\u4e48\u3002"
)

DEFAULT_RESOURCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "2026-06-29-unified-coach-master-plan.md"
)

OPENAI_LIKE_PROTOCOLS = {
    "openai_chat_completions_compatible",
    "openai_chat_completions",
    "openai_responses",
}


class ProbeFailure(RuntimeError):
    def __init__(self, step: str, category: str, *, status: int | None = None) -> None:
        self.step = step
        self.category = category
        self.status = status
        super().__init__(f"{step}: {category}")


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _load_cases() -> list[dict[str, Any]]:
    raw = _require_env("TRAINER_LIVE_GROUNDING_CASES_JSON")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("TRAINER_LIVE_GROUNDING_CASES_JSON must be valid JSON.") from exc
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("TRAINER_LIVE_GROUNDING_CASES_JSON must be a non-empty JSON array.")

    cases: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise RuntimeError("Each grounding protocol case must be a JSON object.")
        protocol = str(item.get("protocol") or "").strip()
        base_url = str(item.get("baseUrl") or item.get("base_url") or "").strip()
        model = str(item.get("model") or "").strip()
        if not protocol or not base_url or not model:
            raise RuntimeError("Each grounding case requires protocol, baseUrl, and model.")
        if "apiKey" in item or "api_key" in item:
            raise RuntimeError(
                "TRAINER_LIVE_GROUNDING_CASES_JSON must not contain apiKey; "
                "use TRAINER_LIVE_GROUNDING_API_KEY."
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
    timeout: int = 180,
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
        raise ProbeFailure(path.strip("/").replace("/", "_") or "request", "http_error", status=exc.code) from exc


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


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise ProbeFailure("contract", "assertion_failed")


def _has_cjk(value: str) -> bool:
    return bool(CJK_RE.search(value))


def _reply_mentions_promise(reply: str) -> bool:
    lowered = reply.lower()
    if "first viewport promise" in lowered or "first viewport" in lowered:
        return True
    return any(token in reply for token in ("\u9996\u5c4f", "\u7b2c\u4e00\u89c6\u53e3")) and any(
        token in reply for token in ("\u627f\u8bfa", "\u5951\u7ea6")
    )


def _reply_mentions_boundary(reply: str) -> bool:
    lowered = reply.lower()
    if "must not become" in lowered or "raw filesystem browser" in lowered:
        return True
    has_boundary = any(
        token in reply
        for token in ("\u4e0d\u80fd", "\u4e0d\u8be5", "\u7ea2\u7ebf", "\u9000\u5316", "\u6ca6\u4e3a")
    )
    has_browser = any(
        token in reply
        for token in (
            "\u6587\u4ef6\u7cfb\u7edf",
            "\u6587\u4ef6\u6d4f\u89c8\u5668",
            "filesystem browser",
        )
    )
    return has_boundary and has_browser


def _provider_payload(case: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": f"grounding-{case['protocol']}",
        "baseUrl": case["baseUrl"],
        "apiKeyRef": "trainer.live-grounding",
        "model": case["model"],
        "protocol": case["protocol"],
        "requestDefaults": {"temperature": 0},
    }
    if case["protocol"] in OPENAI_LIKE_PROTOCOLS:
        payload["requestDefaults"]["extra_body"] = {"thinking": {"type": "disabled"}}
    return payload


def _resolve_case_api_key(case: dict[str, Any], default_api_key: str | None) -> str:
    api_key = str(default_api_key or "").strip()
    if not api_key:
        raise RuntimeError(
            f"{case.get('protocol') or 'grounding case'} requires TRAINER_LIVE_GROUNDING_API_KEY."
        )
    return api_key


def _load_resource(path_text: str | None) -> tuple[Path, str]:
    raw = str(path_text or "").strip()
    resource_path = Path(raw).expanduser().resolve(strict=False) if raw else DEFAULT_RESOURCE_PATH
    if not resource_path.exists() or not resource_path.is_file():
        raise RuntimeError(f"Grounding resource path does not exist: {resource_path}")
    return resource_path, resource_path.read_text(encoding="utf-8")


def _collect_grounding_evidence(
    payload: dict[str, Any],
    *,
    expected_title: str,
) -> dict[str, Any]:
    agent_meta = payload.get("agent_meta") if isinstance(payload, dict) else None
    meta = agent_meta if isinstance(agent_meta, dict) else {}
    tool_events = meta.get("tool_events")
    search_calls = 0
    search_results = 0
    hit_titles: list[str] = []
    matched_expected_title = False

    for item in tool_events if isinstance(tool_events, list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip() != "search_resources":
            continue
        if str(item.get("type") or "").strip() == "tool_call":
            search_calls += 1
            continue
        if str(item.get("type") or "").strip() != "tool_result":
            continue
        search_results += 1
        result_payload = item.get("result")
        if not isinstance(result_payload, dict):
            continue
        hits = result_payload.get("hits")
        if not isinstance(hits, list):
            continue
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            title = str(hit.get("title") or "").strip()
            if title:
                hit_titles.append(title)

    deduped_titles = list(dict.fromkeys(hit_titles))
    reply_record = payload.get("reply") if isinstance(payload, dict) else None
    reply_text = str(reply_record.get("content") if isinstance(reply_record, dict) else "").strip()
    mentions_promise = _reply_mentions_promise(reply_text)
    mentions_boundary = _reply_mentions_boundary(reply_text)
    matched_expected_title = expected_title in deduped_titles
    return {
        "autoResourceLookup": meta.get("auto_resource_lookup") is True,
        "searchCalls": search_calls,
        "searchResults": search_results,
        "replyPresent": bool(reply_text),
        "replyHasCjk": _has_cjk(reply_text),
        "mentionsPromise": mentions_promise,
        "mentionsBoundary": mentions_boundary,
        "coversRequestedContract": mentions_promise and mentions_boundary,
        "stopCompleted": str(meta.get("stop_reason") or "").strip() == "completed",
        "matchedExpectedTitle": matched_expected_title,
    }


def main() -> int:
    sidecar_url = _require_env("TRAINER_LIVE_GROUNDING_SIDECAR_URL").rstrip("/")
    default_api_key = os.environ.get("TRAINER_LIVE_GROUNDING_API_KEY", "").strip() or None
    cases = _load_cases()
    resource_path, resource_text = _load_resource(
        os.environ.get("TRAINER_LIVE_GROUNDING_RESOURCE_PATH", str(DEFAULT_RESOURCE_PATH))
    )
    resource_name = (
        str(os.environ.get("TRAINER_LIVE_GROUNDING_RESOURCE_NAME", resource_path.name)).strip()
        or resource_path.name
    )
    prompt = os.environ.get("TRAINER_LIVE_GROUNDING_PROMPT", DEFAULT_GROUNDING_PROMPT).strip()
    _require(prompt, "Grounding prompt must not be empty.")

    summary: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        api_key = _resolve_case_api_key(case, default_api_key)
        provider = _provider_payload(case)

        provider_test_status, provider_test_payload = _post_json(
            sidecar_url,
            "/provider/test",
            {
                "provider": provider,
                "api_key": api_key,
                "probe_message": prompt,
                "response_language": "zh-CN",
            },
        )
        _require(
            provider_test_status == 200 and bool(provider_test_payload.get("ok")),
            f"{case['protocol']}: /provider/test failed: {provider_test_payload}",
        )

        workspace_id = f"live-grounding-{index}-{int(time.time() * 1000)}"
        start_status, start_payload = _post_json(
            sidecar_url,
            "/session/start",
            {
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "workspace_path": str(resource_path.parents[1]),
                "profile": {
                    "long_term_goal": "Verify mixed-language resource grounding with a real provider.",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "coach-first",
                },
            },
        )
        _require(start_status == 200, f"{case['protocol']}: /session/start returned {start_status}")
        session_id = str(start_payload.get("session_id") or "").strip()
        _require(session_id, f"{case['protocol']}: missing session_id")

        upload_status, upload_payload = _post_json(
            sidecar_url,
            "/resource/upload",
            {
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": resource_name,
                "source": f"inline://{resource_name}",
                "content": resource_text,
                "content_encoding": "utf-8",
                "tags": ["live", "grounding", case["protocol"]],
            },
        )
        _require(upload_status == 200, f"{case['protocol']}: /resource/upload returned {upload_status}")
        resource_id = str(upload_payload.get("id") or "").strip()
        _require(resource_id, f"{case['protocol']}: upload did not return resource id")

        index_status, index_payload = _post_json(
            sidecar_url,
            "/resource/index",
            {
                "workspace_id": workspace_id,
                "resource_id": resource_id,
                "enable_network": False,
            },
        )
        _require(index_status == 200, f"{case['protocol']}: /resource/index returned {index_status}")
        _require(
            str(index_payload.get("index_status") or "").strip() == "indexed",
            f"{case['protocol']}: resource did not index cleanly: {index_payload}",
        )

        message_status, message_payload = _post_json(
            sidecar_url,
            "/session/message",
            {
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": prompt,
                "response_language": "zh-CN",
                "provider": provider,
                "api_key": api_key,
            },
            timeout=240,
        )
        _require(
            message_status == 200,
            f"{case['protocol']}: /session/message returned HTTP {message_status}",
        )

        evidence = _collect_grounding_evidence(message_payload, expected_title=resource_name)
        _require(
            evidence["searchCalls"] > 0 or evidence["autoResourceLookup"] is True,
            f"{case['protocol']}: expected resource grounding search evidence, got {evidence}",
        )
        _require(
            evidence["searchResults"] > 0,
            f"{case['protocol']}: expected search_resources tool results, got {evidence}",
        )
        _require(
            evidence["matchedExpectedTitle"],
            f"{case['protocol']}: expected uploaded resource in hits, got {evidence}",
        )
        _require(
            evidence["replyPresent"],
            f"{case['protocol']}: missing visible reply after grounding probe",
        )
        _require(
            evidence["replyHasCjk"],
            f"{case['protocol']}: grounding reply is not zh-CN enough: {evidence}",
        )
        _require(
            evidence["coversRequestedContract"],
            (
                f"{case['protocol']}: grounding reply did not cover both the promise and the "
                f"boundary: {evidence}"
            ),
        )

        summary.append(
            {
                "protocol": case["protocol"],
                "providerTest": "passed",
                **evidence,
            }
        )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeFailure as exc:
        report: dict[str, Any] = {
            "ok": False,
            "step": exc.step,
            "category": exc.category,
        }
        if exc.status is not None:
            report["status"] = exc.status
            report["responseBodyRedacted"] = True
        print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print(
            json.dumps(
                {"ok": False, "step": "runtime", "category": "probe_failed"},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from None
