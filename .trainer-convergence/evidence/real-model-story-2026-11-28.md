# 契约 §10 故事（真实模型） — coach replies for the human teaching-quality sign-off

Run: 2026-11-28 13:25:13. Model: MiniMax-M2.7. Gateway: the owner's. Path: `/turn/stream` through a real sidecar, guided answer policy, tools enabled, a scratch learner project. The learner's messages and code edits were scripted to play the learner; every coach reply below is the model's visible text, verbatim.

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

- 模型请求 2 次；工具调用：project_read
- 首个可见文字：请求后 3546 ms；回复完整：5302 ms
- 长度 668 字；代码块 0 个；内部术语命中：none；空话命中：none
- 存下的“下一步”：说清 TimeoutError 的来源层和你定义的幂等不变量

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

好，先不给答案。我先只把当前状态摆清楚，你来说理解。

现状是 `payments.py` 里三个东西：`charge(order_id, amount)` 往 `CHARGED` 里追加一条记录；`retry()` 在 `for attempt in range(3)` 里调 `charge`，捕获 `TimeoutError` 后 sleep 再试，全失败返回 `"failed"`。

在你说理解之前，我想要你先卡住两个点：

第一，`charge` 里并没有任何地方会抛 `TimeoutError`。也就是说当前这版代码里，`retry` 的 except 分支永远不会走到--那 `TimeoutError` 是从哪来的？这个"从哪来"决定了幂等问题到底发生在哪一层：是在 `charge` 内部（钱扣了但客户端没收到响应），还是在 `charge` 之前（请求根本没到）。这两种情况的幂等解法完全不同。

第二，`CHARGED` 是个进程内全局列表。你先想清楚：在这个模型里，"幂等"到底意味着什么状态不变量？是 `CHARGED` 里同一个 `order_id` 最多出现一次，还是"重试和一次成功调用产生的最终效果一致"？这两句话看起来像，其实约束的对象不一样--前者约束列表内容，后者约束调用次数与副作用的关系。

你先回答我这两个点：TimeoutError 应该从哪一层抛出，以及你理解的幂等不变量是哪一句。答完我再顺着你的理解往下推。

下一步：说清 TimeoutError 的来源层和你定义的幂等不变量

---

## 回合 2：`mon-2 understanding`

- 模型请求 1 次；工具调用：无
- 首个可见文字：请求后 6237 ms；回复完整：8111 ms
- 长度 523 字；代码块 0 个；内部术语命中：none；空话命中：none
- 存下的“下一步”：写出网关超时抛在 append 之前和之后两种时序，各说一句会不会重复扣款

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

你的第二条抓对了--"同一个请求做多次，结果和做一次一样"是幂等该有的样子，而且你特意说的是"结果"而不是"调用次数"，这个区分很关键。

第一条还差一层。**当前代码里 `except TimeoutError` 根本走不到**：`charge` 只有一行 `append`，不会抛超时。所以"可能被记两次"目前是一个假设，不是既有行为。你要定位的是：`TimeoutError` 在真实世界里从哪一层冒出来。

那层就是**支付网关的调用**。而这带来两种时序：

1. 网关调通了，钱扣了，但读响应时超时 → 异常在 `append` 之前抛，还是在 `append` 之后抛？
2. 请求压根没到网关 → 干净失败，重试是安全的。

真正决定幂等要不要做、怎么做的是这两种时序的差别。特别提醒一个容易被跳过的点：**幂等是 `charge` 的性质，`retry` 只是放大器**。`charge` 自己重复调用两次，`CHARGED` 里就是两条,状态已经不一样了--retry 只是让它被触发得更频繁。你要修的不是"别重试",是"重复触发也安全"。

下一步：写出网关超时抛在 append 之前和之后两种时序，各说一句会不会重复扣款

---

## 回合 3：`mon-3 fixed`

- 模型请求 1 次；工具调用：无
- 首个可见文字：请求后 11434 ms；回复完整：13957 ms
- 长度 920 字；代码块 1 个；内部术语命中：none；空话命中：none
- 存下的“下一步”：在 charge 里加一层会抛 TimeoutError 的网关调用，让重试路径真正可跑

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

先说对的部分：你的检查确实实现了你定义的那句不变量--同一个 `order_id` 第二次进 `charge`，`CHARGED` 不变、返回 `"already charged"`，所以"做多次"和"做一次"结果一致。而且检查放在 `charge` 里而不是 `retry` 里，这是对的，因为幂等是 `charge` 的性质。

但有三个缺口，按严重程度排：

**一、你的保护护不住真正花钱的那一步。** `CHARGED.append` 不是副作用，网关扣款才是。超时发生在网关扣完款、响应回来之前时：

```python
def gateway_charge(oid):
    print("gateway charged", oid)   # 钱已经扣了
    raise TimeoutError()             # 但响应没回来
```

这时本地 `CHARGED` 还是空的。你的检查看到"没有这条记录"，于是重试再次调网关 → 重复扣款，而 `CHARGED` 最后只有一条。**列表记录的是"我们以为发生过什么"，不是"实际发生过什么"**--这就是为什么本地去重不等于幂等。

**二、`except TimeoutError` 依然不可达。** `charge` 里没有网关调用，就永远不会抛超时，`retry` 的 except 分支是死代码。这意味着你的重试路径从没被真正跑过，而且现在的 `retry` 实际上总是第一次就成功返回。

**三、只比 `order_id` 不比 `amount`。** 同一 `order_id` 换了金额会被当成"已扣款"静默吞掉，调用方拿到的是成功信号却没有任何告警。

正确的方向：幂等键（`order_id`）要传到网关那一层，由网关保证同一个键不重复扣；本地列表降级成"观察网关结果的地方"，而不是幂等的执行者。同时 `charge` 里补一个金额一致性检查。

已知：`charge` 现在对本地状态幂等了；未知：网关那层的重复扣款还没被防住。

下一步：在 charge 里加一层会抛 TimeoutError 的网关调用，让重试路径真正可跑

---

## 回合 4：`thu-1 similar bug`

- 模型请求 1 次；工具调用：无
- 首个可见文字：请求后 2645 ms；回复完整：3036 ms
- 长度 169 字；代码块 0 个；内部术语命中：none；空话命中：none
- 存下的“下一步”：在 refund 里加一层会抛 TimeoutError 的网关退款调用

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

一句提示:先让 `TimeoutError` 真的从"退钱那一步"抛出来--否则你的重试分支和 `payments.py` 一样是死代码,你修不到真正的风险点。

已知:幂等键要落在执行副作用的那一层;未知:`refund` 目前没有可抛超时的外部调用。

下一步：在 refund 里加一层会抛 TimeoutError 的网关退款调用

---

## 回合 5：`thu-2 fixed`

- 模型请求 4 次；工具调用：project_read, project_read, project_read, project_verify
- 首个可见文字：请求后 15504 ms；回复完整：18635 ms
- 长度 808 字；代码块 0 个；内部术语命中：none；空话命中：none
- 存下的“下一步”：保存 refunds.py 后，让 refund 调用一个会抛 TimeoutError 的网关函数

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

我读了你磁盘上的 `refunds.py`--它和上一轮我看到的内容**逐字相同**，没有网关调用，`except TimeoutError` 还是走不到。所以要么改动没保存，要么改在了别的文件里。先确认一下保存。

另外有两个缺口，即使你加了网关层也还在：

**一、`retry_refund` 丢掉了 `refund` 的返回值。** `refund` 现在有两条出口：命中重复时返回 `"already refunded"`，正常路径返回 `None`。但 `retry_refund` 里是 `refund(...)` 然后无条件 `return "ok"`--调用方分不清"这次真的退了"和"上次已经退过了"。这在退钱场景里是要出事的：调用方拿到 `"ok"` 就认为可以给用户确认退款，而实际这一轮什么都没做。对比一下 `payments.py` 的 `retry`，同一个毛病。

**二、退款失败不能是"空操作"式的成功。** 现在如果 `refund` 抛异常（不是超时，而是别的错误，比如网关明确拒绝），`retry_refund` 会把异常直接抛出去--这个其实对。但超时重试三次后返回 `"failed"`，此时**钱可能已经退给了用户**（网关扣完款、响应超时），本地 `REFUNDED` 却是空的。这跟扣款那次的结构一模一样：本地列表记的是"我们以为发生过什么"。

所以这次真正要落的是上一轮那个提示的完整版：幂等键 `order_id` 必须一路传到网关，由网关保证同一个键不重复退款；本地 `REFUNDED` 只是"观察网关结果"的地方。

已知：`refund` 对本地状态幂等，`retry_refund` 会吞掉结果;未知：重复退款和"假成功"都还没被防住。

下一步：保存 refunds.py 后，让 refund 调用一个会抛 TimeoutError 的网关函数

---

## 这次运行的客观记录（供签核参考）

| 回合 | 模型请求 | 工具 | 首个可见文字 | 回复完整 | 字数 | 代码块 |
|---|---|---|---|---|---|---|
| 1 mon-1 | 2 | project_read | 3.5 s | 5.3 s | 668 | 0 |
| 2 mon-2 | 1 | 无 | 6.2 s | 8.1 s | 523 | 0 |
| 3 mon-3 | 1 | 无 | 11.4 s | 14.0 s | 920 | 1 |
| 4 thu-1 | 1 | 无 | 2.6 s | 3.0 s | 169 | 0 |
| 5 thu-2 | 4 | project_read ×3, project_verify | 15.5 s | 18.6 s | 808 | 0 |

- 五个回合都以“下一步：…”收尾，存下的“下一步”都是具体动作；教练的最后一行之后没有被追加任何服务端句子。
- 回合 4（“只给我一句提示就好”）是一句 169 字的提示，没有代码，2.6 秒出现。
- 回合 3 的那个代码块是一个独立的示例函数（“扣款之后抛超时”的网关），不是学习者代码的改写。
- 回合 1 先摆现状、提出两个要学习者先想清楚的点，要学习者先回答，再往下推；没有给出结论。
- 回合 5 慢在工具：学习者说“改好了，帮我确认”，教练读了三个文件并跑了一次诊断，共 4 次模型往返。
- 这一版代码相对前一次运行的变化：模型现在拿到了项目文件清单（此前它每个项目问题都要先列目录再读文件）；只答一句“然后呢？”且当前文件有报错时，不给它工具，一次请求作答；引导模式下每个回复都要以“下一步”收尾；网关的协议标记和“空内容”哨兵不再进入回复。
- 同一故事此前在中间版本上还跑过五次，原文在会话的临时目录里，没有进仓库。其中两次遇到网关上游 502（连续请求过密时出现），服务端如实报告了失败，没有编造回复。
