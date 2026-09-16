import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

/**
 * TrainerFileStore — Codex/pi-agent 式的用户目录文件存储。
 *
 * 全部 Trainer 状态以明文 JSON 放在 ~/.trainer/ 下,人可读、可直接备份、
 * 跨重启稳定:不依赖 VS Code globalState/state.vscdb,也不依赖
 * SecretStorage 的加密密钥链(BAD_DECRYPT 类故障从此消失)。
 *
 * 文件布局:
 *   ~/.trainer/config.json    供应商连接、最近测试结果、模型缓存
 *   ~/.trainer/auth.json      apiKeyRef → API 密钥(0600)
 *   ~/.trainer/profiles.json  供应商档案注册表(预留)
 *
 * 写入为原子操作(临时文件 + rename);auth.json 权限 0600。
 */
export const TRAINER_FILE_STORE_ROOT = '.trainer';

export class TrainerFileStore {
  readonly root: string;

  constructor(rootOverride?: string) {
    // 优先级:显式覆盖 > TRAINER_FILE_STORE_ROOT 环境变量(测试/多实例隔离)
    // > ~/.trainer(日常默认)。
    const envRoot = process.env.TRAINER_FILE_STORE_ROOT?.trim();
    this.root = rootOverride?.trim()
      ? path.resolve(rootOverride)
      : envRoot
        ? path.resolve(envRoot)
        : path.join(os.homedir(), TRAINER_FILE_STORE_ROOT);
    fs.mkdirSync(this.root, { recursive: true });
  }

  readJSON<T>(file: string, fallback: T): T {
    try {
      return JSON.parse(fs.readFileSync(path.join(this.root, file), 'utf8')) as T;
    } catch {
      return fallback;
    }
  }

  writeJSON(file: string, value: unknown, mode?: number): void {
    const target = path.join(this.root, file);
    const temp = `${target}.${process.pid}.tmp`;
    fs.writeFileSync(temp, JSON.stringify(value, null, 2), { encoding: 'utf8', mode: mode ?? 0o644 });
    fs.renameSync(temp, target);
  }

  deleteFile(file: string): void {
    try {
      fs.rmSync(path.join(this.root, file), { force: true });
    } catch {
      // best-effort
    }
  }
}
