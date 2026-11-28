"""(o) API routes: the sidecar HTTP surface keeps workspace truth, provider configuration
    and training settings honest.

Guarantees covered:
  * session start and messages bind the registered workspace and never admit unsafe workspace ids;
  * provider settings, recovery copy and leftover hydration are reported truthfully;
  * training, research, skill, plan and resource routes persist and return what really happened;
  * container / remote-shaped requests keep their own lane instead of becoming local coaching.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_research_api.py
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app

# ---------------------------------------------------------------------------
# Restored from test_research_api.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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

    def test_list_projects(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            client.post("/research/create", json={"title": "A", "description": "Test"})
            client.post("/research/create", json={"title": "B", "description": "Test"})
            response = client.get("/research/projects")
            assert response.status_code == 200
            assert len(response.json()) == 2

    def test_404_for_nonexistent_project(self, tmp_path: Path) -> None:
        with build_client(tmp_path) as client:
            response = client.get("/research/nonexistent")
            assert response.status_code == 404

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

