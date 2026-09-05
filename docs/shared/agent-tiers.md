# Agent Tiers

This file records the current Codex delegation contract for this workspace. It is separate from Trainer's own provider configuration and describes how ultrawork-style agent calls are routed today.

## Tier Summary

| Tier | Model | Typical roles | Notes |
| --- | --- | --- | --- |
| LOW | `gpt-5.3-codex-spark` | `explore`, `style-reviewer` | Fast, narrow lookups and lightweight review. |
| STANDARD | `gpt-5.4-mini` | `debugger`, `writer`, `verifier`, `build-fixer`, `qa-tester`, `designer`, `researcher` | Default lane for most bounded implementation and validation work. |
| THOROUGH | `gpt-5.4` | `executor`, `planner`, `analyst`, `architect`, `critic`, `code-reviewer`, `security-reviewer`, `team-executor`, `test-engineer` | Use for deeper reasoning, orchestration, and higher-risk changes. |

## Current Role Map

This is the current workspace mapping from the OMX model table.

| Role | Model | Reasoning |
| --- | --- | --- |
| `explore` | `gpt-5.3-codex-spark` | low |
| `style-reviewer` | `gpt-5.3-codex-spark` | low |
| `debugger` | `gpt-5.4-mini` | high |
| `writer` | `gpt-5.4-mini` | high |
| `verifier` | `gpt-5.4-mini` | high |
| `quality-reviewer` | `gpt-5.4-mini` | medium |
| `api-reviewer` | `gpt-5.4-mini` | medium |
| `performance-reviewer` | `gpt-5.4-mini` | medium |
| `dependency-expert` | `gpt-5.4-mini` | high |
| `build-fixer` | `gpt-5.4-mini` | high |
| `designer` | `gpt-5.4-mini` | high |
| `qa-tester` | `gpt-5.4-mini` | low |
| `researcher` | `gpt-5.4-mini` | high |
| `test-engineer` | `gpt-5.4` | medium |
| `git-master` | `gpt-5.4-mini` | high |
| `code-simplifier` | `gpt-5.4` | high |
| `quality-strategist` | `gpt-5.4-mini` | medium |
| `analyst` | `gpt-5.4` | medium |
| `planner` | `gpt-5.4` | medium |
| `architect` | `gpt-5.4` | high |
| `executor` | `gpt-5.4` | high |
| `team-executor` | `gpt-5.4` | medium |
| `security-reviewer` | `gpt-5.4` | medium |
| `code-reviewer` | `gpt-5.4` | high |
| `product-manager` | `gpt-5.4` | medium |
| `ux-researcher` | `gpt-5.4` | medium |
| `information-architect` | `gpt-5.4-mini` | low |
| `product-analyst` | `gpt-5.4-mini` | low |
| `vision` | `gpt-5.4` | low |

## Notes

- The workspace does not implement its own agent scheduler in application code.
- The app's runtime model setting lives in the VS Code extension provider config and defaults to `gpt-4.1-mini`.
- Change this document only when the workspace's current OMX model table changes.
