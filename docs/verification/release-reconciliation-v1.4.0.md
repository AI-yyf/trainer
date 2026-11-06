# Release 对账 — v1.4.0（2026-11-06）

| 项 | 值 | 一致 |
| --- | --- | --- |
| tag `v1.4.0` → commit | `2f1bb68` | ✅ |
| Release `targetCommitish` | main @ `2f1bb68` | ✅ |
| Release manifest `sourceCommit` | `2f1bb6861af3…` | ✅ |
| `productVersion` | `1.4.0` | ✅ |
| `sourceDirty` | `false` | ✅ |
| Release 资产 SHA-256 | `4d6aa3bc…568d` 与 manifest `vsix.sha256` 完全一致 | ✅ |
| 跨平台同源 | darwin(`7074581`) 与 linux(`2f1bb68`) manifest 的 `sidecarBuild.sourceSnapshot.sha256` 均为 `6a9c01e2…`、205 文件 | ✅ |
| 构建→安装→交付同源 | 141s 预置 VSIX 已替换为官方 Release 资产并校验哈希 | ✅ |

已知事实（如实）：PyInstaller 产物跨 run 字节级不可复现——同一 commit 的两次构建 VSIX sha 不同；对账锚点是 manifest 的 `sourceCommit` + `sourceSnapshot.sha256`，而非跨 run 的 VSIX 哈希。
