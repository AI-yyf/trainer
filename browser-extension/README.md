# Trainer Capture（浏览器拓展）

把**当前网页 / PDF / GitHub 仓库**一键加入 Trainer 资料库，把 **PDF / GitHub 仓库下载到项目文件夹**，并把**划词**送进 Trainer 教练输入框的 Chromium MV3 拓展。

拓展只有一个归宿：**资料库**。它没有「待学队列」之类的概念——离线时进入的是「待投递队列」（等待网络恢复后原样投递给 sidecar），投递完成后即出队。下载是采集的**附加动作**（同一个来源既可以入资料库，也可以落到项目文件夹），不是替代路径。

## 设计边界

- **纯数据通道**：不注入页面脚本执行代码，不读取 cookie，不读取页面正文；只发送用户明确触发的内容（`url` / `kind` / `title` / 选中的文本）。
- **服务端抓取**：正文、快照、权威去重全部由本地 Trainer sidecar 完成（网页 → 正文抽取；PDF → 下载后 PDF ingest；GitHub → repo URL + README/结构）。
- **面向本机的权限**：`host_permissions` 仅覆盖 `http://127.0.0.1/*` 与 `http://localhost/*`。content script 只在 http(s) 页面按 `document.contentType` 判断是否为 PDF，非 PDF 页面完全静默。

## 加载（开发者模式）

1. 打开 `chrome://extensions`（Edge 为 `edge://extensions`），开启右上角「开发者模式」。
2. 点击「加载已解压的扩展程序」，选择本目录（`browser-extension/`）。
3. 保持 Trainer 的 sidecar 在运行（VS Code 中打开 Trainer 即可）。

也可以在仓库根目录执行 `npm run package:browser-extension` 生成
`dist/trainer-capture-extension.zip`，解压后再按上面步骤加载。

## 配对（零手动配置）

1. 打开拓展弹窗。拓展会自动探测本机 sidecar：先试 `http://127.0.0.1:8765`，再扫描 VS Code 托管端口段 `34891-34911`（短超时）。
2. 探测成功后，在 VS Code 执行 **「Trainer: 复制配对码」**，把 6 位码粘贴进弹窗并点「配对」。
3. 拓展调用 `POST /browser/pair {code}` 换取凭证（credential），凭证与端口写入 `chrome.storage.local`——之后打开弹窗无感直连，不需要再输入任何地址或令牌。
4. 弹窗底部提供「撤销配对」（`DELETE /browser/pair`，并清空本地凭证、待投递队列与本地采集记录）与「重新配对」。

未配对时，所有采集入口（右键菜单 / 弹窗按钮 / PDF 浮出按钮）都会先提示完成配对，而不会丢失任何输入。

## 采集

| 入口 | 行为 |
| --- | --- |
| 页面右键「加入 Trainer 资料库」 | 采集当前页面（自动识别 `.pdf` / GitHub 仓库地址） |
| 链接右键「加入资料库（链接）」 | 采集链接地址，`.pdf` 按 PDF 处理 |
| PDF 页右键「PDF 选项」子菜单 | 「加入资料库（PDF）」/「下载 PDF 到项目文件夹」 |
| PDF 链接右键「PDF 选项」子菜单 | 同上，针对被右键的链接地址 |
| GitHub 仓库页右键「加入资料库（GitHub 仓库）」 | 子项「README+结构」/「含 docs/」/「下载项目到文件夹」分别提交 `include_docs:false/true` 与 `download:true` |
| 选中文本右键「问 Trainer 教练」 | `POST /browser/coach-draft`，通知「已送入 Trainer 输入框」——**不自动发送**，预填由宿主侧完成 |
| PDF 页面角落浮出按钮「加入 Trainer」 | 仅当 `document.contentType === 'application/pdf'` 时出现 |
| 弹窗「将当前页面加入资料库」 | 采集当前标签页，并可先在下拉里**可选**绑定学习目标 |
| 弹窗「下载到项目文件夹」 | 仅对 PDF / GitHub 仓库出现；目标文件夹可编辑（默认 `Trainer Library/`），选择即成为右键菜单下载的默认值 |

**绑定学习目标**：下拉选项来自 `GET /browser/status` 的 `focus_options`，可留空不绑；弹窗里的选择同时作为右键菜单采集的默认绑定（存 `chrome.storage.local`）。

**幂等**：每次捕获都带 `client_capture_id`，离线重投不会产生重复记录；服务端返回 `deduped=true` 时提示「已在资料库」并给出深链。

## 下载到项目文件夹

下载是采集的附加选项，捕获进资料库仍是一切的基础动作：

- 请求体在捕获字段之上追加 `download: true` 与 `target_dir`（项目内相对路径，默认 `Trainer Library/`，服务端实时创建目录）。
- PDF（页面或链接）与 GitHub 仓库各有一个「下载…到项目文件夹」入口；网页没有单一可下载文件，因此不提供该入口。
- 目标文件夹由弹窗维护（存 `chrome.storage.local`），右键菜单下载沿用最近一次设置；弹窗里输入绝对路径、`~`、盘符或含 `..` 的路径会当场拒绝（校验在 `shared.js` 的 `normalizeTargetDir`，不会把可逃逸路径发给 sidecar）。
- 完成通知显示服务端返回的 `saved_path`，并附「在 VS Code 打开」深链（点击通知即打开）；弹窗「最近采集」同样显示保存路径与深链。
- 离线时下载请求与普通采集一样入队（队列项保存 `download` / `targetDir`），恢复后按原字段自动投递，仍然幂等。

## 去重（客户端提示层 + 服务端权威层）

- 客户端先做 URL 规范化：去 `utm_*` / `fbclid` / `gclid` 等跟踪参数、去 `#hash`、去尾斜杠、排序查询参数（仅用于去重键），再比对本地历史与待投递队列。
- GitHub「README+结构」与「含 docs/」变体使用不同的去重键，不会被误判为重复。
- 服务端仍是权威去重方（快照内容、跨设备）；本地这层只避免重复提交与重复排队。
- 命中本地历史（状态为成功 / 已在资料库）时直接给出「已在资料库（本地记录）」与深链，不再发起请求；命中待投递队列时提示「已在待投递队列」。删掉资料库里的资源后如需重新采集，先执行「撤销配对」（会同时清空本地采集记录）再重新配对即可。

## 离线队列 + 自动投递

- sidecar 不可达（连接失败 / 超时 / 5xx）→ 捕获连同全部字段与 `client_capture_id` 进入 `chrome.storage.local` 队列。
- `chrome.alarms` 每 1 分钟探活；成功即按序 FIFO 投递：成功出队，`deduped=true` 同样视为成功并标记为重复。
- 永久性失败（如 4xx：工作区只读、网络抓取被关闭、凭证失效）不会排队，直接记为失败并提示。
- 工具栏角标显示队列数量（未配对时显示 `!`），徽标底色与图标同为 Trainer indigo `#4338CA`。
- 弹窗在「Trainer 未运行」状态下提供**完整队列管理**：条目列表（标题 / 类型 / 时间 / 尝试次数 / 下载目标）、单条删除、「立即重试」、「清空队列」（带确认），并说明「捕获会自动暂存，Trainer 启动后自动送达」。

## Trainer 未运行时的状态（三态弹窗）

| 状态 | 判定 | 提供什么 |
| --- | --- | --- |
| 未配对 | 没有本地凭证 | 探测 sidecar、6 位配对码输入、去 VS Code 取码的说明 |
| 已配对 / Trainer 未运行 | 有凭证，但最近一次探活失败 | 「Trainer 未运行」状态卡 + 自动送达说明 + 完整队列管理；**采集 / 下载 / 划词照常可用**，全部入队 |
| 已连接 | 有凭证且 sidecar 有响应 | 状态卡（工作区名 + 资料库计数）、最近 5 条记录（含深链）、快速绑定学习目标；队列非空时同时显示队列区块 |

连通性快照（`ok` / `offline` / `unknown`）由后台在每次探活、采集与投递后写入 `chrome.storage.local`，弹窗据此区分「未配对」与「Trainer 未运行」——已配对但未运行时，捕获不会丢失、不报错，只是排队。

## 深链

捕获成功 / 已存在 / 队列投递完成的入口都会给出「在 Trainer 中打开」链接：

```
vscode://local.trainer-extension/library/<resource_id>
```

system 通知可直接点击打开；弹窗「最近采集」列表（最近 5 条）内的链接同样可点。

## 弹窗结构

| 区块 | 内容 |
| --- | --- |
| 顶部 | 品牌标记（indigo 圆角方 + 金色几何 T）、状态行（配对 / 未运行 / 已连接，带状态点）、队列计数 chip |
| 配对面板（未配对） | 探测结果、6 位配对码输入、配对 / 重新探测、取码说明 |
| 未运行面板（已配对、Trainer 未运行） | 「Trainer 未运行」状态卡 + 自动送达说明 |
| 已连接面板 | 工作区名、资料库计数 |
| 采集面板（两种已配对状态） | 当前页面、绑定学习目标下拉、「加入资料库」；PDF / GitHub 页额外显示「下载到项目文件夹」区块（目标文件夹输入 + 下载按钮） |
| 待投递 | 队列计数、条目列表（单条删除）、「立即重试」、「清空队列」 |
| 最近采集 | 最近 5 条记录（来源、状态、时间、下载保存路径、深链） |
| 底部 | 撤销配对 / 重新配对（已配对时显示）/ 打开 Trainer；配对失效等提示 |

### 设计语言与动效

- 令牌化配色：indigo `#4338CA`（主色）/ gold `#F59E0B`（强调、离线与下载）/ slate 中性色；`prefers-color-scheme` 提供深浅两套，圆角、留白与层次（卡片阴影、状态点光晕）统一由 CSS 变量驱动，无硬编码散色。
- 动效轻且解释状态变化：弹窗打开淡入上移（120–160ms）、状态面板切换上移淡入、捕获成功勾线绘制 ✓、队列计数变化微弹、按钮 hover 上浮 / 按压回弹、错误抖动一次。
- 所有动画在 `prefers-reduced-motion: reduce` 下退化为瞬时；`prefers-color-scheme` 与动效均可在 CSS 静态审查。
- 弹窗内小图标统一为内联 SVG sprite：`stroke-width 1.7`、圆头圆角（`round` cap/join），与品牌标记同一套语法。

### 图标

`icons/icon16|32|48|128.png` 由手绘 SVG 源文件 `icons/trainer-capture.svg` 渲染（indigo 圆角方 + 金色几何 T 与教练标记点），`manifest.json` 的 `icons` / `action.default_icon` 指向这四个 PNG：

```bash
cd server && .venv/bin/python - <<'PY'
import pymupdf
src = "../browser-extension/icons/trainer-capture.svg"
for size in (16, 32, 48, 128):
    page = pymupdf.open(src)[0]
    zoom = size / max(page.rect.width, page.rect.height)
    page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True).save(
        f"../browser-extension/icons/icon{size}.png"
    )
PY
```

UI 文案跟随浏览器 locale，提供 **8 套**：zh-CN、en-US、es-ES、fr-FR、de-DE、ja-JP、ko-KR、pt-BR。

语言解析链：`chrome.i18n.getUILanguage()` → `navigator.language` → `en` 回落；按语言前缀匹配（zh-TW → zh、en-GB → en、es-419 → es、pt-PT → pt 等），未识别一律回落英文。弹窗、右键菜单、系统通知与 PDF 浮出按钮的文案全部来自 `shared.js` 的同一张 copy map（`COPY`），无硬编码；缺失键由英文兜底。宿主侧（VS Code 信息条）的安装引导、配对码与撤销提示也按 VS Code UI locale 提供同样 8 种语言。

拓展自身的名称与描述（浏览器工具栏提示、扩展列表、商店条目）走 `_locales/<lang>/messages.json`（`manifest.json` 的 `__MSG_appName__` / `__MSG_appDescription__`，`default_locale: en`），目录同样覆盖 8 种语言前缀，且 `appName` 与 copy map 的 `appTitle` 逐语言一致（有测试守卫）。

## 代码结构

```
browser-extension/
├── manifest.json          # MV3：tabs/contextMenus/storage/alarms/notifications + 127.0.0.1 host_permissions
│                          #      name/description 经 __MSG_*__ 本地化，default_locale: en
├── _locales/<lang>/messages.json  # 8 语言的拓展名称与描述（en/zh/es/fr/de/ja/ko/pt）
├── shared.js              # 第 1 节：无 chrome 依赖的纯逻辑（URL 规范化、去重键、下载目标路径、队列操作、端口探测候选、i18n 文案）
│                          # 第 2 节：薄 chrome 封装（storage / fetch / locale / 连通性快照）
│                          # 第 3 节：PDF 浮出按钮（manifest 里声明的 content script，非 PDF 页面立即返回）
├── background.js          # 右键菜单（含 PDF/GitHub 下载子菜单）、配对状态、采集管线、离线队列、告警、角标、通知、队列管理动作
├── popup/                 # 三态：配对 / Trainer 未运行（队列管理）/ 已连接；采集 + 下载 + 最近记录
└── icons/                 # 手绘 SVG 源 + 由 PyMuPDF 渲染的 16/32/48/128 PNG
```

纯逻辑可用 `node --test extension/tests/browserCaptureShared.test.js` 直接测试（`shared.js` 不依赖 chrome，可在 Node 里 `require`）。同一套测试还静态守卫：8 语言 copy 键齐全性与前缀匹配、下载字段与目标路径校验、popup 三态标记与 `data-copy` 键完整性、图标 PNG 与 manifest 引用一致、打包白名单覆盖 manifest 引用的每个文件。
