"""The browser capture lane: pairing codes, Bearer credentials, draft queue.

Covers ``POST /browser/pair-code``, ``POST /browser/pair``, ``DELETE
/browser/pair``, ``GET /browser/status`` and the pending coach-draft queue
(``POST /browser/coach-draft``, ``GET /browser/pending-drafts``, ``POST
/browser/pending-drafts/ack``). Network fetching is not involved here.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.browser_bridge import BrowserBridgeService, build_coach_draft_text
from app.core.models import LearningPlan, PlanStage
from app.core.settings import AppSettings
from app.main import create_app


def build_client(tmp_path: Path, *, enable_network_fetch: bool = False) -> TestClient:
    settings = AppSettings(
        app_name="Trainer browser bridge",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-browser-bridge.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=enable_network_fetch,
    )
    return TestClient(create_app(settings))


def _start_session(client: TestClient, workspace_id: str, workspace_name: str = "Bridge WS") -> str:
    started = client.post(
        "/session/start",
        json={"workspace_id": workspace_id, "workspace_name": workspace_name},
    )
    assert started.status_code == 200, started.text
    return started.json()["session_id"]


def _pair(client: TestClient, workspace_id: str, code: str = "135790") -> str:
    session_id = _start_session(client, workspace_id)
    registered = client.post(
        "/browser/pair-code",
        json={
            "code": code,
            "expires_in": 600,
            "session_id": session_id,
            "workspace_id": workspace_id,
        },
    )
    assert registered.status_code == 200, registered.text
    paired = client.post("/browser/pair", json={"code": code})
    assert paired.status_code == 200, paired.text
    return str(paired.json()["credential"])


def test_pair_code_registration_reports_the_workspace_binding(tmp_path) -> None:
    with build_client(tmp_path) as client:
        session_id = _start_session(client, "workspace-bridge-bind", "Bridge bind")
        response = client.post(
            "/browser/pair-code",
            json={
                "code": "012345",
                "expires_in": 300,
                "session_id": session_id,
                "workspace_id": "workspace-bridge-bind",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == "012345"
    assert payload["workspace_id"] == "workspace-bridge-bind"
    assert payload["workspace_name"] == "Bridge bind"
    assert payload["expires_in"] == 300
    assert payload["expires_at"] > 0


def test_pair_code_registration_rejects_non_six_digit_codes(tmp_path) -> None:
    with build_client(tmp_path) as client:
        session_id = _start_session(client, "workspace-bridge-shape")
        for code in ("12345", "1234567", "abcdef", ""):
            response = client.post(
                "/browser/pair-code",
                json={"code": code, "expires_in": 300, "session_id": session_id},
            )
            assert response.status_code == 422, (code, response.text)
            assert response.json()["detail"]["code"] == "invalid_pair_code"


def test_pair_exchange_issues_a_working_credential_once(tmp_path) -> None:
    with build_client(tmp_path) as client:
        token = _pair(client, "workspace-bridge-exchange")
        assert token.startswith("trcb_") and len(token) > 20

        status = client.get("/browser/status", headers={"Authorization": f"Bearer {token}"})
        assert status.status_code == 200, status.text
        assert status.json()["workspace_id"] == "workspace-bridge-exchange"

        # Single use: the code cannot mint a second credential.
        repeated = client.post("/browser/pair", json={"code": "135790"})
        assert repeated.status_code == 404, repeated.text
        assert repeated.json()["detail"]["code"] == "unknown_pair_code"


def test_status_reports_workspace_name_focus_options_and_library_count(tmp_path) -> None:
    with build_client(tmp_path) as client:
        token = _pair(client, "workspace-bridge-status", code="246810")
        _start_session(client, "workspace-bridge-status")

        # A plan stage becomes a learning-focus option for the browser binding.
        runtime = client.app.state.runtime  # type: ignore[attr-defined]
        runtime.repository.save_plan(
            "workspace-bridge-status",
            LearningPlan(
                id="plan-bridge",
                title="Bridge plan",
                stages=[
                    PlanStage(
                        id="stage-errors",
                        title="Error handling",
                        goal="Handle failures honestly",
                        outcomes=["one retry path"],
                        status="active",
                    )
                ],
                current_stage_id="stage-errors",
            ),
        )

        status = client.get(
            "/browser/status",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert status.status_code == 200, status.text
    payload = status.json()
    assert payload["workspace_name"] == "Bridge WS"
    assert payload["library_count"] == 0
    assert payload["focus_options"] == [{"id": "stage-errors", "label": "Error handling"}]


def test_expired_pair_codes_are_refused(tmp_path) -> None:
    with build_client(tmp_path) as client:
        session_id = _start_session(client, "workspace-bridge-expired")
        registered = client.post(
            "/browser/pair-code",
            json={"code": "999999", "expires_in": 30, "session_id": session_id},
        )
        assert registered.status_code == 200, registered.text

        runtime = client.app.state.runtime  # type: ignore[attr-defined]
        bridge = runtime.browser_bridge
        assert isinstance(bridge, BrowserBridgeService)
        bridge._clock = lambda: registered.json()["expires_at"] + 1  # noqa: SLF001 - test clock

        expired = client.post("/browser/pair", json={"code": "999999"})
        assert expired.status_code == 410, expired.text
        assert expired.json()["detail"]["code"] == "expired_pair_code"


def test_credentials_are_persisted_and_revocable_across_restart(tmp_path) -> None:
    with build_client(tmp_path) as client:
        token = _pair(client, "workspace-bridge-persist", code="112233")

    # Only the hash is written; the raw token survives as a credential hash file entry.
    state = json.loads((tmp_path / "browser_bridge.json").read_text(encoding="utf-8"))
    assert token not in json.dumps(state)
    assert len(state["credentials"]) == 1

    with build_client(tmp_path) as client:
        status = client.get("/browser/status", headers={"Authorization": f"Bearer {token}"})
        assert status.status_code == 200, status.text

        revoked = client.delete("/browser/pair", headers={"Authorization": f"Bearer {token}"})
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["revoked"] is True

        after = client.get("/browser/status", headers={"Authorization": f"Bearer {token}"})
        assert after.status_code == 401

    # The revocation is durable.
    with build_client(tmp_path) as client:
        after_restart = client.get(
            "/browser/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert after_restart.status_code == 401


def test_host_revocation_without_bearer_retires_the_registration(tmp_path) -> None:
    with build_client(tmp_path) as client:
        token = _pair(client, "workspace-bridge-host-revoke", code="445566")
        response = client.delete("/browser/pair")
        assert response.status_code == 200, response.text
        assert response.json()["revoked"] is True
        assert response.json()["had_registration"] is True

        after = client.get("/browser/status", headers={"Authorization": f"Bearer {token}"})
        assert after.status_code == 401


def test_invalid_credentials_are_refused_without_falling_back(tmp_path) -> None:
    with build_client(tmp_path) as client:
        _start_session(client, "workspace-bridge-auth")
        for header in ("", "Bearer ", "Basic abc", "Bearer not-a-credential"):
            response = client.get(
                "/browser/status",
                headers={"Authorization": header} if header else {},
            )
            assert response.status_code == 401, (header, response.text)


def test_coach_drafts_queue_dedupe_and_ack(tmp_path) -> None:
    with build_client(tmp_path) as client:
        token = _pair(client, "workspace-bridge-drafts", code="778899")
        headers = {"Authorization": f"Bearer {token}"}
        first = client.post(
            "/browser/coach-draft",
            json={
                "selection": "The rotation guard runs before the retry queue drains.",
                "url": "https://docs.example.com/rotation",
                "title": "Rotation notes",
                "client_id": "draft-client-1",
            },
            headers=headers,
        )
        assert first.status_code == 200, first.text
        assert first.json()["ok"] is True
        assert first.json()["duplicate"] is False
        assert first.json()["workspace_id"] == "workspace-bridge-drafts"
        draft_id = first.json()["draft_id"]

        repeated = client.post(
            "/browser/coach-draft",
            json={
                "selection": "The rotation guard runs before the retry queue drains.",
                "url": "https://docs.example.com/rotation",
                "title": "Rotation notes",
                "client_id": "draft-client-1",
            },
            headers=headers,
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["duplicate"] is True
        assert repeated.json()["draft_id"] == draft_id

        # The host polls and acks on the trusted loopback boundary (no Bearer):
        # it cannot read the browser credential.
        pending = client.get(
            "/browser/pending-drafts",
            params={"workspace_id": "workspace-bridge-drafts"},
        )
        assert pending.status_code == 200, pending.text
        assert pending.json()["workspace_id"] == "workspace-bridge-drafts"
        drafts = pending.json()["drafts"]
        assert [draft["id"] for draft in drafts] == [draft_id]
        assert drafts[0]["workspace_id"] == "workspace-bridge-drafts"
        text = drafts[0]["text"]
        # The draft quotes the selection and cites title + URL, and stays editable text.
        assert "rotation guard" in text
        assert "Rotation notes" in text
        assert "https://docs.example.com/rotation" in text

        acked = client.post(
            "/browser/pending-drafts/ack",
            json={"ids": [draft_id], "workspace_id": "workspace-bridge-drafts"},
        )
        assert acked.status_code == 200, acked.text
        assert acked.json()["removed"] == 1
        assert (
            client.get(
                "/browser/pending-drafts",
                params={"workspace_id": "workspace-bridge-drafts"},
            ).json()["drafts"]
            == []
        )

        # An acked client id does not come back as a fresh duplicate.
        replayed = client.post(
            "/browser/coach-draft",
            json={"selection": "something else", "client_id": "draft-client-1"},
            headers=headers,
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["duplicate"] is True


def test_pending_drafts_are_scoped_to_the_polling_workspace(tmp_path) -> None:
    """A capture from project A must never surface in project B's coach."""

    with build_client(tmp_path) as client:
        token_a = _pair(client, "workspace-bridge-a", code="111111")
        token_b = _pair(client, "workspace-bridge-b", code="222222")

        created_a = client.post(
            "/browser/coach-draft",
            json={"selection": "captured in project A", "client_id": "a-1"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert created_a.status_code == 200, created_a.text
        created_b = client.post(
            "/browser/coach-draft",
            json={"selection": "captured in project B", "client_id": "b-1"},
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert created_b.status_code == 200, created_b.text
        draft_a = created_a.json()["draft_id"]
        draft_b = created_b.json()["draft_id"]

        only_a = client.get("/browser/pending-drafts", params={"workspace_id": "workspace-bridge-a"})
        only_b = client.get("/browser/pending-drafts", params={"workspace_id": "workspace-bridge-b"})
        assert [draft["id"] for draft in only_a.json()["drafts"]] == [draft_a]
        assert [draft["id"] for draft in only_b.json()["drafts"]] == [draft_b]
        # The draft text itself never crosses the workspace boundary.
        assert "captured in project A" in only_a.json()["drafts"][0]["text"]
        assert draft_b not in [draft["id"] for draft in only_a.json()["drafts"]]

        # Acking A's queue leaves B untouched, and B's id cannot be acked
        # through A's scope even when presented explicitly.
        acked = client.post(
            "/browser/pending-drafts/ack",
            json={"ids": [draft_a, draft_b], "workspace_id": "workspace-bridge-a"},
        )
        assert acked.status_code == 200, acked.text
        assert acked.json()["removed"] == 1
        assert client.get("/browser/pending-drafts", params={"workspace_id": "workspace-bridge-a"}).json()[
            "drafts"
        ] == []
        remaining_b = client.get(
            "/browser/pending-drafts",
            params={"workspace_id": "workspace-bridge-b"},
        ).json()["drafts"]
        assert [draft["id"] for draft in remaining_b] == [draft_b]


def test_pending_drafts_refuse_an_unscoped_host_call(tmp_path) -> None:
    """Without a workspace reference the sidecar refuses instead of guessing."""

    with build_client(tmp_path) as client:
        _pair(client, "workspace-bridge-scope", code="333333")

        unscoped = client.get("/browser/pending-drafts")
        assert unscoped.status_code == 422, unscoped.text
        assert unscoped.json()["detail"]["code"] == "workspace_required"

        unscoped_ack = client.post("/browser/pending-drafts/ack", json={"ids": ["draft-unknown"]})
        assert unscoped_ack.status_code == 422, unscoped_ack.text
        assert unscoped_ack.json()["detail"]["code"] == "workspace_required"


def test_a_full_draft_queue_refuses_new_captures_loudly(tmp_path, monkeypatch) -> None:
    """Capacity refuses the new capture; queued drafts are never silently evicted."""

    monkeypatch.setattr("app.browser_bridge.service._MAX_PENDING_DRAFTS", 2)
    with build_client(tmp_path) as client:
        token = _pair(client, "workspace-bridge-full", code="444444")
        headers = {"Authorization": f"Bearer {token}"}
        for index in (1, 2):
            created = client.post(
                "/browser/coach-draft",
                json={"selection": f"capture {index}", "client_id": f"full-{index}"},
                headers=headers,
            )
            assert created.status_code == 200, created.text

        overflow = client.post(
            "/browser/coach-draft",
            json={"selection": "one capture too many", "client_id": "full-3"},
            headers=headers,
        )
        assert overflow.status_code == 429, overflow.text
        assert overflow.json()["detail"]["code"] == "draft_queue_full"

        # Both earlier captures are still queued and deliverable.
        drafts = client.get(
            "/browser/pending-drafts",
            params={"workspace_id": "workspace-bridge-full"},
        ).json()["drafts"]
        queued_excerpts = [
            next(line for line in draft["text"].splitlines() if line.startswith("> capture"))
            for draft in drafts
        ]
        assert queued_excerpts == ["> capture 1", "> capture 2"]


def test_coach_drafts_require_a_selection_and_a_credential(tmp_path) -> None:
    with build_client(tmp_path) as client:
        token = _pair(client, "workspace-bridge-draft-guard", code="101010")
        headers = {"Authorization": f"Bearer {token}"}
        empty = client.post("/browser/coach-draft", json={"selection": "  "}, headers=headers)
        assert empty.status_code == 422, empty.text
        assert empty.json()["detail"]["code"] == "empty_selection"

        anonymous = client.post("/browser/coach-draft", json={"selection": "hi"})
        assert anonymous.status_code == 401


def test_coach_draft_text_follows_the_workspace_language(tmp_path) -> None:
    chinese = build_coach_draft_text(
        selection="\u8bf7\u89e3\u91ca\u8fd9\u6bb5",
        url="https://docs.example.com/a",
        title="\u7b14\u8bb0",
        language="zh-CN",
    )
    assert chinese.startswith("\u8bf7\u5e2e\u6211\u7406\u89e3\u8fd9\u6bb5\u5185\u5bb9")
    assert "> \u8bf7\u89e3\u91ca\u8fd9\u6bb5" in chinese

    english = build_coach_draft_text(
        selection="Explain this",
        url="https://docs.example.com/a",
        title="Notes",
        language="en-US",
    )
    assert english.startswith("Help me understand this excerpt")


def test_coach_draft_text_covers_all_eight_supported_languages() -> None:
    """A Spanish/Japanese/... workspace gets a natural draft, not English."""

    expected_openers = {
        "zh-CN": "\u8bf7\u5e2e\u6211\u7406\u89e3\u8fd9\u6bb5\u5185\u5bb9",
        "en-US": "Help me understand this excerpt",
        "es-ES": "Ayudame a entender este fragmento",
        "fr-FR": "Aide-moi a comprendre cet extrait",
        "de-DE": "Hilf mir, diesen Ausschnitt zu verstehen",
        "ja-JP": "\u3053\u306e\u629c\u7c8b\u3092\u7406\u89e3\u3057\u305f\u3044\u3067\u3059",
        "ko-KR": "\uc774 \ubc1c\ucdcc\ub97c \uc774\ud574\ud558\uace0 \uc2f6\uc5b4\uc694",
        "pt-BR": "Ajude-me a entender este trecho",
    }
    for language, opener in expected_openers.items():
        text = build_coach_draft_text(
            selection="Retry queues drain after the guard run.",
            url="https://docs.example.com/rotation",
            title="Rotation notes",
            language=language,
        )
        assert text.startswith(opener), (language, text)
        # The excerpt, the title and the URL survive in every language.
        assert "> Retry queues drain after the guard run." in text
        assert "Rotation notes" in text
        assert "https://docs.example.com/rotation" in text

    # A bare base tag still resolves; an unknown language falls back to English.
    assert build_coach_draft_text(selection="x", title="T", language="es").startswith("Ayudame")
    assert build_coach_draft_text(selection="x", title="T", language="xx-YY").startswith("Help me")


def test_coach_draft_route_uses_the_workspace_response_language(tmp_path) -> None:
    with build_client(tmp_path) as client:
        token = _pair(client, "workspace-bridge-draft-language", code="202020")
        headers = {"Authorization": f"Bearer {token}"}
        runtime = client.app.state.runtime  # type: ignore[attr-defined]
        runtime.memory_service.update_workspace_state(
            "workspace-bridge-draft-language",
            response_language="es-ES",
        )

        created = client.post(
            "/browser/coach-draft",
            json={"selection": "Reset the guard.", "url": "https://docs.example.com/es", "client_id": "es-1"},
            headers=headers,
        )
        assert created.status_code == 200, created.text

        drafts = client.get(
            "/browser/pending-drafts",
            params={"workspace_id": "workspace-bridge-draft-language"},
        ).json()["drafts"]
        assert len(drafts) == 1
        assert drafts[0]["text"].startswith("Ayudame a entender este fragmento")


def test_browser_lane_paths_are_not_blocked_by_the_instance_token(tmp_path, monkeypatch) -> None:
    """The browser extension cannot read TRAINER_SIDECAR_TOKEN: its lane is exempt."""

    monkeypatch.setenv("TRAINER_SIDECAR_TOKEN", "instance-secret")
    with build_client(tmp_path) as client:
        blocked = client.post(
            "/session/start",
            json={"workspace_id": "ws", "workspace_name": "Blocked"},
        )
        assert blocked.status_code == 401

        session_id = client.post(
            "/session/start",
            json={"workspace_id": "workspace-bridge-token", "workspace_name": "Token lane"},
            headers={"x-trainer-token": "instance-secret"},
        ).json()["session_id"]
        registered = client.post(
            "/browser/pair-code",
            json={"code": "654123", "expires_in": 600, "session_id": session_id},
            headers={"x-trainer-token": "instance-secret"},
        )
        assert registered.status_code == 200, registered.text
        # pair-code itself stays inside the instance-token boundary...
        assert (
            client.post("/browser/pair-code", json={"code": "654123", "expires_in": 600})
            .status_code
            == 401
        )

        paired = client.post("/browser/pair", json={"code": "654123"})
        assert paired.status_code == 200, paired.text
        token = paired.json()["credential"]
        assert (
            client.get("/browser/status", headers={"Authorization": f"Bearer {token}"}).status_code
            == 200
        )

        # ...while the host-facing pending-draft queue stays inside the boundary:
        # the host can present the instance token, the browser lane cannot.
        queue_path = "/browser/pending-drafts"
        blocked_queue = client.get(queue_path, params={"workspace_id": "workspace-bridge-token"})
        assert blocked_queue.status_code == 401, blocked_queue.text
        allowed_queue = client.get(
            queue_path,
            params={"workspace_id": "workspace-bridge-token"},
            headers={"x-trainer-token": "instance-secret"},
        )
        assert allowed_queue.status_code == 200, allowed_queue.text
        assert allowed_queue.json()["drafts"] == []
