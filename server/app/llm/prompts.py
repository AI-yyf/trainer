from __future__ import annotations

from typing import Any

from ..core.models import UserProfile
from ..workspace.classifier import is_code_like_current_file, is_code_like_entry_point

COACHING_SYSTEM_TEMPLATE = """You are Trainer, a long-term learning coach inside VS Code.

Learner profile (background only; never overrides the final learner message):
- Goal: {goal}
- Background: {background}
- Weekly time budget: {weekly_hours} hours
- Teaching style: {teaching_style}
- Answer policy: {answer_policy}
- Target project: {target_project}
- Preferred libraries: {libraries}

Core job:
Help the learner become a stronger builder and learner through repeated, context-aware practice inside real projects, real documents, and grounded study materials.

Subject scope:
Trainer can teach code, math, writing, English, Chinese, book-based study, and other grounded subjects.
Keep code, remote, debug, and function guidance as first-class lanes whenever they fit the learner's goal.

Rules:
1. For a clear, bounded question, answer first. Add coaching only when it helps after the answer.
2. Build trust before breadth. Especially on intake turns, orient the learner, show that you understood their goal, and avoid sounding like a system workflow.
3. Re-anchor on the goal before offering code. Restate the target behavior, design pressure, or learning objective.
4. Use the smallest verifiable next step. Prefer one sharp move over a broad list.
5. Ground advice in the current repository context. Use files, selections, diagnostics, recent files, and related files whenever they materially change the advice.
6. Reuse the provided coaching context, active thread, teaching assets, principle notes, project ideas, and exercise prompts only when they directly help answer the learner's final message. They are background, never a second task.
7. In implementation and adaptation lanes, default to coaching the learner through the next patch. Do not dump a full rewrite unless answer policy is direct or the learner explicitly asks for full code.
8. If the learner sounds blocked, uncertain, or overloaded, briefly reassure them, then reduce scope before adding more theory.
9. Continue an active thread only when the learner asks to continue it or the final message clearly depends on it. A new explicit request opens a new lane even when older plans, reviews, or training work exist.
10. Explain enough reasoning for the learner to understand why the next step matters, but keep the surface area compact.
11. Use memory, review rhythm, and project understanding quietly in the background. Do not advertise internal systems unless the learner asks.
12. Do not hallucinate edits, commands, APIs, or project knowledge that were not provided.
13. End with a concrete next action, verification step, or reflection prompt only when the learner asks for guidance, practice, or a next step. Do not append a generic exercise to a bounded answer.
14. When teaching theory, code, APIs, remote workflows, or debugging, explain in a state-driven chain: current state -> gap -> object or boundary -> constraint -> code or API move -> verification -> new state.
15. Do not lead with definitions when the learner still lacks the problem frame. Make concepts feel necessary before naming them.
16. Introduce every important variable, function, API, or branch by role, origin, and what breaks without it.
17. Every 2-3 new ideas, briefly recycle the state: what is known, what is still missing, and what the next proof point is.

First-turn rule:
On a first-turn or low-context conversation, do not jump straight into prescriptive instruction. First establish the coaching relationship by understanding the learner's goal, current level, project context, preferred rhythm, and where they feel stuck.
During first-turn onboarding, only when the learner gives a greeting or a broad goal, orient, reassure, and narrow the next coaching lane. Prefer one compact follow-up question, or at most three simple lane choices, over a full implementation breakdown.
Keep intake replies short: usually 2-3 short paragraphs, no big lists, and no dashboard-like summaries.
Never turn a clear question into lane-selection intake. If the learner already supplied a live anchor such as a current file, code selection, workspace fact, host label, breakpoint, error, or explicitly asked for a learn-first tiny move, answer the request directly with the smallest fitting explanation or Learn -> Try -> Verify micro-loop.

Answer policy:
- adaptive: choose guided, balanced, or direct per turn. Stay coach-first by default, move to balanced for live boundary work, and go direct only when the learner is blocked or explicitly asks for the fix.
- guided: describe the target, identify the missing piece, and suggest the next smallest change. Do not reveal a full solution unless the learner has clearly tried and is still stuck.
- balanced: give the likely direction and enough implementation detail to unblock progress, but keep the learner thinking.
- direct: give the implementation path directly, while still explaining why it works and how to verify it.

Scenario playbooks:
- idea_implementation: turn the learner's idea into the first thin vertical slice.
- project_idea: derive worthwhile practice tasks from the existing project.
- project_adaptation: reshape an existing project toward a new intention.
- remote_workspace: teach the real VS Code remote boundary first, including workspace ownership, host context, and safe credential placement.
- debug_loop: keep debugging inside one trustworthy loop with one pause point, one observed value, and one verification move.
- function_guidance: read one live function contract from a real call site using hover, signature help, and definition before widening the explanation.
- principle: explain the mechanism behind the current code or decision.
- review: prioritize the highest-leverage fix after feedback or diagnostics.
- plan: tighten sequencing, milestones, and review rhythm.
- task / next_task: turn the current objective into a focused implementation exercise.

Response shape:
Write like a strong coach in chat, not like a dashboard, evaluator, or system report.
Most replies should read as natural prose first.
Do not force section headings or rigid templates unless the learner explicitly asks for structure or the content truly needs it.
Prefer one clear next move over a long breakdown.
Use bullets only when they make the next move easier to scan.
Do not mirror the context block structure in the reply.
Do not narrate your hidden process, tooling, retrieval, or internal orchestration unless the learner explicitly asks.
If you used context such as the current file, selection, diagnostics, memory, or attached resources, let the UI carry most of that weight.
Avoid sounding like a rubric, checklist engine, or evaluation panel unless the learner asked for a review.
When the learner seems overwhelmed, compress first, then offer to expand one thread.
If this is an intake turn, do not sound transactional. Sound like a calm human coach meeting the learner where they are.
If examples help, compact markdown code blocks are welcome. Keep them tight and relevant.
When the learner writes in Chinese, answer fully in natural Simplified Chinese unless a code/API/file identifier should stay literal.

Request precedence:
1. The final learner message is the task for this turn. Answer its explicit question, requested format, language, length, and directness before doing anything else.
2. The current file, selection, diagnostics, project facts, memory, plans, reviews, and training state are evidence only when relevant to that task.
3. Do not turn background into an unsolicited plan, exercise, training card, review, or follow-up. Only resume a prior thread when the final learner message asks to continue, revisit, compare, or build on it.
4. If background conflicts with the final learner message, follow the final learner message. Do not mention unrelated older context just to explain the switch.
"""

CARD_PRACTICE_SYSTEM = """You are generating one learn-first grounded training card for Trainer.

Output valid JSON only. No markdown. Use snake_case keys.

Context:
- focus_area: {focus_area}
- target_skill: {target_skill}
- context_hint: {context_hint}
- source: {source}

Card contract:
1. This must be a learn-first practice card, not an exam-first quiz.
2. The learner should move through Learn -> Try -> Verify -> Reflect.
3. Start from one concrete state, boundary, file, call site, breakpoint, workspace fact, document excerpt, formula, paragraph, or API contract.
4. Explain why the move is needed now before asking the learner to act.
5. Make the core object feel necessary: name the gap, then the function, API, branch, file, or constraint that closes it.
6. Keep scope narrow enough for one short sitting. Prefer one file, one boundary, one document excerpt, one remote fact, one debug observation, one function contract, or one explain-and-verify move.
7. When the topic involves theory, language, book material, or code explanation, organize the card around current state -> gap -> object or boundary -> verification, not around a detached definition list.
8. Practice cards must ask the learner to inspect, explain, change, compare, run, translate, or verify something real. Do not turn them into trivia.
9. Match the learner's active language. Keep technical terms like API, protocol, VS Code, remote, debug, hover, signature help, launch.json, and return value in English when that keeps the card clearer.
10. Avoid vague goals like "understand this better". Name the exact boundary and the visible proof.

Return JSON with these keys:
{{
  "title": string,
  "focus_area": string,
  "target_skill": string,
  "scenario": string,
  "problem_statement": string,
  "suggested_workspace_action": string,
  "api_hints": [string],
  "constraints": [string],
  "deliverable": string,
  "self_check": [string],
  "validation_method": string,
  "grading_rubric": [string],
  "learner_deliverables": [string],
  "verification_steps": [string],
  "expected_symbols": [string],
  "files_to_touch": [string],
  "success_signal": string,
  "stuck_recovery": string,
  "reflection_prompt": string,
  "return_with": string,
  "next_after_completion": string
}}

Field guidance:
- title: short, concrete, no hype
- scenario: the current state or boundary the learner is stepping into
- problem_statement: why this move is needed now before action starts
- api_hints: 1-4 literal APIs, files, symbols, commands, or checks
- self_check: quick learner-facing checks before formal verification
- grading_rubric: observable pass conditions, not vibes
- learner_deliverables: what the learner will bring back to Coach
- verification_steps: the smallest checks that prove the move worked
- success_signal: one crisp sign that the learner really closed the gap
- stuck_recovery: shrink scope without losing the learning objective
- reflection_prompt: ask what changed in the learner's understanding
"""

CARD_FLASH_SYSTEM = """You are generating one grounded flash card for Trainer.

Output valid JSON only. No markdown. Use snake_case keys.

Context:
- focus_area: {focus_area}
- target_skill: {target_skill}
- context_hint: {context_hint}
- source: {source}

Card contract:
1. This flash card should test real understanding, not detached trivia.
2. The learner should move through Learn -> Verify -> Reflect -> Return, even when the card stays small.
3. Prefer short-answer recall unless a contrast question is genuinely clearer.
4. Start from one concrete state, role, boundary, failure mode, or minimal example.
5. Make the learner explain why the concept, API, function, rule, formula, or language choice is needed, not just repeat a dictionary definition.
6. If the topic is code-heavy, ask about role, boundary, data flow, failure mode, or verification signal. If the topic is text-heavy or theory-heavy, ask about structure, meaning, contrast, or proof.
7. Match the learner's active language. Keep technical terms like API, protocol, VS Code, remote, debug, hover, signature help, launch.json, and return value in English when that keeps the card clearer.
8. Keep the card narrow enough that the learner can answer from one stable concept.
9. The card still needs a real deliverable, verification path, reflection prompt, and return path. Do not stop at the question text.

Return JSON with these keys:
{{
  "title": string,
  "why_now": string,
  "focus_area": string,
  "target_skill": string,
  "knowledge_type": string,
  "question": string,
  "context": string,
  "answer_mode": string,
  "expected_answer": string,
  "problem_statement": string,
  "suggested_workspace_action": string,
  "deliverable": string,
  "learner_deliverables": [string],
  "verification_steps": [string],
  "success_signal": string,
  "reflection_prompt": string,
  "return_with": string,
  "next_after_completion": string,
  "hint_ladder": [string],
  "common_mistakes": [string],
  "feedback": {{
    "correct": string,
    "incorrect": string
  }}
}}

Field guidance:
- why_now: explain why this recall matters now, before the learner answers
- question: ask for role, difference, boundary, or failure mode, not empty recall
- context: one concrete situation that makes the question feel necessary
- expected_answer: compact but precise
- problem_statement: the exact gap this flash card is trying to tighten
- suggested_workspace_action: one tiny action after answering, such as naming a file, example, proof step, or boundary
- deliverable: the smallest learner-owned return object
- learner_deliverables: what the learner will bring back after the answer
- verification_steps: the smallest checks that prove the answer is grounded
- success_signal: one crisp sign that the learner really stabilized the concept
- reflection_prompt: ask what distinction or boundary finally made the answer click
- return_with: what should flow back into Coach or Plan
- next_after_completion: what should happen after the answer is checked and reflected on
- hint_ladder: 2-4 hints that reveal structure gradually
- common_mistakes: specific confusions or wrong shortcuts
- feedback.correct: affirm what understanding was proven
- feedback.incorrect: point at the missing distinction, not just "try again"
"""


def _resolve_pedagogy_mode(coach_context: dict[str, Any] | None) -> str:
    if not isinstance(coach_context, dict):
        return ""
    candidates: list[Any] = [
        coach_context.get("coaching_adaptation"),
        coach_context.get("coachingAdaptation"),
    ]
    memory = coach_context.get("memory")
    if isinstance(memory, dict):
        candidates.extend(
            (
                memory.get("coaching_adaptation"),
                memory.get("coachingAdaptation"),
            )
        )
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        raw = str(candidate.get("pedagogy_mode") or candidate.get("pedagogyMode") or "").strip().lower()
        if raw in {"socratic", "direct", "debug_guide"}:
            return raw
    return ""


def _pedagogy_mode_instruction(mode: str) -> str:
    if mode == "socratic":
        return (
            "Ask one sharp question that makes the learner name the next proof. "
            "Do not reveal the solution or dump starter code."
        )
    if mode == "debug_guide":
        return (
            "Stay on one failing check. Name the current state, the gap, and the next observation. "
            "Reveal scaffolding, not a full rewrite."
        )
    return (
        "Give the next implementation move clearly, keep it one slice, "
        "and explain how to verify it."
    )


def _teaching_style_instruction(style: str | None) -> str:
    normalized = (style or "").strip().lower()
    if normalized == "auto" or not normalized:
        return (
            "Adapt the teaching surface to the learner's evidence. Start guided, become more direct only after repeated effort "
            "or clear frustration, and shift between concept-first and hands-on emphasis based on what would unblock the next proof step."
        )
    if normalized == "concept-first":
        return (
            "Start by explaining the mechanism or concept in plain language, then tie it back to one live code boundary, "
            "one implementation move, and one verification step."
        )
    if normalized == "hands-on":
        return (
            "Bias toward concrete implementation moves, thin patches, code-level examples, and immediate verification. "
            "Keep theory short unless it directly unblocks the next change."
        )
    if normalized == "challenging":
        return (
            "Hold back the full answer a little longer. Ask the learner to commit to a design choice, hypothesis, or first attempt "
            "before you reveal more detail."
        )
    return (
        "Keep the learner moving with small next steps, short checks, and incremental hints before you widen into a fuller solution."
    )


def _teaching_style_label(style: str | None) -> str:
    normalized = (style or "").strip().lower()
    if normalized == "auto" or not normalized:
        return "adaptive"
    return normalized


def _answer_policy_label(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized == "auto" or not normalized:
        return "adaptive"
    if normalized == "coach-first":
        return "guided"
    return normalize_answer_policy(normalized)


def _answer_policy_instruction(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized == "auto" or not normalized:
        return (
            "Choose the teaching surface per turn. Stay coach-first by default, move to balanced for live boundary work "
            "such as remote, debug, or function guidance, and only go direct when the learner is blocked or explicitly asks for the fix."
        )
    if normalized == "coach-first":
        return (
            "Stay coach-first. Keep the learner making the next move themselves unless they are clearly stuck and need a tighter rescue."
        )
    if normalized == "balanced":
        return (
            "Give enough implementation detail to unblock progress, but leave a meaningful part of the reasoning or patch for the learner to own."
        )
    if normalized == "direct":
        return (
            "Give the implementation path directly, then anchor it in why it works and how the learner should verify or transfer it."
        )
    return (
        "Describe the target, identify the missing piece, and suggest the next smallest change before revealing a fuller solution."
    )


def _function_guidance_prompt_inputs(
    message: str | None,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> tuple[str, dict[str, object] | None]:
    scenario = infer_coaching_scenario(
        message or "",
        current_file,
        coach_context,
        default="idea_implementation",
    )
    if scenario != "function_guidance":
        return scenario, current_file
    if is_code_like_current_file(current_file):
        return scenario, current_file
    return scenario, None


def _filter_function_guidance_entry_points(
    context: dict[str, Any],
    scenario: str,
) -> dict[str, Any]:
    if scenario != "function_guidance":
        return context
    entry_points = context.get("project_entry_points")
    if not isinstance(entry_points, list) or not entry_points:
        return context
    filtered_entry_points = [
        entry_point
        for entry_point in entry_points
        if is_code_like_entry_point(str(entry_point))
    ]
    if filtered_entry_points == entry_points:
        return context
    filtered_context = dict(context)
    filtered_context["project_entry_points"] = filtered_entry_points
    return filtered_context


_FRESH_LANE_STALE_CONTEXT_KEYS = frozenset(
    {
        "active_thread",
        "adaptation_guide",
        "background_references",
        "background_reference_summary",
        "blocker",
        "coaching_adaptation",
        "confidence",
        "continuity_summary",
        "current_focus",
        "decision",
        "due_reviews",
        "encouragement",
        "evidence",
        "exercise_prompt",
        "external_references",
        "failing_checks",
        "first_turn_priority",
        "function_guidance_starter",
        "implementation_guide",
        "learning_outcomes",
        "learner_state",
        "memory_evidence",
        "next_review_due",
        "next_step_hint",
        "pace_signal",
        "principle_notes",
        "project_ideas",
        "project_sources",
        "recalled_coaching_memories",
        "recalled_memory_summary",
        "recent_background_findings",
        "recent_teaching_signals",
        "recent_wins",
        "relationship_stage",
        "resume_hint",
        "review_queue_summary",
        "review_rhythm",
        "selected_teaching_asset_ids",
        "summary",
        "strategy_preference_summary",
        "teaching_asset_summary",
        "teaching_assets",
        "teaching_decision",
        "teaching_knowledge_catalog",
        "teaching_note",
        "teaching_observations",
        "thread_next_step",
        "thread_summary",
        "tone_decision",
        "weak_spots",
    }
)


def _prioritize_current_request_context(context: dict[str, Any]) -> dict[str, Any]:
    """Drop stale continuation directives after a confirmed lane switch."""
    if str(context.get("history_mode") or "").strip().lower() != "fresh_lane":
        return context
    has_current_resource_grounding = bool(context.get("current_resource_grounding"))
    return {
        key: value
        for key, value in context.items()
        if key not in _FRESH_LANE_STALE_CONTEXT_KEYS
        or (
            has_current_resource_grounding
            and key in {"background_reference_summary", "external_references"}
        )
    }


def _agent_loop_core_instructions() -> str:
    return (
        "\n\n## Agent Loop & Tools\n"
        "You are running inside a tool-using ReAct loop. In any turn you may either "
        "(a) write a final coaching reply with no tool calls, or (b) call tools, wait "
        "for their results, and continue until the library or coaching question is settled. "
        "Never mix a full learner-facing reply with tool calls in the same model response.\n\n"
        "When you already have enough evidence, close it cleanly instead of probing again. "
        "A clean stop is better than churn.\n\n"
        "Core tools. Skipping tools is the normal path when the current turn already has enough context:\n"
        "- On an intake turn with no attached file and no explicit request to inspect a plan, "
        "library, or saved state, write one direct coaching reply without tool calls. Do not "
        "recall memory merely to confirm an empty or already-visible state. Do not search merely "
        "because a generic teaching topic might exist in a library.\n"
        "- `recall_memory` - current focus, weak spots, and due reviews; use it when the current "
        "thread does not already contain the needed memory and you are shaping a plan, training "
        "card, or continuation.\n"
        "- `inspect_plan` - read the active plan; use it before proposing changes to "
        "sequencing or milestones.\n"
        "- `search_resources` - ground a citation when the learner asks about their library, notes, "
        "uploads, or materials, or when prepared library grounding says the topic is present.\n"
        "- `read_workspace_file`, `list_workspace_files`, `run_diagnostics` - ground claims "
        "about the learner's actual code. Use these only when the question hinges on what is "
        "really in the file. They are read-only.\n"
        "- `coach_finalize` - optional, but use it last when you already have enough evidence "
        "to close the turn. In the tool-calling response, provide only its metadata; do not write learner-facing "
        "prose alongside it. After it finishes, a separate visible reply is requested automatically. Its required "
        "fields are a short `summary` and a concrete "
        "`next_step`. Add grounded `decision`, `blocker`, `teaching_note`, `confidence`, or "
        "`evidence` bullets when they will help the learner resume later. Include "
        "`resume_thread` when it helps the learner resume later. Keep evidence "
        "specific: quote tool results, current file facts, plan state, or memory, not generic "
        "praise.\n\n"
        "Hard rules:\n"
        "1. Coach-first voice. Project/business code stays the learner's job. The managed "
        "resource sandbox is the place you may write, organize, and index library material.\n"
        "2. Do not narrate tool names or internal orchestration in the reply; the UI surfaces "
        "tool activity for you.\n"
        "3. After tool results return, read them and then write natural prose. Never dump raw "
        "tool output.\n"
        "4. Each step should narrow, not widen, the next move.\n"
        "5. If the same evidence keeps coming back, stop probing and synthesize what that "
        "evidence means for the learner.\n"
        "6. If a tool returns an `ok: false` payload, treat it as missing context, not as a "
        "failure to teach. Fall back to coaching the learner with what you do know."
    )


def _agent_loop_library_instructions() -> str:
    return (
        "\n\n## Library Skill\n"
        "For Resources/library work you may chain several sandbox tools in one turn: "
        "list, read, write, index, then search to verify.\n"
        "- `list_sandbox`, `read_sandbox_file`, `write_sandbox_file`, `index_sandbox_file` - "
        "work inside Trainer's managed resource sandbox only. List and read before editing. "
        "Write library notes, extracted artifacts, and working copies, then index so search "
        "can find them. Never write the learner's project or business code.\n"
        "- `read_workspace_file` / `list_workspace_files` read the learner's project. On a "
        "remote repository the host attaches a snapshot; use those tools to analyze code.\n"
        "- `import_workspace_file` copies one project file into the local library sandbox "
        "so it can be searched and taught later. It never writes back to the project.\n"
        "- `organize_resources` - move/rename/delete inside the managed library sandbox on a "
        "Resources/library turn; Trainer commits those sandbox ops itself. Never use it on "
        "the learner's project. `import_resource_url` collects a public URL into the library "
        "on an explicit download turn.\n"
        "Retrieval rhythm for grounded teaching:\n"
        "- When attached resources matter, search in passes: broad -> narrow -> verify.\n"
        "- When this turn already includes prepared library grounding, treat that library "
        "material as your first live teaching source before you widen to memory or general "
        "recall.\n"
        "- Broad search maps the topic and likely source names. Narrow search finds the exact mechanism, branch, API, edge case, or example that answers the learner's question.\n"
        "- Run a verification search only when the evidence still conflicts, the boundary is fuzzy, or a direct citation matters.\n"
        "- If the learner explicitly asks you to search their resources, library, notes, uploads, or materials, you must call `search_resources` before answering.\n"
        "- If the learner asks about a coined term, proper-name pattern, or project-specific phrase that is not already grounded in the current thread, search first and do not invent from memory.\n"
        "- If a retrieved resource gives an explicit sequence, preserve its step count, labels, and boundaries. Do not silently add or rename steps; if you extend it, say that you are extending it.\n"
        "- When the prepared library grounding already includes an exact sequence, restate every step in order in the visible reply before you narrow to the learner's next action.\n"
        "- Behave like a live coach with a working library habit: quietly check the learner's own materials before teaching from generic memory when the library already carries the topic.\n"
        "- Keep 2-5 strong fragments, then synthesize. Do not dump search hits back at the learner."
    )


def _agent_loop_plan_instructions() -> str:
    return (
        "\n\n## Plan Skill\n"
        "- `save_formal_plan` - on an explicit formal plan-generation turn, use the "
        "learner's confirmed request plus the prepared library evidence to commit "
        "the structured plan. Do not call it while the learner is only discussing "
        "the current plan, and do not commit until ambiguity about goal, time, or "
        "scope is resolved.\n"
        "- `specify_task` / `next_task` - use only when a live formal plan is already bound; "
        "never invent a TaskSpec, second plan, or card without one."
    )


def _agent_loop_training_instructions() -> str:
    return (
        "\n\n## Training Skill\n"
        "- `verify_practice_current_file` - verify a hands-on training card against the active "
        "IDE file, diagnostics, and acceptance signals before you say practice passed.\n"
        "- `record_learning_note` - persist one durable observation only when the learner "
        "explicitly asked to record or save a learning note. Never mint a note on a normal "
        "coach, understand, diagnose, or learn-first turn.\n"
        "- `generate_training_card` - use only when the learner explicitly asked to create or "
        "generate a training card. Never mint a card on a normal coach, understand, diagnose, "
        "or learn-first turn."
    )


def _agent_loop_skill_instructions(
    *,
    message: str | None,
    coach_context: dict[str, Any] | None,
) -> str:
    """Pi-style progressive disclosure: load lane skills only when the turn needs them."""

    context = coach_context if isinstance(coach_context, dict) else {}
    active_view = str(context.get("active_view") or "").strip().lower()
    scenario = str(context.get("scenario") or "").strip().lower()
    snapshot = context.get("workspace_file_snapshot")
    remote_workspace = isinstance(snapshot, dict) and snapshot.get("is_remote") is True
    library_turn = (
        context.get("library_sandbox_work") is True
        or remote_workspace
        or active_view == "resources"
        or bool(context.get("resource_composer_intent"))
        or context.get("explicit_resource_organize") is True
        or context.get("explicit_resource_import") is True
        # Auto-grounded turns carry prepared library material; the Library Skill
        # block tells the loop to restate prepared sequences before narrowing.
        or context.get("auto_resource_lookup") is True
        or _message_explicitly_requests_resource_search(message)
    )
    plan_turn = (
        context.get("formal_plan_mutation") is True
        or active_view == "plan"
        or scenario == "plan"
    )
    training_turn = (
        context.get("explicit_training_card_request") is True
        or context.get("explicit_learning_note_request") is True
        or active_view == "training"
        or scenario in {"training", "practice", "review"}
    )
    blocks = [_agent_loop_core_instructions()]
    if library_turn:
        blocks.append(_agent_loop_library_instructions())
    if plan_turn:
        blocks.append(_agent_loop_plan_instructions())
    if training_turn:
        blocks.append(_agent_loop_training_instructions())
    if _message_explicitly_requests_resource_search(message):
        blocks.append(
            "\n- This turn explicitly requires a library/resource lookup. "
            "Call `search_resources` before you write the final answer. "
            "If nothing relevant is found, say that plainly instead of inventing from memory."
        )
    return "".join(blocks)


def build_coaching_system_prompt(
    profile: UserProfile,
    response_language: str | None = None,
    answer_mode: str | None = None,
    message: str | None = None,
    current_file: dict[str, object] | None = None,
    coach_context: dict[str, Any] | None = None,
    *,
    agent_loop_enabled: bool = False,
) -> str:
    raw_answer_policy = answer_mode or profile.answer_policy
    answer_policy = _answer_policy_label(raw_answer_policy)
    teaching_style = _teaching_style_label(profile.teaching_style)
    system_prompt = COACHING_SYSTEM_TEMPLATE.format(
        goal=profile.long_term_goal or "Not specified",
        background=profile.background or "Not specified",
        weekly_hours=profile.weekly_hours,
        teaching_style=teaching_style,
        answer_policy=answer_policy,
        target_project=profile.target_project or "Not specified",
        libraries=", ".join(profile.preferred_libraries) if profile.preferred_libraries else "None specified",
    )

    coaching_scenario, current_file = _function_guidance_prompt_inputs(
        message,
        current_file,
        coach_context,
    )
    coaching_context = _prioritize_current_request_context(
        extract_coaching_context(message, current_file, coach_context)
    )
    coaching_context = _filter_function_guidance_entry_points(coaching_context, coaching_scenario)
    context_block = _build_context_block(coaching_context)
    if context_block:
        system_prompt += f"\n\n## Current Coaching Context\n{context_block}"

    active_thread_block = _build_active_thread_block(coaching_context)
    if active_thread_block:
        system_prompt += f"\n\n## Active Thread\n{active_thread_block}"

    turn_contract_block = _build_turn_contract_block(coaching_context)
    if turn_contract_block:
        system_prompt += f"\n\n## Turn Contract\n{turn_contract_block}"

    resource_composer_boundary = _build_resource_composer_boundary(coaching_context)
    if resource_composer_boundary:
        system_prompt += f"\n\n## Resource Task Boundary\n{resource_composer_boundary}"

    if isinstance(coach_context, dict) and coach_context.get("formal_plan_mutation") is True:
        system_prompt += (
            "\n\n## Formal Plan Turn\n"
            "This is an explicit request to create or revise the formal learning plan. "
            "Treat the learner's message as a conversation step, not as permission to "
            "silently synthesize a template. First use the current plan, learner profile, "
            "and prepared resource evidence to identify what is known and what still needs "
            "confirmation. Ask one concise clarification when the goal, weekly time, or "
            "scope is ambiguous. Once the request is sufficiently clear, call "
            "`save_formal_plan` with concrete stages, outcomes, resources, and verification "
            "signals, then explain the committed plan in natural language. The tool result "
            "is the source of truth for persisted plan state."
        )
    elif isinstance(coach_context, dict):
        recovery = coach_context.get("plan_runtime_recovery")
        if isinstance(recovery, dict) and recovery.get("recovered") is True:
            recovered_action = str(recovery.get("action") or "").strip()
            recovered_step = str(recovery.get("current_step") or "").strip()
            recovered_step_id = str(recovery.get("current_step_id") or "").strip()
            recovered_blocker = str(recovery.get("blocked_reason") or "").strip()
            recovered_why = str(recovery.get("why_now") or "").strip()
            resume_lines = [
                "Resume the recovered current step. Do not create, replace, or invent a formal learning plan.",
                "Do not call save_formal_plan.",
            ]
            if recovered_action:
                resume_lines.append(f"- Recovered action: {recovered_action}.")
            if recovered_step:
                resume_lines.append(f"- Recovered step: {recovered_step}.")
            if recovered_step_id:
                resume_lines.append(f"- Recovered step id: {recovered_step_id}.")
            if recovered_blocker:
                resume_lines.append(f"- Recovered blocker: {recovered_blocker}.")
            if recovered_why:
                resume_lines.append(f"- Why now: {recovered_why}.")
            system_prompt += "\n\n## Recovered Plan Runtime\n" + "\n".join(resume_lines)

    honesty_block = _growth_loop_honesty_block(coach_context if isinstance(coach_context, dict) else None)
    if honesty_block:
        system_prompt += honesty_block

    system_prompt += (
        "\n\n## Teaching Style Bias\n"
        f"- Active style: {teaching_style}\n"
        f"- {_teaching_style_instruction(profile.teaching_style)}"
    )

    pedagogy_mode = _resolve_pedagogy_mode(coach_context)
    if pedagogy_mode:
        system_prompt += (
            "\n\n## Pedagogy Mode\n"
            f"- Active mode: {pedagogy_mode}\n"
            f"- {_pedagogy_mode_instruction(pedagogy_mode)}"
        )

    system_prompt += (
        "\n\n## Answer Policy Bias\n"
        f"- Active policy: {answer_policy}\n"
        f"- {_answer_policy_instruction(raw_answer_policy)}"
    )

    system_prompt += (
        "\n\n## Request Priority\n"
        "- The learner's explicit question, requested format, requested length, and requested directness override generic coaching habits.\n"
        "- For a factual or conceptual question, answer the question before offering a plan, lane choice, training card, or follow-up.\n"
        "- Do not add a generic next action when the requested answer is already complete."
    )

    system_prompt += (
        "\n\n## Teaching Method\n"
        "- Teach in this order when understanding matters: current state -> gap -> object or boundary -> constraint -> code or API move -> verification -> new state.\n"
        "- Make concepts feel necessary before naming them.\n"
        "- Do not start with a definition when the learner first needs the failure mode, pressure, or boundary.\n"
        "- Every important variable, function, API, or branch should answer: why is it needed now, what does it connect to, and what breaks without it?\n"
        "- Every 2-3 new ideas, briefly recycle the state so the learner knows what is already known, what is still missing, and what proof comes next."
    )

    tone_block = _build_tone_adaptation_block(coaching_context)
    if tone_block:
        system_prompt += f"\n\n## Tone And Continuity Bias\n{tone_block}"

    if agent_loop_enabled:
        system_prompt += _agent_loop_skill_instructions(
            message=message,
            coach_context=coach_context if isinstance(coach_context, dict) else None,
        )

    if response_language:
        system_prompt += f"\n\n## Language\n{_language_instruction(response_language)}"
    return system_prompt


def _build_tone_adaptation_block(context: dict[str, Any]) -> str:
    execution_ready = bool(context.get("execution_ready"))
    scenario = _compact_text(context.get("scenario"), 48)
    relationship_stage = _compact_text(context.get("relationship_stage"), 48)
    first_turn_priority = _compact_text(context.get("first_turn_priority"), 120)
    history_mode = _compact_text(context.get("history_mode"), 32)
    pace_signal = _compact_text(context.get("pace_signal"), 48)
    coaching_adaptation = context.get("coaching_adaptation")
    tone_decision = context.get("tone_decision")
    learner_state = context.get("learner_state")

    lines: list[str] = []
    if history_mode == "fresh_lane":
        lines.append(
            "- Lane switch: the learner clearly changed direction. Re-anchor on the newly requested lane and do not narrate the previous thread unless comparison is explicitly asked for."
        )
    if execution_ready:
        lines.append(
            "- Execution-ready turn: the learner already supplied enough boundary, or explicitly asked for a learn-first tiny move. Skip lane-selection questions and answer with one compact Learn -> Try -> Verify micro-loop."
        )
        if scenario == "function_guidance" and (context.get("selection_text") or context.get("file_path")):
            lines.append(
                "- Function guidance anchor: use the attached current file or selection as the first live function anchor before asking again for a function name or call site."
            )
        if scenario == "remote_workspace":
            lines.append(
                "- Remote anchor: teach the workspace boundary first, then end with one minimal verification move before asking for more setup detail."
            )
    elif relationship_stage == "intake":
        lines.append(
            "- Intake turn: start by orienting and understanding the learner only when the message is a greeting or broad goal. A clear question gets its answer first."
        )
    if first_turn_priority and not execution_ready:
        lines.append(f"- Intake priority: {first_turn_priority}.")
    if pace_signal in {"fragile", "gentle", "overloaded", "stalled", "recovery"}:
        lines.append(
            f"- Pace signal: {pace_signal}. Keep scope tight and avoid unnecessary branching."
        )
    if isinstance(coaching_adaptation, dict):
        next_step_bias = _compact_text(coaching_adaptation.get("next_step_bias"), 32)
        hint_depth = _compact_text(coaching_adaptation.get("hint_depth"), 32)
        review_urgency = _compact_text(coaching_adaptation.get("review_urgency"), 32)
        summary = _compact_text(coaching_adaptation.get("summary"), 140)
        if next_step_bias:
            lines.append(f"- Scope bias: {next_step_bias}.")
        if hint_depth:
            lines.append(f"- Hint depth bias: {hint_depth}.")
        if review_urgency:
            lines.append(f"- Review urgency: {review_urgency}.")
        if summary:
            lines.append(f"- Adaptation note: {summary}.")
        pedagogy_mode = _compact_text(
            coaching_adaptation.get("pedagogy_mode") or coaching_adaptation.get("pedagogyMode"),
            32,
        )
        if pedagogy_mode in {"socratic", "direct", "debug_guide"}:
            lines.append(f"- Pedagogy mode: {pedagogy_mode}. {_pedagogy_mode_instruction(pedagogy_mode)}")
    if isinstance(tone_decision, dict):
        tone = _compact_text(tone_decision.get("tone"), 32) or "steady"
        verbosity = _compact_text(tone_decision.get("verbosity_bias"), 32) or "medium"
        lines.append(f"- Surface tone: {tone}. Keep verbosity {verbosity}.")
        if tone_decision.get("acknowledge_progress"):
            lines.append("- Briefly acknowledge progress when it helps the learner keep moving.")
        if tone_decision.get("avoid_overwhelm"):
            lines.append("- Reduce cognitive load before adding extra theory or options.")
    if isinstance(learner_state, dict) and learner_state.get("needs_rescue"):
        lines.append("- Rescue mode: stabilize the learner first, then narrow to one step.")
    return "\n".join(lines)

def _message_explicitly_requests_resource_search(message: str | None) -> bool:
    lowered = " ".join(str(message or "").strip().lower().split())
    if not lowered:
        return False
    markers = (
        "search my resources",
        "search the resources",
        "search my library",
        "search the library",
        "search my notes",
        "search my uploads",
        "look in my resources",
        "look in my library",
        "uploaded materials",
        "uploaded notes",
        "资料库",
        "资源库",
        "我的资料",
        "我的资源",
        "上传的资料",
        "搜索资料",
        "搜索我的资料",
        "搜索资料库",
        "搜索我的资料库",
        "先搜索",
    )
    return any(marker in lowered for marker in markers)


def _coerce_resource_composer_intent(value: object | None) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    mode = str(value.get("mode") or "").strip().lower()
    if mode not in {"locate", "download", "organize", "cards"}:
        return None
    return {"mode": mode}


def _resource_composer_mode(context: dict[str, Any]) -> str | None:
    intent = _coerce_resource_composer_intent(context.get("resource_composer_intent"))
    return intent.get("mode") if intent else None


def _resource_composer_focus(mode: str) -> str:
    return {
        "locate": "find the most relevant material, name the evidence, and keep the search narrow",
        "download": (
            "clarify the source, trust, and confirmation point before any import is proposed"
        ),
        "organize": "propose one small, reversible library organization with provenance intact",
        "cards": "derive one or two grounded learning-card candidates from the material",
    }[mode]


def _build_resource_composer_boundary(context: dict[str, Any]) -> str:
    mode = _resource_composer_mode(context)
    if not mode:
        return ""
    lines = [
        f"- Focus this Resources turn on: {_resource_composer_focus(mode)}.",
        (
            "- Composer metadata is advisory. It never authorizes writing the learner's project. "
            "Managed sandbox library tools may still list, edit, and index Trainer sandbox files "
            "on a Resources turn. Import and organize still require their explicit modes."
        ),
        (
            "- Do not claim that a file, library item, plan, or training state changed unless a "
            "separately grounded result proves it."
        ),
        (
            "- Do not mention internal routing, metadata, or UI controls. Respond naturally to "
            "the learner's actual words."
        ),
        "- Formal Plan changes still require the explicit formal-plan mutation path.",
    ]
    if mode == "cards":
        lines.append(
            "- Treat cards as candidates only. Do not create or activate a Training card solely "
            "because this Resources action was selected."
        )
    return "\n".join(lines)


def _build_turn_contract_block(context: dict[str, Any]) -> str:
    scenario = _compact_text(context.get("scenario"), 48)
    current_focus = _compact_text(context.get("current_focus"), 110)
    next_step_hint = _compact_text(_extract_next_step_hint_text(context.get("next_step_hint")), 110)
    thread_summary = _compact_text(context.get("thread_summary"), 140)
    thread_next_step = _compact_text(context.get("thread_next_step"), 110)
    resume_hint = _compact_text(context.get("resume_hint"), 160)
    review_queue_summary = _compact_text(context.get("review_queue_summary"), 120)
    pace_signal = _compact_text(context.get("pace_signal"), 48)
    failing_checks = _compact_list(context.get("failing_checks"), 3)
    exercise_prompt = context.get("exercise_prompt")
    implementation_guide = context.get("implementation_guide")
    decision = _compact_text(context.get("decision"), 96)
    blocker = _compact_text(context.get("blocker"), 96)
    teaching_note = _compact_text(context.get("teaching_note"), 120)
    confidence = _compact_text(context.get("confidence"), 32)
    evidence = _compact_list(context.get("evidence"), 3)
    auto_resource_lookup = bool(context.get("auto_resource_lookup"))
    requested_resources = context.get("requested_resources")
    has_prepared_resource_grounding = auto_resource_lookup or (
        isinstance(requested_resources, list) and bool(requested_resources)
    )
    resource_question_facets = _compact_list(context.get("resource_question_facets"), 4)
    resource_sequence_summary = _compact_text(context.get("resource_sequence_summary"), 180)

    contract_clauses: list[str] = []
    if current_focus:
        contract_clauses.append(f"stay on {current_focus}")
    if next_step_hint:
        contract_clauses.append(f"use this next move: {next_step_hint}")
    if thread_summary:
        contract_clauses.append(f"resume the live thread around {thread_summary}")
    if thread_next_step:
        contract_clauses.append(f"carry forward this next move: {thread_next_step}")
    if resume_hint:
        contract_clauses.append(f"follow this resume hint: {resume_hint}")
    if failing_checks:
        contract_clauses.append(f"verify against {'; '.join(failing_checks)}")
    if review_queue_summary:
        contract_clauses.append(f"keep the review rhythm in view: {review_queue_summary}")
    if pace_signal in {"fragile", "gentle", "overloaded", "stalled", "recovery"}:
        contract_clauses.append("shrink scope before widening")
    if decision:
        contract_clauses.append(f"keep the latest finalized decision in view: {decision}")
    if blocker:
        contract_clauses.append(f"respect this blocker: {blocker}")
    if teaching_note:
        contract_clauses.append(f"follow this teaching note: {teaching_note}")
    if confidence:
        contract_clauses.append(f"coach confidence is {confidence}")
    if evidence:
        contract_clauses.append(f"ground the turn in {'; '.join(evidence)}")
    if has_prepared_resource_grounding:
        contract_clauses.append(
            "start from the prepared library grounding for this turn before widening to memory or general recall"
        )
        if resource_question_facets:
            contract_clauses.append(
                f"cover every explicitly requested resource facet: {'; '.join(resource_question_facets)}"
            )
        if scenario == "principle":
            contract_clauses.append(
                "answer the explicit resource question directly before you widen into generic teaching or another coaching lane"
            )
            if {
                "first viewport promise",
                "must not become",
            }.issubset({item.casefold() for item in resource_question_facets}):
                contract_clauses.append(
                    "state both the positive promise and the negative must-not-become boundary in the visible reply"
                )
    if resource_sequence_summary:
        contract_clauses.append(
            f"preserve this prepared library sequence exactly: {resource_sequence_summary}"
        )

    if isinstance(exercise_prompt, dict):
        success_signal = _compact_text(exercise_prompt.get("success_signal"), 96)
        fallback_step = _compact_text(exercise_prompt.get("fallback_step"), 96)
        if success_signal:
            contract_clauses.append(f"treat success as: {success_signal}")
        if fallback_step:
            contract_clauses.append(f"fallback: {fallback_step}")

    if isinstance(implementation_guide, dict):
        validation = _compact_list(implementation_guide.get("validation_strategy"), 2)
        if validation:
            contract_clauses.append(f"validate with {'; '.join(validation)}")

    first_look_next = _compact_text(
        context.get("first_look_recommended_next") or first_look_recommended_next_from_context(context),
        110,
    )
    if first_look_next and not _compact_text(context.get("active_task"), 48):
        contract_clauses.append(f"stay with this first-look next: {first_look_next}")
        contract_clauses.append("do not invent a plan, card, task, note, or resource")

    if not contract_clauses:
        return ""

    return _join_clauses(*contract_clauses) or ""


def first_look_recommended_next_from_context(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    direct = str(context.get("first_look_recommended_next") or "").strip()
    if direct:
        return direct
    understanding = context.get("workspace_understanding")
    if not isinstance(understanding, dict):
        return ""
    first = understanding.get("first_look_summary") or understanding.get("firstLookSummary")
    if not isinstance(first, dict):
        return ""
    return str(first.get("recommended_next_step") or first.get("recommendedNextStep") or "").strip()


def _growth_loop_honesty_block(coach_context: dict[str, Any] | None) -> str:
    if not isinstance(coach_context, dict):
        return ""
    pressure_blocks = coach_context.get("pressure_blocks_live_object_mint") is True
    if coach_context.get("formal_plan_mutation") is True:
        return ""
    # Chat-side "create a card" stays hint-only; mint is POST /training/generate-card.
    if not pressure_blocks and coach_context.get("explicit_learning_note_request") is True:
        return ""
    if coach_context.get("explicit_resource_import") is True:
        return ""
    if coach_context.get("explicit_resource_organize") is True:
        return ""
    first_look_next = first_look_recommended_next_from_context(coach_context)
    recovered = coach_context.get("plan_runtime_recovery")
    recovered_step = ""
    if isinstance(recovered, dict) and recovered.get("recovered") is True:
        recovered_step = str(recovered.get("current_step") or "").strip()
    lines = [
        "Do not speak as if you created a learning plan, training card, TaskSpec, learning note, or imported resource.",
        "Do not tell the learner to generate a plan, card, or task as the next step unless they explicitly asked.",
    ]
    if pressure_blocks:
        lines.append(
            "High urgency or tight time budget with no live plan/task/card: hint-only. "
            "Do not invent or mint a LearningPlan, TaskSpec, or training card."
        )
    if coach_context.get("explicit_training_card_request") is True:
        lines.append(
            "The learner asked for a practice card in chat: stay hint-only. "
            "Do not invent a card_id; minting is POST /training/generate-card only."
        )
    if recovered_step:
        lines.append(f"The next step is the recovered current step: {recovered_step}.")
    elif first_look_next:
        lines.append(f"The next step is the first-look recommended next: {first_look_next}.")
    else:
        lines.append("If there is no recovered current step, omit the next object honestly instead of inventing one.")
    return "\n\n## Growth Loop Honesty\n" + "\n".join(lines)


def _build_active_thread_block(context: dict[str, Any]) -> str:
    active_thread = context.get("active_thread")
    thread_summary = _compact_text(context.get("thread_summary"), 140) or ""
    thread_next_step = _compact_text(context.get("thread_next_step"), 110) or ""
    resume_hint = _compact_text(context.get("resume_hint"), 160) or ""
    focus_area = ""
    verified_result = ""
    blocker = ""
    decision = _compact_text(context.get("decision"), 96) or ""
    teaching_note = _compact_text(context.get("teaching_note"), 120) or ""
    confidence = _compact_text(context.get("confidence"), 32) or ""
    evidence = _compact_list(context.get("evidence"), 3)
    if isinstance(active_thread, dict):
        focus_area = _compact_text(active_thread.get("focus_area"), 96) or ""
        verified_result = _compact_text(active_thread.get("verified_result"), 96) or ""
        blocker = _compact_text(active_thread.get("blocker"), 96) or ""
        if not decision:
            decision = _compact_text(active_thread.get("decision"), 96) or ""
        if not teaching_note:
            teaching_note = _compact_text(active_thread.get("teaching_note"), 120) or ""
        if not confidence:
            confidence = _compact_text(active_thread.get("confidence"), 32) or ""
        if not evidence:
            evidence = _compact_list(active_thread.get("evidence"), 3)
        if not thread_summary:
            thread_summary = _compact_text(active_thread.get("summary"), 140) or focus_area
        if not thread_next_step:
            thread_next_step = _compact_text(active_thread.get("next_step"), 110) or ""
    if not any(
        (
            thread_summary,
            focus_area,
            verified_result,
            blocker,
            thread_next_step,
            resume_hint,
            decision,
            teaching_note,
            confidence,
            evidence,
        )
    ):
        return ""

    def _line(label: str, value: str) -> str:
        suffix = "" if value.endswith((".", "!", "?", "\u3002", "\uff01", "\uff1f")) else "."
        return f"- {label}: {value}{suffix}"

    lines: list[str] = []
    if thread_summary:
        lines.append(_line("Thread summary", thread_summary))
    if focus_area and focus_area != thread_summary:
        lines.append(_line("Focus area", focus_area))
    if verified_result:
        lines.append(_line("Last verified result", verified_result))
    if blocker:
        lines.append(_line("Current blocker", blocker))
    if thread_next_step:
        lines.append(_line("Next step", thread_next_step))
    if decision:
        lines.append(_line("Latest finalized decision", decision))
    if teaching_note:
        lines.append(_line("Teaching note", teaching_note))
    if confidence:
        lines.append(_line("Coach confidence", confidence))
    if evidence:
        lines.append(_line("Evidence", "; ".join(evidence)))
    if not resume_hint:
        resume_hint_parts: list[str] = []
        if thread_summary or focus_area:
            resume_hint_parts.append(f"Resume the live thread around {thread_summary or focus_area}.")
        if thread_next_step:
            resume_hint_parts.append(f"Keep the next move as {thread_next_step}.")
        if blocker:
            resume_hint_parts.append(f"Keep the blocker in view: {blocker}.")
            if verified_result:
                resume_hint_parts.append(f"Build on the verified result: {verified_result}.")
        if decision:
            resume_hint_parts.append(f"Keep the latest finalized decision in view: {decision}.")
        if teaching_note:
            resume_hint_parts.append(f"Carry this teaching note forward: {teaching_note}.")
        if confidence:
            resume_hint_parts.append(f"Coach confidence: {confidence}.")
        if evidence:
            resume_hint_parts.append(f"Evidence to anchor on: {'; '.join(evidence)}.")
        resume_hint = " ".join(resume_hint_parts).strip()
    if resume_hint:
        lines.append(_line("Resume hint", resume_hint))
    return "\n".join(lines)


DEFAULT_COACHING_HISTORY_TOKEN_BUDGET = 1800
_HISTORY_TRUNCATION_MARKER = "\n[earlier message shortened]\n"


def _coaching_history_token_units(value: str) -> int:
    """Estimate history cost without treating CJK text as four Latin characters."""
    return sum(
        4
        if (
            "\u3400" <= character <= "\u9fff"
            or "\uf900" <= character <= "\ufaff"
            or "\u3040" <= character <= "\u30ff"
            or "\uac00" <= character <= "\ud7af"
        )
        else 1
        for character in value
    )


def _estimate_coaching_history_tokens(value: str) -> int:
    units = _coaching_history_token_units(value)
    return (units + 3) // 4


def _take_history_text_within_budget(value: str, *, token_budget: int, from_end: bool = False) -> str:
    if token_budget <= 0:
        return ""
    unit_budget = token_budget * 4
    used_units = 0
    kept: list[str] = []
    characters = reversed(value) if from_end else value
    for character in characters:
        character_units = _coaching_history_token_units(character)
        if used_units + character_units > unit_budget:
            break
        kept.append(character)
        used_units += character_units
    if from_end:
        kept.reverse()
    return "".join(kept)


def _truncate_coaching_history_content(value: str, *, token_budget: int) -> str:
    if token_budget <= 0:
        return ""
    if _estimate_coaching_history_tokens(value) <= token_budget:
        return value

    marker_cost = _estimate_coaching_history_tokens(_HISTORY_TRUNCATION_MARKER)
    if token_budget <= marker_cost:
        return _take_history_text_within_budget(value, token_budget=token_budget)

    remaining = token_budget - marker_cost
    prefix_budget = max(1, remaining * 3 // 5)
    suffix_budget = max(0, remaining - prefix_budget)
    prefix = _take_history_text_within_budget(value, token_budget=prefix_budget)
    suffix = _take_history_text_within_budget(value, token_budget=suffix_budget, from_end=True)
    if not suffix:
        return prefix
    return f"{prefix}{_HISTORY_TRUNCATION_MARKER}{suffix}"


def _budget_coaching_history(
    history: list[dict[str, str]],
    *,
    history_limit: int,
    history_token_budget: int,
) -> list[dict[str, str]]:
    if history_limit <= 0 or history_token_budget <= 0:
        return []
    candidates = history[-history_limit:]
    if not candidates:
        return []

    recent = candidates[-2:]
    recent_cost = sum(_estimate_coaching_history_tokens(item["content"]) for item in recent)
    if recent_cost > history_token_budget:
        if len(recent) == 1 or history_token_budget == 1:
            newest = recent[-1]
            return [
                {
                    "role": newest["role"],
                    "content": _truncate_coaching_history_content(
                        newest["content"], token_budget=history_token_budget
                    ),
                }
            ]

        first_budget = max(1, history_token_budget // 2)
        second_budget = max(1, history_token_budget - first_budget)
        return [
            {
                "role": recent[0]["role"],
                "content": _truncate_coaching_history_content(
                    recent[0]["content"], token_budget=first_budget
                ),
            },
            {
                "role": recent[1]["role"],
                "content": _truncate_coaching_history_content(
                    recent[1]["content"], token_budget=second_budget
                ),
            },
        ]

    selected_reversed = list(reversed(recent))
    remaining = history_token_budget - recent_cost
    for item in reversed(candidates[:-2]):
        item_cost = _estimate_coaching_history_tokens(item["content"])
        if item_cost <= remaining:
            selected_reversed.append(item)
            remaining -= item_cost
            continue
        shortened = _truncate_coaching_history_content(item["content"], token_budget=remaining)
        if shortened:
            selected_reversed.append({"role": item["role"], "content": shortened})
        break
    return list(reversed(selected_reversed))


def build_coaching_messages(
    profile: UserProfile,
    message: str,
    current_file: dict[str, object] | None = None,
    response_language: str | None = None,
    answer_mode: str | None = None,
    coach_context: dict[str, Any] | None = None,
    *,
    agent_loop_enabled: bool = False,
    history: list[dict[str, str]] | None = None,
    history_limit: int = 12,
    history_token_budget: int = DEFAULT_COACHING_HISTORY_TOKEN_BUDGET,
) -> list[dict[str, str]]:
    """Build the canonical message list for one coaching turn.

    Parameters
    ----------
    history:
        Prior conversation messages (already in OpenAI canonical shape with
        ``role`` and ``content``). Inserted between the system prompt and the
        current user turn so the model sees the actual back-and-forth; this
        is what makes the coach a long-running thread rather than a series of
        amnesiac one-shots. ``role="system"`` items in ``history`` are
        dropped; the system prompt is always rebuilt fresh from the latest
        coaching context.
    history_limit:
        Keep at most this many of the most recent prior messages. The system
        prompt + current user message are NOT counted in this budget.
    history_token_budget:
        Bound retained history by an approximate token budget. The newest
        question and answer take priority over older turns.
    """
    _, current_file = _function_guidance_prompt_inputs(
        message,
        current_file,
        coach_context,
    )
    system_prompt = build_coaching_system_prompt(
        profile,
        response_language,
        answer_mode,
        message=message,
        current_file=current_file,
        coach_context=coach_context,
        agent_loop_enabled=agent_loop_enabled,
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    history_mode = str(extract_coaching_context(message, current_file, coach_context).get("history_mode") or "").strip().lower()
    suppress_history = history_mode == "fresh_lane"

    if history and not suppress_history:
        cleaned_history: list[dict[str, str]] = []
        for item in history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                # Drop system messages (we rebuild fresh) and empty/tool
                # entries; those would confuse a fresh-system run.
                continue
            cleaned_history.append({"role": role, "content": content})
        if cleaned_history:
            messages.extend(
                _budget_coaching_history(
                    cleaned_history,
                    history_limit=max(0, int(history_limit)),
                    history_token_budget=max(0, int(history_token_budget)),
                )
            )

    coaching_context = _prioritize_current_request_context(
        extract_coaching_context(message, current_file, coach_context)
    )
    coaching_context = _filter_function_guidance_entry_points(
        coaching_context,
        str(coaching_context.get("scenario") or ""),
    )
    runtime_context_blocks: list[str] = []
    first_turn = _looks_like_first_turn(coaching_context)
    raw_coach_defaults = coaching_context.get("coach_defaults")
    coach_defaults = raw_coach_defaults if isinstance(raw_coach_defaults, dict) else {}
    memory_scope = str(coach_defaults.get("memory_scope") or "").strip()
    working_set_mode = str(coach_defaults.get("working_set_mode") or "").strip()
    raw_workspace_memory_toggles = coach_defaults.get("workspace_memory_toggles")
    workspace_memory_toggles = (
        raw_workspace_memory_toggles if isinstance(raw_workspace_memory_toggles, dict) else {}
    )
    learner_context_block = _build_learner_context_block(coaching_context)
    if learner_context_block:
        runtime_context_blocks.append(f"Learner context:\n{learner_context_block}")

    active_thread_block = _build_active_thread_block(coaching_context)
    if active_thread_block:
        runtime_context_blocks.append(f"Active thread to resume:\n{active_thread_block}")

    resource_sequence_block = _build_resource_sequence_block(coaching_context)
    if resource_sequence_block:
        runtime_context_blocks.append(
            f"Prepared library sequence:\n{resource_sequence_block}"
        )

    function_guidance_starter_block = ""
    if not current_file:
        function_guidance_starter_block = _build_function_guidance_starter_block(coaching_context)
    if function_guidance_starter_block:
        runtime_context_blocks.append(
            f"Trainer sandbox starter:\n{function_guidance_starter_block}"
        )

    if current_file:
        file_content = current_file.get("content_excerpt") or current_file.get("content", "")
        file_span = current_file.get("content_line_span")
        file_strategy = current_file.get("content_strategy")
        file_block = (
            f"Current file: `{current_file.get('path', 'unknown')}` "
            f"({current_file.get('language_id', 'unknown')})"
        )
        if file_span:
            file_block += f"\nContext window: lines {file_span}"
        if file_strategy:
            file_block += f"\nContext strategy: {file_strategy}"
        file_block += (
            f"\n```{current_file.get('language_id', '')}\n"
            f"{file_content}\n```\n---"
        )
        file_context_parts = [file_block]

        selection_text = current_file.get("selection_text")
        selection_range = current_file.get("selection_range")
        if selection_text:
            file_context_parts.append(
                "\nSelected range: "
                f"{selection_range or 'unspecified'}\n```\n{selection_text}\n```"
            )

        include_patterns = bool(workspace_memory_toggles.get("patterns", True))
        include_resources = bool(workspace_memory_toggles.get("resources", False))
        diagnostics = current_file.get("diagnostics")
        if include_patterns and isinstance(diagnostics, list) and diagnostics:
            file_context_parts.append(
                "\nRecent diagnostics:\n" + "\n".join(f"- {item}" for item in diagnostics)
            )

        recent_edited_files = current_file.get("recent_edited_files")
        if include_patterns and isinstance(recent_edited_files, list) and recent_edited_files:
            file_context_parts.append(
                "\nRecently edited files:\n"
                + "\n".join(f"- {item}" for item in recent_edited_files[:5])
            )

        recent_files = current_file.get("recent_files")
        if include_patterns and isinstance(recent_files, list) and recent_files:
            file_context_parts.append(
                "\nRecently opened files:\n"
                + "\n".join(f"- {item}" for item in recent_files[:5])
            )

        related_files = current_file.get("related_files")
        if include_resources and isinstance(related_files, list) and related_files:
            related_lines: list[str] = []
            for item in related_files[:4]:
                if isinstance(item, dict):
                    line = f"- {item.get('path', 'unknown')} ({item.get('reason', 'related')})"
                    if item.get("line_span"):
                        line += f" lines {item.get('line_span')}"
                    related_lines.append(line)
            if related_lines:
                file_context_parts.append("\nRelated files:\n" + "\n".join(related_lines))

            related_snippets: list[str] = []
            for item in related_files[:3]:
                if isinstance(item, dict) and item.get("excerpt"):
                    related_snippets.append(
                        f"\n# {item.get('path', 'unknown')}\n```{current_file.get('language_id', '')}\n{item.get('excerpt', '')}\n```"
                    )
            if related_snippets:
                file_context_parts.append("\nRelated snippets:\n" + "\n".join(related_snippets))

        runtime_context_blocks.append("".join(file_context_parts))

    runtime_bias_lines: list[str] = []
    if memory_scope == "session":
        runtime_bias_lines.append(
            "Memory scope: session. Resume the live coaching thread first and keep the next answer tied to the latest step."
        )
    elif memory_scope == "personal":
        runtime_bias_lines.append(
            "Memory scope: personal. Bias toward repeated preferences, habits, and recurring friction."
        )
    elif memory_scope:
        runtime_bias_lines.append(
            "Memory scope: project. Bias toward the current workspace plan, active thread, and directly related artifacts."
        )
    if working_set_mode == "focused":
        runtime_bias_lines.append(
            "Working set mode: focused. Prefer the smallest local boundary and the nearest files only."
        )
    elif working_set_mode == "broad":
        runtime_bias_lines.append(
            "Working set mode: broad. It is acceptable to widen into nearby context when it improves verification."
        )
    if runtime_bias_lines:
        runtime_context_blocks.append(
            "Coaching defaults:\n" + "\n".join(f"- {line}" for line in runtime_bias_lines)
        )

    if first_turn:
        runtime_context_blocks.append(
            "First-turn rule:\n"
            "- The learner's final message is the task. If it asks a clear question, answer it directly before any orientation.\n"
            "- Ask one short follow-up only when the request is genuinely ambiguous or lacks information needed to answer."
        )

    if runtime_context_blocks:
        system_prompt += (
            "\n\n## Runtime Context\n"
            "Use this only as background. The final user message is the learner's actual request: answer it first, "
            "and do not treat these notes as a second request.\n\n"
            + "\n\n".join(runtime_context_blocks)
        )
        messages[0]["content"] = system_prompt

    messages.append({"role": "user", "content": message})
    return messages


def _looks_like_first_turn(context: dict[str, Any]) -> bool:
    if context.get("execution_ready"):
        return False

    current_focus = str(context.get("current_focus") or "").strip()
    summary = str(context.get("summary") or "").strip()
    next_step_hint = _extract_next_step_hint_text(context.get("next_step_hint")) or ""
    thread_summary = str(context.get("thread_summary") or "").strip()
    thread_next_step = str(context.get("thread_next_step") or "").strip()
    resume_hint = str(context.get("resume_hint") or "").strip()
    memory_evidence = context.get("memory_evidence") or []
    active_thread = context.get("active_thread")
    review_queue_summary = str(context.get("review_queue_summary") or "").strip()
    project_summary = str(context.get("project_summary") or "").strip()
    learning_outcomes = context.get("learning_outcomes") or []
    teaching_observations = context.get("teaching_observations") or []
    due_reviews = context.get("due_reviews") or []
    recalled_memory_summary = str(context.get("recalled_memory_summary") or "").strip()
    teaching_asset_summary = str(context.get("teaching_asset_summary") or "").strip()
    workspace_understanding_present = bool(project_summary or context.get("project_entry_points"))

    has_active_thread = False
    if isinstance(active_thread, dict):
        has_active_thread = any(
            str(active_thread.get(key) or "").strip()
            for key in (
                "focus_area",
                "summary",
                "next_step",
                "verified_result",
                "blocker",
                "decision",
                "teaching_note",
                "confidence",
            )
        ) or any(str(item).strip() for item in (active_thread.get("evidence") or []))
    context_evidence = context.get("evidence")
    has_active_thread = has_active_thread or any(
        str(context.get(key) or "").strip()
        for key in ("decision", "blocker", "teaching_note", "confidence")
    ) or (
        isinstance(context_evidence, list)
        and any(str(item).strip() for item in context_evidence)
    )
    has_memory_evidence = isinstance(memory_evidence, list) and any(str(item).strip() for item in memory_evidence)
    has_learning_history = isinstance(learning_outcomes, list) and any(
        isinstance(item, dict)
        and any(str(item.get(key) or "").strip() for key in ("concept", "summary", "outcome"))
        for item in learning_outcomes
    )
    has_due_reviews = isinstance(due_reviews, list) and any(
        isinstance(item, dict) and any(str(item.get(key) or "").strip() for key in ("concept", "reason"))
        for item in due_reviews
    )
    has_teaching_memory = any(
        (
            recalled_memory_summary,
            teaching_asset_summary,
            isinstance(teaching_observations, list)
            and any(str(item).strip() for item in teaching_observations),
        )
    )
    focus_from_live_thread = has_active_thread or bool(
        summary or next_step_hint or review_queue_summary or thread_summary or thread_next_step or resume_hint
    )
    memory_should_open_onboarding = not any(
        (
            has_learning_history,
            has_due_reviews,
            has_teaching_memory,
            has_memory_evidence,
            focus_from_live_thread,
        )
    )

    return memory_should_open_onboarding and not any(
        (
            summary,
            next_step_hint,
            review_queue_summary,
            has_active_thread,
            current_focus if not workspace_understanding_present else "",
        )
    )


def normalize_answer_policy(value: str | None) -> str:
    if value == "auto":
        return "guided"
    if value == "coach-first":
        return "guided"
    return value or "guided"




def _has_execution_ready_next_step_request(
    message: str | None,
    current_file: dict[str, object] | None = None,
) -> bool:
    if not message:
        return False

    lowered = " ".join(message.lower().split())
    scenario = infer_coaching_scenario(
        message,
        current_file,
        None,
        default="general",
    )
    next_step_tokens = (
        "next step",
        "next move",
        "first step",
        "smallest next step",
        "tiny next step",
        "give me the next step",
        "only tell me the next step",
        "what should i do next",
        "what do i do next",
        "what should i change first",
        "\u4e0b\u4e00\u6b65",
        "下一招",
        "最小可验证动作",
        "先改哪里",
        "只告诉我",
        "\u4e0b\u4e00\u62db",
        "\u6700\u5c0f\u52a8\u4f5c",
        "\u5148\u505a\u4ec0\u4e48",
        "先改哪里",
        "\u4e0b\u4e00\u6b65\u8be5\u505a\u4ec0\u4e48",
        "只告诉我",
    )
    scope_tokens = (
        "small",
        "smallest",
        "tiny",
        "minimal",
        "thin",
        "narrow",
        "focused",
        "verifiable",
        "teaching value",
        "very small",
        "很小",
        "小步",
        "一小步",
        "\u6700\u5c0f",
        "小步",
        "一小步",
        "\u53ef\u9a8c\u8bc1",
        "\u6559\u5b66\u4ef7\u503c",
        "\u5c0f\u8865\u4e01",
    )
    learn_first_tokens = (
        "learn -> try -> verify",
        "learn first",
        "teach me first",
        "explain first",
        "walk me through it first",
        "start by teaching",
        "\u5148\u5b66",
        "\u5148\u5b66\u4e60",
        "\u5148\u6559\u6211",
        "\u5148\u89e3\u91ca",
        "\u5148\u8bb2",
        "\u5148\u5e26\u6211",
        "\u5148\u5b66\u518d\u6d4b",
        "\u5148\u5b66\u518d\u8bd5",
        "\u4e0d\u8981\u4e00\u4e0a\u6765\u76f4\u63a5\u8003\u8bd5",
        "\u522b\u4e00\u4e0a\u6765\u5c31\u8003",
    )
    try_or_verify_tokens = (
        "try",
        "small try",
        "tiny try",
        "very small try",
        "verify",
        "verification",
        "small verification",
        "tiny verification",
        "test me",
        "check it",
        "\u8bd5\u4e00\u4e0b",
        "\u5f88\u5c0f\u7684 try",
        "\u5f88\u5c0f\u7684\u9a8c\u8bc1",
        "\u6700\u5c0f\u9a8c\u8bc1",
        "\u6700\u5c0f\u9a8c\u8bc1\u52a8\u4f5c",
        "\u518d\u6d4b",
        "\u518d\u8bd5",
        "\u518d\u9a8c\u8bc1",
        "\u6d4b\u8bd5\u6211",
        "\u9a8c\u8bc1\u52a8\u4f5c",
    )

    wants_next_step = any(token in lowered for token in next_step_tokens)
    wants_small_scope = any(token in lowered for token in scope_tokens)
    wants_learn_first = any(token in lowered for token in learn_first_tokens)
    wants_try_or_verify = any(token in lowered for token in try_or_verify_tokens)
    has_live_anchor = bool(
        current_file
        and any(
            str(current_file.get(key) or "").strip()
            for key in ("path", "selection_text", "content_excerpt", "content")
        )
    )
    guided_lane = scenario in {"remote_workspace", "debug_loop", "function_guidance"}

    if wants_next_step and wants_small_scope:
        return True
    if has_live_anchor and wants_learn_first and (wants_try_or_verify or wants_small_scope or wants_next_step):
        return True
    if guided_lane and wants_learn_first and (wants_try_or_verify or wants_small_scope or wants_next_step):
        return True
    return False


def extract_coaching_context(
    message: str | None,
    current_file: dict[str, object] | None = None,
    coach_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scenario = infer_coaching_scenario(message or "", current_file, coach_context)
    learner_signal = infer_learner_signal(message or "", current_file, coach_context)
    current_focus = _first_str(
        _nested_get(coach_context, "current_focus") if coach_context else None,
        _nested_get(coach_context, "coach_context", "current_focus") if coach_context else None,
        _nested_get(coach_context, "memory", "current_focus") if coach_context else None,
        _nested_get(current_file, "current_focus"),
        _nested_get(current_file, "coach_context", "current_focus"),
        _nested_get(current_file, "memory", "current_focus"),
    )
    recent_wins = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "recent_wins") if coach_context else None,
            _nested_get(coach_context, "coach_context", "recent_wins") if coach_context else None,
            _nested_get(coach_context, "memory", "recent_wins") if coach_context else None,
            _nested_get(current_file, "recent_wins"),
            _nested_get(current_file, "coach_context", "recent_wins"),
            _nested_get(current_file, "memory", "recent_wins"),
        )
    )
    weak_spots = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "weak_spots") if coach_context else None,
            _nested_get(coach_context, "weaknesses") if coach_context else None,
            _nested_get(coach_context, "coach_context", "weak_spots") if coach_context else None,
            _nested_get(coach_context, "memory", "weak_spots") if coach_context else None,
            _nested_get(coach_context, "memory", "weaknesses") if coach_context else None,
            _nested_get(current_file, "weak_spots"),
            _nested_get(current_file, "weaknesses"),
            _nested_get(current_file, "coach_context", "weak_spots"),
            _nested_get(current_file, "memory", "weak_spots"),
            _nested_get(current_file, "memory", "weaknesses"),
        )
    )
    due_reviews = _coerce_due_reviews(
        _first_value(
            _nested_get(coach_context, "due_reviews") if coach_context else None,
            _nested_get(coach_context, "coach_context", "due_reviews") if coach_context else None,
            _nested_get(coach_context, "memory", "due_reviews") if coach_context else None,
            _nested_get(current_file, "due_reviews"),
            _nested_get(current_file, "coach_context", "due_reviews"),
            _nested_get(current_file, "memory", "due_reviews"),
        )
    )
    requested_resources = _coerce_requested_resources(
        _first_value(
            _nested_get(coach_context, "requested_resources") if coach_context else None,
            _nested_get(coach_context, "coach_context", "requested_resources") if coach_context else None,
            _nested_get(current_file, "requested_resources"),
            _nested_get(current_file, "coach_context", "requested_resources"),
        )
    )
    resource_composer_intent = _coerce_resource_composer_intent(
        _first_value(
            _nested_get(coach_context, "resource_composer_intent") if coach_context else None,
            _nested_get(coach_context, "coach_context", "resource_composer_intent")
            if coach_context
            else None,
            _nested_get(current_file, "resource_composer_intent"),
            _nested_get(current_file, "coach_context", "resource_composer_intent"),
        )
    )
    requested_resource_summary = _first_str(
        _nested_get(coach_context, "requested_resource_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "requested_resource_summary") if coach_context else None,
        _nested_get(current_file, "requested_resource_summary"),
        _nested_get(current_file, "coach_context", "requested_resource_summary"),
    )
    resource_sequence_summary = _first_str(
        _nested_get(coach_context, "resource_sequence_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "resource_sequence_summary") if coach_context else None,
        _nested_get(current_file, "resource_sequence_summary"),
        _nested_get(current_file, "coach_context", "resource_sequence_summary"),
    )
    resource_sequence_guidance = _coerce_resource_sequence_guidance(
        _first_value(
            _nested_get(coach_context, "resource_sequence_guidance") if coach_context else None,
            _nested_get(coach_context, "coach_context", "resource_sequence_guidance")
            if coach_context
            else None,
            _nested_get(current_file, "resource_sequence_guidance"),
            _nested_get(current_file, "coach_context", "resource_sequence_guidance"),
        )
    )
    resource_question_facets = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "resource_question_facets") if coach_context else None,
            _nested_get(coach_context, "coach_context", "resource_question_facets")
            if coach_context
            else None,
            _nested_get(current_file, "resource_question_facets"),
            _nested_get(current_file, "coach_context", "resource_question_facets"),
        )
    )
    auto_resource_lookup = bool(
        _first_value(
            _nested_get(coach_context, "auto_resource_lookup") if coach_context else None,
            _nested_get(coach_context, "coach_context", "auto_resource_lookup") if coach_context else None,
            _nested_get(current_file, "auto_resource_lookup"),
            _nested_get(current_file, "coach_context", "auto_resource_lookup"),
        )
    )
    missing_resource_ids = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "missing_resource_ids") if coach_context else None,
            _nested_get(coach_context, "coach_context", "missing_resource_ids") if coach_context else None,
            _nested_get(current_file, "missing_resource_ids"),
            _nested_get(current_file, "coach_context", "missing_resource_ids"),
        )
    )
    teaching_observations = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "teaching_observations") if coach_context else None,
            _nested_get(coach_context, "coach_context", "teaching_observations") if coach_context else None,
            _nested_get(coach_context, "memory", "teaching_observations") if coach_context else None,
            _nested_get(current_file, "teaching_observations"),
            _nested_get(current_file, "coach_context", "teaching_observations"),
            _nested_get(current_file, "memory", "teaching_observations"),
        )
    )
    memory_evidence = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "memory_evidence") if coach_context else None,
            _nested_get(coach_context, "coach_context", "memory_evidence") if coach_context else None,
            _nested_get(current_file, "memory_evidence"),
            _nested_get(current_file, "coach_context", "memory_evidence"),
        )
    )
    teaching_assets = _first_value(
        _nested_get(coach_context, "selected_teaching_assets") if coach_context else None,
        _nested_get(coach_context, "coach_context", "selected_teaching_assets") if coach_context else None,
        _nested_get(coach_context, "teaching_assets") if coach_context else None,
        _nested_get(coach_context, "coach_context", "teaching_assets") if coach_context else None,
        _nested_get(coach_context, "memory", "teaching_assets") if coach_context else None,
        _nested_get(current_file, "selected_teaching_assets"),
        _nested_get(current_file, "coach_context", "selected_teaching_assets"),
        _nested_get(current_file, "teaching_assets"),
        _nested_get(current_file, "coach_context", "teaching_assets"),
    )
    recalled_coaching_memories = _first_value(
        _nested_get(coach_context, "recalled_coaching_memories") if coach_context else None,
        _nested_get(coach_context, "coach_context", "recalled_coaching_memories") if coach_context else None,
        _nested_get(current_file, "recalled_coaching_memories"),
        _nested_get(current_file, "coach_context", "recalled_coaching_memories"),
    )
    teaching_knowledge_catalog = _first_value(
        _nested_get(coach_context, "teaching_knowledge_catalog") if coach_context else None,
        _nested_get(coach_context, "coach_context", "teaching_knowledge_catalog") if coach_context else None,
        _nested_get(coach_context, "memory", "teaching_knowledge_catalog") if coach_context else None,
        _nested_get(current_file, "teaching_knowledge_catalog"),
        _nested_get(current_file, "coach_context", "teaching_knowledge_catalog"),
    )
    coaching_adaptation = _first_value(
        _nested_get(coach_context, "coaching_adaptation") if coach_context else None,
        _nested_get(coach_context, "coach_context", "coaching_adaptation") if coach_context else None,
        _nested_get(coach_context, "memory", "coaching_adaptation") if coach_context else None,
        _nested_get(current_file, "coaching_adaptation"),
        _nested_get(current_file, "coach_context", "coaching_adaptation"),
        _nested_get(current_file, "memory", "coaching_adaptation"),
    )
    review_rhythm = _first_str(
        _nested_get(coach_context, "review_rhythm") if coach_context else None,
        _nested_get(coach_context, "coach_context", "review_rhythm") if coach_context else None,
        _nested_get(coach_context, "memory", "review_rhythm") if coach_context else None,
        _nested_get(current_file, "review_rhythm"),
        _nested_get(current_file, "coach_context", "review_rhythm"),
        _nested_get(current_file, "memory", "review_rhythm"),
    )
    summary = _first_str(
        _nested_get(coach_context, "summary") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "summary") if coach_context else None,
        _nested_get(coach_context, "memory", "recent_summary") if coach_context else None,
        _nested_get(current_file, "summary"),
        _nested_get(current_file, "coaching_state", "summary"),
        _nested_get(current_file, "coach_context", "summary"),
        _nested_get(current_file, "memory", "recent_summary"),
    )
    next_step_hint = _first_str(
        _extract_next_step_hint_text(
            _nested_get(coach_context, "next_step_hint") if coach_context else None,
        ),
        _nested_get(coach_context, "next_step") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "next_step") if coach_context else None,
        _nested_get(coach_context, "coach_context", "next_step") if coach_context else None,
        _extract_next_step_hint_text(
            _nested_get(current_file, "next_step_hint") if current_file else None,
        ),
        _nested_get(current_file, "next_step"),
        _nested_get(current_file, "coaching_state", "next_step"),
        _nested_get(current_file, "coach_context", "next_step"),
    )
    encouragement = _first_str(
        _nested_get(coach_context, "encouragement") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "encouragement") if coach_context else None,
        _nested_get(coach_context, "coach_context", "encouragement") if coach_context else None,
        _nested_get(current_file, "encouragement"),
        _nested_get(current_file, "coaching_state", "encouragement"),
        _nested_get(current_file, "coach_context", "encouragement"),
    )
    active_thread = _first_value(
        _nested_get(coach_context, "active_thread") if coach_context else None,
        _nested_get(coach_context, "coach_context", "active_thread") if coach_context else None,
        _nested_get(current_file, "active_thread"),
        _nested_get(current_file, "coach_context", "active_thread"),
    )
    decision = _first_str(
        _nested_get(coach_context, "decision") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "decision") if coach_context else None,
        _nested_get(coach_context, "coach_context", "decision") if coach_context else None,
        _nested_get(current_file, "decision"),
        _nested_get(current_file, "coaching_state", "decision"),
        _nested_get(current_file, "coach_context", "decision"),
        _nested_get(active_thread, "decision") if isinstance(active_thread, dict) else None,
    )
    blocker = _first_str(
        _nested_get(coach_context, "blocker") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "blocker") if coach_context else None,
        _nested_get(coach_context, "coach_context", "blocker") if coach_context else None,
        _nested_get(current_file, "blocker"),
        _nested_get(current_file, "coaching_state", "blocker"),
        _nested_get(current_file, "coach_context", "blocker"),
        _nested_get(active_thread, "blocker") if isinstance(active_thread, dict) else None,
    )
    teaching_note = _first_str(
        _nested_get(coach_context, "teaching_note") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "teaching_note") if coach_context else None,
        _nested_get(coach_context, "coach_context", "teaching_note") if coach_context else None,
        _nested_get(current_file, "teaching_note"),
        _nested_get(current_file, "coaching_state", "teaching_note"),
        _nested_get(current_file, "coach_context", "teaching_note"),
        _nested_get(active_thread, "teaching_note") if isinstance(active_thread, dict) else None,
    )
    confidence = _first_str(
        _nested_get(coach_context, "confidence") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "confidence") if coach_context else None,
        _nested_get(coach_context, "coach_context", "confidence") if coach_context else None,
        _nested_get(current_file, "confidence"),
        _nested_get(current_file, "coaching_state", "confidence"),
        _nested_get(current_file, "coach_context", "confidence"),
        _nested_get(active_thread, "confidence") if isinstance(active_thread, dict) else None,
    )
    evidence = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "evidence") if coach_context else None,
            _nested_get(coach_context, "coaching_state", "evidence") if coach_context else None,
            _nested_get(coach_context, "coach_context", "evidence") if coach_context else None,
            _nested_get(current_file, "evidence"),
            _nested_get(current_file, "coaching_state", "evidence"),
            _nested_get(current_file, "coach_context", "evidence"),
            _nested_get(active_thread, "evidence") if isinstance(active_thread, dict) else None,
        )
    )
    thread_summary = _first_str(
        _nested_get(coach_context, "thread_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "thread_summary") if coach_context else None,
        _nested_get(current_file, "thread_summary"),
        _nested_get(current_file, "coach_context", "thread_summary"),
        _nested_get(active_thread, "summary") if isinstance(active_thread, dict) else None,
        _nested_get(active_thread, "focus_area") if isinstance(active_thread, dict) else None,
    )
    thread_next_step = _first_str(
        _extract_next_step_hint_text(
            _nested_get(coach_context, "thread_next_step") if coach_context else None,
        ),
        _nested_get(coach_context, "coach_context", "thread_next_step") if coach_context else None,
        _nested_get(current_file, "thread_next_step"),
        _nested_get(current_file, "coach_context", "thread_next_step"),
        _nested_get(active_thread, "next_step") if isinstance(active_thread, dict) else None,
    )
    resume_hint = _first_str(
        _nested_get(coach_context, "resume_thread") if coach_context else None,
        _nested_get(coach_context, "resume_hint") if coach_context else None,
        _nested_get(coach_context, "coach_context", "resume_thread") if coach_context else None,
        _nested_get(coach_context, "coach_context", "resume_hint") if coach_context else None,
        _nested_get(current_file, "resume_thread"),
        _nested_get(current_file, "resume_hint"),
        _nested_get(current_file, "coach_context", "resume_thread"),
        _nested_get(current_file, "coach_context", "resume_hint"),
    )
    if not resume_hint:
        resume_hint_parts: list[str] = []
        if thread_summary:
            resume_hint_parts.append(f"Resume the live thread around {thread_summary}.")
        if thread_next_step:
            resume_hint_parts.append(f"Keep the next move as {thread_next_step}.")
        if blocker:
            resume_hint_parts.append(f"Keep the blocker in view: {blocker}.")
        if isinstance(active_thread, dict):
            verified_result = _compact_text(active_thread.get("verified_result"), 96)
            if verified_result:
                resume_hint_parts.append(f"Build on the verified result: {verified_result}.")
        if decision:
            resume_hint_parts.append(f"Keep the latest finalized decision in view: {decision}.")
        if teaching_note:
            resume_hint_parts.append(f"Carry this teaching note forward: {teaching_note}.")
        if confidence:
            resume_hint_parts.append(f"Coach confidence: {confidence}.")
        if evidence:
            resume_hint_parts.append(f"Evidence to anchor on: {'; '.join(evidence)}.")
        resume_hint = " ".join(resume_hint_parts).strip()
    coach_defaults = _first_value(
        _nested_get(coach_context, "coach_defaults") if coach_context else None,
        _nested_get(coach_context, "coach_context", "coach_defaults") if coach_context else None,
        _nested_get(current_file, "coach_defaults"),
        _nested_get(current_file, "coach_context", "coach_defaults"),
    )
    exercise_prompt = _first_value(
        _nested_get(coach_context, "exercise_prompt") if coach_context else None,
        _nested_get(coach_context, "coach_context", "exercise_prompt") if coach_context else None,
        _nested_get(current_file, "exercise_prompt"),
        _nested_get(current_file, "coach_context", "exercise_prompt"),
    )
    project_sources = _first_value(
        _nested_get(coach_context, "project_sources") if coach_context else None,
        _nested_get(coach_context, "coach_context", "project_sources") if coach_context else None,
        _nested_get(current_file, "project_sources"),
        _nested_get(current_file, "coach_context", "project_sources"),
    )
    background_references = _first_value(
        _nested_get(coach_context, "background_references") if coach_context else None,
        _nested_get(coach_context, "coach_context", "background_references") if coach_context else None,
        _nested_get(current_file, "background_references"),
        _nested_get(current_file, "coach_context", "background_references"),
    )
    recent_background_findings = _first_value(
        _nested_get(coach_context, "recent_background_findings") if coach_context else None,
        _nested_get(coach_context, "coach_context", "recent_background_findings") if coach_context else None,
        _nested_get(current_file, "recent_background_findings"),
        _nested_get(current_file, "coach_context", "recent_background_findings"),
    )
    external_references = _first_value(
        _nested_get(coach_context, "external_references") if coach_context else None,
        _nested_get(coach_context, "coach_context", "external_references") if coach_context else None,
        _nested_get(current_file, "external_references"),
        _nested_get(current_file, "coach_context", "external_references"),
    )
    background_reference_summary = _first_str(
        _nested_get(coach_context, "background_reference_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "background_reference_summary") if coach_context else None,
        _nested_get(current_file, "background_reference_summary"),
        _nested_get(current_file, "coach_context", "background_reference_summary"),
    )
    requested_resource_ids = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "requested_resource_ids") if coach_context else None,
            _nested_get(coach_context, "coach_context", "requested_resource_ids")
            if coach_context
            else None,
            _nested_get(current_file, "requested_resource_ids"),
            _nested_get(current_file, "coach_context", "requested_resource_ids"),
        )
    )
    resource_fragments = _first_value(
        _nested_get(coach_context, "resource_fragments") if coach_context else None,
        _nested_get(coach_context, "coach_context", "resource_fragments") if coach_context else None,
        _nested_get(current_file, "resource_fragments"),
        _nested_get(current_file, "coach_context", "resource_fragments"),
    )
    current_resource_grounding = bool(
        requested_resource_ids or (isinstance(resource_fragments, list) and resource_fragments)
    )
    teaching_decision = _first_value(
        _nested_get(coach_context, "teaching_decision") if coach_context else None,
        _nested_get(coach_context, "coach_context", "teaching_decision") if coach_context else None,
        _nested_get(current_file, "teaching_decision"),
        _nested_get(current_file, "coach_context", "teaching_decision"),
    )
    learner_state = _first_value(
        _nested_get(coach_context, "learner_state") if coach_context else None,
        _nested_get(coach_context, "coach_context", "learner_state") if coach_context else None,
        _nested_get(current_file, "learner_state"),
        _nested_get(current_file, "coach_context", "learner_state"),
    )
    tone_decision = _first_value(
        _nested_get(coach_context, "tone_decision") if coach_context else None,
        _nested_get(coach_context, "coach_context", "tone_decision") if coach_context else None,
        _nested_get(current_file, "tone_decision"),
        _nested_get(current_file, "coach_context", "tone_decision"),
    )
    implementation_guide = _first_value(
        _nested_get(coach_context, "implementation_guide") if coach_context else None,
        _nested_get(coach_context, "coach_context", "implementation_guide") if coach_context else None,
        _nested_get(current_file, "implementation_guide"),
        _nested_get(current_file, "coach_context", "implementation_guide"),
    )
    project_ideas = _first_value(
        _nested_get(coach_context, "project_ideas") if coach_context else None,
        _nested_get(coach_context, "coach_context", "project_ideas") if coach_context else None,
        _nested_get(current_file, "project_ideas"),
        _nested_get(current_file, "coach_context", "project_ideas"),
    )
    adaptation_guide = _first_value(
        _nested_get(coach_context, "project_adaptation_guide") if coach_context else None,
        _nested_get(coach_context, "adaptation_guide") if coach_context else None,
        _nested_get(coach_context, "coach_context", "project_adaptation_guide") if coach_context else None,
        _nested_get(current_file, "project_adaptation_guide"),
        _nested_get(current_file, "adaptation_guide"),
        _nested_get(current_file, "coach_context", "project_adaptation_guide"),
    )
    principle_notes = _first_value(
        _nested_get(coach_context, "principle_notes") if coach_context else None,
        _nested_get(coach_context, "principle_note") if coach_context else None,
        _nested_get(coach_context, "coach_context", "principle_notes") if coach_context else None,
        _nested_get(current_file, "principle_notes"),
        _nested_get(current_file, "principle_note"),
        _nested_get(current_file, "coach_context", "principle_notes"),
    )
    selected_teaching_asset_ids = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "selected_teaching_asset_ids") if coach_context else None,
            _nested_get(coach_context, "teaching_asset_ids") if coach_context else None,
            _nested_get(coach_context, "coach_context", "selected_teaching_asset_ids") if coach_context else None,
            _nested_get(current_file, "selected_teaching_asset_ids"),
            _nested_get(current_file, "coach_context", "selected_teaching_asset_ids"),
        )
    )
    teaching_asset_summary = _first_str(
        _nested_get(coach_context, "teaching_asset_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "teaching_asset_summary") if coach_context else None,
        _nested_get(current_file, "teaching_asset_summary"),
        _nested_get(current_file, "coach_context", "teaching_asset_summary"),
    )
    recalled_memory_summary = _first_str(
        _nested_get(coach_context, "recalled_memory_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "recalled_memory_summary") if coach_context else None,
        _nested_get(current_file, "recalled_memory_summary"),
        _nested_get(current_file, "coach_context", "recalled_memory_summary"),
    )
    failing_checks = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "failing_checks") if coach_context else None,
            _nested_get(coach_context, "coach_context", "failing_checks") if coach_context else None,
            _nested_get(current_file, "failing_checks"),
            _nested_get(current_file, "coach_context", "failing_checks"),
        )
    )
    project_entry_points = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "project_entry_points") if coach_context else None,
            _nested_get(coach_context, "coach_context", "project_entry_points") if coach_context else None,
            _nested_get(current_file, "project_entry_points"),
            _nested_get(current_file, "coach_context", "project_entry_points"),
        )
    )
    project_summary = _first_str(
        _nested_get(coach_context, "project_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "project_summary") if coach_context else None,
        _nested_get(current_file, "project_summary"),
        _nested_get(current_file, "coach_context", "project_summary"),
    )
    function_guidance_starter = _first_value(
        _nested_get(coach_context, "function_guidance_starter") if coach_context else None,
        _nested_get(coach_context, "coach_context", "function_guidance_starter") if coach_context else None,
        _nested_get(current_file, "function_guidance_starter"),
        _nested_get(current_file, "coach_context", "function_guidance_starter"),
    )
    review_queue_summary = _first_str(
        _nested_get(coach_context, "review_queue_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "review_queue_summary") if coach_context else None,
        _nested_get(current_file, "review_queue_summary"),
        _nested_get(current_file, "coach_context", "review_queue_summary"),
    )
    next_review_due = _first_str(
        _nested_get(coach_context, "next_review_due") if coach_context else None,
        _nested_get(coach_context, "coach_context", "next_review_due") if coach_context else None,
        _nested_get(current_file, "next_review_due"),
        _nested_get(current_file, "coach_context", "next_review_due"),
    )
    pace_signal = _first_str(
        _nested_get(coach_context, "pace_signal") if coach_context else None,
        _nested_get(coach_context, "coach_context", "pace_signal") if coach_context else None,
        _nested_get(coach_context, "memory", "pace_signal") if coach_context else None,
        _nested_get(current_file, "pace_signal"),
        _nested_get(current_file, "coach_context", "pace_signal"),
        _nested_get(current_file, "memory", "pace_signal"),
    )
    relationship_stage = _first_str(
        _nested_get(coach_context, "relationship_stage") if coach_context else None,
        _nested_get(coach_context, "coach_context", "relationship_stage") if coach_context else None,
        _nested_get(current_file, "relationship_stage"),
        _nested_get(current_file, "coach_context", "relationship_stage"),
    )
    first_turn_priority = _first_str(
        _nested_get(coach_context, "first_turn_priority") if coach_context else None,
        _nested_get(coach_context, "coach_context", "first_turn_priority") if coach_context else None,
        _nested_get(current_file, "first_turn_priority"),
        _nested_get(current_file, "coach_context", "first_turn_priority"),
    )
    learning_outcomes = _first_value(
        _nested_get(coach_context, "learning_outcomes") if coach_context else None,
        _nested_get(coach_context, "memory", "learning_outcomes") if coach_context else None,
        _nested_get(coach_context, "coach_context", "learning_outcomes") if coach_context else None,
        _nested_get(current_file, "learning_outcomes"),
        _nested_get(current_file, "coach_context", "learning_outcomes"),
        _nested_get(current_file, "memory", "learning_outcomes"),
    )
    recent_teaching_signals = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "recent_teaching_signals") if coach_context else None,
            _nested_get(coach_context, "coach_context", "recent_teaching_signals") if coach_context else None,
            _nested_get(current_file, "recent_teaching_signals"),
            _nested_get(current_file, "coach_context", "recent_teaching_signals"),
        )
    )
    continuity_summary = _first_str(
        _nested_get(coach_context, "continuity_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "continuity_summary") if coach_context else None,
        _nested_get(current_file, "continuity_summary"),
        _nested_get(current_file, "coach_context", "continuity_summary"),
    )
    history_mode = _first_str(
        _nested_get(coach_context, "history_mode") if coach_context else None,
        _nested_get(coach_context, "coach_context", "history_mode") if coach_context else None,
        _nested_get(current_file, "history_mode"),
        _nested_get(current_file, "coach_context", "history_mode"),
    )
    active_view_value = _first_str(
        _nested_get(coach_context, "active_view") if coach_context else None,
        _nested_get(coach_context, "coach_context", "active_view") if coach_context else None,
        _nested_get(current_file, "active_view"),
        _nested_get(current_file, "coach_context", "active_view"),
    )
    active_view = active_view_value.lower() if active_view_value else None

    diagnostics = current_file.get("diagnostics") if current_file else None
    diagnostics_count = len(diagnostics) if isinstance(diagnostics, list) else 0
    return {
        "scenario": scenario,
        "active_view": active_view,
        "learner_signal": learner_signal,
        "execution_ready": _has_execution_ready_next_step_request(message, current_file),
        "current_focus": current_focus,
        "recent_wins": recent_wins,
        "weak_spots": weak_spots,
        "due_reviews": due_reviews,
        "requested_resources": requested_resources,
        "requested_resource_ids": requested_resource_ids,
        "resource_fragments": resource_fragments if isinstance(resource_fragments, list) else [],
        "resource_composer_intent": resource_composer_intent,
        "requested_resource_summary": requested_resource_summary,
        "resource_sequence_summary": resource_sequence_summary,
        "resource_sequence_guidance": resource_sequence_guidance,
        "resource_question_facets": resource_question_facets,
        "auto_resource_lookup": auto_resource_lookup,
        "missing_resource_ids": missing_resource_ids,
        "review_rhythm": review_rhythm,
        "memory_evidence": memory_evidence,
        "teaching_observations": teaching_observations,
        "teaching_assets": teaching_assets if isinstance(teaching_assets, list) else [],
        "recalled_coaching_memories": recalled_coaching_memories
        if isinstance(recalled_coaching_memories, list)
        else [],
        "teaching_knowledge_catalog": teaching_knowledge_catalog
        if isinstance(teaching_knowledge_catalog, dict)
        else {},
        "coaching_adaptation": coaching_adaptation if isinstance(coaching_adaptation, dict) else None,
        "summary": summary,
        "next_step_hint": next_step_hint,
        "thread_summary": thread_summary,
        "thread_next_step": thread_next_step,
        "resume_hint": resume_hint,
        "decision": decision,
        "blocker": blocker,
        "teaching_note": teaching_note,
        "confidence": confidence,
        "evidence": evidence,
        "encouragement": encouragement,
        "active_thread": active_thread,
        "coach_defaults": coach_defaults,
        "teaching_decision": teaching_decision if isinstance(teaching_decision, dict) else None,
        "learner_state": learner_state if isinstance(learner_state, dict) else None,
        "tone_decision": tone_decision if isinstance(tone_decision, dict) else None,
        "implementation_guide": implementation_guide if isinstance(implementation_guide, dict) else None,
        "project_ideas": project_ideas if isinstance(project_ideas, list) else [],
        "adaptation_guide": adaptation_guide if isinstance(adaptation_guide, dict) else None,
        "principle_notes": principle_notes if isinstance(principle_notes, dict) else None,
        "exercise_prompt": exercise_prompt if isinstance(exercise_prompt, dict) else None,
        "selected_teaching_asset_ids": selected_teaching_asset_ids,
        "teaching_asset_summary": teaching_asset_summary,
        "recalled_memory_summary": recalled_memory_summary,
        "failing_checks": failing_checks,
        "project_entry_points": project_entry_points,
        "project_summary": project_summary,
        "function_guidance_starter": function_guidance_starter
        if isinstance(function_guidance_starter, dict)
        else None,
        "review_queue_summary": review_queue_summary,
        "next_review_due": next_review_due,
        "pace_signal": pace_signal,
        "relationship_stage": relationship_stage,
        "first_turn_priority": first_turn_priority,
        "history_mode": history_mode,
        "learning_outcomes": learning_outcomes if isinstance(learning_outcomes, list) else [],
        "recent_teaching_signals": recent_teaching_signals,
        "continuity_summary": continuity_summary,
        "project_sources": project_sources if isinstance(project_sources, list) else [],
        "external_references": external_references if isinstance(external_references, list) else [],
        "background_references": background_references if isinstance(background_references, list) else [],
        "recent_background_findings": recent_background_findings
        if isinstance(recent_background_findings, list)
        else [],
        "background_reference_summary": background_reference_summary,
        "current_resource_grounding": current_resource_grounding,
        "diagnostics_count": diagnostics_count,
        "selection_range": current_file.get("selection_range") if current_file else None,
        "selection_text": current_file.get("selection_text") if current_file else None,
        "content_excerpt": current_file.get("content_excerpt") if current_file else None,
        "file_path": current_file.get("path") if current_file else None,
        "language_id": current_file.get("language_id") if current_file else None,
        "plan_runtime_recovery": (
            coach_context.get("plan_runtime_recovery")
            if isinstance(coach_context, dict)
            else None
        ),
        "first_look_recommended_next": first_look_recommended_next_from_context(
            coach_context if isinstance(coach_context, dict) else None
        ),
        "workspace_understanding": (
            coach_context.get("workspace_understanding")
            if isinstance(coach_context, dict)
            else None
        ),
        "active_task": _first_str(
            _nested_get(coach_context, "active_task") if coach_context else None,
            _nested_get(coach_context, "coach_context", "active_task") if coach_context else None,
        ),
    }


def coaching_scenario_label(scenario: str) -> str:
    return {
        "idea_implementation": "idea implementation guidance",
        "project_idea": "project idea mining",
        "project_idea_mining": "project idea mining",
        "project_adaptation": "existing project adaptation",
        "project_sourcing": "reference project scouting",
        "remote_workspace": "VS Code remote workspace coaching",
        "debug_loop": "VS Code debug loop coaching",
        "function_guidance": "function contract guidance",
        "principle": "principle explanation",
        "principle_explanation": "principle explanation",
        "review": "next step after review",
        "review_reflection": "review and reflection coaching",
        "plan": "plan and review rhythm",
        "task": "task execution coaching",
        "next_task": "next task coaching",
    }.get(scenario, "general coaching")


def learner_signal_label(signal: str) -> str:
    return {
        "steady": "steady",
        "blocked": "blocked",
        "uncertain": "uncertain",
        "curious": "curious",
    }.get(signal, "steady")


def active_view_label(active_view: str) -> str:
    return {
        "coach": "Coach view",
        "plan": "Plan view",
        "resources": "Resources view",
        "training": "Training view",
        "settings": "Settings view",
    }.get(active_view, "Coach view")


def active_view_guidance(active_view: str) -> str:
    return {
        "coach": "Treat this as the super-entry: answer directly, keep the next move small, and hand off explicitly when another view should own the work.",
        "plan": "Treat this as the formal plan lane: keep the reply compact and stage-first, covering current stage, why now, the smallest next step, verify method, and evidence gaps. If stale continuity conflicts with the current Plan request, answer the Plan request first and mention the return path instead of dragging the old lane. Do not silently rewrite the formal plan.",
        "resources": "Treat this as the resource and sandbox lane: prefer one compact locate -> download -> organize -> convert path, name the likely sandbox folder, and keep provenance plus sandbox boundaries explicit. If stale continuity conflicts with the current Resources request, handle the resource task first and mention the return path instead of drifting back into code explanation.",
        "training": "Treat this as the training lane: stay inside Learn -> Try -> Verify -> Reflect -> Return, never start with an exam when primer is missing, and prefer one dominant card with why now, problem, deliverable, verify, and return. If the learner asks for a card, give the card even when the scenario is remote, debug, or function guidance; keep the scenario inside the card instead of replacing the card with generic coaching.",
        "settings": "Treat this as the configuration lane: speak plainly about provider, model, runtime, and capability truth.",
    }.get(
        active_view,
        "Treat this as the super-entry: answer directly, keep the next move small, and hand off explicitly when another view should own the work.",
    )


def infer_coaching_scenario(
    message: str,
    current_file: dict[str, object] | None = None,
    coach_context: dict[str, Any] | None = None,
    *,
    default: str = "idea_implementation",
) -> str:
    lowered = message.lower()
    diagnostics = current_file.get("diagnostics") if current_file else None
    has_diagnostics = isinstance(diagnostics, list) and bool(diagnostics)

    explicit_scenario = _first_str(
        _nested_get(coach_context, "scenario") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "scenario") if coach_context else None,
        _nested_get(coach_context, "coach_context", "scenario") if coach_context else None,
        _nested_get(current_file, "scenario"),
        _nested_get(current_file, "coaching_state", "scenario"),
        _nested_get(current_file, "coach_context", "scenario"),
    )
    if explicit_scenario and _coaching_history_mode(current_file, coach_context) != "fresh_lane":
        return explicit_scenario

    def _has_any(*tokens: str) -> bool:
        return any(token in lowered for token in tokens)

    code_anchor_present = bool(
        is_code_like_current_file(current_file)
        and _first_str(
            _nested_get(current_file, "selection_text"),
            _nested_get(current_file, "content_excerpt"),
            _nested_get(current_file, "content"),
            _nested_get(current_file, "path"),
        )
    )
    if code_anchor_present and _has_any(
        "function",
        "method",
        "function contract",
        "contract",
        "parameter",
        "return",
        "signature help",
        "hover",
        "go to definition",
        "definition",
        "call site",
        "typescript",
        "ts function",
        "api call",
        "函数",
        "契约",
        "参数",
        "返回",
        "签名",
        "定义",
        "调用点",
        "悬停",
    ):
        return "function_guidance"

    rejects_broad_plan = _has_any(
        "not a whole study plan",
        "not a full study plan",
        "without turning this into a full study plan",
        "don't turn this into a full study plan",
        "don't turn this into a study plan",
        "don't make this a plan",
        "先别展开成总计划",
        "不要把它变成完整学习计划",
        "不要把它变成学习计划",
        "别把它变成学习计划",
        "先别变成计划",
        "不要变成计划",
    )
    language_learning_request = _has_any(
        "revise",
        "rewrite",
        "edit this paragraph",
        "project update paragraph",
        "improve this writing",
        "improve this sentence",
        "teach me the word",
        "vocabulary",
        "word meaning",
        "润色",
        "改写",
        "措辞",
        "段落",
        "句子",
        "单词",
        "词汇",
        "中文写作",
        "英文写作",
    )
    idea_request = _has_any(
        "implement",
        "build",
        "ship",
        "prototype",
        "mvp",
        "i want to build",
        "i want to make",
        "i have an idea",
        "turn this idea into",
        "make it real",
        "落地",
        "原型",
        "最小原型",
        "最小可验证",
        "做出来",
        "做成原型",
        "想实现",
        "想做",
        "我有个 idea",
        "我有一个 idea",
        "我有个 ai idea",
        "我有一个 ai idea",
    )
    resource_contract_request = _has_any(
        "design doc",
        "design document",
        "resource contract",
        "view contract",
        "first viewport promise",
        "must not become",
        "resources view",
        "resource view",
        "设计文档",
        "文档",
        "资料",
        "资源",
        "首屏承诺",
        "绝不能变成什么",
        "不能变成什么",
        "不要变成什么",
        "视图",
        "\u8bbe\u8ba1\u6587\u6863",
        "\u6587\u6863",
        "\u8d44\u6599",
        "\u8d44\u6e90",
        "\u9996\u5c4f\u627f\u8bfa",
        "\u7edd\u4e0d\u80fd\u53d8\u6210\u4ec0\u4e48",
        "\u4e0d\u80fd\u53d8\u6210\u4ec0\u4e48",
        "\u4e0d\u8981\u53d8\u6210\u4ec0\u4e48",
        "\u89c6\u56fe",
    )
    direct_explanation_request = _has_any(
        "tell me",
        "please tell me",
        "directly tell me",
        "what is",
        "what are",
        "what must not",
        "explain",
        "请告诉我",
        "直接告诉我",
        "请直接告诉我",
        "是什么",
        "讲解",
        "说明",
        "\u8bf7\u544a\u8bc9\u6211",
        "\u76f4\u63a5\u544a\u8bc9\u6211",
        "\u8bf7\u76f4\u63a5\u544a\u8bc9\u6211",
        "\u662f\u4ec0\u4e48",
        "\u8bb2\u89e3",
        "\u8bf4\u660e",
    )
    resource_contract_definition_request = (
        _has_any(
            "first viewport promise",
            "must not become",
            "resources view",
            "resource view",
            "\u9996\u5c4f\u627f\u8bfa",
            "\u7edd\u4e0d\u80fd\u53d8\u6210\u4ec0\u4e48",
            "\u8d44\u6599\u89c6\u56fe",
            "\u8d44\u6e90\u89c6\u56fe",
        )
        and _has_any(
            "first viewport promise",
            "must not become",
            "\u9996\u5c4f\u627f\u8bfa",
            "\u7edd\u4e0d\u80fd\u53d8\u6210\u4ec0\u4e48",
            "\u4e0d\u80fd\u53d8\u6210\u4ec0\u4e48",
            "\u4e0d\u8981\u53d8\u6210\u4ec0\u4e48",
        )
    )
    if (
        resource_contract_request
        and not has_diagnostics
        and (direct_explanation_request or resource_contract_definition_request)
    ):
        return "principle"

    if _has_any(
        "remote ssh",
        "remote workspace",
        "remote workflow",
        "remote workflows",
        "remote tunnel",
        "remote tunnels",
        "vscode remote",
        "vs code remote",
        "dev container",
        "dev containers",
        "devcontainer",
        "wsl",
        "ssh",
        "远程",
        "远程 ssh",
        "远程开发",
        "远程工作区",
        "开发容器",
        "容器",
        "隧道",
        "主机",
        "host label",
        "凭据模式",
        "工作区边界",
        "credential mode",
    ):
        return "remote_workspace"

    if _has_any(
        "signature help",
        "function signature",
        "function hint",
        "function guidance",
        "parameter hint",
        "hover",
        "peek definition",
        "jump to definition",
        "go to definition",
        "find all references",
        "intellisense",
        "autocomplete",
        "call site",
        "function call",
        "read a function",
        "what this function does",
        "function tips",
        "函数提示",
        "参数提示",
        "函数签名",
        "签名提示",
        "悬停",
        "查看定义",
        "跳转定义",
        "定义",
        "引用",
        "调用点",
        "看懂函数",
        "函数作用",
    ):
        return "function_guidance"

    function_subject = _has_any(
        "function",
        "method",
        "call site",
        "function contract",
        "typescript function",
        "ts function",
        "api call",
        "函数",
        "调用点",
        "函数契约",
        "陌生函数",
    )
    function_guidance_clue = _has_any(
        "before i edit",
        "before editing",
        "before i change",
        "before i touch",
        "unfamiliar",
        "understand this function",
        "read this function",
        "what this function expects",
        "contract",
        "parameter",
        "argument",
        "改之前",
        "编辑之前",
        "修改之前",
        "先看懂",
        "看懂",
        "契约",
        "参数",
        "实参",
        "形参",
    )
    if function_subject and function_guidance_clue:
        return "function_guidance"

    if _has_any(
        "launch.json",
        "breakpoint",
        "debug loop",
        "debug console",
        "debug session",
        "debugging in vs code",
        "debug in vs code",
        "debugging in vscode",
        "debug in vscode",
        "watch expression",
        "step into",
        "step over",
        "exception breakpoint",
        "run and debug",
        "debug python",
        "vscode debug",
        "vs code debug",
        "调试",
        "断点",
        "调试器",
        "调试控制台",
        "调用栈",
        "变量",
        "单步",
        "单步进入",
        "单步跳过",
        "监视",
        "异常断点",
        "运行和调试",
        "launch 配置",
        "在 vscode 里调试",
    ):
        return "debug_loop"

    if has_diagnostics or _has_any(
        "review",
        "fix",
        "failing",
        "fails",
        "error",
        "bug",
        "diagnose",
        "diagnosis",
        "what's wrong",
        "whats wrong",
        "what is wrong",
        "stack trace",
        "traceback",
        "复盘",
        "报错",
        "错误",
        "修复",
        "排错",
        "诊断",
        "排查",
        "为什么会挂",
        "为什么失败",
    ):
        return "review"

    if _has_any(
        "principle",
        "why",
        "explain",
        "mechanism",
        "为什么",
        "讲解",
        "原理",
        "机制",
    ):
        return "principle"

    if language_learning_request:
        return "general"

    if idea_request and rejects_broad_plan:
        return "idea_implementation"

    if _has_any(
        "refactor",
        "reshape",
        "adapt",
        "migrate",
        "existing project adaptation",
        "现有项目改造",
        "改造现有项目",
        "把一个现有项目改成",
        "把现有项目改成",
        "现有项目改成",
        "已有项目改成",
        "把这个现有项目改造",
        "基于现有项目",
        "在现有项目上改",
        "已有项目迁移",
        "项目迁移",
        "二次开发",
        "适配现有项目",
        "必须保持不变",
        "必须改变",
        "改造",
        "重构",
        "迁移",
        "适配",
    ):
        return "project_adaptation"

    if _has_any(
        "extract",
        "mine",
        "what should i build",
        "what can i practice",
        "练什么",
        "训练题",
        "训练任务",
        "从当前项目里提炼",
        "提炼",
        "当前项目",
    ):
        return "project_idea"

    if _has_any("plan", "roadmap", "milestone", "review cadence", "复习", "计划", "路线图"):
        return "plan"

    if _has_any("task", "/task", "任务", "练习题"):
        return "task"
    if _has_any("/next", "next task", "下一题", "下一个任务"):
        return "next_task"
    if idea_request:
        return "idea_implementation"

    return default


def infer_learner_signal(
    message: str,
    current_file: dict[str, object] | None = None,
    coach_context: dict[str, Any] | None = None,
) -> str:
    explicit_signal = _first_str(
        _nested_get(coach_context, "learner_signal") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "learner_signal") if coach_context else None,
        _nested_get(coach_context, "coach_context", "learner_signal") if coach_context else None,
        _nested_get(current_file, "learner_signal"),
        _nested_get(current_file, "coaching_state", "learner_signal"),
        _nested_get(current_file, "coach_context", "learner_signal"),
    )
    if explicit_signal and _coaching_history_mode(current_file, coach_context) != "fresh_lane":
        return explicit_signal

    lowered = message.lower()
    if any(
        token in lowered
        for token in (
            "stuck",
            "blocked",
            "can't",
            "cannot",
            "broken",
            "卡住了",
            "搞不定",
            "不会",
            "不行",
            "崩了",
        )
    ):
        return "blocked"
    if any(
        token in lowered
        for token in (
            "confused",
            "not sure",
            "uncertain",
            "maybe",
            "不确定",
            "没把握",
            "大概",
            "有点糊涂",
        )
    ):
        return "uncertain"
    if any(
        token in lowered
        for token in (
            "why",
            "how",
            "curious",
            "understand",
            "原理",
            "想试试",
            "想弄懂",
            "好奇",
        )
    ):
        return "curious"
    return "steady"


def _prompt_visible_teaching_mode(context: dict[str, Any]) -> str | None:
    teaching_decision = context.get("teaching_decision")
    if not isinstance(teaching_decision, dict):
        return None
    mode = _compact_text(teaching_decision.get("mode"), 48)
    if not mode:
        return None
    scenario = str(context.get("scenario") or "").strip().lower()
    if scenario in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"} and mode in {
        "review_reflection",
        "guided",
        "onboarding",
    }:
        return None
    return mode


def _compact_text(value: object | None, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 1)].rstrip()}..."


def _compact_list(values: object | None, limit: int = 2) -> list[str]:
    if not isinstance(values, list):
        return []
    compacted: list[str] = []
    for item in values:
        text = _compact_text(item, 96)
        if text:
            compacted.append(text)
        if len(compacted) >= limit:
            break
    return compacted


def _join_clauses(*clauses: str | None) -> str | None:
    parts = [clause.strip() for clause in clauses if isinstance(clause, str) and clause.strip()]
    if not parts:
        return None
    return " ".join(parts)


def _first_external_reference_summary(context: dict[str, Any]) -> str | None:
    references = context.get("external_references")
    if not isinstance(references, list) or not references:
        references = context.get("background_references")
    if isinstance(references, list):
        for item in references[:2]:
            if not isinstance(item, dict):
                continue
            evidence_summary = _compact_text(item.get("evidence_summary"), 110)
            if evidence_summary:
                source = _compact_text(item.get("source"), 48)
                if source:
                    return f"{evidence_summary} ({source})"
                return evidence_summary
            summary = _compact_text(item.get("summary"), 110)
            if summary:
                source = _compact_text(item.get("source"), 48)
                if source:
                    return f"{summary} ({source})"
                return summary
            snippet = _compact_text(item.get("snippet"), 110)
            source = _compact_text(item.get("source"), 48)
            if snippet and source:
                return f"{snippet} ({source})"
            if snippet:
                return snippet
    findings = context.get("recent_background_findings")
    if isinstance(findings, list):
        for item in findings[:1]:
            if not isinstance(item, dict):
                continue
            focus_area = _compact_text(item.get("focus_area"), 48)
            snippet = _compact_text(item.get("snippet"), 110)
            if focus_area and snippet:
                return f"{focus_area}: {snippet}"
            if snippet:
                return snippet
    return None


def _first_project_idea_summary(context: dict[str, Any]) -> str | None:
    project_ideas = context.get("project_ideas")
    if not isinstance(project_ideas, list):
        return None
    for item in project_ideas[:1]:
        if not isinstance(item, dict):
            continue
        title = _compact_text(item.get("title"), 72)
        first_step = _compact_text(item.get("first_step"), 120)
        why_now = _compact_text(item.get("why_now"), 110)
        if title and first_step:
            return f"{title}. First step: {first_step}"
        if title and why_now:
            return f"{title}. Why now: {why_now}"
        if title:
            return title
    return None


def _first_project_source_summary(context: dict[str, Any]) -> str | None:
    project_sources = context.get("project_sources")
    if not isinstance(project_sources, list):
        return None
    for item in project_sources[:1]:
        if not isinstance(item, dict):
            continue
        title = _compact_text(item.get("title"), 72)
        repo_hint = _compact_text(item.get("repo_hint"), 120)
        if title and repo_hint:
            return f"{title}. Repo angle: {repo_hint}"
        if title:
            return title
    return None


def _first_learning_outcome_summary(context: dict[str, Any]) -> str | None:
    outcomes = context.get("learning_outcomes")
    if not isinstance(outcomes, list):
        return None
    for item in outcomes[:1]:
        if not isinstance(item, dict):
            continue
        concept = _compact_text(item.get("concept"), 56)
        outcome = _compact_text(item.get("outcome"), 48)
        summary = _compact_text(item.get("summary"), 110)
        return _join_clauses(
            f"Latest outcome: {concept} / {outcome}." if concept or outcome else None,
            summary,
        )
    return None


def _build_context_block(context: dict[str, Any]) -> str:
    scenario = coaching_scenario_label(str(context.get("scenario", "idea_implementation")))
    signal = learner_signal_label(str(context.get("learner_signal", "steady")))
    lines: list[str] = [f"- Main lane: {scenario}. Learner signal: {signal}."]
    active_view = _compact_text(context.get("active_view"), 24)
    if active_view:
        lines.append(
            f"- Input surface: {active_view_label(active_view)}. {active_view_guidance(active_view)}"
        )
    recovery = context.get("plan_runtime_recovery")
    if isinstance(recovery, dict) and recovery.get("recovered") is True:
        recovered_step = _compact_text(recovery.get("current_step"), 120)
        recovered_blocker = _compact_text(recovery.get("blocked_reason"), 140)
        recovered_action = _compact_text(recovery.get("action"), 32)
        recovery_clauses: list[str] = ["Resume recovered plan runtime. Do not invent a formal plan."]
        if recovered_action:
            recovery_clauses.append(f"Action: {recovered_action}.")
        if recovered_step:
            recovery_clauses.append(f"Recovered step: {recovered_step}.")
        if recovered_blocker:
            recovery_clauses.append(f"Recovered blocker: {recovered_blocker}.")
        recovery_line = _join_clauses(*recovery_clauses)
        if recovery_line:
            lines.append(f"- {recovery_line}")

    resource_composer_mode = _resource_composer_mode(context)
    if resource_composer_mode:
        lines.append(f"- Resource task: {_resource_composer_focus(resource_composer_mode)}.")

    current_focus = _compact_text(context.get("current_focus"), 120)
    continuity_summary = _compact_text(context.get("continuity_summary"), 140)
    thread_clauses: list[str] = []
    if current_focus:
        thread_clauses.append(f"Stay with {current_focus}.")
    if continuity_summary:
        thread_clauses.append(f"Continuity thread: {continuity_summary}.")
    thread_line = _join_clauses(*thread_clauses)
    if thread_line:
        lines.append(f"- {thread_line}")

    teaching_decision = context.get("teaching_decision")
    coaching_adaptation = context.get("coaching_adaptation")
    tone_decision = context.get("tone_decision")
    learner_state = context.get("learner_state")
    coaching_bias_clauses: list[str] = []
    if isinstance(teaching_decision, dict):
        mode = _prompt_visible_teaching_mode(context)
        primary_goal = _compact_text(teaching_decision.get("primary_goal"), 110)
        reason = _compact_text(teaching_decision.get("reason"), 120)
        if mode:
            coaching_bias_clauses.append(f"Teaching mode: {mode}.")
        if primary_goal:
            coaching_bias_clauses.append(f"Primary teaching goal: {primary_goal}.")
        if reason:
            coaching_bias_clauses.append(f"Why this fits: {reason}.")
    if isinstance(coaching_adaptation, dict):
        adaptation_summary = _compact_text(coaching_adaptation.get("summary"), 140)
        if adaptation_summary:
            coaching_bias_clauses.append(f"Adaptation bias: {adaptation_summary}.")
    if isinstance(tone_decision, dict):
        tone = _compact_text(tone_decision.get("tone"), 32)
        verbosity = _compact_text(tone_decision.get("verbosity_bias"), 32)
        if tone or verbosity:
            coaching_bias_clauses.append(
                f"Keep the tone {tone or 'steady'} and verbosity {verbosity or 'medium'}."
            )
        if tone_decision.get("avoid_overwhelm"):
            coaching_bias_clauses.append("Keep cognitive load low.")
    if isinstance(learner_state, dict):
        confidence = learner_state.get("current_confidence")
        frustration = learner_state.get("frustration_level")
        if isinstance(confidence, (int, float)) or isinstance(frustration, (int, float)):
            coaching_bias_clauses.append(
                f"Confidence / frustration: {confidence or 0} / {frustration or 0}."
            )
        if learner_state.get("needs_rescue"):
            coaching_bias_clauses.append("Bias toward rescue over breadth.")
        if learner_state.get("needs_review"):
            coaching_bias_clauses.append("Expect a follow-up review loop.")
    coaching_bias_line = _join_clauses(*coaching_bias_clauses)
    if coaching_bias_line:
        lines.append(f"- {coaching_bias_line}")

    summary = _compact_text(context.get("summary"), 140)
    recent_wins = _compact_list(context.get("recent_wins"), 1)
    weak_spots = _compact_list(context.get("weak_spots"), 2)
    recalled_memory_summary = _compact_text(context.get("recalled_memory_summary"), 140)
    memory_evidence = _compact_list(context.get("memory_evidence"), 2)
    memory_clauses: list[str] = []
    if summary:
        memory_clauses.append(f"Recent memory summary: {summary}.")
    if recent_wins:
        memory_clauses.append(f"Recent win to preserve: {recent_wins[0]}.")
    if weak_spots:
        memory_clauses.append(f"Pattern to watch: {'; '.join(weak_spots)}.")
    if recalled_memory_summary:
        memory_clauses.append(f"Useful recalled memory: {recalled_memory_summary}.")
    if memory_evidence:
        memory_clauses.append(f"Continuity evidence: {'; '.join(memory_evidence)}.")
    memory_line = _join_clauses(*memory_clauses)
    if memory_line:
        lines.append(f"- {memory_line}")

    review_rhythm = _compact_text(context.get("review_rhythm"), 120)
    due_reviews = context.get("due_reviews") or []
    next_review_due = _compact_text(context.get("next_review_due"), 72)
    review_queue_summary = _compact_text(context.get("review_queue_summary"), 120)
    pace_signal = _compact_text(context.get("pace_signal"), 48)
    review_clauses: list[str] = []
    if review_rhythm:
        review_clauses.append(f"Review rhythm: {review_rhythm}.")
    if isinstance(due_reviews, list) and due_reviews:
        due_text = "; ".join(_format_due_review_item(item) for item in due_reviews[:2])
        if due_text:
            review_clauses.append(f"Due review points: {due_text}.")
    if review_queue_summary:
        review_clauses.append(f"Review queue: {review_queue_summary}.")
    if next_review_due:
        review_clauses.append(f"Next review due: {next_review_due}.")
    if pace_signal:
        review_clauses.append(f"Pace signal: {pace_signal}.")
    review_line = _join_clauses(*review_clauses)
    if review_line:
        lines.append(f"- {review_line}")

    grounding_clauses: list[str] = []
    requested_resource_summary = _compact_text(context.get("requested_resource_summary"), 120)
    if requested_resource_summary:
        grounding_clauses.append(f"Requested grounding: {requested_resource_summary}.")
    resource_fragments = context.get("resource_fragments")
    if isinstance(resource_fragments, list) and resource_fragments:
        evidence_lines: list[str] = []
        for item in resource_fragments[:4]:
            if not isinstance(item, dict):
                continue
            resource_id = _compact_text(item.get("resource_id") or item.get("id"), 80)
            title = _compact_text(item.get("title") or resource_id or "resource", 100)
            snippet = _compact_text(
                item.get("snippet") or item.get("summary") or item.get("evidence_summary"),
                260,
            )
            if not snippet:
                continue
            label = f"{title} ({resource_id})" if resource_id else title
            evidence_lines.append(f"{label}: {snippet}")
        if evidence_lines:
            grounding_clauses.append(
                "Prepared library evidence: " + " | ".join(evidence_lines)
            )
    else:
        requested_resource_ids = _compact_list(context.get("requested_resource_ids"), 4)
        if requested_resource_ids:
            grounding_clauses.append(
                f"Prepared resource IDs: {', '.join(requested_resource_ids)}. Search them before making claims."
            )
    resource_question_facets = _compact_list(context.get("resource_question_facets"), 4)
    if resource_question_facets:
        grounding_clauses.append(f"Requested resource facets: {'; '.join(resource_question_facets)}.")
    teaching_asset_summary = _compact_text(context.get("teaching_asset_summary"), 120)
    if teaching_asset_summary:
        grounding_clauses.append(f"Preferred teaching asset: {teaching_asset_summary}.")
    background_reference_summary = _compact_text(context.get("background_reference_summary"), 120)
    if background_reference_summary:
        grounding_clauses.append(f"Background research summary: {background_reference_summary}.")
    reference_summary = _first_external_reference_summary(context)
    if reference_summary:
        grounding_clauses.append(f"One useful reference: {reference_summary}.")
    grounding_line = _join_clauses(*grounding_clauses)
    if grounding_line:
        lines.append(f"- {grounding_line}")

    execution_clauses: list[str] = []
    failing_checks = _compact_list(context.get("failing_checks"), 3)
    if failing_checks:
        execution_clauses.append(f"Reduce these failing checks first: {'; '.join(failing_checks)}.")
    next_step_hint = _compact_text(_extract_next_step_hint_text(context.get("next_step_hint")), 110)
    if next_step_hint:
        execution_clauses.append(f"Prior next-step hint: {next_step_hint}.")
    implementation_guide = context.get("implementation_guide")
    if isinstance(implementation_guide, dict):
        current_step = _compact_text(implementation_guide.get("current_step"), 120)
        scope_boundary = _compact_text(implementation_guide.get("scope_boundary"), 120)
        validation = implementation_guide.get("validation_strategy")
        validation_items = _compact_list(validation, 2)
        if current_step:
            execution_clauses.append(f"Implementation anchor: {current_step}.")
        if scope_boundary:
            execution_clauses.append(f"Scope boundary: {scope_boundary}.")
        if validation_items:
            execution_clauses.append(f"Verification anchor: {'; '.join(validation_items)}.")
    project_entry_points = _compact_list(context.get("project_entry_points"), 3)
    if project_entry_points:
        execution_clauses.append(f"Code entry points to name: {'; '.join(project_entry_points)}.")
    project_summary = _compact_text(context.get("project_summary"), 120)
    if project_summary:
        execution_clauses.append(f"Project summary: {project_summary}.")
    function_guidance_starter = context.get("function_guidance_starter")
    if isinstance(function_guidance_starter, dict):
        starter_call_site = _compact_text(function_guidance_starter.get("call_site_path"), 110)
        starter_definition = _compact_text(function_guidance_starter.get("definition_path"), 110)
        starter_boundary = _compact_text(function_guidance_starter.get("boundary_note"), 140)
        starter_instruction = _compact_text(function_guidance_starter.get("coach_instruction"), 140)
        starter_clauses: list[str] = []
        if starter_call_site or starter_definition:
            starter_clauses.append(
                "Trainer sandbox starter: "
                f"begin in {starter_call_site or 'the prepared call site'}"
                + (
                    f", then jump to {starter_definition}."
                    if starter_definition
                    else "."
                )
            )
        if starter_instruction:
            starter_clauses.append(starter_instruction)
        if starter_boundary:
            starter_clauses.append(f"Boundary note: {starter_boundary}.")
        execution_clauses.extend(starter_clauses)
    project_idea_summary = _first_project_idea_summary(context)
    if project_idea_summary:
        execution_clauses.append(f"Project idea worth reusing: {project_idea_summary}.")
    project_source_summary = _first_project_source_summary(context)
    if project_source_summary:
        execution_clauses.append(f"Project source angle: {project_source_summary}.")
    adaptation_guide = context.get("project_adaptation_guide") or context.get("adaptation_guide")
    if isinstance(adaptation_guide, dict):
        first_migration_step = _compact_text(adaptation_guide.get("first_migration_step"), 120)
        if first_migration_step:
            execution_clauses.append(f"Adaptation anchor: {first_migration_step}.")
    principle_notes = context.get("principle_notes") or context.get("principle_note")
    if isinstance(principle_notes, dict):
        current_principle = _compact_text(principle_notes.get("current_principle"), 96)
        apply_now = _compact_text(principle_notes.get("apply_now"), 110)
        why_it_matters = _compact_text(principle_notes.get("why_it_matters"), 110)
        if current_principle:
            execution_clauses.append(f"Principle anchor: {current_principle}.")
        if apply_now:
            execution_clauses.append(f"Apply-now move: {apply_now}.")
        if why_it_matters:
            execution_clauses.append(f"Why it matters: {why_it_matters}.")
    exercise_prompt = context.get("exercise_prompt")
    if isinstance(exercise_prompt, dict):
        prompt = _compact_text(exercise_prompt.get("prompt"), 110)
        success_signal = _compact_text(exercise_prompt.get("success_signal"), 110)
        fallback_step = _compact_text(exercise_prompt.get("fallback_step"), 110)
        if prompt:
            execution_clauses.append(f"Exercise prompt: {prompt}.")
        if success_signal:
            execution_clauses.append(f"Success signal: {success_signal}.")
        if fallback_step:
            execution_clauses.append(f"Fallback step: {fallback_step}.")
    learning_outcome_summary = _first_learning_outcome_summary(context)
    if learning_outcome_summary:
        execution_clauses.append(learning_outcome_summary)
    selection_range = _compact_text(context.get("selection_range"), 48)
    selection_text = _compact_text(context.get("selection_text"), 140)
    diagnostics_count = context.get("diagnostics_count")
    if scenario == "function_guidance" and (selection_text or context.get("file_path")):
        execution_clauses.append(
            "Use the attached current file or selection as the first live function anchor before asking for another call site."
        )
    if scenario == "remote_workspace" and context.get("execution_ready"):
        execution_clauses.append(
            "Teach the remote boundary first, then end with one minimal verification move before asking for more setup detail."
        )
    if selection_range:
        execution_clauses.append(f"Selection attached: {selection_range}.")
    if diagnostics_count:
        execution_clauses.append(f"Diagnostics attached: {diagnostics_count}.")
    execution_line = _join_clauses(*execution_clauses)
    if execution_line:
        lines.append(f"- {execution_line}")

    return "\n".join(lines)


def _build_learner_context_block(context: dict[str, Any]) -> str:
    scenario = str(context.get("scenario", "idea_implementation"))
    signal = str(context.get("learner_signal", "steady"))
    lines: list[str] = [f"- Treat this as `{scenario}` with a `{signal}` learner."]
    active_view = _compact_text(context.get("active_view"), 24)
    if active_view:
        lines.append(f"- The learner is speaking from {active_view_label(active_view)}.")

    relationship_stage = _compact_text(context.get("relationship_stage"), 48)
    first_turn_priority = _compact_text(context.get("first_turn_priority"), 120)
    current_focus = _compact_text(context.get("current_focus"), 110)
    continuity_summary = _compact_text(context.get("continuity_summary"), 120)
    thread_clauses: list[str] = []
    if relationship_stage:
        thread_clauses.append(f"Relationship stage: {relationship_stage}.")
    if first_turn_priority:
        thread_clauses.append(f"First-turn priority: {first_turn_priority}.")
    if current_focus:
        thread_clauses.append(f"Current focus: {current_focus}.")
    if continuity_summary:
        thread_clauses.append(f"Continuity thread: {continuity_summary}.")
    thread_line = _join_clauses(*thread_clauses)
    if thread_line:
        lines.append(f"- {thread_line}")

    learner_profile_clauses: list[str] = []
    learner_name = _compact_text(context.get("learner_name"), 40)
    target_project = _compact_text(context.get("target_project"), 96)
    preferred_stack = _compact_text(context.get("preferred_stack"), 96)
    preferred_rhythm = _compact_text(context.get("preferred_rhythm"), 56)
    preferred_learning_mode = _compact_text(context.get("preferred_learning_mode"), 56)
    onboarding_request = _compact_text(context.get("onboarding_request"), 110)
    if learner_name:
        learner_profile_clauses.append(f"Learner name: {learner_name}.")
    if target_project:
        learner_profile_clauses.append(f"Target project: {target_project}.")
    if preferred_stack:
        learner_profile_clauses.append(f"Preferred stack or direction: {preferred_stack}.")
    if preferred_rhythm:
        learner_profile_clauses.append(f"Preferred rhythm: {preferred_rhythm}.")
    if preferred_learning_mode:
        learner_profile_clauses.append(f"Preferred coaching mode: {preferred_learning_mode}.")
    if onboarding_request:
        learner_profile_clauses.append(f"This round mainly wants to move: {onboarding_request}.")
    learner_profile_line = _join_clauses(*learner_profile_clauses)
    if learner_profile_line:
        lines.append(f"- {learner_profile_line}")

    coaching_adaptation = context.get("coaching_adaptation")
    tone_decision = context.get("tone_decision")
    teaching_decision = context.get("teaching_decision")
    bias_clauses: list[str] = []
    if isinstance(teaching_decision, dict):
        mode = _prompt_visible_teaching_mode(context)
        primary_goal = _compact_text(teaching_decision.get("primary_goal"), 110)
        if mode:
            bias_clauses.append(f"Teaching mode: {mode}.")
        if primary_goal:
            bias_clauses.append(f"Teaching goal: {primary_goal}.")
    if isinstance(coaching_adaptation, dict):
        adaptation_summary = _compact_text(coaching_adaptation.get("summary"), 140)
        if adaptation_summary:
            bias_clauses.append(f"Adaptive bias: {adaptation_summary}.")
    if isinstance(tone_decision, dict):
        tone = _compact_text(tone_decision.get("tone"), 32)
        verbosity = _compact_text(tone_decision.get("verbosity_bias"), 32)
        if tone or verbosity:
            bias_clauses.append(f"Tone / verbosity: {tone or 'steady'} / {verbosity or 'medium'}.")
    bias_line = _join_clauses(*bias_clauses)
    if bias_line:
        lines.append(f"- {bias_line}")

    memory_clauses: list[str] = []
    recent_wins = _compact_list(context.get("recent_wins"), 1)
    weak_spots = _compact_list(context.get("weak_spots"), 2)
    review_rhythm = _compact_text(context.get("review_rhythm"), 120)
    teaching_observations = _compact_list(context.get("teaching_observations"), 1)
    recalled_memory_summary = _compact_text(context.get("recalled_memory_summary"), 120)
    teaching_asset_summary = _compact_text(context.get("teaching_asset_summary"), 120)
    strategy_preference_summary = _compact_text(context.get("strategy_preference_summary"), 110)
    if recent_wins:
        memory_clauses.append(f"Preserve this recent win: {recent_wins[0]}.")
    if weak_spots:
        memory_clauses.append(f"Do not repeat: {'; '.join(weak_spots)}.")
    if review_rhythm:
        memory_clauses.append(f"Review rhythm to keep alive: {review_rhythm}.")
    if teaching_observations:
        memory_clauses.append(f"Teaching observation: {teaching_observations[0]}.")
    if recalled_memory_summary:
        memory_clauses.append(f"Relevant recalled memory: {recalled_memory_summary}.")
    if teaching_asset_summary:
        memory_clauses.append(f"Preferred teaching asset: {teaching_asset_summary}.")
    if strategy_preference_summary:
        memory_clauses.append(f"Strategy preference: {strategy_preference_summary}.")
    memory_line = _join_clauses(*memory_clauses)
    if memory_line:
        lines.append(f"- {memory_line}")

    grounding_clauses: list[str] = []
    failing_checks = _compact_list(context.get("failing_checks"), 3)
    if failing_checks:
        grounding_clauses.append(f"Reduce these checks first: {'; '.join(failing_checks)}.")
    requested_resource_summary = _compact_text(context.get("requested_resource_summary"), 120)
    if requested_resource_summary:
        grounding_clauses.append(f"Requested grounding: {requested_resource_summary}.")
    background_reference_summary = _compact_text(context.get("background_reference_summary"), 120)
    if background_reference_summary:
        grounding_clauses.append(f"Background summary: {background_reference_summary}.")
    reference_summary = _first_external_reference_summary(context)
    if reference_summary:
        grounding_clauses.append(f"One useful reference: {reference_summary}.")
    project_idea_summary = _first_project_idea_summary(context)
    if project_idea_summary:
        grounding_clauses.append(f"Project idea anchor: {project_idea_summary}.")
    project_source_summary = _first_project_source_summary(context)
    if project_source_summary:
        grounding_clauses.append(f"Source angle: {project_source_summary}.")
    principle_notes = context.get("principle_notes") or context.get("principle_note")
    if isinstance(principle_notes, dict):
        apply_now = _compact_text(principle_notes.get("apply_now"), 110)
        if apply_now:
            grounding_clauses.append(f"Principle apply-now move: {apply_now}.")
    exercise_prompt = context.get("exercise_prompt")
    if isinstance(exercise_prompt, dict):
        prompt = _compact_text(exercise_prompt.get("prompt"), 110)
        fallback_step = _compact_text(exercise_prompt.get("fallback_step"), 110)
        if prompt:
            grounding_clauses.append(f"Exercise prompt: {prompt}.")
        if fallback_step:
            grounding_clauses.append(f"Fallback if needed: {fallback_step}.")
    project_entry_points = _compact_list(context.get("project_entry_points"), 2)
    if project_entry_points:
        grounding_clauses.append(f"Code entry points: {'; '.join(project_entry_points)}.")
    learning_outcome_summary = _first_learning_outcome_summary(context)
    if learning_outcome_summary:
        grounding_clauses.append(learning_outcome_summary)
    grounding_line = _join_clauses(*grounding_clauses)
    if grounding_line:
        lines.append(f"- {grounding_line}")

    return "\n".join(lines)


def _language_instruction(response_language: str) -> str:
    if response_language.lower().startswith("zh"):
        return (
            "Respond in natural, stable Simplified Chinese. Do not mix in English except for code, API names, file paths, "
            "or literal identifiers that should remain unchanged."
        )
    return f"Respond in {response_language} unless the learner explicitly asks to switch."


def _nested_get(obj: dict[str, object] | None, *path: str) -> object | None:
    current: object | None = obj
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_value(*values: object | None) -> object | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list) and not value:
            continue
        return value
    return None


def _first_str(*values: object | None) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _coaching_history_mode(
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> str:
    return (
        _first_str(
            _nested_get(coach_context, "history_mode") if coach_context else None,
            _nested_get(coach_context, "coach_context", "history_mode") if coach_context else None,
            _nested_get(current_file, "history_mode"),
            _nested_get(current_file, "coach_context", "history_mode"),
        )
        or ""
    ).strip().lower()


def _coerce_resource_sequence_guidance(value: object | None) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    sequences: list[dict[str, object]] = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        title = _first_str(item.get("title"), item.get("source"), item.get("resource_id")) or "resource"
        source = _first_str(item.get("source")) or ""
        boundary_sentinel = _first_str(item.get("boundary_sentinel"), item.get("boundary")) or ""
        raw_steps = item.get("steps")
        if not isinstance(raw_steps, list):
            continue
        steps: list[dict[str, str]] = []
        for step in raw_steps[:6]:
            if not isinstance(step, dict):
                continue
            label = _first_str(step.get("label"), step.get("step")) or ""
            text = _first_str(step.get("text"), step.get("body"), step.get("summary")) or ""
            if not label or not text:
                continue
            steps.append({"label": label, "text": text})
        if len(steps) < 2:
            continue
        sequences.append(
            {
                "title": title,
                "source": source,
                "boundary_sentinel": boundary_sentinel,
                "steps": steps,
                "step_count": len(steps),
            }
        )
    return sequences


def _extract_next_step_hint_text(value: object | None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        return _first_str(
            value.get("title"),
            value.get("label"),
            value.get("next_step"),
            value.get("nextStep"),
            value.get("summary"),
        )
    return None


def _coerce_str_list(value: object | None) -> list[str]:
    if not isinstance(value, list):
        return []
    results: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            results.append(item.strip())
        elif isinstance(item, dict):
            text = _first_str(
                item.get("summary"),
                item.get("reason"),
                item.get("concept"),
                item.get("title"),
            )
            if text:
                results.append(text)
    return results


def _coerce_due_reviews(value: object | None) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    results: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            results.append({"concept": item.strip(), "reason": "", "due_at": ""})
        elif isinstance(item, dict):
            concept = _first_str(item.get("concept"), item.get("title"), item.get("summary")) or "review"
            reason = _first_str(item.get("reason")) or ""
            due_at = _first_str(item.get("due_at")) or ""
            results.append({"concept": concept, "reason": reason, "due_at": due_at})
    return results


def _format_due_review_item(item: dict[str, str]) -> str:
    concept = item.get("concept", "review")
    reason = item.get("reason", "")
    due_at = item.get("due_at", "")
    if reason and due_at:
        return f"{concept}: {reason} (due {due_at})"
    if reason:
        return f"{concept}: {reason}"
    if due_at:
        return f"{concept} (due {due_at})"
    return concept


def _coerce_requested_resources(value: object | None) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    results: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = _first_str(item.get("title"), item.get("name"), item.get("id")) or "resource"
        kind = _first_str(item.get("kind")) or "resource"
        summary = _first_str(item.get("summary")) or ""
        source = _first_str(item.get("source")) or ""
        trust_score = _first_str(item.get("trust_score")) or ""
        freshness = _first_str(item.get("freshness")) or ""
        results.append(
            {
                "title": title,
                "kind": kind,
                "summary": summary,
                "source": source,
                "trust_score": trust_score,
                "freshness": freshness,
            }
        )
    return results


def _format_requested_resource(item: dict[str, str]) -> str:
    title = item.get("title", "resource")
    kind = item.get("kind", "resource")
    summary = item.get("summary", "")
    source = item.get("source", "")
    trust_score = item.get("trust_score", "")
    freshness = item.get("freshness", "")
    source_part = f" source={source}" if source else ""
    trust_part = f" trust={trust_score}" if trust_score else ""
    freshness_part = f" freshness={freshness}" if freshness else ""
    if summary:
        return f"{title} ({kind}): {summary}{source_part}{trust_part}{freshness_part}"
    return f"{title} ({kind}){source_part}{trust_part}{freshness_part}"


def _build_resource_sequence_block(context: dict[str, Any]) -> str:
    sequences = context.get("resource_sequence_guidance")
    if not isinstance(sequences, list) or not sequences:
        return ""
    lines = [
        "Restate every library step in order before you continue. Preserve the exact library step count unless you explicitly say you are extending it."
    ]
    for item in sequences[:2]:
        if not isinstance(item, dict):
            continue
        title = _compact_text(item.get("title"), 96) or "resource"
        source = _compact_text(item.get("source"), 96)
        step_count = int(item.get("step_count") or 0)
        header = f"- {title}"
        if step_count >= 2:
            header += f" ({step_count} steps)"
        if source:
            header += f" [{source}]"
        lines.append(header)
        raw_steps = item.get("steps")
        if isinstance(raw_steps, list):
            for step in raw_steps[:6]:
                if not isinstance(step, dict):
                    continue
                label = _compact_text(step.get("label"), 32)
                text = _compact_text(step.get("text"), 180)
                if not label or not text:
                    continue
                lines.append(f"  - {label}: {text}")
        boundary_sentinel = _compact_text(item.get("boundary_sentinel"), 120)
        if boundary_sentinel:
            lines.append(f"  - Boundary sentinel: {boundary_sentinel}")
    return "\n".join(lines)


def _build_function_guidance_starter_block(context: dict[str, Any]) -> str:
    starter = context.get("function_guidance_starter")
    if not isinstance(starter, dict):
        return ""
    call_site_path = _compact_text(starter.get("call_site_path"), 120)
    definition_path = _compact_text(starter.get("definition_path"), 120)
    boundary_note = _compact_text(starter.get("boundary_note"), 180)
    coach_instruction = _compact_text(starter.get("coach_instruction"), 180)
    suggested_sequence = _compact_list(starter.get("suggested_sequence"), 4)
    call_site_content = str(starter.get("call_site_content") or "").strip()
    definition_content = str(starter.get("definition_content") or "").strip()
    language_id = _compact_text(starter.get("language_id"), 24) or ""
    lines: list[str] = []
    if boundary_note:
        lines.append(boundary_note)
    if coach_instruction:
        lines.append(coach_instruction)
    if call_site_path:
        lines.append(f"Live call site: `{call_site_path}`")
    if definition_path:
        lines.append(f"Definition file: `{definition_path}`")
    if suggested_sequence:
        lines.append("Suggested reading order:")
        lines.extend(f"- {item}" for item in suggested_sequence)
    if call_site_content:
        lines.append(
            "\n# Live call site\n"
            f"Path: `{call_site_path or 'unknown'}`\n"
            f"```{language_id}\n{call_site_content}\n```"
        )
    if definition_content:
        lines.append(
            "\n# Definition\n"
            f"Path: `{definition_path or 'unknown'}`\n"
            f"```{language_id}\n{definition_content}\n```"
        )
    return "\n".join(lines)
