# Trainer

<div align="center">

<img src="assets/banner.png" alt="Trainer — 당신의 AI를 훈련하세요 · AI와 함께 성장하세요 · AI와 사람이 함께 성장하는 곳" width="100%" />

**VS Code 사이드바에 함께 사는 장기 코딩 코치입니다.**

**계획하고, 훈련시키고, 검증하고, 당신에 대한 모든 것을 기억합니다 — 하지만 코드는 절대 대신 쓰지 않습니다.**

**// 출력 ≠ 성장 // 검증 + 복습 = 성장**

[English](README.md) · [简体中文](README_zh-CN.md) · [Español](README_es-ES.md) · [Français](README_fr-FR.md) · [Deutsch](README_de-DE.md) · [日本語](README_ja-JP.md) · 한국어 · [Português](README_pt-BR.md)

[![릴리스](https://img.shields.io/badge/release-v1.0.3-1f6feb)](https://github.com/AI-yyf/trainer/releases/tag/v1.0.3)
[![라이선스](https://img.shields.io/badge/license-MIT-3fb950)](LICENSE)
[![플랫폼](https://img.shields.io/badge/platforms-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-8b949e)](#설치)
[![테스트](https://img.shields.io/badge/tests-3%2C328%20cases-F59E0B)](#품질-게이트)
[![i18n](https://img.shields.io/badge/i18n-8%20languages-A78BFA)](#i18n--8개-언어)

[존재 이유](#trainer가-존재하는-이유) ·
[설치](#설치) ·
[설정](#세-단계뿐-네-번째는-없습니다) ·
[메커니즘](#핵심-메커니즘) ·
[다섯 뷰](#다섯-가지-뷰) ·
[비교](#비교) ·
[5분 데모](#5분-데모) ·
[설계](#다르게-느껴지는-이유) ·
[아키텍처](#아키텍처) ·
[안전](#안전-모델) ·
[품질](#품질-게이트) ·
[감사의 말](#감사의-말) ·
[🎭 캐스트](docs/CAST.md)

</div>

---

## Trainer가 존재하는 이유

> 개발자가 멈출 때는 튜토리얼이 부족해서가 아닙니다.
> 학습 루프를 닫아 주는 것이 없기 때문입니다.

LLM과의 대화는 끝나는 순간 증발하고, 영상은 일방향에 그치며, 화요일에 거의 이해한 그 개념은 금요일이면 사라집니다.

더 나쁜 것은 **vibe coding**입니다 — 3개월 동안 AI가 코드를 쓰게 두고 정작 자신은 하나도 이해하지 못하는 것.

북마크는 쌓여가는데 산출은 제자리입니다. 저장소는 불어나는데 머릿속은 텅 비어갑니다.

**Trainer는 에디터 안에서 이 문제를 해결합니다.**

단순한 채팅 창이 아니라, 기억과 커리큘럼, 그리고 시험 원칙을 갖춘 코치입니다:

- 학습을 단계별로 **계획**하고, 느낌이 아니라 실제로 어디쯤 와 있는지 추적합니다
- 플래시카드, 이론 드릴, 시나리오 실험으로 **훈련**합니다
- 실제 코드로 숙달을 **검증**합니다 — 현재 파일이 증명해 주기 전까지 FastAPI 이야기는 아무런 힘이 없습니다
- 세션과 프로젝트, 몇 주에 걸쳐 당신을 **기억**하며, FSRS 망각 곡선 위에 복습을 배치합니다
- 프로덕션 코드는 **절대 대신 쓰지 않습니다** — 당신이 쓰고, 코치가 가르치고, **함께 성장합니다**

<div align="center">

| vibe coding · 오늘날의 표준 | Trainer · 있어야 할 모습 |
|:---:|:---:|
| `def ship(code):` <br> `    ai.write(code)` <br> `# 이해했나요?` <br> `    return forget(code)` | `def ship(code):` <br> `    you.write(code)` <br> `    ai.verify(code)` <br> `    you.recall(code)` <br> `    return grown(code)` |
| 출력 = 망각 | 출력 + 기억 + 복습 = 성장 |

</div>

---

## 설치

**VSIX로 설치 (미리 빌드됨, 3개 플랫폼):**

플랫폼에 맞는 `.vsix`(`darwin-arm64` / `linux-x64` / `win32-x64`)를 [v1.0.3 릴리스](https://github.com/AI-yyf/trainer/releases/tag/v1.0.3)에서 내려받습니다.

VS Code 확장 패널 → `···` → *VSIX에서 설치* → 창을 다시 불러옵니다.

**소스에서 빌드:**

```bash
git clone https://github.com/AI-yyf/trainer.git
cd trainer && npm install
cd server && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cd .. && npm run build
```

이 저장소를 VS Code로 열고 F5(Extension Development Host)를 누르거나, 패키징된 VSIX를 설치합니다.

**요구 사항:** VS Code ≥ 1.96 · Python ≥ 3.12 (소스 빌드) · macOS / Linux / Windows

---

## 세 단계뿐, 네 번째는 없습니다

1. Trainer 사이드바를 열고 Settings 뷰로 이동
2. 릴레이 연결 정보를 붙여넣습니다 (릴레이 대시보드에서 복사한 JSON 블록 전체는 자동으로 파싱됩니다 — 엔드포인트와 키를 알아서 분리해 줍니다) → API 키를 붙여넣습니다
3. **Save & Connect**를 누릅니다

Trainer가 실시간 모델 목록을 가져오고, 기본 모델을 고르고, streaming 경로를 한 번에 검증합니다.

잘못된 키는 `invalid_key_or_permission`으로 보고합니다 — 막연한 스피너가 아니라.

<p align="center">
  <img src="assets/screenshots/settings-quick-setup.png" alt="빠른 설정" width="420" />
</p>

---

## 핵심 메커니즘

### ① 검증 게이트 — 코드는 당신이 쓰고, 코드가 증명합니다

훈련 카드는 실제 파일에 대한 검증이 실행되기 전에는 "구현됨" 상태로 넘어갈 수 없습니다. 수동 "완료 표시" 버튼은 의도적으로 빠져 있습니다.

학습을 가장하는 가장 빠른 길은 체크박스를 전부 눌러 버리는 것입니다. Trainer는 그것을 거부합니다.

<p align="center"><img src="assets/feat-verify.png" alt="검증 게이트" width="720" /></p>

**방법:**
- 서버의 `EvaluatorService`가 현재 파일을 `tempfile.TemporaryDirectory`로 **복사**한 뒤 ruff + pyright + pytest를 실행하고, 임시 디렉터리를 정리합니다
- 도구는 학습자의 프로젝트에서는 **절대** 실행되지 않습니다 — `.pytest_cache` 오염이 없습니다
- 모든 검사는 명시적인 `acceptance_criteria` + `expected_symbols` 목록을 기준으로 항목별 Matched/Missing 상세를 보고합니다
- 코드: `server/app/evaluator/service.py:198-312`

### ② 장기 기억 — FSRS 망각 곡선 스케줄링

숙달한 것, 약점, 복습할 것은 SQLite에 기록되고 Qdrant 시맨틱 검색으로 뒷받침됩니다.

복습은 FSRS 망각 곡선 위에서 나타납니다 — 잊을 만한 순간에 나타나고, 아직 기억하고 있는 동안에는 조용히 있습니다.

<p align="center"><img src="assets/feat-memory.png" alt="장기 기억" width="720" /></p>

**방법:**
- 2계층 메모리: 구조화(`StructuredMemoryService`, 약 480개 레코드) + 시맨틱(Qdrant + sentence-transformer 오프라인 폴백)
- **`_should_delay_live_thread_reviews()`** — 아이디어 구현 흐름이 진행 중인 동안에는 복습을 적극적으로 억제해 사고의 흐름이 끊기지 않습니다
- **전이 가능 스킬은 워크스페이스 간 fail-closed**: 한 프로젝트에서의 성공이 전역 숙달이 되는 일은 없으며, 승격은 ≥2개 워크스페이스 통과를 요구합니다
- 핵심 코드: `server/app/memory/service.py:1357-1597` · `transfer_skills.py:81-113` · `review_scheduler.py:522-544`

### ③ 훈련 루프 — 복습 시점에 나타나고, 검증되어야 전진합니다

플래시카드, 이론 드릴, 시나리오 실험이 Training 뷰에 큐로 쌓입니다: 복습은 시점이 되면 나타나고, 카드는 검증되면 전진하며, 대화 중 발견된 지식 공백은 클릭 한 번으로 훈련 카드가 됩니다.

<p align="center"><img src="assets/feat-training.png" alt="훈련 루프" width="720" /></p>

**방법:**
- **5단계 상태 머신** `LEARN → TRY → VERIFY → REFLECT → RETURN`, 모든 전이는 `phase_history`에 기록됩니다
- **신뢰된 검증 출처 화이트리스트**: `automated_test` / `evaluator` / `ide_current_file` / `server_evaluator` / `test_runner` / `verification_service` — "수동 주장"은 카드를 절대 전진시킬 수 없습니다
- 카드 UI의 `onSkip` / `onRate` 핸들러는 **`@deprecated Unused`** 상태입니다 — 유일한 진행 경로는 `onCardStatusTransition`입니다
- 핵심 코드: `server/app/training/handoff.py:40-47` · `extension/webview/src/components/training/TrainingCardPanel.tsx:78-85`

### ④ 당신이 쓰고, 코치가 이끕니다

코치는 파일을 읽고, 진단을 확인하고, 워크스페이스를 검색합니다 — 하지만 프로덕션 코드는 언제나 당신의 손에서 나옵니다.

`direct` 모드는 즉시 답하고, `coach-first` 모드는 먼저 생각하게 만듭니다. **인지 부하는 당신의 몫이지 코치의 몫이 아닙니다.**

<p align="center"><img src="assets/feat-youwrite.png" alt="당신이 쓰고 코치가 이끕니다" width="720" /></p>

**방법:**
- `PedagogyService`는 매 턴 12개 필드의 `ImplementationGuide`를 만들어 냅니다 — 모든 필드는 코치가 다음에 무엇을 물을 수 있는지에 대한 제약입니다
- `ImplementationCoach._current_step`은 "가장 먼저 실패하는 경로"나 "가장 먼저 알려진 진입점"에 고정됩니다 — "코드베이스 탐색" 같은 것은 없습니다
- 감정 기반 톤: `AffectService`는 연속 두 번 실패하면 `concise_rescue` 모드로 전환합니다
- 핵심 코드: `server/app/pedagogy/implementation_coach.py:140-186` · `affect/service.py:142-152`

---

## 다섯 가지 뷰

> 고정된 다섯 개의 최상위 뷰. 각각 책임 경계가 엄격합니다.

| 뷰 | 역할 | 한 줄 요약 |
|-----------|------|--------|
| **Coach** | streaming 채팅 | **입구**: 도구 접근 + `$` 스킬 팔레트 + 이미지 첨부 + 답변 모드 |
| **Plan** | 학습 플랜 | **지도**: 단계, 진행 상황, 근거, 플랜 고정/해제 |
| **Resources** | 라이브러리 | **책장**: FTS5 검색 + 3단계 샌드박스 미리보기 + 복원 가능한 휴지통 |
| **Training** | 훈련 | **놀이터**: FSRS 플래시카드 + 이론 드릴 + 시나리오 실험 + 검증 게이트 |
| **Settings** | 설정 | **콘솔**: 59개 명령 + 엔드포인트 속도 측정 + thinking 강도 + 워크스페이스 승인 |

<p align="center">
  <img src="assets/screenshots/plan.png" alt="Plan 뷰" width="260" />
  <img src="assets/screenshots/resources.png" alt="Resources 뷰" width="260" />
  <img src="assets/screenshots/training.png" alt="Training 뷰" width="260" />
</p>

### Coach 뷰 (입구)

도구 접근, `$` 스킬 팔레트, 이미지 첨부, 답변 모드, context 사용량 링, 세션 히스토리와 공유를 갖춘 streaming 코치 채팅입니다.

**모든 코치 답변 아래에는 세 가지 빠른 액션이 붙어 있습니다:**

- **답변을 Markdown으로 복사**
- **라이브러리에 저장** (검색 가능 + 미리보기 가능)
- **검증 가능한 훈련 카드로 변환** — 세션 단위가 아니라 메시지 단위

<p align="center"><img src="assets/screenshots/message-actions.png" alt="메시지별 액션" width="520" /></p>

### 커스텀 `$` 스킬 — 만들기, 공유, 설치

`$`를 입력하면 스킬 팔레트가 열립니다: 기본 제공 스킬을 넘어, 자신만의 프롬프트를 트리거 단어와 키워드를 갖춘 스킬로 감싸 다른 사람에게 공유하거나, 다른 사람이 공유한 스킬을 설치할 수 있습니다 — **전부 순수 데이터 채널을 통해서이며, 코드 실행은 없습니다**.

<p align="center">
  <img src="assets/screenshots/skill-deck.png" alt="스킬 팔레트" width="380" />
  <img src="assets/screenshots/skill-manager.png" alt="스킬 관리자" width="380" />
</p>

<p align="center"><img src="assets/feat-skills.png" alt="커스텀 스킬" width="720" /></p>

**방법:**
- 커스텀 스킬은 순수 JSON 임포트입니다 — `{ _type, version, trigger, title, prompt, keywords }`; `eval`도 없고, `Function()`도 없고, 코드 경로도 없습니다
- 하드 상한: prompt ≤ 4000자, title ≤ 160자, keywords ≤ 16개, 사용자 스킬 ≤ 24개
- 충돌 시에는 기본 제공 트리거가 이깁니다 — 사용자가 가져온 `$explain`은 기본 제공 것을 가릴 수 없습니다
- 핵심 코드: `shared/src/skillCatalog.ts:614-764`

---

## 비교

> Trainer는 누군가를 대체하러 온 것이 아닙니다 — 아무도 채우지 않는 공백을 채웁니다.

| 차원 | vibe 도구 | 채팅 IDE | 플래시카드 앱 | **Trainer** |
|---|---|---|---|---|
| 대신 코드를 작성 | ✅ | ✅ | ❌ | ❌ |
| 당신의 코드를 검증 | ❌ | ❌ | ❌ | ✅ 현재 파일 기준 |
| 세션을 넘어 기억 | ⚠️ context window | ⚠️ 요약 | ✅ | ✅ SQLite + Qdrant |
| FSRS 기반 간격 반복 | ❌ | ❌ | ✅ | ✅ + 진행 중 흐름 억제 |
| 워크스페이스 권한 단계 | ❌ | ⚠️ 신뢰 대화상자 | ❌ | ✅ 6단계 + 원격 하드 잠금 |
| 카드 진행에 게이트 | ❌ | ❌ | ⚠️ 수동 체크박스 | ✅ 검증 강제 |
| 전이 가능 스킬 승격 | ❌ | ❌ | ❌ | ✅ 워크스페이스 간 fail-closed |
| i18n | ⚠️ | ⚠️ | ⚠️ | ✅ 600+ 키 × 8개 언어 |
| 테스트 스위트 | 비공개 소스 | 비공개 소스 | 비공개 소스 | ✅ **3,328개 케이스** (공개) |
| 대신 쓰기를 거부 | ❌ | ❌ | 해당 없음 | ✅ 철학적인 최후 방어선 |

> 한 줄 요약: 다른 도구는 더 빨리 쓰게 해 줍니다. Trainer는 정작 당신이 쓰게 만듭니다.

---

## 5분 데모

> 처음 5분이 실제로 어떻게 흘러가는지 보여 드립니다.

### T+0:00 — 사이드바 열기

활동 막대에서 Trainer 아이콘을 클릭합니다. 사이드바가 열리고 기본으로 **Coach 뷰**가 나타납니다.

<p align="center">
  <img src="assets/screenshots/settings-quick-setup.png" alt="첫 실행" width="420" />
</p>

### T+0:30 — 프로바이더 설정 (최초 1회)

Settings → 릴레이 JSON + API 키 붙여넣기 → Save & Connect.

Trainer가 실시간 모델 목록을 가져오고, 기본값을 고르고, streaming을 검증합니다. 잘못된 키라면 `invalid_key_or_permission`을 알려 줍니다.

### T+1:30 — 첫 대화

Coach 뷰로 전환하고 입력합니다: `@current_file explain what this async/await is doing?`

Trainer가 답변을 streaming 합니다. **코드를 다시 쓰지 않습니다.** 17번 줄을 가리키며 말합니다: "이건 fan-out입니다"; 23번 줄: "여기가 barrier입니다. 이걸 제대로 익히려면 실행 도중에 한 작업을 취소하는 버전을 직접 써 보세요 — 제가 함께 검증을 돌려 드리겠습니다."

### T+2:30 — 원클릭 훈련 카드

답변에 마우스를 올립니다. 세 개의 버튼: `Copy` / `Save to library` / **`Create training card`**.

`Create training card`를 클릭 → 카드가 생성됩니다 → Training 뷰로 진입 → FSRS가 3일 후로 복습을 예약합니다.

### T+4:00 — 직접 쓰고, 검증받기

코드는 당신이 씁니다. Trainer는 **대신 써 주지 않습니다**.

Training 뷰 열기 → 카드 넘기기 → 통과 기준 확인 → 코드 작성 → `Request verification` 클릭 → Trainer가 샌드박스에서 ruff + pyright + pytest를 실행 → 통과를 보고하거나 누락된 기준을 표시합니다.

### T+5:00 — 다음 날

내일 VS Code를 열면: Trainer가 자동으로 복원합니다 — 마지막 세션, 플랜, 카드 진행 상황이 모두 그대로 있습니다.

그 카드가 FSRS 리듬 디스크 위에서 깜빡입니다 — 오늘이 복습일입니다.

**이제 당신은 vibe coding 개발자가 아닙니다.**

---

## 다르게 느껴지는 이유

### 정직한 실패

잘못된 키는 `invalid_key_or_permission`이라고 말하고, 연결 불가는 `network`라고 말하며, 깨진 답변은 "이 답변을 명확히 읽지 못했습니다. 다시 보내 주세요"라고 말합니다 — **깨진 출력을 답변으로 포장하는 일은 없습니다**.

알 수 없는 게이트웨이를 조용히 OpenAI 호환으로 가정하지 않습니다.

**방법:** 오류 분류기(`provider_service.py:2823-2874`) + 자격 증명 스크러빙(`provider_protocols.py:640-681`) + 미지 핑거프린트 탐침(`provider_gateway.py:39-70`).

### 엔드포인트 속도 측정

프로바이더 엔드포인트가 병렬로 경주합니다 (**먼저 워밍업으로 cold-start 페널티를 상쇄한 뒤 시간을 측정**).

500 ms 미만이면 초록색, 1 s 미만이면 노란색. 클릭 한 번으로 가장 빠른 것을 채택합니다.

<p align="center"><img src="assets/feat-speed.png" alt="엔드포인트 속도 측정" width="720" /></p>

**방법:** `Promise.all` + 측정 전에 URL마다 버려지는 워밍업 요청 하나 (`providerWebviewCommands.ts:2275-2352`).

### Context 사용량 링

대화 위에 실시간 context 사용량 링이 떠 있습니다 — **압축이 오기 전에 미리 보입니다**.

### Thinking 강도

모델별 근거에 따라 게이트됩니다 — 선언된 능력 **또는** 검증된 프로브. 맹목적으로 전달하지 않습니다.

### 풀 파워 라이브러리

<p align="center"><img src="assets/feat-library.png" alt="풀 파워 라이브러리" width="720" /></p>

업로드 즉시 색인, FTS5 전문 검색, **3단계 샌드박스 미리보기** (A 리치 / B 변환 / C 메타데이터 + 네이티브 에디터 폴백), 삭제는 복원 가능한 휴지통으로.

**3구역 물리적 분리**: workspace / sandbox / trash. 절대 섞이지 않습니다.

코치 답변은 클릭 한 번으로 라이브러리에 들어옵니다 — **다시 검색해낼 수 있다면, 그건 정말 배운 것입니다**.

### 장기적으로 이어지는 상태

플랜은 고정되고 해제되며, 세션은 재시작을 넘어 살아남고, 카드 진행은 SQLite에 기록되고, 복습은 FSRS 곡선 위에서 시점이 됩니다 — **할 일 목록 위가 아니라**.

---

## 아키텍처

### 시스템 토폴로지

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

### 디렉터리 구성

| 폴더 | 내용 | 크기 |
|---|---|---|
| `extension/src/` | 호스트: 명령, 워크스페이스 신뢰, 시크릿 저장, sidecar 라이프사이클 | ~30k 줄 TS |
| `extension/webview/` | React 워크벤치: 5개 뷰 + Zustand + 8개 언어 | ~50k 줄 TSX |
| `extension/tests/` | node:test 스위트 (220개 파일 / 1,679개 케이스) | 73,744줄 |
| `server/app/` | FastAPI 두뇌: agent / pedagogy / memory / FSRS / training | ~120k 줄 Python |
| `server/tests/` | pytest 스위트 (159개 파일 / 1,649개 케이스) | 106,422줄 |
| `shared/src/` | **공유 순수 함수 + 24개 거버넌스 모듈** (host + webview + test) | ~3k 줄 TS |
| `extension/bundled/` | VSIX에 번들된 sidecar (PyInstaller onedir) | ~250 MB |

### 단 하나의 표준 봉투

> Trainer의 모든 HTTP 응답(`/health` 제외)은 **동일한** `WorkbenchSnapshot`(31개 필드)을 반환합니다.

| 카테고리 | 필드 예시 | 생산자 |
|---|---|---|
| 세션 | `messages`, `coaching_state`, `learner_state` | `pedagogy/service.py` |
| 플랜 | `plan`, `global_plan`, `project_plan_link`, `current_task` | `planner/service.py` |
| 메모리 | `memory`, `selected_teaching_assets`, `next_review_due` | `memory/service.py` |
| 교육 | `teaching_decision`, `implementation_guide`, `project_ideas` | `pedagogy/*` |
| 정서 | `affect_state`, `tone_decision` | `affect/service.py` |
| 훈련 | `evaluation`, `review_queue_summary` | `training/*` |
| 메타 | `context_id`, `sidecar_status`, `snapshot_revision`, `active_panel` | `api/runtime.py` |

**왜 하나의 봉투인가:**
- 웹뷰는 **이 하나의 객체만으로 전부 렌더링**합니다 — 12개 서브시스템이 각자 필드를 쓰고, 하이드레이션은 한 번입니다
- **CRDT 라이트 점진 동기화**: 각 스냅샷에는 `snapshot_revision`이 있고, `GET /snapshot?since_revision=N`은 N이 오래되었을 때만 전체 블롭을 보내며, 그 외에는 `{unchanged: true}`를 반환합니다
- 핵심 코드: `server/app/core/models.py:2304-2336` · `server/app/api/routers.py:11648-11710`

### 공유 거버넌스 모듈

> Trainer의 아키텍처 척추는 **24개 순수 함수 거버넌스 모듈**입니다 — host, webview, test가 모두 동일한 결정론적 로직을 실행합니다.

| 모듈 | 역할 |
|---|---|
| `planGovernance` · `masterPlanGovernance` | 플랜 편집, 크로스 프로젝트 마스터 플랜 |
| `trainingHandoffGovernance` · `trainingRecoveryGovernance` · `trainingReliabilityGovernance` | 카드 라우팅, 복구, 신뢰성 |
| `reviewQueueGovernance` · `reviewArtifactGovernance` | FSRS 큐 정렬, 근거 리뷰 |
| `workspaceAuthority` · `workspaceRecoveryGovernance` | 6단계 권한, 복구 |
| `suggestedActionGovernance` · `conversationCandidateGovernance` | 제안 액션, 대화 중재 |
| `transferEvidenceGovernance` · `transferSkillGovernance` | 크로스 프로젝트 근거, 스킬 승격 |
| `coachOrientationGovernance` · `resourcesOrientationGovernance` | Coach/Resources 뷰 방향 안내 |
| `settingsCapabilityGovernance` · `operationReliabilityGovernance` | 설정 기능 게이팅, 작업 신뢰성 |
| `hostLastTestGovernance` · `providerModelPolicy` | 프로바이더 마지막 테스트, 모델 정책 |
| `sandboxNetworkCapabilityNarrative` · `projectLaneGovernance` | 샌드박스 기능 설명, 프로젝트 레인 |
| `previewAssets` · `materialRecommendationGovernance` | 미리보기 에셋 단계, 자료 추천 |

**이유:** 동일한 `resolveSuggestedActionGovernance`가 host, webview, 테스트에서 실행됩니다 — **3방향 일관성, 왕복 없음**.

---

## 안전 모델

- API 키는 **VS Code SecretStorage**(OS 수준 암호화)에 저장됩니다 — 설정 파일에도, git에도 절대 저장되지 않습니다
- 워크스페이스는 **VS Code 기본 신뢰 모델**을 따릅니다 — 신뢰하지 않는 동안에는 모든 쓰기가 거부됩니다
- **6단계 권한 사다리**: INSPECT < ANNOTATE < REORGANIZE < GENERATE < APPLY < DESTRUCTIVE — 기본은 읽기 전용이며, 쓰기/삭제/수정에는 단계적으로 높은 증명이 필요합니다
- **원격 워크스페이스는 REORGANIZE 미만으로 하드 잠금**됩니다 — 사용자가 직접 허용해도 올릴 수 없습니다
- **삭제는 휴지통으로**: `delete` 연산은 없으며, `move to <root>/.trash/<timestamp-uuid>/`만 있습니다
- 샌드박스 미리보기는 엄격한 **경로 거버넌스**를 강제합니다 — 범위를 벗어난 경로에는 무조건 422를 반환합니다
- 스킬 공유는 **순수 데이터 임포트**입니다 — 필드 길이 상한, 기본 제공 우선, **코드 경로 자체가 없습니다**

**핵심 코드:** `server/app/workspace/authority.py:33-962` · `extension/src/provider/providerConfigStore.ts` · `shared/src/skillCatalog.ts:614-764`

---

## 품질 게이트

> Trainer는 자체 검증 스택을 하나의 제품으로 다룹니다.

| 게이트 | 커버리지 | 비고 |
|---|---|---|
| **서버 테스트** (pytest) | **159개 파일 / 1,649개 케이스 / 106,422줄** | Hypothesis 속성 기반 스위트 6개 포함 |
| **확장 테스트** (node:test) | **220개 파일 / 1,679개 케이스 / 73,744줄** | 소스 가드 파일 109개 + 동작 테스트 111개 |
| **E2E** | **11개 스펙 / 4,335줄** | 실제 모델을 상대로 실제 VS Code 인스턴스에서 실행 |
| **경험 매트릭스** | **200개 시나리오 × 2개 레이어** | preview fixture + 실제 sidecar |
| **VSIX 호스트 드라이버** | **33단계** | 설치 → 활성화 → streaming → 검증 → 실제 웹뷰 렌더링 단언 |
| **정적 분석** | ruff + pyright + tsc | 경고 0개 |
| **프로토콜 매트릭스** | **5개 프로토콜** | OpenAI Chat / Responses / Anthropic / Gemini / OpenAI-Compatible |
| **i18n** | **8개 언어 × 600+ 키** | zh-CN / en-US / es-ES / fr-FR / de-DE / ja-JP / ko-KR / pt-BR |
| **번들 sidecar** | **6개 플랫폼 바이너리** | win32-x64 / win32-arm64 / darwin-x64 / darwin-arm64 / linux-x64 / linux-arm64 |

**E2E 스위트는 실제 모델을 상대로 실제 VS Code 인스턴스에서 실행됩니다:**

> 패키징된 확장을 활성화 → 번들 sidecar 부팅 → 프로바이더 저장 → 전체 코치 턴 streaming → 훈련 카드 생성 및 검증 → 웹뷰가 **실제로 렌더링한 것**을 단언 → 스크린샷 → 워크스페이스를 넘어 다시 열고 히스토리 복구.

**테스트는 스스로 한계를 선언합니다:**
각 E2E 시나리오는 `evidence: { realSidecar, limitation }`을 갖습니다 — **테스트가 증명하지 않는 것을 스스로 밝힙니다.**

---

## i18n · 8개 언어

| 언어 | 코드 | 기본 |
|---|---|---|
| 简体中文 | `zh-CN` | ✅ |
| English | `en-US` | ✅ |
| Español | `es-ES` | ✅ |
| Français | `fr-FR` | ✅ |
| Deutsch | `de-DE` | ✅ |
| 日本語 | `ja-JP` | ✅ |
| 한국어 | `ko-KR` | ✅ |
| Português | `pt-BR` | ✅ |

**폴백 체인:** 사용자 설정 > VS Code `env.language` > `zh-CN`(기본값)

**6개 표면 범위 오버라이드:** `resourceView` / `contextRail` / `trainingUi` / `orientationRail` / `composerAccessibility` / `leftoverHonesty` — 번역자는 자신이 맡은 표면만 채우면 됩니다, **600+ 키 전체 테이블이 아닙니다**.

핵심 코드: `extension/webview/src/lib/i18n/copy.ts` (5,283줄)

---

## 감사의 말

> Trainer는 거인의 어깨 위에 섭니다.

### 🏃 런타임 코어

| 프로젝트 | 용도 | 대체 불가능한 이유 |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | 로컬 sidecar 프레임워크 | async + Pydantic + 자동 OpenAPI 문서 |
| [Uvicorn](https://github.com/encode/uvicorn) | ASGI 서버 | HTTP/1.1 + WebSocket + 높은 동시성 |
| [Pydantic](https://github.com/pydantic/pydantic) | 데이터 검증 및 직렬화 | 31개 필드의 WorkbenchSnapshot이 이 위에서 돌아갑니다 |
| [httpx](https://github.com/encode/httpx) | 비동기 HTTP 클라이언트 | sidecar ↔ LLM 게이트웨이 프로토콜 라우팅 전부 |

### 🤖 LLM 프로토콜

| 프로젝트 | 용도 |
|---|---|
| [openai-python](https://github.com/openai/openai-python) | OpenAI / Anthropic / Gemini 호환 클라이언트 (5개 프로토콜 라우팅) |

### 🧠 훈련 및 메모리

| 프로젝트 | 용도 |
|---|---|
| [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs) | FSRS 망각 곡선 복습 스케줄링 · `TrainingCardState`를 구동 |
| [qdrant-client](https://github.com/qdrant/qdrant-client) | 시맨틱 메모리 벡터 검색 (sentence-transformer 폴백 포함) |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | PDF 파싱 (라이브러리 Tier A 미리보기) |
| [trafilatura](https://github.com/adbar/trafilatura) | 웹 콘텐츠 추출 (리소스 수집) |
| [markitdown](https://github.com/microsoft/markitdown) | 문서 → Markdown 변환 (라이브러리 Tier B 미리보기) |

### ⚛️ 프론트엔드 코어

| 프로젝트 | 용도 |
|---|---|
| [React](https://github.com/facebook/react) | 사이드바 워크벤치 UI |
| [Vite](https://github.com/vitejs/vite) | 빌드 도구 + 개발 서버 |
| [Zustand](https://github.com/pmndrs/zustand) | 워크벤치 상태 관리 |
| [Zod](https://github.com/colinhacks/zod) | 런타임 타입 검증 |

### 🎨 렌더링

| 프로젝트 | 용도 |
|---|---|
| [react-markdown](https://github.com/remarkjs/react-markdown) | Markdown 렌더링 |
| [remark-gfm](https://github.com/remarkjs/remark-gfm) | GFM 확장 (테이블, 작업 목록) |
| [remark-math](https://github.com/remarkjs/remark-math) · [rehype-katex](https://github.com/remarkjs/rehype-katex) · [KaTeX](https://github.com/KaTeX/KaTeX) | 수학 렌더링 |
| [Shiki](https://github.com/shikijs/shiki) | 코드 하이라이팅 (VS Code TextMate 문법) |
| [Mermaid](https://github.com/mermaid-js/mermaid) | 다이어그램 및 플로우차트 |
| [@tanstack/react-table](https://github.com/TanStack/table) | 라이브러리 / 훈련 큐 테이블 |

### 📄 미리보기

| 프로젝트 | 용도 |
|---|---|
| [mammoth](https://github.com/mwilliamson/mammoth.js) · [docx-preview](https://github.com/VolodymyrBaydalka/docx-preview) | DOCX 리치 렌더링 (Tier A) |
| PDF.js (번들) | PDF 리치 렌더링 (Tier A) |

### 🧪 테스트 및 품질

| 프로젝트 | 용도 |
|---|---|
| [pytest](https://github.com/pytest-dev/pytest) · [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) | 서버 159개 파일 / 1,649개 케이스 |
| [Hypothesis](https://github.com/HypothesisWorks/hypothesis) | 속성 테스트 (planner / evaluator / scheduler) |
| [ruff](https://github.com/astral-sh/ruff) | Python 린트 + 포맷 (E/F/I/B, py312, 100열) |
| [pyright](https://github.com/microsoft/pyright) | Python 정적 타입 검사 |
| [TypeScript](https://github.com/microsoft/TypeScript) | strict 모드, 경고 0개 |
| [Playwright](https://github.com/microsoft/playwright) | E2E + 200개 시나리오 경험 매트릭스 |

### 📦 패키징 및 배포

| 프로젝트 | 용도 |
|---|---|
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | sidecar 단일 바이너리 프리즈 (6개 플랫폼, manifest sha256) |

### 💡 방법론적 영감

| 프로젝트 | 영감 |
|---|---|
| [open-spaced-repetition/fsrs4anki](https://github.com/open-spaced-repetition/fsrs4anki) | FSRS 원논문 및 참조 구현 |
| [obra/superpowers](https://github.com/obra/superpowers) | "제안이 아니라 의무 워크플로"라는 코칭 규율 |
| [HKUDS/CLI-Anything](https://github.com/HKUDS/CLI-Anything) | "모든 소프트웨어를 agent-native로"라는 야망 |

### 🎨 비주얼 에셋

| 프로젝트 | 용도 |
|---|---|
| [dora-image](https://github.com/AI-yyf/trainer/tree/main/assets) | 이 README의 모든 이미지 (`assets/MASCOT.md` / `BANNER_PROMPT.md` / `FEATURE_PROMPTS.md` 참조) |
| DeepSeek 공식 모에 소녀 | 치비 비율 / 셀 셰이딩 경향 참조 |
| Pieter Bruegel, *바벨탑* | 좌우 진영 앙상블 구도 참조 |
| Rembrandt, *밤의 경비대* | 7:1 명암 대비 참조 |
| 스튜디오 지브리 캐릭터 디자인 | 3점 하이라이트가 있는 큰 눈, 절제된 표정 |

---

## 라이선스

[MIT](LICENSE)

---

## Trainer 인용하기

Trainer가 작업 흐름에 도움이 되었다면 블로그 / 논문 / 발표에서 자유롭게 인용해 주세요:

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

**// AI를 가르치고 · AI와 함께 성장하세요**

`v1.0.3` · 커피와 FSRS, 24개 순수 함수, 3,328개 테스트, 그리고 대신 코드를 쓰기를 거부하는 마음으로 만들었습니다.

</div>
