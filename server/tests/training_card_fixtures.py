"""Explicit learner confirmation for tests that exercise an active card."""

from fastapi.testclient import TestClient


def open_generated_training_card(client: TestClient, workspace_id: str, card_id: str) -> None:
    identity = {"workspace_id": workspace_id, "card_id": card_id}
    for action in ("save", "start"):
        response = client.post("/training/card/library", json={**identity, "action": action})
        assert response.status_code == 200, response.text
