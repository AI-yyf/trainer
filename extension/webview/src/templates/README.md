# Trainer templates

Choose a template before adding a feature. Templates own information order,
input meaning, action priority and disclosure; domain features supply verified
facts and existing governed handlers.

| Surface | Template | Input/action ownership |
| --- | --- | --- |
| Shell | AppShell | Three stable destinations; History/Settings utilities; all six routes remain valid |
| Coach | Conversation, CoachReply, NextAction | CoachComposer only here; one next action; message utilities in OverflowActions |
| Learning | LearningHome | Current learning/stage/action/completion first; review/route/growth/evidence closed by default |
| Activity | FocusedPractice, PracticeResponse | Same card and attempt across LEARN/TRY/VERIFY/REFLECT/RETURN; dedicated answer or reflection |
| Verification | VerificationResult | Use actual pass/fail facts; unknown/interrupted runs have no verdict; evidence/output in disclosure |
| Growth | GrowthEvidence | Existing understanding/implementation/debugging/transfer bands and real evidence; enter through Learning |
| Library | Library, ResourceReader | Search/folders/recent/trash; reader contextual actions return to Coach with resource IDs |
| Settings | SettingsIndex, SettingsDetail | Connection, Coach/Skills, Workspace/Remote, Preferences/Advanced; no category tab bar |
| Skills | CommandPalette | `$` in Coach; six default suggestions; searched catalog; management in Settings → Coach |
| Runtime state | SystemState | Shared loading/empty/processing/success/error/recovery/requirements and one recovery action |

Keep at most one primary action in the first viewport. Focused activities expose
at most two secondary actions; other actions and full acceptance facts belong in
disclosure. NextAction's reason/completion is limited to two visible lines with
full text available when needed. A notice cannot become verification evidence.

Keep the learner's work intact: drafts are scoped by workspace/session;
activity input has its own card scope; visited surfaces stay mounted; reading
positions track the actual pane. Switches never create an attempt or advance a
phase merely to display the template.

Use VS Code theme tokens and the canonical `templates.css`. Remove displaced
layout selectors instead of adding historical overrides. Use the eight-language
`templateCopy.ts` for template labels. Validate keyboard focus and reduced motion.

Run `npm run check`, extension/Playwright regressions and
`scripts/verify-ui-geometry.mjs`; regenerate goldens with
`scripts/capture-ui-golden.mjs`. Presentation fixtures establish layout only.
Real provider/verification/persistence/SSH claims require the installed native
extension and its real local sidecar/remote Companion.
