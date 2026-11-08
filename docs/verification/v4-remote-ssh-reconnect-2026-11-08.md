# V4 Remote-SSH 重连证据（2026-11-08）

**结论：PASS（CI Layer 1，真实 localhost sshd）**

- 工作流：`Trainer Nightly Remote-SSH E2E`（workflow_dispatch）
- Run：<https://github.com/AI-yyf/trainer/actions/runs/42504402965>
- Commit：`d3080e448ad493185396d66f497a449e2a73c939`
- 结果：11 steps passed / 0 failed
- 产物：`trainer-remote-ssh-l2-vsix`、`trainer-remote-ssh-l2-manual-checklist`

## 11 步

| # | 步骤 | 结果 |
| --- | --- | --- |
| 1 | provision keypair | ✅ |
| 2 | start localhost sshd | ✅ |
| 3 | ssh exec reaches the remote shell | ✅ |
| 4 | seed remote workspace | ✅ |
| 5 | read remote file byte-exact | ✅ |
| 6 | search remote workspace | ✅ |
| 7 | hash remote artifact (sha256 matches local) | ✅ |
| 8 | verification completes and passes | ✅ |
| 9 | artifact change makes the same verification fail | ✅ |
| 10 | interrupted run leaves the outcome unknown | ✅ |
| 11 | **reconnect after disconnect** | ✅ |

## 边界

- 这是 Layer 1 传输层：真实 sshd + 真实字节/哈希/验证/断线重连。
- Layer 2 人类 Remote-SSH 窗口六步已有 `remote-ssh-l2-141s-evidence.md`；本次没有重新执行人工六步。
- 本证据补充的是“断线后重连”路径，不把浏览器 fixture 当作远程窗口证据。
