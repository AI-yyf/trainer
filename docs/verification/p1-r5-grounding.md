# R5 — grounding stamps for unanchored next steps (real-model acceptance)

## Symptom

After the provider fixes, the 32-case / 64-turn real-model run had 2 failures:

| Case | Turn | Reconciliation |
| --- | --- | --- |
| `03-nested-alias` | 1 | server sent no grounding stamp for an ungrounded step |
| `E4-package-layout` | 2 | server sent no grounding stamp for an ungrounded step |

Both next steps named files that do not exist in the learner's workspace
(`late_binding.py`, `test_calc.py` — names from other projects).

## Root causes (three, all real)

1. **Acceptance harness never sent the workspace path.** The extension always
   posts `workspace_path` on `/session/start`; the maturity harness did not.
   Without it the server's checker answers `None`, so file pointers stay
   `unverifiable` and are never downgraded. The harness now sends
   `workspace_path` (M5 parity with production).
2. **The rejected step was fed back verbatim to the regeneration model.** The
   model copied the ungrounded filename out of it. The regeneration prompt now
   receives the ungrounded symbol list explicitly
   ("Do NOT mention any of these unverified references: …"), and the shared
   correction instruction forbids copying names from the rejected sentence.
3. **The retry gate rejected live plain-guided turns and rewrote deterministic
   lanes.** `turn_grounding_retry_eligible` required
   `provider_is_live_usable(service, {})`, which demands a prior Settings
   verification; plain guided turns carry no agent chrome and were blocked
   even though the turn itself had just produced a provider reply. Relaxing it
   naively then rewrote the canonical first-turn lane steps
   (`remote_workspace` etc.). Final rule:
   - deterministic lane scenarios (`remote_workspace`, `debug_loop`,
     `function_guidance`, `project_adaptation`) never get a model rewrite;
     instead a **deterministic trim** (`trim_ungrounded_segments`) removes
     exactly the sentence segments carrying ungrounded references, keeping the
     lane's canonical ruling;
   - non-lane turns may use the one bounded model rewrite, gated only by a
     configured transport + key (the turn itself is the live proof).

A diagnostic line was added for every ungrounded turn:

```
[grounding] ungrounded=[...] retry_eligible=... retry_used=... corrected=...
[grounding] retry blocked: <reason>
```

## Evidence

| Run | Result |
| --- | --- |
| Before R5 | 62 passed / 2 failed (no stamp on 2 ungrounded turns) |
| Two-case subset after each fix | 4/4 passed |
| **Final full 32-case / 64-turn run** | **64 passed / 0 failed / 0 fallback** |

```
夹具：32/32 通过；回合分类：{'passed': 64}
解释质量（非门控）：已评估 64 回合
```

The last acceptance-parity gap was in the harness itself (M5): the server's
grounding corpus is `current_file.path + content + message` and it resolves
file pointers against the workspace root it was started with. The harness now
sends the same workspace path, uses the same root for its local recompute, and
includes the request file path in the local corpus — the local recompute and
the server now agree on every turn.

The 2 previously failing turns now ship grounded steps (the fabricated file
tail is trimmed, or the model rewrite anchors the step), and every ungrounded
turn that cannot be corrected is still stamped
`next_step_requires_confirmation` — honesty is unchanged; the fix makes the
provider produce an anchored step instead of a fabricated reference.

## Tests

- `test_correction_instruction_mentions_grounding_rule` now pins the
  "do not copy names out of the rejected sentence" clause.
- Existing file-pointer semantics tests (`test_turn_grounding.py`) still pass:
  checker `False` → downgrade, `True` → grounded, `None` → unverifiable.
