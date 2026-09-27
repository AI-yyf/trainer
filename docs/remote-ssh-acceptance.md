# Remote-SSH Acceptance Test (§五十五/§五十五)

Manual acceptance guide for Trainer's Remote-SSH support using the `141s` development fixture. Automated tests must NOT depend on this host.

## Prerequisites

- Local VS Code with the Trainer extension installed
- SSH config entry for `141s` (and optionally `20s`)
- Remote host has python3 and git

## Automated Pre-check

```bash
# 1. Connectivity
ssh 141s echo "SSH_OK"

# 2. Environment
ssh 141s "python3 --version && node --version && git --version"

# 3. Disk space (need ≥500MB for Companion + sidecar)
ssh 141s "df -h / | tail -1"

# 4. Create test workspace
ssh 141s "mkdir -p /tmp/trainer-e2e && cd /tmp/trainer-e2e && git init && echo 'def hello(): return 42' > main.py"

# 5. Verify remote hash matches local (cross-machine consistency)
LOCAL=$(shasum -a 256 <<< 'def hello(): return 42' | cut -d' ' -f1)
REMOTE=$(ssh 141s "sha256sum /tmp/trainer-e2e/main.py" | cut -d' ' -f1)
[ "$LOCAL" = "$REMOTE" ] && echo "HASH_MATCH=YES"
```

## Manual E2E Flow

1. **Connect**: VS Code → Remote-SSH → Connect to Host → `141s`
2. **Open project**: Open `/tmp/trainer-e2e` in VS Code
3. **Open Trainer**: Click the Trainer sidebar icon
4. **Provider restore**: Verify the provider is restored from local SecretStorage (no re-auth needed)
5. **Ask a question**: Type a message about the project in Coach
6. **Start practice**: Click a `[开始练习]` button or use a contextual action
7. **Edit remote file**: Modify a file in the Training view
8. **Verify remotely**: Click "验证当前文件" — must run on the remote (not local fallback)
9. **Evidence**: Check that evidence is recorded with the correct artifact hash
10. **Disconnect**: Close the Remote-SSH window — conversation and progress persist
11. **Reconnect**: Re-open the Remote-SSH window — conversation, training, attempt, and evidence are restored

## Known Limitations

- Remote Companion must be installed on the remote extension host (Trainer → Settings → Workspace → Install Remote Support)
- Both 141s and 20s have limited disk (~40GB, historically near capacity)
- Python on the remote is 3.10 (sidecar requires 3.12+ but runs locally, not remotely)
