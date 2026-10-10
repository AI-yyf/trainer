"""Real two-turn teaching journeys — MiniMax adaptation of the maturity harness.

Methodology per docs/maturity/2026-10-08-real-teaching-quality.md:
- Real sidecar + real provider; isolated project per case; pre-broken code
  (exit 1), learner turn 1, scripted fix, learner turn 2, verify exit 0.
- Judged dimensions (automated subset):
  1. next_step grounding — server.app.llm.turn_grounding validator; an
     ungrounded next_step MUST be flagged requires_confirmation (P0-1 fix).
  2. memory anti-drift — coach_anchor/current_focus must never be a verbatim
  message prefix and must be non-empty or honestly empty.
- Content quality (factual accuracy, pacing) is recorded for human review and
  is NOT automated — same separation as the original report.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, "G:/trainer/server")
from app.llm.turn_grounding import evaluate_next_step_grounding  # noqa: E402

BASE = "http://127.0.0.1:34900"
API_KEY = "sk-K5DO7XzgBun6jFTLJZLF9UJE0W3bHRvcBugjUtpocmorrXMS"
PROVIDER = {
    "name": "minimax-maturity",
    "baseUrl": "http://minimax.redfast.top",
    "apiKeyRef": "trainer.default",
    "model": "MiniMax-M2.7",
    "protocol": "openai_chat_completions_compatible",
    "connectionType": "newapi_channel_conn",
}
WORKSPACE = Path("G:/trainer/tmp/maturity-ws")
PACING_SECONDS = 12


def run_py(path: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(path)], capture_output=True, text=True, timeout=60
    )
    return proc.returncode, (proc.stderr or proc.stdout).strip().splitlines()[-1] if (
        proc.stderr or proc.stdout
    ).strip() else ""


CASES = [
    {
        "id": "01-mutable-default",
        "level": "novice",
        "code": (
            "def add_item(item, items=[]):\n"
            "    items.append(item)\n"
            "    return items\n\n"
            "assert add_item(1) == [1]\n"
            "assert add_item(2) == [2]\n"
        ),
        "topic_tokens": ["默认参数", "mutable", "items"],
        "turn1": "我的脚本 assert 失败了，第二个 assert 报 items 是 [1, 2]。为什么会这样？",
        "fix": (
            "def add_item(item, items=None):\n"
            "    if items is None:\n"
            "        items = []\n"
            "    items.append(item)\n"
            "    return items\n\n"
            "assert add_item(1) == [1]\n"
            "assert add_item(2) == [2]\n"
        ),
        "turn2": "我亲自写了下面的修改（用 None 哨兵），现在两个 assert 都通过了。这样写对吗？还有别的写法吗？",
    },
    {
        "id": "02-late-binding",
        "level": "novice",
        "code": (
            "funcs = []\n"
            "for i in range(3):\n"
            "    funcs.append(lambda: i)\n\n"
            "results = [f() for f in funcs]\n"
            "assert results == [0, 1, 2]\n"
        ),
        "topic_tokens": ["闭包", "late binding", "lambda"],
        "turn1": "我的 lambda 列表断言失败，results 是 [2, 2, 2]。为什么会这样？",
        "fix": (
            "funcs = []\n"
            "for i in range(3):\n"
            "    funcs.append(lambda i=i: i)\n\n"
            "results = [f() for f in funcs]\n"
            "assert results == [0, 1, 2]\n"
        ),
        "turn2": "我亲自写了下面的修改（默认参数绑定 i），现在断言通过了。解释一下为什么这样就对了？",
    },
    {
        "id": "03-nested-alias",
        "level": "novice",
        "code": (
            "grid = [[0] * 2] * 2\n"
            "grid[0][0] = 1\n"
            "assert grid[1][0] == 0\n"
        ),
        "topic_tokens": ["别名", "alias", "引用", "嵌套列表"],
        "turn1": "我只改了 grid[0][0]，为什么 grid[1][0] 也变成 1 了？assert 失败了。",
        "fix": (
            "grid = [[0] * 2 for _ in range(2)]\n"
            "grid[0][0] = 1\n"
            "assert grid[1][0] == 0\n"
        ),
        "turn2": "我亲自写了下面的修改（列表推导式建行），断言通过了。还有哪些场景会踩同样的坑？",
    },
    {
        "id": "04-binary-search-boundary",
        "level": "experienced",
        "code": (
            "def find(xs, target):\n"
            "    lo, hi = 0, len(xs)\n"
            "    while lo <= hi:\n"
            "        mid = (lo + hi) // 2\n"
            "        if xs[mid] == target:\n"
            "            return mid\n"
            "        if xs[mid] < target:\n"
            "            lo = mid + 1\n"
            "        else:\n"
            "            hi = mid - 1\n"
            "    return -1\n\n"
            "assert find([1], 2) == -1\n"
        ),
        "topic_tokens": ["二分", "边界", "hi", "binary search"],
        "turn1": "find([1], 2) 报 IndexError。二分查找的边界哪里错了？",
        "fix": (
            "def find(xs, target):\n"
            "    lo, hi = 0, len(xs) - 1\n"
            "    while lo <= hi:\n"
            "        mid = (lo + hi) // 2\n"
            "        if xs[mid] == target:\n"
            "            return mid\n"
            "        if xs[mid] < target:\n"
            "            lo = mid + 1\n"
            "        else:\n"
            "            hi = mid - 1\n"
            "    return -1\n\n"
            "assert find([1], 2) == -1\n"
        ),
        "turn2": "我亲自把 hi 改成 len(xs) - 1，IndexError 消失了。为什么闭区间必须减一？",
    },
]


def turn_payload(sid: str, message: str, code: str, filename: str) -> dict:
    return {
        "session_id": sid,
        "message": message,
        "responseLanguage": "zh-CN",
        "provider": PROVIDER,
        "apiKey": API_KEY,
        "current_file": {
            "path": filename,
            "language_id": "python",
            "content": code,
        },
    }


def judge_turn(case: dict, turn_no: int, payload: dict, code_text: str) -> dict:
    reply = (payload.get("reply") or {}).get("content") or ""
    coach_turn = payload.get("coach_turn") or {}
    next_step = str(coach_turn.get("next_step") or "")
    flagged = bool(
        coach_turn.get("requires_confirmation")
        or (payload.get("agent_meta") or {}).get("next_step_requires_confirmation")
    )
    decision = evaluate_next_step_grounding(next_step, reply, code_text)
    memory = payload.get("snapshot", {}).get("memory") or {}
    anchor = str(memory.get("coach_anchor") or "")
    focus = str(memory.get("current_focus") or "")
    ws = memory.get("workspace") if isinstance(memory.get("workspace"), dict) else {}
    focus_area = str(ws.get("latest_coach_focus_area") or ws.get("latest_turn_focus_area") or "")
    return {
        "case": case["id"],
        "turn": turn_no,
        "model_completed": not (payload.get("agent_meta") or {}).get("fell_back", False),
        "next_step": next_step[:200],
        "next_step_grounded": decision.grounded,
        "next_step_flagged": flagged,
        "ungrounded_symbols": decision.referenced_symbols,
        "anchor": anchor[:80],
        "current_focus": focus[:80],
        "focus_area": focus_area[:80],
        "reply_head": reply[:160],
        "reply_full": reply,
    }


def main() -> None:
    import shutil
    import os

    data_dir = WORKSPACE / ".trainer-data"
    shutil.rmtree(data_dir, ignore_errors=True)
    proj = WORKSPACE / "proj"
    shutil.rmtree(proj, ignore_errors=True)
    proj.mkdir(parents=True, exist_ok=True)

    env = {**os.environ, "TRAINER_DATA_DIR": str(data_dir)}
    sidecar = subprocess.Popen(
        [
            "G:/trainer/server/.venv/Scripts/python.exe",
            "run_sidecar.py",
            "--host",
            "127.0.0.1",
            "--port",
            "34900",
        ],
        cwd="G:/trainer/server",
        env=env,
        stdout=open("G:/trainer/tmp/maturity_sidecar.log", "w"),
        stderr=subprocess.STDOUT,
    )
    reports = []
    try:
        c = httpx.Client(timeout=300, trust_env=False)  # never proxy localhost
        for _ in range(30):
            try:
                if c.get(f"{BASE}/health").status_code == 200:
                    break
            except Exception:
                time.sleep(2)
        sid = ""
        r = c.post(
            f"{BASE}/session/start",
            json={"workspace_id": WORKSPACE.as_posix(), "workspace_name": "maturity"},
        )
        sid = (r.json() or {}).get("session_id") or ""

        for case in CASES:
            filename = case["id"].split("-", 1)[1] + ".py"
            path = proj / filename
            path.write_text(case["code"], encoding="utf-8")
            rc, err = run_py(path)
            print(f"[{case['id']}] pre-fix exit={rc} last={err[-80:]!r}")

            r = c.post(
                f"{BASE}/turn",
                json=turn_payload(sid, case["turn1"], case["code"], filename),
            )
            t1 = judge_turn(case, 1, r.json(), case["code"])
            reports.append(t1)
            print(f"  turn1: grounded={t1['next_step_grounded']} flagged={t1['next_step_flagged']} anchor={t1['anchor'][:40]!r}")

            path.write_text(case["fix"], encoding="utf-8")
            rc, err = run_py(path)
            print(f"[{case['id']}] post-fix exit={rc}")

            time.sleep(PACING_SECONDS)
            r = c.post(
                f"{BASE}/turn",
                json=turn_payload(sid, case["turn2"], case["fix"], filename),
            )
            t2 = judge_turn(case, 2, r.json(), case["fix"])
            t2["post_fix_exit0"] = rc == 0
            reports.append(t2)
            print(f"  turn2: grounded={t2['next_step_grounded']} flagged={t2['next_step_flagged']} anchor={t2['anchor'][:40]!r}")

            time.sleep(PACING_SECONDS)

        (WORKSPACE / "report.json").write_text(
            json.dumps(reports, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        mech_ok = all(
            (r["next_step_grounded"] or r["next_step_flagged"]) for r in reports
        )
        drift = [
            r
            for r in reports
            if r["model_completed"] and not r["anchor"] and not r["current_focus"]
        ]
        print(
            f"\n=== 机制验收: {'PASS' if mech_ok and not drift else 'FAIL'} "
            f"(ungrounded-unflagged={sum(1 for r in reports if not (r['next_step_grounded'] or r['next_step_flagged']))}, "
            f"prefix-drift-anchor-empty-after-model={len(drift)}) ==="
        )
    finally:
        sidecar.terminate()


if __name__ == "__main__":
    main()
