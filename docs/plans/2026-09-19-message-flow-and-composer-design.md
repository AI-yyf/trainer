# Trainer message flow and composer design

## Outcome

Trainer keeps each turn in one visible conversation line: the user message appears immediately, the assistant lane shows a lightweight thinking animation, and safe operational stages update in place until the answer streams. Hidden chain-of-thought is never displayed.

## Interaction rules

- Context and files are optional. Empty context produces no warning or “not selected” label; selected inputs appear as quiet chips.
- The plus button opens a wide, keyboard-navigable panel grouped into Add and Skills. Each action has an icon, title, and concise description.
- The skill picker uses dense rows with an icon, name, trigger, origin, description, and section so it remains scannable in a narrow sidebar.
- Saved provider configuration is reusable across restarts. Missing or stale proof may be revalidated by the real send path; only explicit credential, model, protocol, or transport failures block chat.
- An offline local Trainer service retries startup instead of asking the user to retest the model connection.
- Global informational notices use neutral surfaces. Semantic color is reserved for success, warning, and failure.

## Verification

Cover the behavior with TypeScript checks, source-contract tests, browser tests for the add/skill panels and stream stages, and visual inspection at a 520-pixel viewport.
