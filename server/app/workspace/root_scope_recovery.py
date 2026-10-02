"""Recover registrations stranded by older unscoped project-adoption launches."""

from __future__ import annotations

import json
import logging
import re
import sqlite3

from ..core.models import ProjectContext, TrainerProject, TrainerRoot, UserProfile
from ..db.repository import TrainerRepository

logger = logging.getLogger(__name__)
_ROOT_ID = re.compile(r"root-[a-zA-Z0-9-]{1,96}\Z")
_IDENTITY_FIELDS = (
    "workspace_id", "context_id", "root_id", "root_path", "project_id", "project_path",
    "canonical_project_path", "project_name", "project_memory", "project_training_state",
    "project_agent_context", "project_provisioning",
)


def recover_legacy_root_registrations(repository: TrainerRepository) -> int:
    """Import only this root's missing registrations; preserve newer scoped learning data.

    The source is the sibling legacy database in the extension's default storage.
    Custom data directories and unrelated roots never participate in this repair.
    """
    target = repository.database_path.resolve()
    if target.parent.parent.name != "roots" or not _ROOT_ID.fullmatch(target.parent.name):
        return 0
    source = target.parent.parent.parent / target.name
    if not source.is_file():
        return 0
    recovered = 0
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as legacy:
        legacy.row_factory = sqlite3.Row
        root_row = legacy.execute(
            "SELECT payload FROM trainer_roots WHERE root_id = ?", (target.parent.name,)
        ).fetchone()
        if root_row is None:
            return 0
        root = TrainerRoot.model_validate_json(root_row["payload"])
        current_root = repository.get_trainer_root(root.root_id)
        if current_root is not None and current_root.root_path != root.root_path:
            logger.warning("Legacy Trainer root location conflicts with scoped data; repair skipped.")
            return 0
        if current_root is None:
            registered_root = repository.register_trainer_root(root)
            if registered_root.root_id != root.root_id:
                logger.warning("Another Trainer root owns the legacy location; repair skipped.")
                return 0
        rows = legacy.execute(
            "SELECT payload FROM project_contexts WHERE root_id = ?", (root.root_id,)
        ).fetchall()
        for row in rows:
            context = ProjectContext.model_validate_json(row["payload"])
            if repository.get_project_context(context.context_id) is not None:
                continue
            project_row = legacy.execute(
                "SELECT payload FROM trainer_projects WHERE project_id = ? AND root_id = ?",
                (context.project_id, root.root_id),
            ).fetchone()
            profile_row = legacy.execute(
                "SELECT payload FROM user_profile WHERE workspace_id = ?", (context.context_id,)
            ).fetchone()
            memory_row = legacy.execute(
                "SELECT payload FROM structured_memory WHERE workspace_id = ?", (context.context_id,)
            ).fetchone()
            session_row = legacy.execute(
                "SELECT payload FROM sessions WHERE session_id = ? AND workspace_id = ?",
                (context.agent_session_id, context.context_id),
            ).fetchone()
            if any(item is None for item in (project_row, profile_row, memory_row, session_row)):
                logger.warning("Legacy Trainer project registration is incomplete; repair skipped.")
                continue
            project = TrainerProject.model_validate_json(project_row["payload"])
            legacy_memory = json.loads(memory_row["payload"])
            memory = repository.load_structured_memory(context.context_id) or legacy_memory
            workspace = dict(memory.get("workspace") or {})
            old_workspace = legacy_memory.get("workspace") or {}
            conflicting_identity = any(
                key in workspace and key in old_workspace and workspace[key] != old_workspace[key]
                for key in ("context_id", "root_id", "project_id", "project_memory",
                            "project_agent_context", "project_provisioning")
            )
            if conflicting_identity:
                logger.warning("Scoped Trainer project identity conflicts with legacy data; repair skipped.")
                continue
            for key in _IDENTITY_FIELDS:
                if key not in workspace and key in old_workspace:
                    workspace[key] = old_workspace[key]
            memory = {**memory, "workspace": workspace}
            profile = repository.get_profile(context.context_id) or UserProfile.model_validate_json(
                profile_row["payload"]
            )
            session = repository.load_session(context.agent_session_id) or json.loads(session_row["payload"])
            try:
                repository.create_project_context_bundle(
                    root=root, project=project, context=context, profile=profile, plan=None,
                    structured_memory=memory, session_payload=session,
                )
            except (ValueError, RuntimeError):
                logger.warning("Legacy Trainer project registration conflicts with scoped data; repair skipped.")
                continue
            recovered += 1
    if recovered:
        logger.info("Recovered %d root-scoped Trainer project registrations.", recovered)
    return recovered
