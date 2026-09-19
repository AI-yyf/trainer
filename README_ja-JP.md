# Trainer

<div align="center">

<img src="assets/banner.png" alt="Trainer — AIを鍛える · AIとともに成長する · AIと人がともに育つ場所" width="100%" />

**VS Code のサイドバーに住み着く、長期の coding coach。**

**計画し、鍛え、検証し、あなたのことをすべて記憶する — しかし、あなたのコードは決して書きません。**

**// 出力 ≠ 成長 // 検証 + 復習 = 成長**

[English](README.md) · [简体中文](README_zh-CN.md) · [Español](README_es-ES.md) · [Français](README_fr-FR.md) · [Deutsch](README_de-DE.md) · 日本語 · [한국어](README_ko-KR.md) · [Português](README_pt-BR.md)

[![Release](https://img.shields.io/badge/release-v1.0.3-1f6feb)](https://github.com/AI-yyf/trainer/releases/tag/v1.0.3)
[![License](https://img.shields.io/badge/license-MIT-3fb950)](LICENSE)
[![Platforms](https://img.shields.io/badge/platforms-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-8b949e)](#インストール)
[![Tests](https://img.shields.io/badge/tests-3%2C328%20cases-F59E0B)](#品質ゲート)
[![i18n](https://img.shields.io/badge/i18n-8%20languages-A78BFA)](#i18n--8言語)

[なぜ](#なぜ-trainer-を作ったのか) ·
[インストール](#インストール) ·
[セットアップ](#セットアップは3ステップで完了) ·
[仕組み](#コアの仕組み) ·
[5つのビュー](#5つのビュー) ·
[比較](#比較) ·
[5分デモ](#5分デモ) ·
[設計思想](#なぜ使い心地が違うのか) ·
[アーキテクチャ](#アーキテクチャ) ·
[安全モデル](#安全モデル) ·
[品質](#品質ゲート) ·
[謝辞](#謝辞) ·
[🎭 キャラクター](docs/CAST.md)

</div>

---

## なぜ Trainer を作ったのか

> 開発者がつまずくのは、チュートリアルが足りないからではありません。
> 学習ループを閉じてくれるものが、何ひとつないからです。

LLM との会話は終わった瞬間に蒸発し、動画は一方通行。火曜日に「ほぼ理解した」はずの概念は、金曜日には消えています。

さらに悪いのが **バイブコーディング** — 3 ヶ月もの間 AI にコードを書かせ続け、自分はひとつも理解していない状態です。

ブックマークは増える一方でアウトプットは横ばい。リポジトリは育っても、頭の中は空になっていく。

**Trainer はこの問題を、エディタの中から解決します。**

これはただのチャットシェルではありません — 記憶とカリキュラムと試験方針を備えたコーチです:

- 学習をステージに**計画**し、あなたの「実際の」位置を追跡します — 感覚上の位置ではなく
- フラッシュカード、理論ドリル、シナリオ実験であなたを**訓練**します
- 実際のコードに対して習得を**検証**します — 現在のファイルが証明するまで、FastAPI について語っても何の証明にもなりません
- セッション・プロジェクト・週をまたいであなたを**記憶**し、FSRS の忘却曲線に沿って復習をスケジューリングします
- 本番コードをあなたの代わりに書くことは**決してありません** — あなたが書き、Trainer が教える。**ともに成長する**のです

<div align="center">

| バイブコーディング · 今日の常識 | Trainer · あるべき姿 |
|:---:|:---:|
| `def ship(code):` <br> `    ai.write(code)` <br> `# 本当に理解しましたか？` <br> `    return forget(code)` | `def ship(code):` <br> `    you.write(code)` <br> `    ai.verify(code)` <br> `    you.recall(code)` <br> `    return grown(code)` |
| 出力 = 忘却 | 出力 + 記憶 + 復習 = 成長 |

</div>

---

## インストール

**VSIX から（ビルド済み、3 プラットフォーム対応）:**

お使いのプラットフォーム（`darwin-arm64` / `linux-x64` / `win32-x64`）向けの `.vsix` を [v1.0.3 リリース](https://github.com/AI-yyf/trainer/releases/tag/v1.0.3)からダウンロードしてください。

VS Code の拡張機能パネル → `···` → *VSIX からのインストール* → ウィンドウを再読み込み。

**ソースから:**

```bash
git clone https://github.com/AI-yyf/trainer.git
cd trainer && npm install
cd server && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cd .. && npm run build
```

このリポジトリを VS Code で開いて F5 を押す（Extension Development Host）か、パッケージ済みの VSIX をインストールしてください。

**必要要件:** VS Code ≥ 1.96 · Python ≥ 3.12（ソースビルド時）· macOS / Linux / Windows

---

## セットアップは3ステップで完了

1. Trainer サイドバーを開く → Settings
2. リレーの接続情報を貼り付ける（リレーダッシュボードからコピーした JSON ブロック全体は自動でパースされ、エンドポイントとキーに分解されます）→ API キーを貼り付ける
3. **Save & Connect** をクリック

Trainer が最新のモデル一覧を取得し、デフォルトモデルを選び、ストリーミング経路を一括で検証します。

誤ったキーは `invalid_key_or_permission` と報告されます — 曖昧なスピナーのままにはなりません。

<p align="center">
  <img src="assets/screenshots/settings-quick-setup.png" alt="クイックセットアップ" width="420" />
</p>

---

## コアの仕組み

### ① 検証ゲート — あなたが書き、コードが証明する

トレーニングカードは、実際のファイルに対して検証が走るまで「実装済み」へ進めません。「完了にする」手動ボタンは意図的に存在しません。

学習の偽装を最も速く済ませる方法は、チェックボックスを全部埋めること。Trainer はそれを拒みます。

<p align="center"><img src="assets/feat-verify.png" alt="検証ゲート" width="720" /></p>

**仕組み:**
- サーバー側の `EvaluatorService` が現在のファイルを `tempfile.TemporaryDirectory` へ**コピー**し、ruff + pyright + pytest を実行してから、一時ディレクトリを片付けます
- ツールが学習者のプロジェクト内で実行されることは**決して**ありません — `.pytest_cache` による汚染もありません
- すべてのチェックは、明示的な `acceptance_criteria` + `expected_symbols` リストに対して、基準ごとの Matched/Missing 詳細を報告します
- コード: `server/app/evaluator/service.py:198-312`

### ② 長期記憶 — FSRS 忘却曲線スケジューリング

習得状況も弱点も来たるべき復習も、SQLite 上に Qdrant セマンティック検索とともに保存されます。

復習は FSRS の忘却曲線に沿って現れます — 忘れかける直前に現れ、まだ覚えている間は静かにしています。

<p align="center"><img src="assets/feat-memory.png" alt="長期記憶" width="720" /></p>

**仕組み:**
- 2 層メモリ: 構造化（`StructuredMemoryService`、約 480 レコード）+ セマンティック（Qdrant + sentence-transformer のオフラインフォールバック）
- **`_should_delay_live_thread_reviews()`** — アイデア実装フローの進行中は復習を積極的に抑制し、思考の流れを中断させません
- **移植可能スキルはワークスペース横断で fail-closed**: あるプロジェクトでの成功がそのまま全体的な習得になることはなく、昇格には 2 ワークスペース以上での合格が必要です
- 主要コード: `server/app/memory/service.py:1357-1597` · `transfer_skills.py:81-113` · `review_scheduler.py:522-544`

### ③ トレーニングループ — 期日になったら現れ、検証されたら進む

フラッシュカード、理論ドリル、シナリオ実験は Training ビューにキューイングされます: 復習は期日になると現れ、カードは検証されて初めて進み、会話中のどんな知識の穴もワンクリックでトレーニングカードに変わります。

<p align="center"><img src="assets/feat-training.png" alt="トレーニングループ" width="720" /></p>

**仕組み:**
- **5 フェーズのステートマシン** `LEARN → TRY → VERIFY → REFLECT → RETURN`。すべての遷移は `phase_history` に記録されます
- **信頼できる検証ソースのホワイトリスト**: `automated_test` / `evaluator` / `ide_current_file` / `server_evaluator` / `test_runner` / `verification_service` — 「手動での申告」がカードを進めることは決してありません
- カード UI の `onSkip` / `onRate` ハンドラは **`@deprecated Unused`** — 進行できる唯一の経路は `onCardStatusTransition` です
- 主要コード: `server/app/training/handoff.py:40-47` · `extension/webview/src/components/training/TrainingCardPanel.tsx:78-85`

### ④ 書くのはあなた、導くのはコーチ

コーチはあなたのファイルを読み、診断を確認し、ワークスペースを検索します — それでも、本番コードは常にあなたの手から生まれます。

`direct` は即座に答え、`coach-first` はまずあなたに考えさせます。**認知的負荷を背負うのはあなたであって、コーチではありません。**

<p align="center"><img src="assets/feat-youwrite.png" alt="あなたが書き、コーチが導く" width="720" /></p>

**仕組み:**
- `PedagogyService` は毎ターン、12 フィールドの `ImplementationGuide` を出力します — そのどのフィールドも「コーチが次に何を問えるか」への制約です
- `ImplementationCoach._current_step` は「最初に失敗しているパス」か「最初に既知のエントリポイント」に固定されます — 「コードベースを探索する」ことは決してありません
- 感情駆動のトーン: `AffectService` は 2 回連続で失敗すると `concise_rescue` モードへ切り替わります
- 主要コード: `server/app/pedagogy/implementation_coach.py:140-186` · `affect/service.py:142-152`

---

## 5つのビュー

> 固定された 5 つのトップレベルビュー。それぞれが厳密な責務境界を持ちます。

| ビュー | 役割 | ひとことで |
|-----------|------|--------|
| **Coach** | ストリーミングチャット | **入り口**: ツールアクセス + `$` スキルパレット + 画像添付 + 回答モード |
| **Plan** | 学習プラン | **地図**: ステージ、進捗、エビデンス、プランの凍結/解除 |
| **Resources** | ライブラリ | **本棚**: FTS5 検索 + 3 層サンドボックスプレビュー + 復元できるゴミ箱 |
| **Training** | トレーニング | **遊び場**: FSRS フラッシュカード + 理論ドリル + シナリオ実験 + 検証ゲート |
| **Settings** | 設定 | **コントロールパネル**: 59 個のコマンド + エンドポイント速度テスト + 思考強度 + ワークスペースの受け入れ制御 |

<p align="center">
  <img src="assets/screenshots/plan.png" alt="Plan ビュー" width="260" />
  <img src="assets/screenshots/resources.png" alt="Resources ビュー" width="260" />
  <img src="assets/screenshots/training.png" alt="Training ビュー" width="260" />
</p>

### Coach ビュー（入り口）

ツールアクセス、`$` スキルパレット、画像添付、回答モード、コンテキスト使用量リング、セッション履歴と共有を備えた、ストリーミング型のコーチチャット。

**すべてのコーチの返信の下には、3 つのクイックアクションが付きます:**

- **返信を Markdown としてコピー**
- **ライブラリに保存**（検索可能 + プレビュー可能）
- **検証可能なトレーニングカードに変換** — セッション単位ではなく、メッセージ単位

<p align="center"><img src="assets/screenshots/message-actions.png" alt="メッセージごとのアクション" width="520" /></p>

### カスタム `$` スキル — 作る、共有する、インストールする

`$` と入力するとスキルパレットが開きます: ビルトインに加えて、自分のプロンプトをトリガーワードとキーワード付きのスキルにラップして他の人と共有したり、他の人が共有したスキルをインストールしたりできます — **そのすべてが純粋なデータチャネル経由で、コード実行は一切ありません**。

<p align="center">
  <img src="assets/screenshots/skill-deck.png" alt="スキルパレット" width="380" />
  <img src="assets/screenshots/skill-manager.png" alt="スキルマネージャー" width="380" />
</p>

<p align="center"><img src="assets/feat-skills.png" alt="カスタムスキル" width="720" /></p>

**仕組み:**
- カスタムスキルは純粋な JSON インポートです — `{ _type, version, trigger, title, prompt, keywords }`。`eval` も `Function()` もコード経路もありません
- ハード上限: プロンプト ≤ 4000 文字、タイトル ≤ 160、キーワード ≤ 16、ユーザースキル ≤ 24
- トリガーが衝突した場合はビルトインが勝ちます — ユーザーがインポートした `$explain` が同梱のものを覆い隠すことはありません
- 主要コード: `shared/src/skillCatalog.ts:614-764`

---

## 比較

> Trainer は誰かを置き換えるためにあるのではありません — 誰も所有していないギャップを埋めます。

| 観点 | バイブコーディング系ツール | チャット IDE | フラッシュカードアプリ | **Trainer** |
|---|---|---|---|---|
| あなたの代わりにコードを書く | ✅ | ✅ | ❌ | ❌ |
| あなたのコードを検証する | ❌ | ❌ | ❌ | ✅ 現在のファイルに対して |
| セッションをまたいで記憶 | ⚠️ コンテキストウィンドウ | ⚠️ 要約 | ✅ | ✅ SQLite + Qdrant |
| FSRS による間隔反復 | ❌ | ❌ | ✅ | ✅ + ライブフロー中は抑制 |
| ワークスペース権限の段階 | ❌ | ⚠️ 信頼ダイアログ | ❌ | ✅ 6 段階 + リモートはハードロック |
| カード進行のゲート制御 | ❌ | ❌ | ⚠️ 手動チェックボックス | ✅ 検証を強制 |
| 移植可能スキルの昇格 | ❌ | ❌ | ❌ | ✅ ワークスペース横断で fail-closed |
| i18n | ⚠️ | ⚠️ | ⚠️ | ✅ 600+ キー × 8 言語 |
| テストスイート | クローズドソース | クローズドソース | クローズドソース | ✅ **3,328 ケース**（公開） |
| 代筆の拒否 | ❌ | ❌ | 該当なし | ✅ 哲学的な一線 |

> ひとことで言えば: 他のツールはあなたを速く書かせます。Trainer はあなたを本当に書かせます。

---

## 5分デモ

> 最初の 5 分間が、実際にはどうなるかを見ていきましょう。

### T+0:00 — サイドバーを開く

アクティビティバーの Trainer アイコンをクリックします。サイドバーが開き、**Coach ビュー**がデフォルトで表示されます。

<p align="center">
  <img src="assets/screenshots/settings-quick-setup.png" alt="初回起動" width="420" />
</p>

### T+0:30 — プロバイダを設定する（初回のみ）

Settings → リレーの JSON + API キーを貼り付け → Save & Connect。

Trainer が最新のモデル一覧を取得し、デフォルトを選び、ストリーミングを検証します。誤ったキーなら `invalid_key_or_permission` と教えてくれます。

### T+1:30 — 最初の会話

Coach に切り替えて、次のように入力します: `@current_file explain what this async/await is doing?`

Trainer は返信をストリーミングします。**あなたのコードを書き換えることはありません。** 17 行目を指して「これは fan-out」、23 行目は「これがバリア。本当に身につけたければ、実行中のタスクを途中でキャンセルするバージョンを書いてみましょう — 検証は私が一緒に走らせます」と。

### T+2:30 — ワンクリックでトレーニングカード

返信にカーソルを合わせます。3 つのボタン: `Copy` / `Save to library` / **`Create training card`**。

`Create training card` をクリック → カードが生成される → Training ビューに入る → FSRS が 3 日後にスケジュールします。

### T+4:00 — 自分で書いて、検証を受ける

コードを書くのはあなたです。Trainer が**代わりに書くことはありません**。

Training を開く → カードをめくる → 合格基準を確認する → 書く → `Request verification` をクリック → Trainer がサンドボックスで ruff + pyright + pytest を実行 → 合格を報告するか、欠けている基準を指摘します。

### T+5:00 — 翌日

翌日 VS Code を開くと: Trainer が自動復元します — 前回のセッションも、プランも、カードの進捗も、すべてそこにあります。

あのカードが FSRS のリズム盤の上で脈打っています — 期日は今日です。

**あなたはもう、バイブコーディングする開発者ではありません。**

---

## なぜ使い心地が違うのか

### 正直な失敗

誤ったキーなら `invalid_key_or_permission`、到達不能なら `network`、壊れた返信なら「この返信は正しく読み取れませんでした。再送してください」と表示されます — **壊れた出力を答えとして飾り立てることは決してありません**。

未知のゲートウェイを、黙って OpenAI 互換と決めつけることもありません。

**仕組み:** エラー分類器（`provider_service.py:2823-2874`）+ 認証情報のスクラビング（`provider_protocols.py:640-681`）+ 未知フィンガープリントのプローブ（`provider_gateway.py:39-70`）。

### エンドポイント速度テスト

プロバイダのエンドポイントが並行して競います（**まずウォームアップでコールドスタートのペナルティを消してから、計測**）。

500 ms 未満は緑、1 秒未満は黄。ワンクリックで最速のものを採用します。

<p align="center"><img src="assets/feat-speed.png" alt="エンドポイント速度テスト" width="720" /></p>

**仕組み:** `Promise.all` + 計測用リクエストの前に、各 URL へ結果を捨てるウォームアップリクエストを送信（`providerWebviewCommands.ts:2275-2352`）。

### コンテキスト使用量リング

会話の上部には常にコンテキスト使用量リングが表示されます — **圧縮が起きる前に、その予兆をつかめます**。

### 思考強度

モデルごとのエビデンスでゲートされます — 宣言された能力**または**検証済みプローブ。盲目的に転送されることはありません。

### 全力ライブラリ

<p align="center"><img src="assets/feat-library.png" alt="全力ライブラリ" width="720" /></p>

アップロードは到着次第インデックス化、FTS5 全文検索、**3 層サンドボックスプレビュー**（A リッチ表示 / B 変換表示 / C メタデータ + ネイティブエディタへのフォールバック）、削除は復元可能なゴミ箱へ。

**3 ゾーンの物理分離**: ワークスペース / サンドボックス / ゴミ箱。決して混ざりません。

コーチの返信もワンクリックで落ちてきます — **検索で取り戻せるなら、それは本当に学んだということ**。

### 長期にわたる状態

プランは凍結・解除でき、セッションは再起動をまたいで生き残り、カードの進捗は SQLite に宿り、復習は FSRS 曲線に従って期日を迎えます — **To-Do リストの上ではありません**。

---

## アーキテクチャ

### システム構成

```
┌─────────────────────────────────────────────────────────────┐
│                    VS Code Window                            │
│  ┌───────────────────────────────────────────────────────┐  │
│  │   Trainer Sidebar                                     │  │
│  │   (React 19 + Zustand, 8-language i18n, 24 governance)│  │
│  │                                                       │  │
│  │   ─── postMessage ─── CommandRegistry ── 59 commands  │  │
│  │                                       │               │  │
│  └───────────────────────────────────────┼───────────────┘  │
│                                          │                   │
│                          ┌───────────────▼──────────────┐    │
│                          │  FastAPI sidecar (127.0.0.1)│    │
│                          │  PyInstaller --onedir frozen│    │
│                          │  (250 MB / 6 platform arch) │    │
│                          │                              │    │
│                          │  ├── ReAct agent loop        │    │
│                          │  │   (dual-channel stream)   │    │
│                          │  ├── Pedagogy (12-field guide)│   │
│                          │  ├── Affect (failures→rescue)│    │
│                          │  ├── Memory                  │    │
│                          │  │   SQLite + Qdrant semantic│    │
│                          │  ├── FSRS scheduler          │    │
│                          │  ├── Authority (6 tiers)     │    │
│                          │  ├── Provider (5 protocols)  │    │
│                          │  ├── Training handoff (5 ph.)│    │
│                          │  └── Resources (3 zones+FTS5)│    │
│                          │                              │    │
│                          │  ─── 24 shared pure fns ────│    │
│                          │      (host + webview + test)  │    │
│                          └──────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### ディレクトリ構成

| フォルダ | 内容 | サイズ |
|---|---|---|
| `extension/src/` | ホスト: コマンド、ワークスペース信頼、シークレットストレージ、sidecar のライフサイクル | ~30k 行の TS |
| `extension/webview/` | React ワークベンチ: 5 ビュー + Zustand + 8 言語 | ~50k 行の TSX |
| `extension/tests/` | node:test スイート（220 ファイル / 1,679 ケース） | 73,744 行 |
| `server/app/` | FastAPI の頭脳: agent / pedagogy / memory / FSRS / training | ~120k 行の Python |
| `server/tests/` | pytest スイート（159 ファイル / 1,649 ケース） | 106,422 行 |
| `shared/src/` | **共有純粋関数 + 24 個のガバナンスモジュール**（host + webview + test） | ~3k 行の TS |
| `extension/bundled/` | VSIX にバンドルされた sidecar（PyInstaller onedir） | ~250 MB |

### 唯一の共通エンベロープ

> Trainer の HTTP レスポンスはすべて（`/health` を除き）、**同一の** `WorkbenchSnapshot`（31 フィールド）を返します。

| カテゴリ | フィールドの例 | 生成元 |
|---|---|---|
| セッション | `messages`, `coaching_state`, `learner_state` | `pedagogy/service.py` |
| プラン | `plan`, `global_plan`, `project_plan_link`, `current_task` | `planner/service.py` |
| メモリ | `memory`, `selected_teaching_assets`, `next_review_due` | `memory/service.py` |
| ティーチング | `teaching_decision`, `implementation_guide`, `project_ideas` | `pedagogy/*` |
| アフェクト | `affect_state`, `tone_decision` | `affect/service.py` |
| トレーニング | `evaluation`, `review_queue_summary` | `training/*` |
| メタ | `context_id`, `sidecar_status`, `snapshot_revision`, `active_panel` | `api/runtime.py` |

**なぜ 1 つのエンベロープなのか:**
- webview は**この 1 つのオブジェクトだけで完全に描画**されます — 12 のサブシステムがフィールドを書き込み、ハイドレートは 1 回だけ
- **CRDT ライトな増分同期**: 各スナップショットは `snapshot_revision` を持ちます。`GET /snapshot?since_revision=N` は N が古いときだけ完全なデータを送り、そうでなければ `{unchanged: true}` を返します
- 主要コード: `server/app/core/models.py:2304-2336` · `server/app/api/routers.py:11648-11710`

### 共有ガバナンスモジュール

> Trainer のアーキテクチャの背骨は **24 個の純粋関数ガバナンスモジュール**です — host、webview、test がすべて同じ決定論的ロジックを走らせます。

| モジュール | 役割 |
|---|---|
| `planGovernance` · `masterPlanGovernance` | プラン編集、クロスプロジェクトのマスタープラン |
| `trainingHandoffGovernance` · `trainingRecoveryGovernance` · `trainingReliabilityGovernance` | カードのルーティング、リカバリ、信頼性 |
| `reviewQueueGovernance` · `reviewArtifactGovernance` | FSRS キューの順序付け、エビデンスレビュー |
| `workspaceAuthority` · `workspaceRecoveryGovernance` | 6 段階の権限、リカバリ |
| `suggestedActionGovernance` · `conversationCandidateGovernance` | 提案アクション、会話の調停 |
| `transferEvidenceGovernance` · `transferSkillGovernance` | クロスプロジェクトのエビデンス、スキル昇格 |
| `coachOrientationGovernance` · `resourcesOrientationGovernance` | Coach/Resources ビューのオリエンテーション |
| `settingsCapabilityGovernance` · `operationReliabilityGovernance` | 設定のケイパビリティゲート、操作の信頼性 |
| `hostLastTestGovernance` · `providerModelPolicy` | プロバイダの最終テスト、モデルポリシー |
| `sandboxNetworkCapabilityNarrative` · `projectLaneGovernance` | サンドボックス機能の説明、プロジェクトレーン |
| `previewAssets` · `materialRecommendationGovernance` | プレビューアセットの階層、教材のレコメンデーション |

**なぜなら:** 同じ `resolveSuggestedActionGovernance` が host、webview、test で走ります — **3 者間で一貫し、ラウンドトリップは不要**です。

---

## 安全モデル

- API キーは **VS Code SecretStorage**（OS レベルの暗号化）に保存されます — 設定ファイルにも git にも決して入りません
- ワークスペースは **VS Code ネイティブの信頼機構**に従います — 未信頼の間はすべての書き込みを拒否します
- **6 段階の権限ラダー**: INSPECT < ANNOTATE < REORGANIZE < GENERATE < APPLY < DESTRUCTIVE — デフォルトは読み取り専用。書き込み/削除/変更には段階的な attestation（証明）が必要です
- **リモートワークスペースは REORGANIZE 未満にハードロック** — ユーザーが許可しても昇格できません
- **削除はゴミ箱行き**: `delete` 操作は存在せず、`move to <root>/.trash/<timestamp-uuid>/` だけです
- サンドボックスプレビューは厳格な **パスガバナンス**を強制します — 範囲外のパスには容赦なく 422 を返します
- スキル共有は **純粋なデータのインポート**です — フィールド長には上限があり、ビルトインが優先され、**コード経路は存在しません**

**主要コード:** `server/app/workspace/authority.py:33-962` · `extension/src/provider/providerConfigStore.ts` · `shared/src/skillCatalog.ts:614-764`

---

## 品質ゲート

> Trainer は自身の検証スタックを 1 つの製品として扱います。

| ゲート | カバレッジ | 備考 |
|---|---|---|
| **サーバーテスト**（pytest） | **159 ファイル / 1,649 ケース / 106,422 行** | Hypothesis によるプロパティベーススイート 6 件を含む |
| **拡張機能テスト**（node:test） | **220 ファイル / 1,679 ケース / 73,744 行** | ソースガード 109 ファイル + 振る舞いテスト 111 件 |
| **E2E** | **11 spec / 4,335 行** | 実際の VS Code インスタンス × 実際のモデル |
| **エクスペリエンスマトリクス** | **200 シナリオ × 2 レイヤ** | プレビューフィクスチャ + 実 sidecar |
| **VSIX ホストドライバ** | **33 ステップ** | インストール → 有効化 → ストリーミング → 検証 → 実際の webview 描画をアサート |
| **静的解析** | ruff + pyright + tsc | 警告ゼロ |
| **プロトコルマトリクス** | **5 プロトコル** | OpenAI Chat / Responses / Anthropic / Gemini / OpenAI-Compatible |
| **i18n** | **8 言語 × 600+ キー** | zh-CN / en-US / es-ES / fr-FR / de-DE / ja-JP / ko-KR / pt-BR |
| **バンドル sidecar** | **6 プラットフォームバイナリ** | win32-x64 / win32-arm64 / darwin-x64 / darwin-arm64 / linux-x64 / linux-arm64 |

**E2E スイートは、実際の VS Code インスタンスで実際のモデルに対して実行されます:**

> パッケージ化された拡張機能を有効化 → バンドル sidecar を起動 → プロバイダを保存 → コーチターン全体をストリーミング → トレーニングカードを生成して検証 → webview が**実際に描画した**内容をアサート → スクリーンショット → ワークスペースをまたいで開き直して履歴を復元。

**テストは自らの限界を自認します:**
各 E2E シナリオは `evidence: { realSidecar, limitation }` を持っています — **テスト自身が、証明していないことを宣言する**のです。

---

## i18n · 8言語

| 言語 | コード | 主要 |
|---|---|---|
| 简体中文 | `zh-CN` | ✅ |
| English | `en-US` | ✅ |
| Español | `es-ES` | ✅ |
| Français | `fr-FR` | ✅ |
| Deutsch | `de-DE` | ✅ |
| 日本語 | `ja-JP` | ✅ |
| 한국어 | `ko-KR` | ✅ |
| Português | `pt-BR` | ✅ |

**フォールバックチェーン:** ユーザー設定 > VS Code `env.language` > `zh-CN`（デフォルト）

**6 つのサーフェス単位オーバーライド:** `resourceView` / `contextRail` / `trainingUi` / `orientationRail` / `composerAccessibility` / `leftoverHonesty` — 翻訳者は自分が担当するサーフェスだけを埋めればよく、**600+ キーの完全なテーブルを埋める必要はありません**。

主要コード: `extension/webview/src/lib/i18n/copy.ts`（5,283 行）

---

## 謝辞

> Trainer は巨人の肩の上に立っています。

### 🏃 ランタイムコア

| プロジェクト | 用途 | 代替が利かない理由 |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | ローカル sidecar フレームワーク | async + Pydantic + 自動 OpenAPI ドキュメント |
| [Uvicorn](https://github.com/encode/uvicorn) | ASGI サーバ | HTTP/1.1 + WebSocket + 高同時実行 |
| [Pydantic](https://github.com/pydantic/pydantic) | データ検証とシリアライズ | 31 フィールドの WorkbenchSnapshot はこれで動いています |
| [httpx](https://github.com/encode/httpx) | 非同期 HTTP クライアント | sidecar ↔ LLM ゲートウェイの全プロトコルルーティング |

### 🤖 LLM プロトコル

| プロジェクト | 用途 |
|---|---|
| [openai-python](https://github.com/openai/openai-python) | OpenAI / Anthropic / Gemini 互換クライアント（5 プロトコルルーティング） |

### 🧠 トレーニングとメモリ

| プロジェクト | 用途 |
|---|---|
| [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs) | FSRS 忘却曲線の復習スケジューリング · `TrainingCardState` を駆動 |
| [qdrant-client](https://github.com/qdrant/qdrant-client) | セマンティックメモリのベクトル検索（sentence-transformer フォールバック付き） |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | PDF パース（ライブラリの Tier A プレビュー） |
| [trafilatura](https://github.com/adbar/trafilatura) | Web コンテンツ抽出（リソースの取り込み） |
| [markitdown](https://github.com/microsoft/markitdown) | ドキュメント → Markdown 変換（ライブラリの Tier B プレビュー） |

### ⚛️ フロントエンドコア

| プロジェクト | 用途 |
|---|---|
| [React](https://github.com/facebook/react) | サイドバーのワークベンチ UI |
| [Vite](https://github.com/vitejs/vite) | ビルドツール + 開発サーバ |
| [Zustand](https://github.com/pmndrs/zustand) | ワークベンチの状態管理 |
| [Zod](https://github.com/colinhacks/zod) | ランタイム型検証 |

### 🎨 レンダリング

| プロジェクト | 用途 |
|---|---|
| [react-markdown](https://github.com/remarkjs/react-markdown) | Markdown レンダリング |
| [remark-gfm](https://github.com/remarkjs/remark-gfm) | GFM 拡張（テーブル、タスクリスト） |
| [remark-math](https://github.com/remarkjs/remark-math) · [rehype-katex](https://github.com/remarkjs/rehype-katex) · [KaTeX](https://github.com/KaTeX/KaTeX) | 数式レンダリング |
| [Shiki](https://github.com/shikijs/shiki) | コードハイライト（VS Code TextMate 文法） |
| [Mermaid](https://github.com/mermaid-js/mermaid) | 図とフローチャート |
| [@tanstack/react-table](https://github.com/TanStack/table) | ライブラリ / トレーニングキューのテーブル |

### 📄 プレビュー

| プロジェクト | 用途 |
|---|---|
| [mammoth](https://github.com/mwilliamson/mammoth.js) · [docx-preview](https://github.com/VolodymyrBaydalka/docx-preview) | DOCX のリッチレンダリング（Tier A） |
| PDF.js（バンドル） | PDF のリッチレンダリング（Tier A） |

### 🧪 テストと品質

| プロジェクト | 用途 |
|---|---|
| [pytest](https://github.com/pytest-dev/pytest) · [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) | サーバー 159 ファイル / 1,649 ケース |
| [Hypothesis](https://github.com/HypothesisWorks/hypothesis) | プロパティテスト（planner / evaluator / scheduler） |
| [ruff](https://github.com/astral-sh/ruff) | Python lint + フォーマット（E/F/I/B、py312、100 カラム） |
| [pyright](https://github.com/microsoft/pyright) | Python 静的型検査 |
| [TypeScript](https://github.com/microsoft/TypeScript) | strict モード、警告ゼロ |
| [Playwright](https://github.com/microsoft/playwright) | E2E + 200 シナリオのエクスペリエンスマトリクス |

### 📦 パッケージングと配布

| プロジェクト | 用途 |
|---|---|
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | sidecar バイナリのフリーズ（6 プラットフォーム、manifest sha256） |

### 💡 方法論のインスピレーション

| プロジェクト | インスピレーション |
|---|---|
| [open-spaced-repetition/fsrs4anki](https://github.com/open-spaced-repetition/fsrs4anki) | FSRS の原論文とリファレンス実装 |
| [obra/superpowers](https://github.com/obra/superpowers) | 「必須のワークフロー、提案にあらず」というコーチングの規律 |
| [HKUDS/CLI-Anything](https://github.com/HKUDS/CLI-Anything) | 「すべてのソフトウェアをエージェントネイティブに」という野心 |

### 🎨 ビジュアルアセット

| プロジェクト | 用途 |
|---|---|
| [dora-image](https://github.com/AI-yyf/trainer/tree/main/assets) | この README のすべての画像（`assets/MASCOT.md` / `BANNER_PROMPT.md` / `FEATURE_PROMPTS.md` を参照） |
| DeepSeek 公式の萌えキャラクター | ちび体型 / セルシェーディング寄りのリファレンス |
| ピーテル・ブリューゲル『バベルの塔』 | 左右の陣営に分かれた群像構図のリファレンス |
| レンブラント『夜警』 | 7:1 のキアロスクーロ対比のリファレンス |
| スタジオジブリのキャラクターデザイン | 3 点ハイライト入りの大きな目、抑えた表情 |

---

## ライセンス

[MIT](LICENSE)

---

## Trainer の引用

Trainer があなたのワークフローに役立ったなら、ブログ / 論文 / 発表でぜひ引用してください:

```bibtex
@software{trainer2026,
  title  = {Trainer: A Long-Term Coding Coach Living in Your Editor},
  author = {AI-yyf and contributors},
  year   = {2026},
  url    = {https://github.com/AI-yyf/trainer},
  note   = {v1.0.3}
}
```

---

<div align="center">

**// AIを鍛える · AIとともに成長する**

`v1.0.3` · コーヒーと、FSRS と、24 個の純粋関数と、3,328 個のテストと、あなたの代わりにコードを書くことを拒む心で作られています。

</div>
