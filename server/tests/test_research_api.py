from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.network_fetch import ControlledFetchResponse


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Research Test",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-research-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
    )
    return TestClient(create_app(settings))


class TestResearchAPI:
    def test_create_project(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            response = client.post(
                "/research/create",
                json={"title": "Climate Study", "description": "Multi-theme climate research"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["project"]["title"] == "Climate Study"
            assert "created successfully" in data["message"]

    def test_list_projects(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            client.post("/research/create", json={"title": "A", "description": "Test"})
            client.post("/research/create", json={"title": "B", "description": "Test"})
            response = client.get("/research/projects")
            assert response.status_code == 200
            assert len(response.json()) == 2

    def test_get_project_state(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            create_resp = client.post(
                "/research/create",
                json={"title": "Test", "description": "Test"},
            )
            project_id = create_resp.json()["project"]["id"]
            response = client.get(f"/research/{project_id}")
            assert response.status_code == 200
            data = response.json()
            assert "project" in data
            assert "schedule_status" in data

    def test_delete_project(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            create_resp = client.post(
                "/research/create",
                json={"title": "Test", "description": "Test"},
            )
            project_id = create_resp.json()["project"]["id"]
            delete_resp = client.delete(f"/research/{project_id}")
            assert delete_resp.status_code == 200
            get_resp = client.get(f"/research/{project_id}")
            assert get_resp.status_code == 404

    def test_add_theme(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            project_id = self._create_project(client)
            response = client.post(
                f"/research/{project_id}/theme",
                json={
                    "title": "Historical Trends",
                    "description": "50-year analysis",
                    "duration_weeks": 4,
                    "cadence": "weekly",
                },
            )
            assert response.status_code == 200
            theme = response.json()["theme"]
            assert theme["title"] == "Historical Trends"
            assert len(theme["schedule"]["checkpoints"]) == 4

    def test_add_theme_custom_duration(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            project_id = self._create_project(client)
            response = client.post(
                f"/research/{project_id}/theme",
                json={
                    "title": "Short Sprint",
                    "description": "1-week sprint",
                    "duration_weeks": 1,
                    "cadence": "daily",
                },
            )
            assert response.status_code == 200
            theme = response.json()["theme"]
            assert len(theme["schedule"]["checkpoints"]) == 7

    def test_activate_theme(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            project_id, theme_id = self._create_project_with_theme(client)
            response = client.post(f"/research/{project_id}/theme/{theme_id}/activate")
            assert response.status_code == 200
            assert response.json()["theme"]["status"] == "active"

    def test_pause_theme(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            project_id, theme_id = self._create_project_with_theme(client)
            client.post(f"/research/{project_id}/theme/{theme_id}/activate")
            response = client.post(f"/research/{project_id}/theme/{theme_id}/pause")
            assert response.status_code == 200
            assert response.json()["theme"]["status"] == "paused"

    def test_add_thread(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            project_id, theme_id = self._create_project_with_theme(client)
            response = client.post(
                f"/research/{project_id}/theme/{theme_id}/thread",
                json={"angle": "Comparative analysis", "depth": "deep"},
            )
            assert response.status_code == 200
            thread = response.json()["thread"]
            assert thread["angle"] == "Comparative analysis"
            assert thread["depth"] == "deep"

    def test_add_finding(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            project_id, theme_id = self._create_project_with_theme(client)
            thread_resp = client.post(
                f"/research/{project_id}/theme/{theme_id}/thread",
                json={"angle": "Test angle"},
            )
            thread_id = thread_resp.json()["thread"]["id"]
            response = client.post(
                f"/research/{project_id}/theme/{theme_id}/thread/{thread_id}/finding",
                json={
                    "content": "Key finding from research",
                    "source": "Primary document",
                    "confidence": 0.9,
                    "tags": ["key", "verified"],
                },
            )
            assert response.status_code == 200
            finding = response.json()["finding"]
            assert finding["content"] == "Key finding from research"
            assert finding["confidence"] == 0.9
            assert finding["created_at"]

    def test_add_artifact(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            project_id, theme_id = self._create_project_with_theme(client)
            response = client.post(
                f"/research/{project_id}/theme/{theme_id}/artifact",
                json={
                    "title": "Research Summary",
                    "kind": "summary",
                    "content": "# Summary\n\nKey findings...",
                },
            )
            assert response.status_code == 200
            artifact = response.json()["artifact"]
            assert artifact["title"] == "Research Summary"
            assert artifact["kind"] == "summary"

    def test_send_message(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            project_id = self._create_project(client)
            response = client.post(
                f"/research/{project_id}/message",
                json={"message": "What should I research first?"},
            )
            assert response.status_code == 200
            data = response.json()
            assert "response" in data
            assert "agent_state" in data

    def test_get_schedule_status(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            project_id, _ = self._create_project_with_theme(client)
            response = client.get(f"/research/{project_id}/schedule")
            assert response.status_code == 200
            data = response.json()
            assert "themes" in data

    def test_404_for_nonexistent_project(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            response = client.get("/research/nonexistent")
            assert response.status_code == 404

    def test_full_research_lifecycle(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            # Create project
            create_resp = client.post(
                "/research/create",
                json={"title": "Full Lifecycle Test", "description": "End-to-end test"},
            )
            project_id = create_resp.json()["project"]["id"]

            # Add two themes
            theme1_resp = client.post(
                f"/research/{project_id}/theme",
                json={"title": "Theme A", "description": "First", "duration_weeks": 2},
            )
            theme1_id = theme1_resp.json()["theme"]["id"]

            theme2_resp = client.post(
                f"/research/{project_id}/theme",
                json={"title": "Theme B", "description": "Second", "duration_weeks": 4},
            )
            theme2_id = theme2_resp.json()["theme"]["id"]

            # Activate both themes
            client.post(f"/research/{project_id}/theme/{theme1_id}/activate")
            client.post(f"/research/{project_id}/theme/{theme2_id}/activate")

            # Add threads
            thread_resp = client.post(
                f"/research/{project_id}/theme/{theme1_id}/thread",
                json={"angle": "Historical", "depth": "medium"},
            )
            thread_id = thread_resp.json()["thread"]["id"]

            # Add findings
            client.post(
                f"/research/{project_id}/theme/{theme1_id}/thread/{thread_id}/finding",
                json={"content": "Finding 1", "source": "Source 1"},
            )

            # Add artifact
            client.post(
                f"/research/{project_id}/theme/{theme1_id}/artifact",
                json={"title": "Notes", "kind": "note", "content": "Research notes"},
            )

            # Send message
            msg_resp = client.post(
                f"/research/{project_id}/message",
                json={"message": "Summarize progress so far"},
            )
            assert msg_resp.status_code == 200

            # Verify state
            state_resp = client.get(f"/research/{project_id}")
            assert state_resp.status_code == 200
            state = state_resp.json()
            assert len(state["project"]["themes"]) == 2
            assert state["project"]["active_themes_count"] == 2

    @patch("app.ingest.service.fetch_url")
    def test_resource_index_logs_background_research_reference(self, mock_fetch_url, tmp_path: Path) -> None:
        mock_fetch_url.return_value = ControlledFetchResponse(
            body=b"<html><body><article><p>Grounded external trainer note.</p></article></body></html>",
            final_url="https://example.com/trainer-note",
            status=200,
            headers={"content-type": "text/html"},
            fetched_at="2026-07-12T00:00:00+00:00",
        )

        settings = AppSettings(
            app_name="Trainer Research Test",
            host="127.0.0.1",
            port=8765,
            data_dir=tmp_path,
            database_name="trainer-research-test.db",
            default_session_stage="intake",
            summary_message_limit=6,
            enable_network_fetch=True,
        )
        with TestClient(create_app(settings)) as client:
            start_response = client.post(
                "/session/start",
                json={
                    "workspace_id": "workspace-research-log",
                    "workspace_name": "trainer-research-log",
                },
            )
            session_id = start_response.json()["session_id"]
            upload = client.post(
                "/resource/upload",
                json={
                    "session_id": session_id,
                    "kind": "url",
                    "name": "External Note",
                    "source": "https://example.com/trainer-note",
                },
            ).json()
            index_response = client.post(
                "/resource/index",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-research-log",
                    "resource_id": upload["id"],
                    "enable_network": True,
                },
            )
            assert index_response.status_code == 200

            background_project = client.get("/research/workspace:workspace-research-log")
            assert background_project.status_code == 200
            payload = background_project.json()
            assert payload["project"]["themes"]
            assert payload["project"]["themes"][0]["threads"][0]["findings_count"] >= 1

    def test_research_stream_emits_bounded_chunks_and_complete(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            project_id = self._create_project(client)
            response = client.post(
                f"/research/{project_id}/message/stream",
                json={"message": "/status"},
            )

        assert response.status_code == 200
        blocks = [block for block in response.text.split("\n\n") if block.strip()]
        chunk_blocks = [block for block in blocks if not block.startswith("event:")]
        assert chunk_blocks
        assert all(len(block) < 600 for block in chunk_blocks)
        assert "event: complete" in response.text

    def _create_project(self, client: TestClient) -> str:
        response = client.post(
            "/research/create",
            json={"title": "Test Project", "description": "Test"},
        )
        return response.json()["project"]["id"]

    def _create_project_with_theme(self, client: TestClient) -> tuple[str, str]:
        project_id = self._create_project(client)
        theme_resp = client.post(
            f"/research/{project_id}/theme",
            json={"title": "Test Theme", "description": "Test", "duration_weeks": 2},
        )
        theme_id = theme_resp.json()["theme"]["id"]
        return project_id, theme_id
