"""Phase 2 browser bridge tests: pre-seeded single-use handshake & SSE event push."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app


def _make_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer Browser Phase 2 Test",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-browser-phase2.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def test_preseeded_bootstrap_token_pairs_once_and_promotes_extension_origin_for_auto_pair(
    tmp_path: Path,
) -> None:
    workspace_id = "ws-bootstrap-zero-code"
    extension_origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    bootstrap_secret = "trbp-0123456789abcdef0123456789abcdef"

    with TestClient(create_app(_make_settings(tmp_path))) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Zero Code Demo"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]

        registered = client.post(
            "/browser/pair-code",
            json={
                "code": bootstrap_secret,
                "expires_in": 600,
                "session_id": session_id,
                "workspace_id": workspace_id,
            },
        )
        assert registered.status_code == 200, registered.text

        paired = client.post(
            "/browser/pair",
            headers={"Origin": extension_origin},
            json={"code": bootstrap_secret},
        )
        assert paired.status_code == 200, paired.text
        body = paired.json()
        assert body["credential"]
        assert body["workspace_id"] == workspace_id
        assert body["workspace_name"] == "Zero Code Demo"

        # Single-use guarantee: replaying the same bootstrap secret fails with 404.
        replay = client.post(
            "/browser/pair",
            headers={"Origin": extension_origin},
            json={"code": bootstrap_secret},
        )
        assert replay.status_code == 404, replay.text

        # Trusted origin promotion: future reconnects from this extension ID succeed with zero code.
        auto_paired = client.post(
            "/browser/auto-pair",
            headers={"Origin": extension_origin},
            json={"workspace_id": workspace_id},
        )
        assert auto_paired.status_code == 200, auto_paired.text
        assert auto_paired.json()["credential"]
        assert auto_paired.json()["workspace_id"] == workspace_id


# Wall-clock ceiling for the streaming assertions. The happy path finishes in
# well under a second; the budget only turns a lost event or a failed producer
# task into a readable failure instead of an endless keep-alive wait.
_STREAM_BUDGET_SECONDS = 60.0


def test_browser_events_stream_enforces_instance_token_and_pushes_realtime_draft_and_library_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = "ws-sse-push"
    host_token = "host-loopback-token-phase2"
    host_headers = {"x-trainer-token": host_token}
    monkeypatch.setenv("TRAINER_SIDECAR_TOKEN", host_token)

    app = create_app(_make_settings(tmp_path))

    async def _exercise() -> None:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 51234))
        # The transport is in-process, so client-side network timeouts do not
        # apply; disable them explicitly so the only deadline here is
        # _STREAM_BUDGET_SECONDS.
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8765",
            timeout=None,
        ) as client:
            unauth = await client.get(
                "/browser/events/stream",
                params={"workspace_id": workspace_id, "once": "true"},
            )
            assert unauth.status_code == 401, unauth.text

            started = await client.post(
                "/session/start",
                headers=host_headers,
                json={"workspace_id": workspace_id, "workspace_name": "SSE Push Demo"},
            )
            assert started.status_code == 200, started.text
            session_id = started.json()["session_id"]

            reg = await client.post(
                "/browser/pair-code",
                headers=host_headers,
                json={
                    "code": "trbp-fedcba9876543210fedcba9876543210",
                    "expires_in": 600,
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                },
            )
            assert reg.status_code == 200, reg.text
            paired = await client.post(
                "/browser/pair",
                json={"code": "trbp-fedcba9876543210fedcba9876543210"},
            )
            assert paired.status_code == 200, paired.text
            browser_cred = paired.json()["credential"]
            browser_headers = {"Authorization": f"Bearer {browser_cred}"}

            once_resp = await client.get(
                "/browser/events/stream",
                headers=host_headers,
                params={"workspace_id": workspace_id, "once": "true"},
            )
            assert once_resp.status_code == 200, once_resp.text
            assert "event: snapshot" in once_resp.text
            snapshot_line = [
                line[len("data: ") :]
                for line in once_resp.text.splitlines()
                if line.startswith("data: ")
            ][0]
            snapshot_data = json.loads(snapshot_line)
            assert snapshot_data["workspace_id"] == workspace_id
            assert snapshot_data["paired_credentials"] == 1
            assert snapshot_data["drafts"] == []

            async def _emit_mutations() -> None:
                await asyncio.sleep(0.05)
                # Foreign workspace mutation must NOT leak into workspace_id's SSE stream
                app.state.runtime.browser_bridge.notify_library_changed("ws-other")
                draft_resp = await client.post(
                    "/browser/coach-draft",
                    headers=browser_headers,
                    json={
                        "url": "https://example.com/guide",
                        "title": "Guide",
                        "selection": "invariant check",
                        "question": "Help me test this invariant",
                    },
                )
                assert draft_resp.status_code == 200, draft_resp.text
                app.state.runtime.browser_bridge.notify_library_changed(workspace_id)

            producer = asyncio.create_task(_emit_mutations())
            async with client.stream(
                "GET",
                "/browser/events/stream",
                headers=host_headers,
                params={"workspace_id": workspace_id, "max_events": 2, "heartbeat_seconds": 5.0},
            ) as stream_resp:
                assert stream_resp.status_code == 200
                # The stream closes only after max_events matching events arrive;
                # until then the server just emits keep-alives. A lost event or a
                # failed producer would therefore wait forever, so bound the read
                # and report the producer's state instead of stalling the suite.
                try:
                    raw_sse = (
                        await asyncio.wait_for(stream_resp.aread(), timeout=_STREAM_BUDGET_SECONDS)
                    ).decode("utf-8")
                except TimeoutError:
                    if not producer.done():
                        producer.cancel()
                    if producer.done() and not producer.cancelled():
                        producer_error: object = repr(producer.exception())
                    else:
                        producer_error = "cancelled or still running"
                    raise AssertionError(
                        "SSE stream did not close within "
                        f"{_STREAM_BUDGET_SECONDS:.0f}s (max_events=2); "
                        f"producer done={producer.done()} error={producer_error!r}"
                    ) from None
            await producer

            frames: list[tuple[str, dict]] = []
            current_event = "message"
            for line in raw_sse.splitlines():
                if line.startswith("event: "):
                    current_event = line[len("event: ") :].strip()
                elif line.startswith("data: "):
                    frames.append((current_event, json.loads(line[len("data: ") :])))

            assert len(frames) == 3, frames
            assert frames[0][0] == "snapshot"
            assert frames[1][0] == "workspace_event"
            assert frames[1][1]["kind"] == "draft_queued"
            assert frames[1][1]["workspace_id"] == workspace_id
            assert len(frames[1][1]["drafts"]) == 1
            assert "Help me test this invariant" in frames[1][1]["drafts"][0]["text"]

            assert frames[2][0] == "workspace_event"
            assert frames[2][1]["kind"] == "library_changed"
            assert frames[2][1]["workspace_id"] == workspace_id

    try:
        asyncio.run(asyncio.wait_for(_exercise(), timeout=_STREAM_BUDGET_SECONDS * 3))
    finally:
        app.state.runtime.resource_service.close()
