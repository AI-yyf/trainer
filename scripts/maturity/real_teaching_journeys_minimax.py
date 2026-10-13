"""Real two-turn teaching journeys — 28-case maturity harness (MiniMax etc.).

Methodology per ``docs/maturity/2026-10-08-real-teaching-quality.md`` and the
case matrix in ``docs/maturity/teaching-case-matrix.md``:

- 28 cases = 7 categories × 4, each a double-turn journey: pre-broken code
  (exit≠0), learner turn 1, scripted fix, learner turn 2, verify exit 0.
- Real sidecar + real provider only. Locally the fixture backbone (pre-fix
  exit≠0 / post-fix exit=0) always runs; the model turns run only when
  credentials are present. Without credentials every turn is recorded as
  ``skipped_no_credentials`` and the run never claims a real-model result.
- Per-turn classification: ``passed / failed / provider_error /
  local_fallback / mock / skipped_no_credentials``.
- Reconciliation (M5): the server's ``agent_meta`` grounding stamps are
  compared with a local recompute (``evaluate_next_step_grounding``); a
  mismatch fails the turn. ``grounding_retry_used`` is server-only.
- Content quality stays with the independent review column («待 owner 确认»),
  never automated here.

Credentials and endpoints are environment-only (never committed):
- ``TRAINER_MATURITY_API_KEY``            provider API key (required for real runs).
- ``TRAINER_MATURITY_PROVIDER_BASE_URL``  provider base URL (required; must be
  https:// — plain http:// is allowed only for 127.0.0.1/localhost).
- ``TRAINER_MATURITY_MODEL``              model id (default: MiniMax-M2.7).
- ``TRAINER_MATURITY_HOST`` / ``_PORT``   sidecar bind address (default
  127.0.0.1:34900). Plaintext HTTP is only used for loopback hosts; a
  non-loopback host is contacted over https:// (fail-closed against sending
  credentials over plaintext).
- ``TRAINER_MATURITY_SIDECAR_URL``        explicit sidecar base URL override;
  must be https:// unless the host is loopback.
- ``TRAINER_MATURITY_WORKSPACE``          scratch dir (default <repo>/tmp/maturity-ws).
- ``TRAINER_MATURITY_PACING_SECONDS``     pacing between turns (default 12).

Run with the server virtualenv interpreter so the sidecar dependencies resolve:

  server/.venv/bin/python scripts/maturity/real_teaching_journeys_minimax.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO_ROOT / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import httpx  # noqa: E402

from app.llm.turn_grounding import evaluate_next_step_grounding  # noqa: E402

SIDECAR_HOST = os.environ.get("TRAINER_MATURITY_HOST", "127.0.0.1").strip() or "127.0.0.1"
SIDECAR_PORT = int(os.environ.get("TRAINER_MATURITY_PORT", "34900"))
WORKSPACE = Path(
    os.environ.get("TRAINER_MATURITY_WORKSPACE", str(REPO_ROOT / "tmp" / "maturity-ws"))
)
PACING_SECONDS = float(os.environ.get("TRAINER_MATURITY_PACING_SECONDS", "12"))
REPORT_PATH = REPO_ROOT / "docs" / "maturity" / "2026-10-13-teaching-journeys-report.md"

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

TURN_CLASSIFICATIONS = (
    "passed",
    "failed",
    "provider_error",
    "local_fallback",
    "mock",
    "skipped_no_credentials",
)


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Credentials live in the environment or an untracked local config only."
        )
    return value


def secure_provider_base_url() -> str:
    """Return the provider endpoint, refusing plaintext transport to the network.

    Plaintext HTTP carries the API key on the wire, so it is only accepted for
    loopback hosts (a local gateway). Any other non-TLS endpoint means we stop
    sending credentials instead of downgrading the transport.
    """
    endpoint = require_env("TRAINER_MATURITY_PROVIDER_BASE_URL")
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https":
        return endpoint
    if parsed.scheme == "http" and host in _LOOPBACK_HOSTS:
        print(f"[warn] provider endpoint {host!r} is loopback http; credential stays on this machine.")
        return endpoint
    raise RuntimeError(
        "Refusing to send provider credentials over plaintext HTTP: "
        "TRAINER_MATURITY_PROVIDER_BASE_URL must be https:// (plain http:// is "
        "allowed only for 127.0.0.1/localhost). If the relay does not support "
        "TLS, do not send credentials to it."
    )


def sidecar_base() -> str:
    """Sidecar endpoint; never plaintext to a non-loopback host.

    ``TRAINER_MATURITY_SIDECAR_URL`` (explicit) must be https:// unless the
    host is loopback. A plain ``TRAINER_MATURITY_HOST`` is contacted over
    https when it is not loopback — credentials travel in the per-turn payload,
    so a remote plaintext sidecar is refused rather than tolerated.
    """
    override = os.environ.get("TRAINER_MATURITY_SIDECAR_URL", "").strip()
    if override:
        parsed = urlparse(override)
        host = (parsed.hostname or "").lower()
        if parsed.scheme == "https" or host in _LOOPBACK_HOSTS:
            return override.rstrip("/")
        raise RuntimeError(
            "TRAINER_MATURITY_SIDECAR_URL must be https:// unless the host is "
            "127.0.0.1/localhost: the turn payload carries the provider API key."
        )
    if SIDECAR_HOST.lower() in _LOOPBACK_HOSTS:
        return f"http://{SIDECAR_HOST}:{SIDECAR_PORT}"
    scheme = "https"
    print(
        f"[warn] sidecar host {SIDECAR_HOST!r} is not loopback; using {scheme}:// "
        "(plaintext is refused for credential-bearing requests)."
    )
    return f"{scheme}://{SIDECAR_HOST}:{SIDECAR_PORT}"


def _case_file(text: str) -> str:
    return textwrap.dedent(text).strip() + "\n"


# ---------------------------------------------------------------------------
# The 28-case matrix (7 categories × 4; the first four ids are the R1 cases
# with their original ids, messages and topic tokens preserved).
# ---------------------------------------------------------------------------


def _case(
    case_id: str,
    category: str,
    level: str,
    runtime: str,
    files: dict[str, str],
    fixed_files: dict[str, str],
    entry: str,
    primary_file: str,
    turn1: str,
    turn2: str,
    topic_tokens: list[str],
    *,
    argv: list[str] | None = None,
    answer_mode: str = "guided",
    new_session: bool = False,
) -> dict:
    return {
        "id": case_id,
        "category": category,
        "level": level,
        "runtime": runtime,
        "files": {name: _case_file(content) for name, content in files.items()},
        "fixed_files": {name: _case_file(content) for name, content in fixed_files.items()},
        "entry": entry,
        "primary_file": primary_file,
        "argv": argv or [entry],
        "turn1": turn1,
        "turn2": turn2,
        "topic_tokens": topic_tokens,
        "answer_mode": answer_mode,
        "new_session": new_session,
    }


CASES: list[dict] = [
    # ----- A. real code errors (4) -----------------------------------------
    _case(
        "01-mutable-default", "A", "novice", "python",
        files={
            "mutable_default.py": """
            def add_item(item, items=[]):
                items.append(item)
                return items

            assert add_item(1) == [1]
            assert add_item(2) == [2]
            """,
        },
        fixed_files={
            "mutable_default.py": """
            def add_item(item, items=None):
                if items is None:
                    items = []
                items.append(item)
                return items

            assert add_item(1) == [1]
            assert add_item(2) == [2]
            """,
        },
        entry="mutable_default.py", primary_file="mutable_default.py",
        turn1="我的脚本 assert 失败了，第二个 assert 报 items 是 [1, 2]。为什么会这样？",
        turn2="我亲自写了下面的修改（用 None 哨兵），现在两个 assert 都通过了。这样写对吗？还有别的写法吗？",
        topic_tokens=["默认参数", "mutable", "items"],
    ),
    _case(
        "02-late-binding", "A", "novice", "python",
        files={
            "late_binding.py": """
            funcs = []
            for i in range(3):
                funcs.append(lambda: i)

            results = [f() for f in funcs]
            assert results == [0, 1, 2]
            """,
        },
        fixed_files={
            "late_binding.py": """
            funcs = []
            for i in range(3):
                funcs.append(lambda i=i: i)

            results = [f() for f in funcs]
            assert results == [0, 1, 2]
            """,
        },
        entry="late_binding.py", primary_file="late_binding.py",
        turn1="我的 lambda 列表断言失败，results 是 [2, 2, 2]。为什么会这样？",
        turn2="我亲自写了下面的修改（默认参数绑定 i），现在断言通过了。解释一下为什么这样就对了？",
        topic_tokens=["闭包", "late binding", "lambda"],
    ),
    _case(
        "03-nested-alias", "A", "novice", "python",
        files={
            "nested_alias.py": """
            grid = [[0] * 2] * 2
            grid[0][0] = 1
            assert grid[1][0] == 0
            """,
        },
        fixed_files={
            "nested_alias.py": """
            grid = [[0] * 2 for _ in range(2)]
            grid[0][0] = 1
            assert grid[1][0] == 0
            """,
        },
        entry="nested_alias.py", primary_file="nested_alias.py",
        turn1="我只改了 grid[0][0]，为什么 grid[1][0] 也变成 1 了？assert 失败了。",
        turn2="我亲自写了下面的修改（列表推导式建行），断言通过了。还有哪些场景会踩同样的坑？",
        topic_tokens=["别名", "alias", "引用", "嵌套列表"],
    ),
    _case(
        "A4-dict-mutation", "A", "novice", "python",
        files={
            "dict_mutation.py": """
            counts = {"a": 1, "b": 2}
            for key in counts:
                if counts[key] == 1:
                    del counts[key]
            print(counts)
            assert counts == {"b": 2}
            """,
        },
        fixed_files={
            "dict_mutation.py": """
            counts = {"a": 1, "b": 2}
            for key in list(counts):
                if counts[key] == 1:
                    del counts[key]
            print(counts)
            assert counts == {"b": 2}
            """,
        },
        entry="dict_mutation.py", primary_file="dict_mutation.py",
        turn1="我的脚本报 RuntimeError: dictionary changed size during iteration。为什么删元素会让循环炸掉？",
        turn2="我亲自改成 for key in list(counts) 了，RuntimeError 消失了。为什么套一层 list() 就行？",
        topic_tokens=["dict", "迭代器", "RuntimeError"],
    ),
    # ----- B. complex debugging (4) ----------------------------------------
    _case(
        "04-binary-search-boundary", "B", "experienced", "python",
        files={
            "binary_search.py": """
            def find(xs, target):
                lo, hi = 0, len(xs)
                while lo <= hi:
                    mid = (lo + hi) // 2
                    if xs[mid] == target:
                        return mid
                    if xs[mid] < target:
                        lo = mid + 1
                    else:
                        hi = mid - 1
                return -1

            assert find([1], 2) == -1
            """,
        },
        fixed_files={
            "binary_search.py": """
            def find(xs, target):
                lo, hi = 0, len(xs) - 1
                while lo <= hi:
                    mid = (lo + hi) // 2
                    if xs[mid] == target:
                        return mid
                    if xs[mid] < target:
                        lo = mid + 1
                    else:
                        hi = mid - 1
                return -1

            assert find([1], 2) == -1
            """,
        },
        entry="binary_search.py", primary_file="binary_search.py",
        turn1="find([1], 2) 报 IndexError。二分查找的边界哪里错了？",
        turn2="我亲自把 hi 改成 len(xs) - 1，IndexError 消失了。为什么闭区间必须减一？",
        topic_tokens=["二分", "边界", "hi", "binary search"],
    ),
    _case(
        "B2-import-env-stale", "B", "experienced", "python",
        files={
            "config.py": """
            import os

            SETTING = os.environ.get("APP_MODE", "default")
            """,
            "app.py": """
            import os

            from config import SETTING

            os.environ["APP_MODE"] = "test"
            print(f"SETTING={SETTING}")
            assert SETTING == "test", f"stale import: SETTING={SETTING}"
            """,
        },
        fixed_files={
            "config.py": """
            import os

            def get_setting():
                return os.environ.get("APP_MODE", "default")
            """,
            "app.py": """
            import os

            from config import get_setting

            os.environ["APP_MODE"] = "test"
            setting = get_setting()
            print(f"SETTING={setting}")
            assert setting == "test", f"stale import: SETTING={setting}"
            """,
        },
        entry="app.py", primary_file="app.py",
        turn1="测试里明明先设置了 APP_MODE=test，可 config 读到的还是 default。为什么环境变量没生效？",
        turn2="我把读取改成惰性函数了，测试通过了。什么时候该惰性读取、什么时候可以早绑定？",
        topic_tokens=["环境变量", "import", "惰性", "config"],
    ),
    _case(
        "B3-async-ordering", "B", "experienced", "python",
        files={
            "async_ordering.py": """
            import asyncio


            async def append_later(items, value):
                await asyncio.sleep(0)
                items.append(value)


            async def main():
                items = []
                asyncio.create_task(append_later(items, 1))
                return items


            result = asyncio.run(main())
            print(result)
            assert result == [1], f"task never completed: {result}"
            """,
        },
        fixed_files={
            "async_ordering.py": """
            import asyncio


            async def append_later(items, value):
                await asyncio.sleep(0)
                items.append(value)


            async def main():
                items = []
                task = asyncio.create_task(append_later(items, 1))
                await task
                return items


            result = asyncio.run(main())
            print(result)
            assert result == [1], f"task never completed: {result}"
            """,
        },
        entry="async_ordering.py", primary_file="async_ordering.py",
        turn1="items 打印出来是空的，任务好像根本没跑完。问题出在哪一步？",
        turn2="我保存了 task 并 await 它，现在拿到 [1] 了。create_task 和直接 await 到底差在哪？",
        topic_tokens=["asyncio", "create_task", "await", "任务"],
    ),
    _case(
        "B4-sqlite-null", "B", "experienced", "python",
        files={
            "sqlite_null.py": """
            import sqlite3

            conn = sqlite3.connect(":memory:")
            conn.execute("CREATE TABLE sales (amount INTEGER)")
            conn.executemany("INSERT INTO sales (amount) VALUES (?)", [(3,), (None,), (5,)])
            total = sum(row[0] for row in conn.execute("SELECT amount FROM sales"))
            print(total)
            assert total == 8, f"total={total}"
            """,
        },
        fixed_files={
            "sqlite_null.py": """
            import sqlite3

            conn = sqlite3.connect(":memory:")
            conn.execute("CREATE TABLE sales (amount INTEGER)")
            conn.executemany("INSERT INTO sales (amount) VALUES (?)", [(3,), (None,), (5,)])
            total = sum(row[0] or 0 for row in conn.execute("SELECT amount FROM sales"))
            print(total)
            assert total == 8, f"total={total}"
            """,
        },
        entry="sqlite_null.py", primary_file="sqlite_null.py",
        turn1="聚合的时候直接 TypeError 了，说 NoneType 不能相加。为什么列里会有 None？该怎么处理？",
        turn2="我加了 or 0，现在 total 是 8。SQL 里 NULL 在聚合函数里到底是怎么算的？",
        topic_tokens=["sqlite", "NULL", "聚合", "TypeError"],
    ),
    # ----- C. cross-language migration (4) ---------------------------------
    _case(
        "C1-shared-default-object", "C", "novice", "node",
        files={
            "shared_default.mjs": """
            const DEFAULTS = { retries: 1 };

            function withDefaults(options = DEFAULTS) {
              options.retries += 1;
              return options;
            }

            const first = withDefaults();
            const second = withDefaults();
            console.log(first, second);
            if (second.retries !== 2) {
              throw new Error(`shared default mutated: ${second.retries}`);
            }
            """,
        },
        fixed_files={
            "shared_default.mjs": """
            function withDefaults(options = null) {
              const resolved = options ? { ...options } : { retries: 1 };
              resolved.retries += 1;
              return resolved;
            }

            const first = withDefaults();
            const second = withDefaults();
            console.log(first, second);
            if (second.retries !== 2) {
              throw new Error(`shared default mutated: ${second.retries}`);
            }
            """,
        },
        entry="shared_default.mjs", primary_file="shared_default.mjs",
        turn1="同一份逻辑搬到 JS 后，两次调用互相污染了。默认对象为什么会被改掉？",
        turn2="我改成每次调用新建对象了，两次互不影响。还有哪些引用共享的坑要注意？",
        topic_tokens=["默认参数", "对象", "引用", "JS"],
    ),
    _case(
        "C2-falsy-vs-null", "C", "novice", "python",
        files={
            "falsy_null.py": """
            def describe(value):
                if value:
                    return "has value"
                return "missing"


            assert describe(0) == "has value", describe(0)
            assert describe("") == "has value", describe("")
            print("ok")
            """,
        },
        fixed_files={
            "falsy_null.py": """
            def describe(value):
                if value is not None:
                    return "has value"
                return "missing"


            assert describe(0) == "has value", describe(0)
            assert describe("") == "has value", describe("")
            print("ok")
            """,
        },
        entry="falsy_null.py", primary_file="falsy_null.py",
        turn1="从 JS 的 != null 迁到 Python 后，0 和空字符串被当成缺省值了。Python 该怎么写才等价？",
        turn2="改成 is not None 后断言通过了。Python 和 JS 的 falsy 判定到底差在哪？",
        topic_tokens=["None", "falsy", "迁移", "判定"],
    ),
    _case(
        "C3-var-capture", "C", "novice", "node",
        files={
            "var_capture.mjs": """
            const callbacks = [];
            for (var i = 0; i < 3; i += 1) {
              callbacks.push(() => i);
            }
            const results = callbacks.map((fn) => fn());
            console.log(results);
            if (JSON.stringify(results) !== "[0,1,2]") {
              throw new Error(`late binding capture: ${results}`);
            }
            """,
        },
        fixed_files={
            "var_capture.mjs": """
            const callbacks = [];
            for (let i = 0; i < 3; i += 1) {
              callbacks.push(() => i);
            }
            const results = callbacks.map((fn) => fn());
            console.log(results);
            if (JSON.stringify(results) !== "[0,1,2]") {
              throw new Error(`late binding capture: ${results}`);
            }
            """,
        },
        entry="var_capture.mjs", primary_file="var_capture.mjs",
        turn1="回调拿到的全是 3。Python 里的闭包坑换到 JS 之后该怎么解？",
        turn2="我把 var 换成 let 就好了。let 和 var 在闭包捕获上为什么不同？",
        topic_tokens=["var", "let", "闭包", "捕获"],
    ),
    _case(
        "C4-resource-cleanup", "C", "experienced", "node",
        files={
            "resource_cleanup.mjs": """
            import { existsSync, unlinkSync, writeFileSync } from "node:fs";

            const path = "scratch-work.tmp";
            try {
              writeFileSync(path, "partial");
              throw new Error("simulated failure after writing");
            } catch (error) {
              // broken: cleanup skipped on the error path
            }
            if (existsSync(path)) {
              unlinkSync(path);
              throw new Error("scratch file leaked after failure");
            }
            console.log("clean");
            """,
        },
        fixed_files={
            "resource_cleanup.mjs": """
            import { existsSync, unlinkSync, writeFileSync } from "node:fs";

            const path = "scratch-work.tmp";
            try {
              writeFileSync(path, "partial");
              throw new Error("simulated failure after writing");
            } catch (error) {
              // handled
            } finally {
              if (existsSync(path)) {
                unlinkSync(path);
              }
            }
            if (existsSync(path)) {
              throw new Error("scratch file leaked after failure");
            }
            console.log("clean");
            """,
        },
        entry="resource_cleanup.mjs", primary_file="resource_cleanup.mjs",
        turn1="中途报错后临时文件没清掉。Python 的 with 换到 JS 里对应的写法是什么？",
        turn2="我补了 finally 清理，现在异常路径也干净了。还有哪些地方必须用 finally？",
        topic_tokens=["finally", "with", "资源", "清理"],
    ),
    # ----- D. principle teaching (4) ---------------------------------------
    _case(
        "D1-default-eval-time", "D", "novice", "python",
        files={
            "default_eval.py": """
            def collect(value, bucket=[]):
                bucket.append(value)
                return bucket


            first = collect("a")
            second = collect("b")
            print(first, second, collect.__defaults__)
            assert first is not second, "expected a fresh list per call"
            """,
        },
        fixed_files={
            "default_eval.py": """
            def collect(value, bucket=None):
                if bucket is None:
                    bucket = []
                bucket.append(value)
                return bucket


            first = collect("a")
            second = collect("b")
            print(first, second, collect.__defaults__)
            assert first is not second, "expected a fresh list per call"
            """,
        },
        entry="default_eval.py", primary_file="default_eval.py",
        turn1="我做了个实验：两次调用居然拿到同一个列表。默认值到底是在什么时候创建的？",
        turn2="我用 None 哨兵改好了。__defaults__ 里还留着什么？还有哪些默认值会这样？",
        topic_tokens=["默认参数", "__defaults__", "求值时机"],
    ),
    _case(
        "D2-closure-experiment", "D", "novice", "python",
        files={
            "closure_experiment.py": """
            def make_counters():
                counters = []
                for i in range(3):
                    counters.append(lambda: i)
                return counters


            results = [counter() for counter in make_counters()]
            print(results)
            assert results == [0, 1, 2], f"expected per-iteration capture: {results}"
            """,
        },
        fixed_files={
            "closure_experiment.py": """
            def make_counters():
                counters = []
                for i in range(3):
                    counters.append(lambda i=i: i)
                return counters


            results = [counter() for counter in make_counters()]
            print(results)
            assert results == [0, 1, 2], f"expected per-iteration capture: {results}"
            """,
        },
        entry="closure_experiment.py", primary_file="closure_experiment.py",
        turn1="这个实验打印出 [2, 2, 2]。闭包到底捕获的是变量还是值？",
        turn2="绑定默认参数后就是 [0, 1, 2] 了。nonlocal 和 i=i 两种写法怎么选？",
        topic_tokens=["闭包", "捕获", "nonlocal"],
    ),
    _case(
        "D3-copy-semantics", "D", "novice", "python",
        files={
            "copy_semantics.py": """
            import copy

            original = {"tags": ["a"]}
            shallow = copy.copy(original)
            shallow["tags"].append("b")
            print(original, shallow)
            assert original["tags"] == ["a"], f"shallow copy shares inner list: {original}"
            """,
        },
        fixed_files={
            "copy_semantics.py": """
            import copy

            original = {"tags": ["a"]}
            shallow = copy.deepcopy(original)
            shallow["tags"].append("b")
            print(original, shallow)
            assert original["tags"] == ["a"], f"shallow copy shares inner list: {original}"
            """,
        },
        entry="copy_semantics.py", primary_file="copy_semantics.py",
        turn1="copy 之后改副本，原始对象也变了。浅拷贝到底复制了什么？",
        turn2="换成 deepcopy 就隔离了。什么时候浅拷贝其实就够用？",
        topic_tokens=["浅拷贝", "deepcopy", "引用"],
    ),
    _case(
        "D4-hash-contract", "D", "experienced", "python",
        files={
            "hash_contract.py": """
            class Key:
                def __init__(self, name):
                    self.name = name

                def __eq__(self, other):
                    return isinstance(other, Key) and other.name == self.name


            lookup = {Key("a"): 1}
            print(lookup.get(Key("a")))
            assert lookup.get(Key("a")) == 1, "equal objects must find the same dict entry"
            """,
        },
        fixed_files={
            "hash_contract.py": """
            class Key:
                def __init__(self, name):
                    self.name = name

                def __eq__(self, other):
                    return isinstance(other, Key) and other.name == self.name

                def __hash__(self):
                    return hash(self.name)


            lookup = {Key("a"): 1}
            print(lookup.get(Key("a")))
            assert lookup.get(Key("a")) == 1, "equal objects must find the same dict entry"
            """,
        },
        entry="hash_contract.py", primary_file="hash_contract.py",
        turn1="我定义了 __eq__ 之后，字典查询直接报错。相等和哈希之间是什么契约？",
        turn2="补上 __hash__ 后查询正常了。为什么 __eq__ 一改，__hash__ 就没了？",
        topic_tokens=["eq", "hash", "字典", "契约"],
    ),
    # ----- E. project adaptation (4) ---------------------------------------
    _case(
        "E1-argparse-entry", "E", "novice", "python",
        files={
            "app.py": """
            import sys


            def read_input(input_path):
                with open(input_path, encoding="utf-8") as handle:
                    return handle.read().strip()


            if __name__ == "__main__":
                print(read_input(sys.argv[1]))
            """,
            "data.txt": "hello\n",
        },
        fixed_files={
            "app.py": """
            import argparse


            def read_input(input_path):
                with open(input_path, encoding="utf-8") as handle:
                    return handle.read().strip()


            def main():
                parser = argparse.ArgumentParser()
                parser.add_argument("--input", required=True)
                args = parser.parse_args()
                print(read_input(args.input))


            if __name__ == "__main__":
                main()
            """,
            "data.txt": "hello\n",
        },
        entry="app.py", primary_file="app.py", argv=["app.py", "--input", "data.txt"],
        turn1="我想给脚本加个 --input 参数，现在直接 sys.argv[1] 拿到的是 --input 本身。怎么组织参数入口？",
        turn2="用 argparse 后 python app.py --input data.txt 正常输出了。以后要加子命令该怎么组织？",
        topic_tokens=["argparse", "参数", "入口"],
    ),
    _case(
        "E2-async-call-site", "E", "experienced", "python",
        files={
            "client.py": """
            import asyncio


            async def fetch(key):
                await asyncio.sleep(0)
                return f"data:{key}"
            """,
            "main.py": """
            import asyncio

            from client import fetch


            def run():
                result = fetch("a")
                print(result)
                assert result == "data:a", f"unawaited coroutine: {result}"


            run()
            """,
        },
        fixed_files={
            "client.py": """
            import asyncio


            async def fetch(key):
                await asyncio.sleep(0)
                return f"data:{key}"
            """,
            "main.py": """
            import asyncio

            from client import fetch


            async def run():
                result = await fetch("a")
                print(result)
                assert result == "data:a", f"unawaited coroutine: {result}"


            asyncio.run(run())
            """,
        },
        entry="main.py", primary_file="main.py",
        turn1="我把 fetch 改成 async 之后，main 里拿到的居然是 coroutine 对象。调用点该怎么跟着改？",
        turn2="我把调用链都补上 await 并用 asyncio.run 驱动了。还有哪些调用点容易漏？",
        topic_tokens=["async", "await", "调用点", "coroutine"],
    ),
    _case(
        "E3-unit-test-contract", "E", "novice", "python",
        files={
            "calc.py": """
            def add(a, b):
                return a - b
            """,
            "test_calc.py": """
            import unittest

            from calc import add


            class TestCalc(unittest.TestCase):
                def test_add(self):
                    self.assertEqual(add(2, 3), 5)
                    self.assertEqual(add(-1, 1), 0)
            """,
        },
        fixed_files={
            "calc.py": """
            def add(a, b):
                return a + b
            """,
            "test_calc.py": """
            import unittest

            from calc import add


            class TestCalc(unittest.TestCase):
                def test_add(self):
                    self.assertEqual(add(2, 3), 5)
                    self.assertEqual(add(-1, 1), 0)
            """,
        },
        entry="test_calc.py",
        primary_file="test_calc.py",
        argv=["-m", "unittest", "test_calc", "-v"],
        turn1="我照着模块写了测试文件，但测试挂了一个断言。是测试写错了还是实现错了？怎么定位？",
        turn2="原来是 add 的实现写成了减法，修好后测试全过。边界用例还应该补哪些？",
        topic_tokens=["测试", "unittest", "add", "断言"],
    ),
    _case(
        "E4-package-layout", "E", "experienced", "python",
        files={
            "pkg/cli.py": """
            from helpers import parse

            print(parse("1,2,3"))
            """,
            "pkg/helpers.py": """
            def parse(text):
                return [int(part) for part in text.split(",")]
            """,
        },
        fixed_files={
            "pkg/__init__.py": """
            """,
            "pkg/cli.py": """
            from pkg.helpers import parse

            print(parse("1,2,3"))
            """,
            "pkg/helpers.py": """
            def parse(text):
                return [int(part) for part in text.split(",")]
            """,
        },
        entry="cli.py", primary_file="pkg/cli.py",
        argv=["-m", "pkg.cli"],
        turn1="python -m pkg.cli 报找不到 helpers 模块。平铺脚本变成包之后，导入该怎么写？",
        turn2="改成包内导入并补了 __init__.py 就好了。入口点以后怎么暴露给别人用？",
        topic_tokens=["包", "__init__", "导入", "pkg"],
    ),
    # ----- F. advanced users (direct mode, 4) ------------------------------
    _case(
        "F1-semaphore-limit", "F", "experienced", "python",
        files={
            "semaphore_limit.py": """
            import asyncio

            active = 0
            peak = 0


            async def task(index):
                global active, peak
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.01)
                active -= 1


            async def main():
                await asyncio.gather(*(task(index) for index in range(10)))
                return peak


            observed = asyncio.run(main())
            print("peak", observed)
            assert observed <= 3, f"concurrency limit exceeded: {observed}"
            """,
        },
        fixed_files={
            "semaphore_limit.py": """
            import asyncio

            active = 0
            peak = 0
            limit = asyncio.Semaphore(3)


            async def task(index):
                global active, peak
                async with limit:
                    active += 1
                    peak = max(peak, active)
                    await asyncio.sleep(0.01)
                    active -= 1


            async def main():
                await asyncio.gather(*(task(index) for index in range(10)))
                return peak


            observed = asyncio.run(main())
            print("peak", observed)
            assert observed <= 3, f"concurrency limit exceeded: {observed}"
            """,
        },
        entry="semaphore_limit.py", primary_file="semaphore_limit.py",
        answer_mode="direct",
        turn1="并发峰值到了 10，我要把它压到 3。asyncio 里最直接的限流手段是什么？给出可运行的改法。",
        turn2="Semaphore 生效了，peak 是 3。调度优先级和公平性上还要注意什么？",
        topic_tokens=["Semaphore", "并发", "asyncio", "限流"],
    ),
    _case(
        "F2-this-binding", "F", "experienced", "node",
        files={
            "this_binding.mjs": """
            const counter = {
              count: 0,
              start(values) {
                values.forEach(function (value) {
                  this.count += value;
                });
              },
            };

            counter.start([1, 2, 3]);
            console.log(counter.count);
            if (counter.count !== 6) {
              throw new Error(`this lost in callback: ${counter.count}`);
            }
            """,
        },
        fixed_files={
            "this_binding.mjs": """
            const counter = {
              count: 0,
              start(values) {
                values.forEach((value) => {
                  this.count += value;
                });
              },
            };

            counter.start([1, 2, 3]);
            console.log(counter.count);
            if (counter.count !== 6) {
              throw new Error(`this lost in callback: ${counter.count}`);
            }
            """,
        },
        entry="this_binding.mjs", primary_file="this_binding.mjs",
        answer_mode="direct",
        turn1="回调里的 this 丢了。四种 this 绑定规则的优先级怎么排？最短的修法是什么？",
        turn2="箭头函数解决了。什么时候不能使用箭头函数？",
        topic_tokens=["this", "回调", "箭头函数", "绑定"],
    ),
    _case(
        "F3-quadratic-scan", "F", "experienced", "python",
        files={
            "quadratic_scan.py": """
            class Tracked:
                comparisons = 0

                def __init__(self, value):
                    self.value = value

                def __eq__(self, other):
                    Tracked.comparisons += 1
                    return self.value == other.value

                def __hash__(self):
                    return hash(self.value)


            def unique(values):
                result = []
                for value in values:
                    if value not in result:
                        result.append(value)
                return result


            data = [Tracked(index) for index in range(300)]
            result = unique(data)
            print("comparisons", Tracked.comparisons, "unique", len(result))
            assert Tracked.comparisons < 10000, f"quadratic scan: {Tracked.comparisons}"
            """,
        },
        fixed_files={
            "quadratic_scan.py": """
            class Tracked:
                comparisons = 0

                def __init__(self, value):
                    self.value = value

                def __eq__(self, other):
                    Tracked.comparisons += 1
                    return self.value == other.value

                def __hash__(self):
                    return hash(self.value)


            def unique(values):
                return list(dict.fromkeys(values))


            data = [Tracked(index) for index in range(300)]
            result = unique(data)
            print("comparisons", Tracked.comparisons, "unique", len(result))
            assert Tracked.comparisons < 10000, f"quadratic scan: {Tracked.comparisons}"
            """,
        },
        entry="quadratic_scan.py", primary_file="quadratic_scan.py",
        answer_mode="direct",
        turn1="这段去重的比较次数是 4.5 万次，我要把它压下来。慢在哪？用哪个内置结构？",
        turn2="dict.fromkeys 把比较次数降到个位数了。内存换时间在这里怎么权衡？",
        topic_tokens=["复杂度", "去重", "dict", "性能"],
    ),
    _case(
        "F4-injectable-clock", "F", "novice", "python",
        files={
            "injectable_clock.py": """
            import time


            class Session:
                def __init__(self, ttl_seconds):
                    self.ttl = ttl_seconds
                    self.started = time.time()

                def expired(self):
                    return (time.time() - self.started) > self.ttl * 60


            fresh = Session(ttl_seconds=1)
            time.sleep(0.1)
            assert fresh.expired() is False, "a 1s TTL must not be expired after 0.1s"
            short = Session(ttl_seconds=0.01)
            time.sleep(0.05)
            assert short.expired() is True, "a 10ms TTL must be expired after 50ms"
            print("ok")
            """,
        },
        fixed_files={
            "injectable_clock.py": """
            import time


            class Session:
                def __init__(self, ttl_seconds):
                    self.ttl = ttl_seconds
                    self.started = time.time()

                def expired(self):
                    return (time.time() - self.started) > self.ttl


            fresh = Session(ttl_seconds=1)
            time.sleep(0.1)
            assert fresh.expired() is False, "a 1s TTL must not be expired after 0.1s"
            short = Session(ttl_seconds=0.01)
            time.sleep(0.05)
            assert short.expired() is True, "a 10ms TTL must be expired after 50ms"
            print("ok")
            """,
        },
        entry="injectable_clock.py", primary_file="injectable_clock.py",
        answer_mode="direct",
        turn1="10ms 的 TTL 过了 50ms 还没过期，单位换算错了。另外这种测试要 sleep，怎么改得可测试？",
        turn2="单位修好了。把 clock 注入进来之后测试就不用 sleep 了，fake 和 spy 的边界在哪？",
        topic_tokens=["时间", "TTL", "注入", "测试"],
    ),
    # ----- G. long-term recovery (4) ---------------------------------------
    _case(
        "G1-cross-session-topic", "G", "novice", "python",
        new_session=True,
        files={
            "cross_session.py": """
            def register(name, registry={}):
                registry[name] = True
                return registry


            first = register("a")
            second = register("b")
            print(first, second)
            assert first is not second, "registry should be per call"
            """,
        },
        fixed_files={
            "cross_session.py": """
            def register(name, registry=None):
                if registry is None:
                    registry = {}
                registry[name] = True
                return registry


            first = register("a")
            second = register("b")
            print(first, second)
            assert first is not second, "registry should be per call"
            """,
        },
        entry="cross_session.py", primary_file="cross_session.py",
        turn1="隔了一次会话回来，又碰到可变默认参数的坑：两次 register 共享了同一个字典。帮我定位一下。",
        turn2="我按照上次那条线的思路改成了 None 惰性初始化，断言过了。上次说到哪了？",
        topic_tokens=["默认参数", "registry", "共享"],
    ),
    _case(
        "G2-review-interval", "G", "novice", "python",
        files={
            "review_interval.py": """
            def next_interval(interval, repetitions):
                return interval * (repetitions + 1)


            assert next_interval(2, 3) == 16, next_interval(2, 3)
            print("ok")
            """,
        },
        fixed_files={
            "review_interval.py": """
            def next_interval(interval, repetitions):
                return interval * (2 ** repetitions)


            assert next_interval(2, 3) == 16, next_interval(2, 3)
            print("ok")
            """,
        },
        entry="review_interval.py", primary_file="review_interval.py",
        turn1="今天先复习这个：间隔翻倍规则我实现错了，next_interval(2, 3) 出来 8 不是 16。",
        turn2="改成 2 的幂后过了。这个规则为什么进复习队列？",
        topic_tokens=["间隔", "复习", "幂"],
    ),
    _case(
        "G3-provider-recovery", "G", "novice", "python",
        files={
            "provider_recovery.py": """
            class Client:
                def __init__(self):
                    self.last_error = None

                def call(self, should_fail):
                    if should_fail:
                        self.last_error = "boom"
                        return None
                    return "ok"


            client = Client()
            assert client.call(False) == "ok"
            assert client.call(True) is None
            assert client.last_error == "boom", f"last_error={client.last_error}"
            assert client.call(False) == "ok", "client must stay usable after an error"
            assert client.last_error is None, "recovery must clear the recorded error"
            print("ok")
            """,
        },
        fixed_files={
            "provider_recovery.py": """
            class Client:
                def __init__(self):
                    self.last_error = None

                def call(self, should_fail):
                    if should_fail:
                        self.last_error = "boom"
                        return None
                    self.last_error = None
                    return "ok"


            client = Client()
            assert client.call(False) == "ok"
            assert client.call(True) is None
            assert client.last_error == "boom", f"last_error={client.last_error}"
            assert client.call(False) == "ok", "client must stay usable after an error"
            print("ok")
            """,
        },
        entry="provider_recovery.py", primary_file="provider_recovery.py",
        turn1="刚才那次对话中断了，我们继续把这个 client 的恢复路径补完：报错后还能继续用。",
        turn2="修好了。刚才的中断算我学会了吗？恢复后的验证才算数吗？",
        topic_tokens=["恢复", "错误", "client"],
    ),
    _case(
        "G4-return-after-days", "G", "novice", "python",
        new_session=True,
        files={
            "return_after_days.py": """
            def last_n(items, n):
                return items[-n:]


            assert last_n([1, 2, 3], 2) == [2, 3]
            assert last_n([1, 2, 3], 0) == []
            print("ok")
            """,
        },
        fixed_files={
            "return_after_days.py": """
            def last_n(items, n):
                if n <= 0:
                    return []
                return items[-n:]


            assert last_n([1, 2, 3], 2) == [2, 3]
            assert last_n([1, 2, 3], 0) == []
            print("ok")
            """,
        },
        entry="return_after_days.py", primary_file="return_after_days.py",
        turn1="隔了几天回来，接着上次的切片问题：last_n 取 0 个时把整个列表返回了，边界判断漏了。",
        turn2="补上 n <= 0 的守卫就对了。之前的结论在别的切片场景还成立吗？",
        topic_tokens=["切片", "边界", "last_n"],
    ),
]


def _case_body(case: dict, *, fixed: bool) -> dict[str, str]:
    return case["fixed_files"] if fixed else case["files"]


def _write_case_files(case: dict, root: Path, *, fixed: bool) -> None:
    for name, content in _case_body(case, fixed=fixed).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _case_command(case: dict) -> list[str]:
    if case["runtime"] == "node":
        return ["node", *case["argv"]]
    return [sys.executable, *case["argv"]]


def run_case_entry(case: dict, root: Path, *, fixed: bool) -> tuple[int, str]:
    _write_case_files(case, root, fixed=fixed)
    proc = subprocess.run(
        _case_command(case),
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    tail = (proc.stderr or proc.stdout).strip().splitlines()
    return proc.returncode, (tail[-1] if tail else "")[:200]


def check_case_fixture(case: dict, root: Path) -> dict:
    """Local backbone: pre-fix exit≠0, post-fix exit=0 (no provider needed)."""
    broken_root = root / "broken"
    fixed_root = root / "fixed"
    shutil.rmtree(broken_root, ignore_errors=True)
    shutil.rmtree(fixed_root, ignore_errors=True)
    broken_root.mkdir(parents=True, exist_ok=True)
    fixed_root.mkdir(parents=True, exist_ok=True)
    pre_exit, pre_tail = run_case_entry(case, broken_root, fixed=False)
    post_exit, post_tail = run_case_entry(case, fixed_root, fixed=True)
    return {
        "pre_fix_exit": pre_exit,
        "pre_fix_tail": pre_tail,
        "post_fix_exit": post_exit,
        "post_fix_tail": post_tail,
        "fixture_ok": pre_exit != 0 and post_exit == 0,
    }


def build_provider() -> dict:
    return {
        "name": "minimax-maturity",
        "baseUrl": secure_provider_base_url(),
        "apiKeyRef": "trainer.default",
        "model": os.environ.get("TRAINER_MATURITY_MODEL", "MiniMax-M2.7").strip() or "MiniMax-M2.7",
        "protocol": "openai_chat_completions_compatible",
        "connectionType": "newapi_channel_conn",
    }


def turn_payload(
    sid: str, case: dict, message: str, code: str, *, provider: dict, api_key: str
) -> dict:
    language = "javascript" if case["runtime"] == "node" else "python"
    return {
        "session_id": sid,
        "message": message,
        "responseLanguage": "zh-CN",
        "answer_mode": case["answer_mode"],
        "provider": provider,
        "apiKey": api_key,
        "current_file": {
            "path": case["primary_file"],
            "language_id": language,
            "content": code,
        },
    }


def _memory_strings(payload: dict) -> dict[str, str]:
    memory = payload.get("snapshot", {}).get("memory") or {}
    workspace = memory.get("workspace") if isinstance(memory.get("workspace"), dict) else {}
    return {
        "anchor": str(memory.get("coach_anchor") or ""),
        "focus": str(memory.get("current_focus") or ""),
        "focus_area": str(workspace.get("latest_coach_focus_area") or workspace.get("latest_turn_focus_area") or ""),
    }


def classify_and_check_turn(
    case: dict,
    turn_no: int,
    payload: dict | None,
    request_error: str | None,
    *,
    code_text: str,
    message: str,
) -> dict:
    """One turn's honest classification + M1/M2/M5 checks (no credits needed
    to be correct here; skipped turns never reach this function)."""
    if request_error is not None:
        return {"classification": "provider_error", "detail": request_error}
    assert payload is not None
    agent_meta = payload.get("agent_meta") or {}
    coach_turn = payload.get("coach_turn") or {}
    reply = str((payload.get("reply") or {}).get("content") or "")
    next_step = str(coach_turn.get("next_step") or "")
    memory = _memory_strings(payload)
    if agent_meta.get("fell_back"):
        return {
            "classification": "local_fallback",
            "next_step": next_step[:200],
            "reply_head": reply[:160],
            "memory": memory,
        }
    local_decision = evaluate_next_step_grounding(next_step, reply, code_text)
    server_outcome = str(agent_meta.get("grounding_outcome") or "")
    server_ungrounded = [str(item) for item in (agent_meta.get("grounding_ungrounded_symbols") or [])]
    server_retry_used = bool(agent_meta.get("grounding_retry_used"))
    flagged = bool(coach_turn.get("requires_confirmation") or agent_meta.get("next_step_requires_confirmation"))
    reconciliation = "ok"
    if server_outcome == "corrected":
        if not local_decision.grounded:
            reconciliation = "corrected text is not grounded locally"
        elif not server_retry_used:
            reconciliation = "corrected outcome without retry_used"
    elif server_outcome == "downgraded":
        if local_decision.grounded:
            reconciliation = "server downgraded but local recompute is grounded"
        elif sorted(server_ungrounded) != sorted(local_decision.referenced_symbols):
            reconciliation = (
                f"ungrounded symbol mismatch: server={sorted(server_ungrounded)} "
                f"local={sorted(local_decision.referenced_symbols)}"
            )
    elif server_outcome == "":
        # No stamp: the clean-reply contract keeps agent_meta empty only when
        # the step is grounded.
        if not local_decision.grounded:
            reconciliation = "server sent no grounding stamp for an ungrounded step"
    else:
        if not local_decision.grounded:
            reconciliation = f"server outcome {server_outcome} but local recompute is ungrounded"
    drift = ""
    if memory["anchor"] and message.startswith(memory["anchor"]):
        drift = "anchor repeats the learner message prefix"
    checks = {
        "grounded_ok": reconciliation == "ok",
        "flagged": flagged,
        "anchor": memory["anchor"][:80],
        "focus": memory["focus"][:80],
        "focus_area": memory["focus_area"][:80],
        "topic_seen": any(token in reply or token in next_step for token in case["topic_tokens"]),
        "drift": drift,
        "reconciliation": reconciliation,
        "server_outcome": server_outcome,
        "next_step": next_step[:200],
        "reply_head": reply[:160],
    }
    classification = "passed" if reconciliation == "ok" and not drift else "failed"
    return {"classification": classification, **checks}


def run_real_journeys(provider: dict, api_key: str) -> dict:
    """Real sidecar + real provider; every case double-turn with pacing."""
    import shutil as _shutil

    data_dir = WORKSPACE / ".trainer-data"
    _shutil.rmtree(data_dir, ignore_errors=True)
    project_root = WORKSPACE / "projects"
    _shutil.rmtree(project_root, ignore_errors=True)
    project_root.mkdir(parents=True, exist_ok=True)
    base = sidecar_base()

    env = {**os.environ, "TRAINER_DATA_DIR": str(data_dir)}
    log_path = WORKSPACE / "maturity_sidecar.log"
    case_reports: list[dict] = []
    with open(log_path, "w", encoding="utf-8") as sidecar_log:
        sidecar = subprocess.Popen(
            [sys.executable, "run_sidecar.py", "--host", SIDECAR_HOST, "--port", str(SIDECAR_PORT)],
            cwd=str(SERVER_DIR),
            env=env,
            stdout=sidecar_log,
            stderr=subprocess.STDOUT,
        )
        try:
            client = httpx.Client(timeout=300, trust_env=False)  # never proxy localhost
            for _ in range(30):
                try:
                    if client.get(f"{base}/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(2)
            session_id = ""
            for case in CASES:
                case_root = project_root / case["id"]
                case_root.mkdir(parents=True, exist_ok=True)
                if not session_id or case["new_session"]:
                    started = client.post(
                        f"{base}/session/start",
                        json={
                            "workspace_id": WORKSPACE.as_posix(),
                            "workspace_name": "maturity-teaching-journeys",
                        },
                    )
                    session_id = str((started.json() or {}).get("session_id") or "")
                _write_case_files(case, case_root, fixed=False)
                turns = []
                for turn_no, message in ((1, case["turn1"]), (2, case["turn2"])):
                    if turn_no == 2:
                        _write_case_files(case, case_root, fixed=True)
                    code_text = (case["fixed_files"] if turn_no == 2 else case["files"])[case["primary_file"]]
                    payload: dict | None = None
                    error: str | None = None
                    try:
                        response = client.post(
                            f"{base}/turn",
                            json=turn_payload(
                                session_id, case, message, code_text, provider=provider, api_key=api_key
                            ),
                        )
                        if response.status_code != 200:
                            error = f"HTTP {response.status_code}"
                        else:
                            payload = response.json()
                    except httpx.HTTPError as exc:
                        error = f"{type(exc).__name__}: {exc}"
                    turns.append(
                        classify_and_check_turn(
                            case, turn_no, payload, error, code_text=code_text, message=message
                        )
                    )
                    time.sleep(PACING_SECONDS)
                fixture = check_case_fixture(case, case_root)
                case_reports.append({"case": case["id"], "fixture": fixture, "turns": turns})
        finally:
            sidecar.terminate()
            try:
                sidecar.wait(timeout=10)
            except subprocess.TimeoutExpired:
                sidecar.kill()
    return {"mode": "real", "cases": case_reports}


def skipped_run(fixtures: dict[str, dict]) -> dict:
    """No credentials: fixtures still validated locally, every turn skipped."""
    cases = []
    for case in CASES:
        cases.append(
            {
                "case": case["id"],
                "fixture": fixtures[case["id"]],
                "turns": [
                    {"classification": "skipped_no_credentials", "turn": 1},
                    {"classification": "skipped_no_credentials", "turn": 2},
                ],
            }
        )
    return {"mode": "skipped_no_credentials", "cases": cases}


def _classification_counts(result: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in result["cases"]:
        for turn in case["turns"]:
            key = str(turn.get("classification") or "unknown")
            counts[key] = counts.get(key, 0) + 1
    return counts


def write_report(result: dict) -> None:
    fixtures_ok = sum(1 for case in result["cases"] if case["fixture"]["fixture_ok"])
    counts = _classification_counts(result)
    lines = [
        "# 教学旅程 28 案例报告（2026-10-13）",
        "",
        "- harness：`scripts/maturity/real_teaching_journeys_minimax.py`（28 组双回合，7 类 × 4）",
        "- 矩阵规格：`docs/maturity/teaching-case-matrix.md`；台账与对账规则见该文件 §2（M1–M5）",
        f"- 运行模式：`{result['mode']}`",
        f"- 夹具校验（本地执行，无模型）：{fixtures_ok}/28 通过（pre-fix exit≠0 且 post-fix exit=0）",
        f"- 回合分类统计：{counts}",
        "",
    ]
    if result["mode"] == "skipped_no_credentials":
        lines += [
            "## 诚实声明",
            "",
            "本环境未设置 `TRAINER_MATURITY_API_KEY` / `TRAINER_MATURITY_PROVIDER_BASE_URL`，",
            "**56 个模型回合全部标记 `skipped_no_credentials`：未向任何 provider 发起调用，",
            "本报告不构成、也不得被引用为「真实模型通过」**。夹具骨架为本地真实执行。",
            "",
        ]
    else:
        lines += [
            "## 诚实声明",
            "",
            "分类逐回合记录；`local_fallback` / `provider_error` 回合不计入模型教学质量；",
            "内容质量栏由独立评审 agent 填写并标注「待 owner 确认」，不记为人工审阅。",
            "",
        ]
    lines += [
        "## 逐案例",
        "",
        "| 案例 | 类别 | 夹具 pre/post exit | 回合分类 | 对账 | 备注 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for case in result["cases"]:
        case_id = case["case"]
        category = next((item["category"] for item in CASES if item["id"] == case_id), "?")
        fixture = case["fixture"]
        classifications = " / ".join(str(turn.get("classification")) for turn in case["turns"])
        reconciliations = " / ".join(str(turn.get("reconciliation") or "-") for turn in case["turns"])
        note = ""
        if not fixture["fixture_ok"]:
            note = f"夹具失败：{fixture['pre_fix_tail'] or fixture['post_fix_tail']}"
        lines.append(
            f"| {case_id} | {category} | {fixture['pre_fix_exit']} / {fixture['post_fix_exit']} | "
            f"{classifications} | {reconciliations} | {note} |"
        )
    lines += [
        "",
        "## 复现",
        "",
        "```bash",
        "server/.venv/bin/python scripts/maturity/real_teaching_journeys_minimax.py",
        "```",
        "",
        "真实模型运行需设置环境变量（凭证绝不出现在仓库中）；结果 JSON 落盘在",
        "`TRAINER_MATURITY_WORKSPACE`（默认 `tmp/maturity-ws/`，不入库）。",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    print("=== Trainer 教学旅程 28 案例 harness ===")
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    fixture_root = WORKSPACE / "fixtures"
    fixtures: dict[str, dict] = {}
    for case in CASES:
        fixture = check_case_fixture(case, fixture_root / case["id"])
        fixtures[case["id"]] = fixture
        status = "ok" if fixture["fixture_ok"] else "FIXTURE-FAIL"
        print(
            f"[{case['id']}] fixture={status} pre={fixture['pre_fix_exit']} "
            f"post={fixture['post_fix_exit']}"
        )

    api_key = os.environ.get("TRAINER_MATURITY_API_KEY", "").strip()
    provider_url = os.environ.get("TRAINER_MATURITY_PROVIDER_BASE_URL", "").strip()
    if not api_key or not provider_url:
        result = skipped_run(fixtures)
        print(
            "\n[skip] TRAINER_MATURITY_API_KEY / TRAINER_MATURITY_PROVIDER_BASE_URL 未设置："
            "56 个模型回合全部 skipped_no_credentials，未执行真实调用。"
        )
    else:
        provider = build_provider()
        result = run_real_journeys(provider, api_key)

    fixture_ok = sum(1 for case in result["cases"] if case["fixture"]["fixture_ok"])
    counts = _classification_counts(result)
    (WORKSPACE / "report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    write_report(result)
    print(f"\n夹具：{fixture_ok}/28 通过；回合分类：{counts}")
    print(f"报告：{REPORT_PATH}")
    return 0 if fixture_ok == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
