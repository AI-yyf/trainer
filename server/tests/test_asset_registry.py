import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import AssetLink, AssetRevision, LibraryAsset, LocalOwner
from app.db.repository import TrainerRepository


def _repository_with_owner(tmp_path: Path) -> tuple[TrainerRepository, LocalOwner]:
    repository = TrainerRepository(tmp_path / "asset-registry.db")
    owner = LocalOwner(id="owner-local", display_name="Local Trainer")
    repository.save_local_owner(owner)
    return repository, owner


def _asset(owner_id: str, *, asset_id: str = "asset-url") -> LibraryAsset:
    return LibraryAsset(
        id=asset_id,
        owner_id=owner_id,
        asset_type="external_source",
        scope="library",
        title="Reference page",
        canonical_source="https://example.test/reference",
    )


def test_asset_registry_keeps_assets_and_revisions_owner_scoped(tmp_path: Path) -> None:
    repository, owner = _repository_with_owner(tmp_path)
    other_owner = LocalOwner(id="owner-other", display_name="Other Trainer")
    repository.save_local_owner(other_owner)
    asset = _asset(owner.id)
    repository.save_library_asset(asset)

    first = AssetRevision(
        id="revision-1",
        owner_id=owner.id,
        asset_id=asset.id,
        content_hash="sha256:first",
        storage_path="snapshots/asset-url/revision-1/page.html",
        media_type="text/html",
        source_url=asset.canonical_source,
    )
    repository.save_asset_revision(first)
    repository.save_asset_revision(first)
    second = AssetRevision(
        id="revision-2",
        owner_id=owner.id,
        asset_id=asset.id,
        parent_revision_id=first.id,
        content_hash="sha256:second",
        storage_path="snapshots/asset-url/revision-2/page.html",
        media_type="text/html",
        source_url=asset.canonical_source,
    )
    repository.save_asset_revision(second)
    repository.save_asset_revision(first)

    stored = repository.get_library_asset(owner.id, asset.id)
    assert stored is not None
    assert stored.current_revision_id == second.id
    repository.save_library_asset(asset.model_copy(update={"title": "Renamed reference page"}))
    stored_after_metadata_update = repository.get_library_asset(owner.id, asset.id)
    assert stored_after_metadata_update is not None
    assert stored_after_metadata_update.current_revision_id == second.id
    assert [item.id for item in repository.list_asset_revisions(owner.id, asset.id)] == [
        second.id,
        first.id,
    ]
    with pytest.raises(ValueError, match="descendants"):
        repository.delete_asset_revision(owner.id, asset.id, first.id)
    with pytest.raises(ValueError, match="cannot be modified"):
        repository.save_asset_revision(first.model_copy(update={"content_hash": "sha256:changed"}))
    assert repository.delete_asset_revision(owner.id, asset.id, second.id)
    restored_current = repository.get_library_asset(owner.id, asset.id)
    assert restored_current is not None
    assert restored_current.current_revision_id == first.id
    assert repository.get_library_asset(other_owner.id, asset.id) is None
    assert repository.get_asset_revision(other_owner.id, asset.id, first.id) is None
    with pytest.raises(PermissionError):
        repository.save_library_asset(asset.model_copy(update={"owner_id": other_owner.id}))
    with pytest.raises(PermissionError):
        repository.save_asset_revision(second.model_copy(update={"owner_id": other_owner.id}))


def test_asset_links_are_idempotent_and_owner_isolated(tmp_path: Path) -> None:
    repository, owner = _repository_with_owner(tmp_path)
    other_owner = LocalOwner(id="owner-other", display_name="Other Trainer")
    repository.save_local_owner(other_owner)
    asset = _asset(owner.id, asset_id="asset-plan")
    repository.save_library_asset(asset)

    link = AssetLink(
        id="link-plan-alpha",
        owner_id=owner.id,
        asset_id=asset.id,
        workspace_id="workspace-alpha",
        relation="available_to",
        source_ref="plan:plan-alpha",
        payload={"pinned": False},
    )
    repository.save_asset_link(link)
    repository.save_asset_link(
        link.model_copy(update={"id": "link-plan-alpha-updated", "payload": {"pinned": True}})
    )

    links = repository.list_asset_links(owner.id, workspace_id="workspace-alpha")
    assert len(links) == 1
    assert links[0].id == "link-plan-alpha"
    assert links[0].payload == {"pinned": True}
    assert repository.list_asset_links(other_owner.id, workspace_id="workspace-alpha") == []
    with pytest.raises(PermissionError):
        repository.save_asset_link(link.model_copy(update={"owner_id": other_owner.id}))
    assert repository.delete_asset_link(
        owner.id,
        asset.id,
        "workspace-alpha",
        "available_to",
        source_ref="plan:plan-alpha",
    )
    assert not repository.delete_asset_link(
        owner.id,
        asset.id,
        "workspace-alpha",
        "available_to",
        source_ref="plan:plan-alpha",
    )


def test_asset_deletion_cascades_links_and_revisions(tmp_path: Path) -> None:
    repository, owner = _repository_with_owner(tmp_path)
    asset = _asset(owner.id, asset_id="asset-memory")
    repository.save_library_asset(asset)
    repository.save_asset_revision(
        AssetRevision(
            id="revision-memory",
            owner_id=owner.id,
            asset_id=asset.id,
            content_hash="sha256:memory",
            payload={"summary": "Durable reflection"},
        )
    )
    repository.save_asset_link(
        AssetLink(
            id="link-memory",
            owner_id=owner.id,
            asset_id=asset.id,
            workspace_id="workspace-alpha",
            relation="references",
        )
    )

    assert repository.delete_library_asset(owner.id, asset.id)
    assert repository.get_library_asset(owner.id, asset.id) is None
    assert repository.list_asset_revisions(owner.id, asset.id) == []
    assert repository.list_asset_links(owner.id, asset_id=asset.id) == []
