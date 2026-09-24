# PR-1 Information Architecture Audit (spec §三/§四/§十七/§六十二)

Grounded in the codebase as of commit `5e4f0eb`. This is the factual
baseline the IA refactor proceeds from — no speculative redesign.

## Current state (verified in code)

| Area | Today | Where |
|------|-------|-------|
| Top-level views | 5 fixed tabs: `coach / plan / resources / training / settings`, keyboard-first | `App.tsx` view registry (~L922), i18n copy |
| Session history | Exists but as a Coach header context menu (`openMenu === "history"`); lists sessions, activates on click | `App.tsx` ~L10409, L11555 |
| Message actions | Share / Save to Resources / Create training card / Regenerate (latest reply only) | `CoachMessageBubble.tsx` L47, L372 |
| Streaming | Incremental SSE pipeline exists; **real-gateway smoke shows full turns arriving as 1 chunk** (gateway buffering risk for §35) | turn-smoke evidence 2026-09-25 |
| Settings | Already categorized: `connection / workspace / teaching / preferences` | `CoachSettingsView.tsx` L3938 |
| Skill projection | Surfaced in Plan view and Training workbench (not hidden internals) | `CoachPlanView.tsx`, `TrainingWorkbenchView.tsx` |
| Model switcher | In composer (e2e-covered), not header | e2e trainer.spec.js |

## Gap analysis vs spec

1. **§四 six logical top levels** — current five map cleanly:
   `plan → Learn`, `training → Practice`; **Progress is missing** as a
   first-class surface (skill states exist but live inside other views).
2. **§十七 two-click reachability** — New chat / history are reachable;
   history is a menu, not a searchable grouped drawer (§63: Today /
   Yesterday / Last 7 Days, search, rename, delete).
3. **§64 Settings** — needs `Skills` and `Advanced` categories; existing
   four are already the right shape, so this is additive, not a rebuild.
4. **§六十二 navigation** — spec puts Settings at the bottom of the nav
   column separated by a divider; today it is a fifth peer tab.
5. **§60/§61 first screen / empty state** — Coach first screen audit
   pending (separate pass; not started here).

## PR-1 incremental plan (behavior-preserving, each step shippable)

- **Step 1 — History drawer (§63).** Promote the existing history menu
  into a drawer/overlay with grouped sessions + search. Session data and
  activation flow already exist; this is presentation + grouping only.
- **Step 2 — Progress view (§十二).** New read-only view fed by the
  existing `skillProjection` snapshot data (dimensions + evidence list).
  No new server surface required. Added as a sixth tab; keep legacy IDs
  (`coach/plan/resources/training`) so snapshots/e2e stay stable.
- **Step 3 — Presentation labels (§四).** Rename displayed labels only
  (Plan→学习, Training→训练场, new Progress→成长) across all 8 locales;
  internal view IDs unchanged.
- **Step 4 — Settings categories (§64).** Add `skills` + `advanced`
  categories; move diagnostics/hashes/internal ids under Advanced.
- **Step 5 — Nav order (§六十二).** Settings moves to a bottom group
  with a divider; verify all 6 widths (300–700px) from §59.

## Explicitly out of scope for PR-1 (later PRs)

- Composer rebuild (PR-2), teaching depth policy (PR-3), Provider
  runtime polish (PR-5), ExecutionTarget rename of the gateway (PR-6 —
  the gateway already implements §29's interface in spirit),
  mega-file splits (PR-7).

## Evidence gathered from real environment (2026-09-25)

- `smoke:provider` against the spec §23 test endpoint: **pass** (6.0s,
  MiniMax-M2.7 via `openai_chat_completions_compatible`).
- Full real coaching turn through a locally running sidecar: **pass**
  (263s, complete turn with tool calling).
- Single-chunk finding, diagnosed: the turn smoke runs the
  `use_agent_loop` lane, which emits the final reply as one event after
  tools complete — expected for that lane. The plain chat lane
  (`coaching_reply_stream`) already streams provider deltas. Follow-up
  for PR-2: stream the agent loop's final reply (and tool activity)
  instead of one silent 4-minute wait, so §35 holds on every lane.
