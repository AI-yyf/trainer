# 契约 §10 故事（真实模型） — coach replies for the human teaching-quality sign-off

Run: 2026-11-28 11:37:05. Model: MiniMax-M2.7. Gateway: the owner's. Path: `/turn/stream` through a real sidecar, guided answer policy, tools enabled, a scratch learner project. The learner's messages and code edits were scripted to play the learner; every coach reply below is the model's visible text, verbatim.

Contract §10 requires a human teaching-quality sign-off before any "complete" claim; this document puts the replies in front of the signer. Not covered by this run, by design: the host attestation that records "independent completion", the two-week review, and the controlled clock.

## What to check (quoted from the contract)

- §2 北极星: 一段学习对话至少留下一次尝试、一条证据或一个约好的复习；教练说得越少越好，学习者动手越多越好。
- §3: 界面只出现目标 / 练习 / 掌握进度 / 资料四个概念，不泄漏内部术语（候选卡、入库、账本、投影、修订号、到期队列……）。
- §5: 先状态后方案；默认快节奏——先给一个最小可验证动作或直指缺口的反问；用学习者的项目当教材；禁用空话垫词。
- §8: 教练只讲解、分析、引导、验证，从不编写或修改学习者的项目代码。
- §10: 周一教练读项目、指出 `retry()` 的重复写入、先让学习者说出自己的理解再让学习者自己改；周四只提醒一句，学习者自己修好。

## 签核

- [ ] 通过        - [ ] 有保留通过        - [ ] 不通过

备注（可写回合编号）：

```

```

---

## 回合 1：`mon-1 goal`

- 模型请求 1 次；工具调用：无
- 首个可见文字：请求后 3753 ms；回复完整：5575 ms
- 长度 583 字；代码块 0 个；内部术语命中：none；空话命中：none
- 存下的“下一步”：写下你对上面三题的回答，尤其第 3 题的 `CHARGED` 结果。

**学习者说**

> 我想真正搞懂幂等。先帮我看看 payments.py 里的 retry() 有没有问题，但先别告诉我答案，让我先说说我的理解。

**学习者当前打开的文件 `payments.py`**

```python
import time

CHARGED = []

def charge(order_id, amount):
    CHARGED.append((order_id, amount))

def retry(order_id, amount):
    for attempt in range(3):
        try:
            charge(order_id, amount)
            return "ok"
        except TimeoutError:
            time.sleep(0.1 * (attempt + 1))
    return "failed"
```

**教练回复（原文）**

先看代码本身，再说你的理解，最后我们才碰结论。

当前 `retry()` 的骨架是：最多 3 轮，每轮调 `charge()`，捕获 `TimeoutError` 就退避后重试。而 `charge()` 做的唯一事是把 `(order_id, amount)` 追加进模块级的 `CHARGED` 列表。注意两点结构事实：`charge` 里没有任何会抛 `TimeoutError` 的语句；`CHARGED` 是一个全局共享的列表，跨调用累积。

在这块之上，我想先听你说三件事（每件一两句话就够，不用长）：

1. 你说的“幂等”，在这个文件里具体指什么？靠哪个字段、哪个状态来判断“这次请求已经做过”？
2. `retry("o1", 10)` 正常跑完一次之后，`CHARGED` 里应该有几条记录？如果重复调用 `retry("o1", 10)` 三次，理想情况下又该是几条？
3. 假设 `charge()` 内部真的可能在“已经把订单写进 `CHARGED`”之后抛出 `TimeoutError`（这是支付网关最典型的形态），那么 `retry` 的第 2 轮会做什么？`CHARGED` 会变成什么？

第 3 题是关键--先别急着看我的判断，你先说出你会怎么想。

下一步：写下你对上面三题的回答，尤其第 3 题的 `CHARGED` 结果。

---

## 回合 2：`mon-2 understanding`

- 模型请求 1 次；工具调用：无
- 首个可见文字：请求后 5371 ms；回复完整：6842 ms
- 长度 446 字；代码块 0 个；内部术语命中：none；空话命中：none
- 存下的“下一步”：用两三行写下你的判据设计，并说明它如何区分同一笔。

**学习者说**

> 我的理解：retry 超时后会再调一次 charge，而 charge 每次都往 CHARGED 里追加，所以同一笔可能被记两次。幂等就是同一个请求做多次，结果和做一次一样。

**学习者当前打开的文件 `payments.py`**

```python
import time

CHARGED = []

def charge(order_id, amount):
    CHARGED.append((order_id, amount))

def retry(order_id, amount):
    for attempt in range(3):
        try:
            charge(order_id, amount)
            return "ok"
        except TimeoutError:
            time.sleep(0.1 * (attempt + 1))
    return "failed"
```

**教练回复（原文）**

你的两点我认可：幂等的定义（同一请求做多次，效果等同做一次）说对了；“超时重试会记两笔”这条推断，在网关真的会在写入之后抛 `TimeoutError` 的前提下也成立。

还差的一块在这里：现在代码里没有任何东西能识别“这是同一笔请求”。`CHARGED` 是只追加的列表，`charge` 只写不查，所以第二轮调用 `retry` 时它根本无从判断--幂等不会因为有了 `retry` 就自动出现，它必须靠一个显式的“这次是不是已经做过”的判据来支撑。

还有个细节值得你留意：按文件现在的写法，`charge` 里没有任何会抛 `TimeoutError` 的语句，所以这份代码跑起来永远不会重试。你要分析的两笔重复，依赖的是网关超时这个外部形态。

先不给实现，先请你补一句：在 `charge` 之前加一道检查时，你打算拿什么当“这同一笔”的依据--复用 `CHARGED` 本身，还是单独维护一个键集合？各说一句理由。

下一步：用两三行写下你的判据设计，并说明它如何区分同一笔。

---

## 回合 3：`mon-3 fixed`

- 模型请求 1 次；工具调用：无
- 首个可见文字：请求后 11081 ms；回复完整：13900 ms
- 长度 971 字；代码块 1 个；内部术语命中：账本；空话命中：显然
- 存下的“下一步”：把 `CHARGED` 改成 dict 并在金额不一致时抛 `ValueError`。

**学习者说**

> 我按你的思路在 charge 里加了一个检查，改好了。帮我看看对不对。

**学习者当前打开的文件 `payments.py`**

```python
import time

CHARGED = []

def charge(order_id, amount):
    if any(entry[0] == order_id for entry in CHARGED):
        return "already charged"
    CHARGED.append((order_id, amount))
    return "ok"

def retry(order_id, amount):
    for attempt in range(3):
        try:
            charge(order_id, amount)
            return "ok"
        except TimeoutError:
            time.sleep(0.1 * (attempt + 1))
    return "failed"
```

**教练回复（原文）**

你的判据选对了：键是 `order_id`（业务键，不是请求参数），检查发生在写入之前，所以“网关已写库、随后超时”的重试会命中检查、返回 `already charged` 而不再追加--账本仍然只有一笔。这正是幂等该有的形状。

但有三处还需要你处理：

**1. `retry` 把 `charge` 的返回值丢了。** 第二次调用返回的是 `"already charged"`，可 `retry` 无视它、自己 `return "ok"`。账本没错，但调用方分不清“这次真扣了”还是“上次已扣过”。如果下游要拿扣款结果，这里得透传。

**2. `amount` 既不在键里、也没被校验。** 同一个 `order_id` 带不同金额再来，会被静默判成“已扣”，钱按第一次的金额算，第二次的金额被无声吞掉。幂等命中和参数冲突是两件事，不该共用一个返回值：

```python
    if order_id in CHARGED:
        if CHARGED[order_id] != amount:
            raise ValueError("amount mismatch")
        return "already charged"
```

要能这样比金额，`CHARGED` 得从 list 改成 `dict`，用 `order_id` 直接索引存金额--现在靠 `any(entry[0] ==...)` 扫描是拿不到已有金额的。

**3. 非显然的那点：这份检查不是原子的。** `any(...)` 检查和 `append` 之间有间隙，两个并发线程可以同时通过检查、各自追加一笔。你现在保证的是“串行重试幂等”，不是“并发幂等”。真要扛并发，得靠数据库唯一索引或一把锁把这两步合成一步。

还有个验证上的空缺：`charge` 里没有会抛 `TimeoutError` 的语句，所以 `retry` 的 `except` 分支目前是死代码--你还没真正跑过重试路径。

已知：判据选对（`order_id`）、检查前置，重试不会重复入账；未知：返回值透传、金额冲突、并发原子性。

下一步：把 `CHARGED` 改成 dict 并在金额不一致时抛 `ValueError`。

---

## 回合 4：`thu-1 similar bug`

- 模型请求 1 次；工具调用：无
- 首个可见文字：请求后 2468 ms；回复完整：2781 ms
- 长度 199 字；代码块 0 个；内部术语命中：none；空话命中：none
- 存下的“下一步”：决定检查放在 `refund` 还是 `retry_refund`，并说明理由。

**学习者说**

> 我在 refunds.py 里也碰到类似的超时重试问题，这次我想自己修，只给我一句提示就好。

**学习者当前打开的文件 `refunds.py`**

```python
import time

REFUNDED = []

def refund(order_id, amount):
    REFUNDED.append((order_id, amount))

def retry_refund(order_id, amount):
    for attempt in range(3):
        try:
            refund(order_id, amount)
            return "ok"
        except TimeoutError:
            time.sleep(0.05)
    return "failed"
```

**教练回复（原文）**

提示：在 `refund` 里追加之前，先看看这个 `order_id` 是否已经在 `REFUNDED` 里出现过。

已知：你的判据思路在 `payments.py` 已验证可行，这次只是换个文件复用同一形状；未知：`refund` 里要不要引入判据、还是把检查放在 `retry_refund` 里。

下一步：决定检查放在 `refund` 还是 `retry_refund`，并说明理由。

---

## 回合 5：`thu-2 fixed`

- 模型请求 2 次；工具调用：project_read, project_verify
- 首个可见文字：请求后 9043 ms；回复完整：12101 ms
- 长度 947 字；代码块 0 个；内部术语命中：none；空话命中：none
- 存下的“下一步”：给 `refund` 加一个可注入的失败点，跑出一次真实超时并确认 `REFUNDED` 只有一条。

**学习者说**

> refunds.py 也改好了，帮我确认一下。

**学习者当前打开的文件 `refunds.py`**

```python
import time

REFUNDED = []

def refund(order_id, amount):
    if any(entry[0] == order_id for entry in REFUNDED):
        return "already refunded"
    REFUNDED.append((order_id, amount))

def retry_refund(order_id, amount):
    for attempt in range(3):
        try:
            refund(order_id, amount)
            return "ok"
        except TimeoutError:
            time.sleep(0.05)
    return "failed"
```

**教练回复（原文）**

结构对了：检查放在 `refund` 里、且在 `append` 之前，所以“网关已写库→超时→重试”这条路会命中检查返回 `already refunded`，`REFUNDED` 里仍是一笔。判据也用 `order_id`，和 `payments.py` 同一形状。

还有四个缺口，按重要性：

**1. 你没法验证重试路径。** `refund` 里没有任何会抛 `TimeoutError` 的语句，`except TimeoutError` 是死代码。幂等的关键恰恰发生在“超时之后”，这条路径你现在跑不到。要验证，得有一个可注入的失败点（比如一个独立的下游调用，或让 `refund` 接受一个可注入的 gateway），否则你的检查只是“顺序调用下不会重复”，不是“重试下不会重复”。

**2. 返回值在 `retry_refund` 里被丢弃。** 第二轮 `refund` 返回 `"already refunded"`，但 `retry_refund` 无视它、自己 `return "ok"`。结果没错，语义错：调用方看到 `"ok"` 无法知道这轮是自己扣的还是早先扣的。

**3. `refund` 成功路径没有 return。** 它 append完就返回 `None`，而 `charge` 返回 `"ok"`。两个文件现在不对称，`refund` 应该在成功时返回 `"ok"`，让 `retry_refund` 有东西可透传。

**4. 金额仍未校验。** 同一个 `order_id` 带不同金额进来会被静默判成“已退款”，金额差异被吞掉。`REFUNDED` 是 list，拿不到首次的金额，所以这一步必须改 dict。

另外顺带一提：我读到磁盘上的 `payments.py` 还是 list 版本，你之前说的 dict + `ValueError` 似乎没保存或存到别处了，两边先对齐再继续。

已知：`refunds.py` 的检查位置和判据正确，串行重试不会重复入账；未知：超时路径根本没被触发验证过，返回值与金额语义仍缺失。

下一步：给 `refund` 加一个可注入的失败点，跑出一次真实超时并确认 `REFUNDED` 只有一条。

---

## 这次运行的客观记录（供签核参考）

| 回合 | 模型请求 | 工具 | 首个可见文字 | 回复完整 | 字数 | 代码块 |
|---|---|---|---|---|---|---|
| 1 mon-1 | 1 | 无 | 3.8 s | 5.6 s | 583 | 0 |
| 2 mon-2 | 1 | 无 | 5.4 s | 6.8 s | 446 | 0 |
| 3 mon-3 | 1 | 无 | 11.1 s | 13.9 s | 971 | 1 |
| 4 thu-1 | 1 | 无 | 2.5 s | 2.8 s | 199 | 0 |
| 5 thu-2 | 2 | project_read, project_verify | 9.0 s | 12.1 s | 947 | 0 |

- 五个回合都以“下一步：…”收尾，存下的“下一步”都是具体动作。
- 回合 4（“只给我一句提示就好”）是一句 199 字的提示，没有代码。
- 回合 3 含一个 4 行的代码片段（金额不一致时抛 `ValueError`），位于学习者的 `charge()` 内部——提示词允许“至多一个指向学习者自己代码的小片段”，但 §8 写的是从不编写学习者的项目代码，请签核时判断。
- 回合 3 用“账本”指支付侧的幂等记录，是业务用语而非 Trainer 的内部术语；脚本按字面把它标了出来。
- 五个回合都没有写出学习者函数的完整版本。
- 同一故事此前还跑过两次（一次在答题模式字段写错、实际为“直接”策略时，一次在“引导”策略下），回复原文在会话的临时目录里，没有进仓库。
