from __future__ import annotations

import logging
from collections.abc import Iterable

from .tool_handlers.organization_and_sandbox import (
    _clear_resource_organization_cancel_requested as _clear_resource_organization_cancel_requested,
)
from .tool_handlers.organization_and_sandbox import (
    _clear_resource_organization_committed as _clear_resource_organization_committed,
)
from .tool_handlers.organization_and_sandbox import (
    _clear_resource_organization_in_flight as _clear_resource_organization_in_flight,
)
from .tool_handlers.organization_and_sandbox import (
    _clear_resource_organization_pending as _clear_resource_organization_pending,
)
from .tool_handlers.organization_and_sandbox import (
    _collect_organization_resource_updates as _collect_organization_resource_updates,
)
from .tool_handlers.organization_and_sandbox import (
    _consume_resource_organization_pending as _consume_resource_organization_pending,
)
from .tool_handlers.organization_and_sandbox import (
    _flatten_sandbox_nodes as _flatten_sandbox_nodes,
)
from .tool_handlers.organization_and_sandbox import (
    _handle_delete_resource as _handle_delete_resource,
)
from .tool_handlers.organization_and_sandbox import (
    _handle_index_sandbox_file as _handle_index_sandbox_file,
)
from .tool_handlers.organization_and_sandbox import (
    _handle_inspect_current_file as _handle_inspect_current_file,
)
from .tool_handlers.organization_and_sandbox import (
    _handle_list_resources as _handle_list_resources,
)
from .tool_handlers.organization_and_sandbox import (
    _handle_list_sandbox as _handle_list_sandbox,
)
from .tool_handlers.organization_and_sandbox import (
    _handle_organize_resources as _handle_organize_resources,
)
from .tool_handlers.organization_and_sandbox import (
    _handle_read_sandbox_file as _handle_read_sandbox_file,
)
from .tool_handlers.organization_and_sandbox import (
    _handle_refresh_resource_index as _handle_refresh_resource_index,
)
from .tool_handlers.organization_and_sandbox import (
    _handle_restore_resource as _handle_restore_resource,
)
from .tool_handlers.organization_and_sandbox import (
    _handle_write_sandbox_file as _handle_write_sandbox_file,
)
from .tool_handlers.organization_and_sandbox import (
    _has_resource_organization_committed as _has_resource_organization_committed,
)
from .tool_handlers.organization_and_sandbox import (
    _has_resource_organization_in_flight as _has_resource_organization_in_flight,
)
from .tool_handlers.organization_and_sandbox import (
    _has_resource_organization_pending as _has_resource_organization_pending,
)
from .tool_handlers.organization_and_sandbox import (
    _latest_trash_relative_path as _latest_trash_relative_path,
)
from .tool_handlers.organization_and_sandbox import (
    _mark_resource_organization_cancel_requested as _mark_resource_organization_cancel_requested,
)
from .tool_handlers.organization_and_sandbox import (
    _mark_resource_organization_in_flight as _mark_resource_organization_in_flight,
)
from .tool_handlers.organization_and_sandbox import (
    _match_resource_by_sandbox_path as _match_resource_by_sandbox_path,
)
from .tool_handlers.organization_and_sandbox import (
    _normalize_sandbox_path_key as _normalize_sandbox_path_key,
)
from .tool_handlers.organization_and_sandbox import (
    _organization_operation_payload as _organization_operation_payload,
)
from .tool_handlers.organization_and_sandbox import (
    _organization_resource_path as _organization_resource_path,
)
from .tool_handlers.organization_and_sandbox import (
    _organization_undo_operations as _organization_undo_operations,
)
from .tool_handlers.organization_and_sandbox import (
    _record_resource_organization_pending as _record_resource_organization_pending,
)
from .tool_handlers.organization_and_sandbox import (
    _reindex_matching_sandbox_resource as _reindex_matching_sandbox_resource,
)
from .tool_handlers.organization_and_sandbox import (
    _resource_for_workspace as _resource_for_workspace,
)
from .tool_handlers.organization_and_sandbox import (
    _resource_organization_autonomous as _resource_organization_autonomous,
)
from .tool_handlers.organization_and_sandbox import (
    _resource_organization_cancel_requested as _resource_organization_cancel_requested,
)
from .tool_handlers.organization_and_sandbox import (
    _resource_organization_cancel_store as _resource_organization_cancel_store,
)
from .tool_handlers.organization_and_sandbox import (
    _resource_organization_committed_store as _resource_organization_committed_store,
)
from .tool_handlers.organization_and_sandbox import (
    _resource_organization_host_confirmed as _resource_organization_host_confirmed,
)
from .tool_handlers.organization_and_sandbox import (
    _resource_organization_in_flight_store as _resource_organization_in_flight_store,
)
from .tool_handlers.organization_and_sandbox import (
    _resource_organization_pending_store as _resource_organization_pending_store,
)
from .tool_handlers.organization_and_sandbox import (
    _resource_organize_allowed as _resource_organize_allowed,
)
from .tool_handlers.organization_and_sandbox import (
    _safe_sandbox_relative_path as _safe_sandbox_relative_path,
)
from .tool_handlers.organization_and_sandbox import (
    _sandbox_preview_payload as _sandbox_preview_payload,
)
from .tool_handlers.organization_and_sandbox import (
    _sandbox_resource_kind as _sandbox_resource_kind,
)
from .tool_handlers.organization_and_sandbox import (
    _sandbox_service as _sandbox_service,
)
from .tool_handlers.organization_and_sandbox import (
    _slice_text_by_lines as _slice_text_by_lines,
)
from .tool_handlers.organization_and_sandbox import (
    _stamp_resource_organization_committed as _stamp_resource_organization_committed,
)
from .tool_handlers.organization_and_sandbox import (
    _take_resource_organization_cancel_requested as _take_resource_organization_cancel_requested,
)
from .tool_handlers.organization_and_sandbox import (
    cancel_resource_organization_pending as cancel_resource_organization_pending,
)
from .tool_handlers.registry_core import (
    PROJECT_WRITE_TOOL_NAMES as PROJECT_WRITE_TOOL_NAMES,
)
from .tool_handlers.registry_core import (
    JsonSchema as JsonSchema,
)
from .tool_handlers.registry_core import (
    ToolContext as ToolContext,
)
from .tool_handlers.registry_core import (
    ToolDefinition as ToolDefinition,
)
from .tool_handlers.registry_core import (
    ToolHandler as ToolHandler,
)
from .tool_handlers.registry_core import (
    ToolRegistry as ToolRegistry,
)
from .tool_handlers.registry_core import (
    _coach_only_tools_allowed as _coach_only_tools_allowed,
)
from .tool_handlers.registry_core import (
    _coerce_arguments as _coerce_arguments,
)
from .tool_handlers.registry_core import (
    _enum as _enum,
)
from .tool_handlers.registry_core import (
    _explicit_learning_note_request_allowed as _explicit_learning_note_request_allowed,
)
from .tool_handlers.registry_core import (
    _explicit_lecture_note_save_allowed as _explicit_lecture_note_save_allowed,
)
from .tool_handlers.registry_core import (
    _explicit_training_card_request_allowed as _explicit_training_card_request_allowed,
)
from .tool_handlers.registry_core import (
    _formal_plan_mutation_allowed as _formal_plan_mutation_allowed,
)
from .tool_handlers.registry_core import (
    _leftover_training_persist_identity as _leftover_training_persist_identity,
)
from .tool_handlers.registry_core import (
    _live_formal_plan_for_task_mint as _live_formal_plan_for_task_mint,
)
from .tool_handlers.registry_core import (
    _normalize_workspace_relpath as _normalize_workspace_relpath,
)
from .tool_handlers.registry_core import (
    _persist_minted_task_on_sessions as _persist_minted_task_on_sessions,
)
from .tool_handlers.registry_core import (
    _prefers_chinese as _prefers_chinese,
)
from .tool_handlers.registry_core import (
    _resolve_workspace_root as _resolve_workspace_root,
)
from .tool_handlers.registry_core import (
    _rubric_review_allowed as _rubric_review_allowed,
)
from .tool_handlers.registry_core import (
    _safe_path_under as _safe_path_under,
)
from .tool_handlers.registry_core import (
    _snapshot_file_list as _snapshot_file_list,
)
from .tool_handlers.registry_core import (
    _snapshot_file_listed as _snapshot_file_listed,
)
from .tool_handlers.registry_core import (
    _snapshot_file_record as _snapshot_file_record,
)
from .tool_handlers.registry_core import (
    _snapshot_path_matches as _snapshot_path_matches,
)
from .tool_handlers.registry_core import (
    _string as _string,
)
from .tool_handlers.registry_core import (
    _string_array as _string_array,
)
from .tool_handlers.registry_core import (
    _task_mint_tool_allowed as _task_mint_tool_allowed,
)
from .tool_handlers.registry_core import (
    _tool_name_allowlist as _tool_name_allowlist,
)
from .tool_handlers.registry_core import (
    _workspace_file_snapshot as _workspace_file_snapshot,
)
from .tool_handlers.registry_core import (
    extra_current_file as extra_current_file,
)
from .tool_handlers.registry_core import (
    resource_write_explicitly_requested as resource_write_explicitly_requested,
)
from .tool_handlers.search_and_research import (
    _HIT_TEXT_FIELDS as _HIT_TEXT_FIELDS,
)
from .tool_handlers.search_and_research import (
    _RETRIEVAL_EXCERPT_BUDGETS as _RETRIEVAL_EXCERPT_BUDGETS,
)
from .tool_handlers.search_and_research import (
    ADAPTIVE_EVIDENCE_DIMENSIONS as ADAPTIVE_EVIDENCE_DIMENSIONS,
)
from .tool_handlers.search_and_research import (
    MAX_RESEARCH_SEARCH_ROUNDS as MAX_RESEARCH_SEARCH_ROUNDS,
)
from .tool_handlers.search_and_research import (
    MAX_RESEARCH_SOURCES as MAX_RESEARCH_SOURCES,
)
from .tool_handlers.search_and_research import (
    _apply_search_mode as _apply_search_mode,
)
from .tool_handlers.search_and_research import (
    _build_search_summary as _build_search_summary,
)
from .tool_handlers.search_and_research import (
    _capture_kind_for_url as _capture_kind_for_url,
)
from .tool_handlers.search_and_research import (
    _handle_analyze_project_impact as _handle_analyze_project_impact,
)
from .tool_handlers.search_and_research import (
    _handle_assess_research_evidence as _handle_assess_research_evidence,
)
from .tool_handlers.search_and_research import (
    _handle_import_resource_url as _handle_import_resource_url,
)
from .tool_handlers.search_and_research import (
    _handle_list_project_modules as _handle_list_project_modules,
)
from .tool_handlers.search_and_research import (
    _handle_read_project_symbol as _handle_read_project_symbol,
)
from .tool_handlers.search_and_research import (
    _handle_search_learning_materials as _handle_search_learning_materials,
)
from .tool_handlers.search_and_research import (
    _handle_search_resources as _handle_search_resources,
)
from .tool_handlers.search_and_research import (
    _internal_search_limit as _internal_search_limit,
)
from .tool_handlers.search_and_research import (
    _is_verification_ready_hit as _is_verification_ready_hit,
)
from .tool_handlers.search_and_research import (
    _load_project_symbol_payload as _load_project_symbol_payload,
)
from .tool_handlers.search_and_research import (
    _normalize_search_hits as _normalize_search_hits,
)
from .tool_handlers.search_and_research import (
    _normalize_search_mode as _normalize_search_mode,
)
from .tool_handlers.search_and_research import (
    _normalize_search_response as _normalize_search_response,
)
from .tool_handlers.search_and_research import (
    _normalized_research_domains as _normalized_research_domains,
)
from .tool_handlers.search_and_research import (
    _normalized_research_facets as _normalized_research_facets,
)
from .tool_handlers.search_and_research import (
    _plain_search_payload as _plain_search_payload,
)
from .tool_handlers.search_and_research import (
    _project_artifact_root as _project_artifact_root,
)
from .tool_handlers.search_and_research import (
    _resolve_project_resource as _resolve_project_resource,
)
from .tool_handlers.search_and_research import (
    _resource_model_payload as _resource_model_payload,
)
from .tool_handlers.search_and_research import (
    _resource_provenance as _resource_provenance,
)
from .tool_handlers.search_and_research import (
    _retrieval_plan as _retrieval_plan,
)
from .tool_handlers.search_and_research import (
    _source_matches_preferred_domain as _source_matches_preferred_domain,
)
from .tool_handlers.search_and_research import (
    _source_trust_score as _source_trust_score,
)
from .tool_handlers.search_and_research import (
    _transition_formal_research_to_synthesis as _transition_formal_research_to_synthesis,
)
from .tool_handlers.search_and_research import (
    _trim_hit_text as _trim_hit_text,
)
from .tool_handlers.search_and_research import (
    _validate_public_http_url as _validate_public_http_url,
)
from .tool_handlers.verification_and_excerpt import (
    _PRACTICE_SIGNAL_STOPWORDS as _PRACTICE_SIGNAL_STOPWORDS,
)
from .tool_handlers.verification_and_excerpt import (
    _acceptance_signal_check as _acceptance_signal_check,
)
from .tool_handlers.verification_and_excerpt import (
    _canonical_excerpt_fallback as _canonical_excerpt_fallback,
)
from .tool_handlers.verification_and_excerpt import (
    _chunk_for_anchor as _chunk_for_anchor,
)
from .tool_handlers.verification_and_excerpt import (
    _chunk_id_for_paragraph_anchor as _chunk_id_for_paragraph_anchor,
)
from .tool_handlers.verification_and_excerpt import (
    _citation_for_anchor as _citation_for_anchor,
)
from .tool_handlers.verification_and_excerpt import (
    _compare_deterministic_signals as _compare_deterministic_signals,
)
from .tool_handlers.verification_and_excerpt import (
    _criterion_result as _criterion_result,
)
from .tool_handlers.verification_and_excerpt import (
    _current_resource_version as _current_resource_version,
)
from .tool_handlers.verification_and_excerpt import (
    _diagnostic_severity as _diagnostic_severity,
)
from .tool_handlers.verification_and_excerpt import (
    _excerpt_sentence_list as _excerpt_sentence_list,
)
from .tool_handlers.verification_and_excerpt import (
    _fragment_for_anchor as _fragment_for_anchor,
)
from .tool_handlers.verification_and_excerpt import (
    _handle_compare_with_anchor as _handle_compare_with_anchor,
)
from .tool_handlers.verification_and_excerpt import (
    _handle_read_resource_excerpt as _handle_read_resource_excerpt,
)
from .tool_handlers.verification_and_excerpt import (
    _handle_read_workspace_file as _handle_read_workspace_file,
)
from .tool_handlers.verification_and_excerpt import (
    _handle_run_rubric_review as _handle_run_rubric_review,
)
from .tool_handlers.verification_and_excerpt import (
    _handle_verify_practice_current_file as _handle_verify_practice_current_file,
)
from .tool_handlers.verification_and_excerpt import (
    _host_rubric_spec as _host_rubric_spec,
)
from .tool_handlers.verification_and_excerpt import (
    _persist_practice_verification_result as _persist_practice_verification_result,
)
from .tool_handlers.verification_and_excerpt import (
    _practice_deliverable_kind as _practice_deliverable_kind,
)
from .tool_handlers.verification_and_excerpt import (
    _practice_failed_checks as _practice_failed_checks,
)
from .tool_handlers.verification_and_excerpt import (
    _practice_signals as _practice_signals,
)
from .tool_handlers.verification_and_excerpt import (
    _practice_subject_family as _practice_subject_family,
)
from .tool_handlers.verification_and_excerpt import (
    _punctuation_density as _punctuation_density,
)
from .tool_handlers.verification_and_excerpt import (
    _repository_resource as _repository_resource,
)
from .tool_handlers.verification_and_excerpt import (
    _resolve_excerpt_resource as _resolve_excerpt_resource,
)
from .tool_handlers.verification_and_excerpt import (
    _resource_display as _resource_display,
)
from .tool_handlers.verification_and_excerpt import (
    _resource_fragments as _resource_fragments,
)
from .tool_handlers.verification_and_excerpt import (
    _sentence_stats as _sentence_stats,
)
from .tool_handlers.verification_and_excerpt import (
    _training_card_context_for_persistence as _training_card_context_for_persistence,
)
from .tool_handlers.verification_and_excerpt import (
    _verify_practice_with_pack as _verify_practice_with_pack,
)
from .tool_handlers.verification_and_excerpt import (
    _workspace_scoped_registry_resource as _workspace_scoped_registry_resource,
)
from .tool_handlers.workspace_memory_and_plan import (
    _LANGUAGE_HINTS as _LANGUAGE_HINTS,
)
from .tool_handlers.workspace_memory_and_plan import (
    _TRUTH_OPAQUE_ID_KEYS as _TRUTH_OPAQUE_ID_KEYS,
)
from .tool_handlers.workspace_memory_and_plan import (
    _WORKSPACE_IGNORED_DIRS as _WORKSPACE_IGNORED_DIRS,
)
from .tool_handlers.workspace_memory_and_plan import (
    _collect_custom_skills_from_context as _collect_custom_skills_from_context,
)
from .tool_handlers.workspace_memory_and_plan import (
    _explicit_formal_plan_stage_count as _explicit_formal_plan_stage_count,
)
from .tool_handlers.workspace_memory_and_plan import (
    _flatten_library_group_nodes as _flatten_library_group_nodes,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_curate_library_resources as _handle_curate_library_resources,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_fetch_web_page as _handle_fetch_web_page,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_generate_image as _handle_generate_image,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_import_workspace_file as _handle_import_workspace_file,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_inspect_learning_truth as _handle_inspect_learning_truth,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_inspect_plan as _handle_inspect_plan,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_invoke_skill as _handle_invoke_skill,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_list_library_folders as _handle_list_library_folders,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_list_skills as _handle_list_skills,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_list_workspace_files as _handle_list_workspace_files,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_next_task as _handle_next_task,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_recall_memory as _handle_recall_memory,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_record_learning_note as _handle_record_learning_note,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_run_diagnostics as _handle_run_diagnostics,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_save_formal_plan as _handle_save_formal_plan,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_save_lecture_note as _handle_save_lecture_note,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_search_academic_papers as _handle_search_academic_papers,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_specify_task as _handle_specify_task,
)
from .tool_handlers.workspace_memory_and_plan import (
    _handle_web_search as _handle_web_search,
)
from .tool_handlers.workspace_memory_and_plan import (
    _import_single_workspace_item as _import_single_workspace_item,
)
from .tool_handlers.workspace_memory_and_plan import (
    _is_ignored_workspace_relpath as _is_ignored_workspace_relpath,
)
from .tool_handlers.workspace_memory_and_plan import (
    _localize_truth_enum as _localize_truth_enum,
)
from .tool_handlers.workspace_memory_and_plan import (
    _network_fetch_enabled as _network_fetch_enabled,
)
from .tool_handlers.workspace_memory_and_plan import (
    _resolve_tool_library_service as _resolve_tool_library_service,
)
from .tool_handlers.workspace_memory_and_plan import (
    _sanitize_learning_truth_value as _sanitize_learning_truth_value,
)
from .tool_handlers.workspace_memory_and_plan import (
    _slug_markdown_filename as _slug_markdown_filename,
)
from .tool_handlers.workspace_memory_and_plan import (
    _summarize_memory_snapshot as _summarize_memory_snapshot,
)
from .tool_handlers.workspace_memory_and_plan import (
    _summarize_plan as _summarize_plan,
)
from .tool_handlers.workspace_memory_and_plan import (
    _tool_text_list as _tool_text_list,
)
from .tool_handlers.workspace_memory_and_plan import (
    _walk_workspace_files as _walk_workspace_files,
)
from .tool_handlers.workspace_memory_and_plan import (
    _workspace_matches_pattern as _workspace_matches_pattern,
)

logger = logging.getLogger("trainer.llm.tools")


def build_default_tool_registry(
    extra_tools: Iterable[ToolDefinition] | None = None,
) -> ToolRegistry:
    """Return the Trainer 2.0 registry containing only the 8 dual-domain orthogonal primitives.

    ``extra_tools`` carries dynamically discovered MCP tools (``mcp_<server>_<tool>``).
    """
    registry = ToolRegistry()

    from .tool_primitives import register_orthogonal_primitives

    register_orthogonal_primitives(registry)

    for extra_tool in extra_tools or ():
        if registry.get(extra_tool.name) is not None:
            logger.warning("extra_tool_name_collision", extra={"tool": extra_tool.name})
            continue
        registry.register(extra_tool)

    return registry


__all__ = [
    "JsonSchema",
    "ToolContext",
    "ToolDefinition",
    "ToolHandler",
    "ToolRegistry",
    "build_default_tool_registry",
]
