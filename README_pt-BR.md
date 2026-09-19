# Trainer

<div align="center">

<img src="assets/banner.png" alt="Trainer — Treine sua IA · Cresça com sua IA · Onde IA e humanos crescem juntos" width="100%" />

**Um coach de código de longo prazo que mora na sua barra lateral do VS Code.**

**Ele planeja, treina, verifica e lembra de tudo sobre você — mas nunca escreve o seu código.**

**// Output ≠ Crescimento // Verificar + Revisar = Crescimento**

[English](README.md) · [简体中文](README_zh-CN.md) · [Español](README_es-ES.md) · [Français](README_fr-FR.md) · [Deutsch](README_de-DE.md) · [日本語](README_ja-JP.md) · [한국어](README_ko-KR.md) · Português

[![Release](https://img.shields.io/badge/release-v1.0.3-1f6feb)](https://github.com/AI-yyf/trainer/releases/tag/v1.0.3)
[![License](https://img.shields.io/badge/license-MIT-3fb950)](LICENSE)
[![Platforms](https://img.shields.io/badge/platforms-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-8b949e)](#instalação)
[![Tests](https://img.shields.io/badge/tests-3%2C328%20cases-F59E0B)](#portões-de-qualidade)
[![i18n](https://img.shields.io/badge/i18n-8%20languages-A78BFA)](#i18n--oito-idiomas)

[Por quê](#por-que-o-trainer-existe) ·
[Instalação](#instalação) ·
[Configuração](#três-passos-não-quatro) ·
[Mecânicas](#mecânicas-centrais) ·
[Cinco visões](#cinco-visões) ·
[Comparação](#comparação) ·
[Demo de 5 min](#demo-de-cinco-minutos) ·
[Design](#por-que-parece-diferente) ·
[Arquitetura](#arquitetura) ·
[Segurança](#modelo-de-segurança) ·
[Qualidade](#portões-de-qualidade) ·
[Agradecimentos](#agradecimentos) ·
[🎭 O elenco](docs/CAST.md)

</div>

---

## Por que o Trainer existe

> Devs não travam por falta de tutoriais.
> Eles travam porque nada fecha o loop de aprendizado.

Uma conversa com um LLM evapora assim que termina; vídeos são passivos; o conceito que você quase entendeu na terça já era na sexta.

Pior: **vibe coding** — três meses deixando a IA escrever código sem você entender nada disso.

Os bookmarks se acumulam enquanto o output fica estagnado. Os repositórios crescem enquanto a sua cabeça esvazia.

**O Trainer resolve isso de dentro do editor.**

Não é uma casca de chat — é um coach com memória, um currículo e uma política de prova:

- Ele **planeja** o seu aprendizado em estágios e acompanha onde você realmente está — não onde você acha que está
- Ele **treina** você com flash cards, exercícios de teoria e experimentos de cenário
- Ele **verifica** o domínio contra o seu código real — falar de FastAPI não vale nada até o arquivo atual provar
- Ele **lembra** de você entre sessões, projetos e semanas, agendando revisões na curva de esquecimento do FSRS
- Ele **nunca escreve código de produção por você** — você escreve, ele ensina, **vocês crescem juntos**

<div align="center">

| vibe coding · a norma de hoje | Trainer · como deveria ser |
|:---:|:---:|
| `def ship(code):` <br> `    ai.write(code)` <br> `# você entendeu mesmo?` <br> `    return forget(code)` | `def ship(code):` <br> `    you.write(code)` <br> `    ai.verify(code)` <br> `    you.recall(code)` <br> `    return grown(code)` |
| output = esquecimento | output + memória + revisão = crescimento |

</div>

---

## Instalação

**Via VSIX (pré-compilado, três plataformas):**

Baixe o `.vsix` da sua plataforma (`darwin-arm64` / `linux-x64` / `win32-x64`) na [release v1.0.3](https://github.com/AI-yyf/trainer/releases/tag/v1.0.3).

Painel de extensões do VS Code → `···` → *Instalar do VSIX* → recarregue a janela.

**Do código-fonte:**

```bash
git clone https://github.com/AI-yyf/trainer.git
cd trainer && npm install
cd server && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cd .. && npm run build
```

Abra este repositório no VS Code e pressione F5 (Extension Development Host), ou instale o VSIX empacotado.

**Requisitos:** VS Code ≥ 1.96 · Python ≥ 3.12 (build via código-fonte) · macOS / Linux / Windows

---

## Três passos, não quatro

1. Abra a barra lateral do Trainer → Settings
2. Cole as informações de conexão do seu relay (o bloco JSON completo copiado do dashboard do relay é interpretado automaticamente — endpoint e key já vêm separados para você) → cole a sua API key
3. Clique em **Save & Connect**

O Trainer puxa a lista de modelos ao vivo, escolhe um modelo padrão e verifica o caminho de streaming numa passada só.

Uma key inválida reporta `invalid_key_or_permission` — não um spinner vago.

<p align="center">
  <img src="assets/screenshots/settings-quick-setup.png" alt="Configuração rápida" width="420" />
</p>

---

## Mecânicas centrais

### ① Portões de verificação — você escreve o código, o código comprova

Um cartão de treino não avança para "implementado" enquanto a verificação não rodar contra o seu arquivo real; o botão manual de "marcar como feito" está ausente por design.

O jeito mais rápido de fingir aprendizado é marcar todas as caixinhas. O Trainer se recusa.

<p align="center"><img src="assets/feat-verify.png" alt="Portões de verificação" width="720" /></p>

**Como:**
- O `EvaluatorService` do servidor **copia** o arquivo atual para um `tempfile.TemporaryDirectory`, roda ruff + pyright + pytest e desmonta o tempdir
- As ferramentas **nunca** rodam no projeto do aprendiz — zero poluição de `.pytest_cache`
- Cada verificação reporta detalhe Matched/Missing por critério contra uma lista explícita de `acceptance_criteria` + `expected_symbols`
- Código: `server/app/evaluator/service.py:198-312`

### ② Memória de longo prazo — agendamento pela curva de esquecimento do FSRS

Domínio, pontos fracos e revisões pendentes vivem em SQLite, com busca semântica no Qdrant.

As revisões surgem na curva de esquecimento do FSRS — aparecem pouco antes de você esquecer e ficam quietas enquanto você ainda lembra.

<p align="center"><img src="assets/feat-memory.png" alt="Memória de longo prazo" width="720" /></p>

**Como:**
- Memória em duas camadas: estruturada (`StructuredMemoryService`, ~480 registros) + semântica (Qdrant + fallback offline com sentence-transformer)
- **`_should_delay_live_thread_reviews()`** — revisões são suprimidas ativamente enquanto um fluxo de implementação de ideia está em andamento; o seu raciocínio nunca é interrompido
- **Habilidades transferíveis falham fechadas entre workspaces**: sucesso em um projeto nunca vira domínio global; a promoção exige passar em ≥2 workspaces
- Código-chave: `server/app/memory/service.py:1357-1597` · `transfer_skills.py:81-113` · `review_scheduler.py:522-544`

### ③ O loop de treino — surge quando vence, avança quando verificado

Flash cards, exercícios de teoria e experimentos de cenário entram na fila da visão Training: as revisões aparecem quando vencem, os cartões avançam quando verificados, e qualquer lacuna de conhecimento numa conversa vira um cartão de treino com um clique.

<p align="center"><img src="assets/feat-training.png" alt="O loop de treino" width="720" /></p>

**Como:**
- **Máquina de estados de 5 fases** `LEARN → TRY → VERIFY → REFLECT → RETURN`, cada transição registrada no `phase_history`
- **Whitelist de fontes de verificação confiáveis**: `automated_test` / `evaluator` / `ide_current_file` / `server_evaluator` / `test_runner` / `verification_service` — um "afirmado manualmente" jamais avança um cartão
- Os handlers `onSkip` / `onRate` da UI do cartão estão marcados como **`@deprecated Unused`** — o único caminho de progressão é o `onCardStatusTransition`
- Código-chave: `server/app/training/handoff.py:40-47` · `extension/webview/src/components/training/TrainingCardPanel.tsx:78-85`

### ④ Você escreve, o coach guia

O coach lê os seus arquivos, confere diagnósticos e pesquisa o workspace — mas o código de produção sempre sai das suas mãos.

Respostas `direct` saem na hora; `coach-first` faz você pensar primeiro. **A carga cognitiva é sua, não dele.**

<p align="center"><img src="assets/feat-youwrite.png" alt="Você escreve, o coach guia" width="720" /></p>

**Como:**
- O `PedagogyService` emite um `ImplementationGuide` de 12 campos a cada turno — cada campo é uma restrição sobre o que o coach pode pedir a seguir
- `ImplementationCoach._current_step` é ancorado em "o primeiro caminho com falha" ou "o primeiro ponto de entrada conhecido" — nunca em "explore o codebase"
- Tom orientado por afeto: o `AffectService` muda para o modo `concise_rescue` após duas falhas seguidas
- Código-chave: `server/app/pedagogy/implementation_coach.py:140-186` · `affect/service.py:142-152`

---

## Cinco visões

> Cinco visões fixas de nível superior. Cada uma com um limite estrito de responsabilidade.

| Visão | Papel | Em uma linha |
|-----------|------|--------|
| **Coach** | Chat com streaming | **Porta de entrada**: acesso a ferramentas + paleta de habilidades `$` + anexos de imagem + modos de resposta |
| **Plan** | Plano de aprendizado | **Mapa**: estágios, progresso, evidências, congelar/descongelar plano |
| **Resources** | Biblioteca | **Estante**: busca com FTS5 + preview em sandbox de 3 níveis + lixeira restaurável |
| **Training** | Treino | **Playground**: flash cards FSRS + exercícios de teoria + experimentos de cenário + portões de verificação |
| **Settings** | Configurações | **Console**: 59 comandos + teste de velocidade de endpoint + intensidade de thinking + admissão de workspace |

<p align="center">
  <img src="assets/screenshots/plan.png" alt="Visão Plan" width="260" />
  <img src="assets/screenshots/resources.png" alt="Visão Resources" width="260" />
  <img src="assets/screenshots/training.png" alt="Visão Training" width="260" />
</p>

### Visão Coach (entrada)

Chat com streaming do coach, com acesso a ferramentas, paleta de habilidades `$`, anexos de imagem, modos de resposta, anel de uso de contexto, histórico de sessões e compartilhamento.

**Toda resposta do coach vem com três ações rápidas embaixo:**

- **Copiar resposta como Markdown**
- **Salvar na biblioteca** (pesquisável + com preview)
- **Converter em cartão de treino verificável** — por mensagem, não por sessão

<p align="center"><img src="assets/screenshots/message-actions.png" alt="Ações por mensagem" width="520" /></p>

### Habilidades `$` personalizadas — crie, compartilhe, instale

Digite `$` para abrir a paleta de habilidades: além das que vêm de fábrica, você pode transformar os seus próprios prompts em habilidades com trigger words e keywords, compartilhá-las com outras pessoas ou instalar habilidades que outras pessoas compartilharam — **tudo por um canal de dados puro, sem execução de código**.

<p align="center">
  <img src="assets/screenshots/skill-deck.png" alt="Paleta de habilidades" width="380" />
  <img src="assets/screenshots/skill-manager.png" alt="Gerenciador de habilidades" width="380" />
</p>

<p align="center"><img src="assets/feat-skills.png" alt="Habilidades personalizadas" width="720" /></p>

**Como:**
- Habilidades personalizadas são imports de JSON puro — `{ _type, version, trigger, title, prompt, keywords }`; sem `eval`, sem `Function()`, sem caminho de código
- Limites rígidos: prompt ≤ 4000 caracteres, title ≤ 160, keywords ≤ 16, habilidades de usuário ≤ 24
- Triggers nativos ganham colisões — um `$explain` importado por usuário não pode ofuscar o que vem de fábrica
- Código-chave: `shared/src/skillCatalog.ts:614-764`

---

## Comparação

> O Trainer não está aqui para substituir ninguém — ele preenche um vão que ninguém mais ocupa.

| Dimensão | ferramentas vibe | IDEs de chat | apps de flashcard | **Trainer** |
|---|---|---|---|---|
| Escreve código por você | ✅ | ✅ | ❌ | ❌ |
| Verifica o seu código | ❌ | ❌ | ❌ | ✅ contra o arquivo atual |
| Lembra entre sessões | ⚠️ janela de contexto | ⚠️ resumos | ✅ | ✅ SQLite + Qdrant |
| Repetição espaçada no FSRS | ❌ | ❌ | ✅ | ✅ + supressão durante fluxo ao vivo |
| Níveis de permissão de workspace | ❌ | ⚠️ diálogo de confiança | ❌ | ✅ 6 níveis + trava dura no remoto |
| Progressão de cartão travada | ❌ | ❌ | ⚠️ checkboxes manuais | ✅ verificação obrigatória |
| Promoção de habilidade transferível | ❌ | ❌ | ❌ | ✅ fail-closed entre workspaces |
| i18n | ⚠️ | ⚠️ | ⚠️ | ✅ 600+ chaves × 8 |
| Suíte de testes | código fechado | código fechado | código fechado | ✅ **3.328 casos** (aberta) |
| Se recusa a escrever por você | ❌ | ❌ | n/a | ✅ um limite filosófico inegociável |

> Em uma linha: as outras ferramentas fazem você escrever mais rápido; o Trainer faz você escrever de verdade.

---

## Demo de cinco minutos

> Veja como são, na prática, os seus primeiros cinco minutos.

### T+0:00 — Abra a barra lateral

Clique no ícone do Trainer na barra de atividades. A barra lateral abre, já na **visão Coach**.

<p align="center">
  <img src="assets/screenshots/settings-quick-setup.png" alt="Primeira abertura" width="420" />
</p>

### T+0:30 — Configure o provedor (só na primeira vez)

Settings → cole o seu JSON de relay + API key → Save & Connect.

O Trainer puxa a lista de modelos ao vivo, escolhe um padrão e verifica o streaming. Key inválida → ele avisa: `invalid_key_or_permission`.

### T+1:30 — Primeira conversa

Vá para o Coach e digite: `@current_file explain what this async/await is doing?`

O Trainer responde em streaming. **Ele não reescreve o seu código.** Ele aponta para a linha 17: "isto aqui é um fan-out"; linha 23: "esta é a barreira. Para aprender isso de verdade, escreva uma versão que cancela uma task no meio do voo — eu rodo a verificação com você."

### T+2:30 — Cartão de treino com um clique

Passe o mouse sobre a resposta. Três botões: `Copy` / `Save to library` / **`Create training card`**.

Clique em `Create training card` → cartão gerado → entra na visão Training → o FSRS agenda para daqui a 3 dias.

### T+4:00 — Escreva você mesmo, seja verificado

Você escreve o código. O Trainer **não escreve por você**.

Abra Training → vire o cartão → veja os critérios de aprovação → escreva → clique em `Request verification` → o Trainer roda ruff + pyright + pytest num sandbox → reporta aprovação ou sinaliza o critério que faltou.

### T+5:00 — No dia seguinte

Abra o VS Code amanhã: o Trainer se auto-restaura — última sessão, plano, progresso dos cartões, tudo no lugar.

Aquele cartão pulsa no disco de ritmo do FSRS — vence hoje.

**Você deixou de ser um dev de vibe coding.**

---

## Por que parece diferente

### Falha honesta

Key inválida diz `invalid_key_or_permission`; endpoint inacessível diz `network`; resposta corrompida diz "não consegui ler essa resposta direito, reenvia" — **saída quebrada nunca é fantasiada de resposta**.

Gateways desconhecidos não são assumidos silenciosamente como OpenAI-compatible.

**Como:** classificador de erros (`provider_service.py:2823-2874`) + scrubbing de credenciais (`provider_protocols.py:640-681`) + probing de fingerprint desconhecida (`provider_gateway.py:39-70`).

### Teste de velocidade de endpoint

Os endpoints do provedor disputam em paralelo (**aquecimento primeiro para cancelar a penalidade de cold start, depois cronometrado**).

Verde abaixo de 500 ms, amarelo abaixo de 1 s. Um clique adota o mais rápido.

<p align="center"><img src="assets/feat-speed.png" alt="Teste de velocidade de endpoint" width="720" /></p>

**Como:** `Promise.all` + uma requisição de aquecimento descartada por URL antes da cronometrada (`providerWebviewCommands.ts:2275-2352`).

### Anel de uso de contexto

Um anel de uso de contexto ao vivo fica no topo da conversa — **você vê a compressão chegando antes de ela acontecer**.

### Intensidade de thinking

Liberado com base em evidência por modelo — capacidade declarada **ou** probe verificado. Nunca encaminhado às cegas.

### Biblioteca em potência máxima

<p align="center"><img src="assets/feat-library.png" alt="Biblioteca em potência máxima" width="720" /></p>

Uploads indexados na chegada, busca full-text com FTS5, **preview em sandbox de 3 níveis** (A rico / B convertido / C metadados + fallback para o editor nativo), exclusões vão para uma lixeira restaurável.

**Separação física em 3 zonas**: workspace / sandbox / trash. Nunca misturadas.

Respostas do coach entram na estante com um clique — **se você consegue pesquisar e reencontrar, é porque aprendeu de verdade**.

### Estado de longo prazo

Planos congelam e descongelam; sessões sobrevivem a reinícios; o progresso dos cartões vive em SQLite; as revisões vencem na curva do FSRS — **não numa lista de tarefas**.

---

## Arquitetura

### Topologia do sistema

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

### Layout de diretórios

| Pasta | Conteúdo | Tamanho |
|---|---|---|
| `extension/src/` | Host: comandos, workspace trust, secret storage, ciclo de vida do sidecar | ~30k linhas TS |
| `extension/webview/` | Workbench React: 5 visões + Zustand + 8 idiomas | ~50k linhas TSX |
| `extension/tests/` | suíte node:test (220 arquivos / 1.679 casos) | 73.744 linhas |
| `server/app/` | Cérebro FastAPI: agent / pedagogy / memory / FSRS / training | ~120k linhas Python |
| `server/tests/` | suíte pytest (159 arquivos / 1.649 casos) | 106.422 linhas |
| `shared/src/` | **Funções puras compartilhadas + 24 módulos de governança** (host + webview + test) | ~3k linhas TS |
| `extension/bundled/` | Sidecar empacotado no VSIX (PyInstaller onedir) | ~250 MB |

### Um envelope canônico

> Todas as respostas HTTP do Trainer (exceto `/health`) retornam o **mesmo** `WorkbenchSnapshot` (31 campos).

| Categoria | Campos de exemplo | Produtor |
|---|---|---|
| Sessão | `messages`, `coaching_state`, `learner_state` | `pedagogy/service.py` |
| Plano | `plan`, `global_plan`, `project_plan_link`, `current_task` | `planner/service.py` |
| Memória | `memory`, `selected_teaching_assets`, `next_review_due` | `memory/service.py` |
| Ensino | `teaching_decision`, `implementation_guide`, `project_ideas` | `pedagogy/*` |
| Afeto | `affect_state`, `tone_decision` | `affect/service.py` |
| Treino | `evaluation`, `review_queue_summary` | `training/*` |
| Meta | `context_id`, `sidecar_status`, `snapshot_revision`, `active_panel` | `api/runtime.py` |

**Por que um envelope só:**
- A webview renderiza **inteiramente a partir desse único objeto** — 12 subsistemas escrevem os seus campos, hidratação feita uma vez
- **Sincronização incremental CRDT-light**: cada snapshot tem um `snapshot_revision`; `GET /snapshot?since_revision=N` só envia o blob completo quando N está defasado; caso contrário, `{unchanged: true}`
- Código-chave: `server/app/core/models.py:2304-2336` · `server/app/api/routers.py:11648-11710`

### Módulos de governança compartilhados

> A espinha dorsal arquitetural do Trainer são **24 módulos de governança de funções puras** — host, webview e testes executam exatamente a mesma lógica determinística.

| Módulo | Papel |
|---|---|
| `planGovernance` · `masterPlanGovernance` | Edição de plano, master plan entre projetos |
| `trainingHandoffGovernance` · `trainingRecoveryGovernance` · `trainingReliabilityGovernance` | Roteamento de cartões, recuperação, confiabilidade |
| `reviewQueueGovernance` · `reviewArtifactGovernance` | Ordenação da fila FSRS, revisão de evidências |
| `workspaceAuthority` · `workspaceRecoveryGovernance` | Permissões de 6 níveis, recuperação |
| `suggestedActionGovernance` · `conversationCandidateGovernance` | Ações sugeridas, arbitração de conversa |
| `transferEvidenceGovernance` · `transferSkillGovernance` | Evidências entre projetos, promoção de habilidades |
| `coachOrientationGovernance` · `resourcesOrientationGovernance` | Orientação das visões Coach/Resources |
| `settingsCapabilityGovernance` · `operationReliabilityGovernance` | Gating de capacidades do Settings, confiabilidade de operações |
| `hostLastTestGovernance` · `providerModelPolicy` | Último teste do provedor, política de modelos |
| `sandboxNetworkCapabilityNarrative` · `projectLaneGovernance` | Narrativa de capacidades do sandbox, project lanes |
| `previewAssets` · `materialRecommendationGovernance` | Níveis de assets de preview, recomendação de materiais |

**Por quê:** o mesmo `resolveSuggestedActionGovernance` roda no host, na webview e nos testes — **consistência em três pontas, sem round-trips**.

---

## Modelo de segurança

- As API keys vivem no **VS Code SecretStorage** (criptografia a nível de SO) — nunca em arquivos de config, nunca no git
- O workspace segue o **trust nativo do VS Code** — toda escrita é recusada enquanto não confiável
- **Escada de permissões de 6 níveis**: INSPECT < ANNOTATE < REORGANIZE < GENERATE < APPLY < DESTRUCTIVE — somente leitura por padrão; escrever/deletar/modificar exige atestação de escalonamento
- **Workspaces remotos ficam travados abaixo de REORGANIZE** — nem concessão do usuário eleva
- **Delete vai para a lixeira**: não existe operação `delete`, apenas `move to <root>/.trash/<timestamp-uuid>/`
- Previews em sandbox impõem **governança de caminhos** estrita — caminho fora do limite recebe um 422 seco
- Compartilhar habilidades é **import de dados puros** — limites de tamanho por campo, nativas vencem, **nenhum caminho de código existe**

**Código-chave:** `server/app/workspace/authority.py:33-962` · `extension/src/provider/providerConfigStore.ts` · `shared/src/skillCatalog.ts:614-764`

---

## Portões de qualidade

> O Trainer trata a própria pilha de verificação como um produto.

| Portão | Cobertura | Notas |
|---|---|---|
| **Testes do servidor** (pytest) | **159 arquivos / 1.649 casos / 106.422 linhas** | inclui 6 suítes property-based com Hypothesis |
| **Testes da extensão** (node:test) | **220 arquivos / 1.679 casos / 73.744 linhas** | 109 arquivos source-guard + 111 testes de comportamento |
| **E2E** | **11 specs / 4.335 linhas** | instância real do VS Code contra um modelo real |
| **Matriz de experiência** | **200 cenários × 2 camadas** | fixture de preview + sidecar real |
| **Driver host do VSIX** | **33 passos** | instalar → ativar → stream → verificar → assegurar a renderização real da webview |
| **Análise estática** | ruff + pyright + tsc | zero warnings |
| **Matriz de protocolos** | **5 protocolos** | OpenAI Chat / Responses / Anthropic / Gemini / OpenAI-Compatible |
| **i18n** | **8 idiomas × 600+ chaves** | zh-CN / en-US / es-ES / fr-FR / de-DE / ja-JP / ko-KR / pt-BR |
| **sidecar empacotado** | **6 binários de plataforma** | win32-x64 / win32-arm64 / darwin-x64 / darwin-arm64 / linux-x64 / linux-arm64 |

**A suíte E2E roda numa instância real do VS Code contra um modelo real:**

> Ativa a extensão empacotada → sobe o sidecar empacotado → salva o provedor → faz o stream de um turno completo do coach → gera e verifica um cartão de treino → assegura o que a webview **realmente renderizou** → captura screenshots → reabre entre workspaces e recupera o histórico.

**Os testes atestam os próprios limites:**
Cada cenário E2E carrega `evidence: { realSidecar, limitation }` — **o teste declara aquilo que ele não prova.**

---

## i18n · Oito idiomas

| Idioma | Código | Primário |
|---|---|---|
| 简体中文 | `zh-CN` | ✅ |
| English | `en-US` | ✅ |
| Español | `es-ES` | ✅ |
| Français | `fr-FR` | ✅ |
| Deutsch | `de-DE` | ✅ |
| 日本語 | `ja-JP` | ✅ |
| 한국어 | `ko-KR` | ✅ |
| Português | `pt-BR` | ✅ |

**Cadeia de fallback:** preferência do usuário > `env.language` do VS Code > `zh-CN` (padrão)

**6 overrides por superfície:** `resourceView` / `contextRail` / `trainingUi` / `orientationRail` / `composerAccessibility` / `leftoverHonesty` — tradutores preenchem apenas as superfícies que lhes pertencem, **não a tabela completa de 600+ chaves**.

Código-chave: `extension/webview/src/lib/i18n/copy.ts` (5.283 linhas)

---

## Agradecimentos

> O Trainer se apoia em ombros de gigantes.

### 🏃 Núcleo de runtime

| Projeto | Propósito | Por que é insubstituível |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | Framework do sidecar local | async + Pydantic + docs OpenAPI automáticas |
| [Uvicorn](https://github.com/encode/uvicorn) | Servidor ASGI | HTTP/1.1 + WebSocket + alta concorrência |
| [Pydantic](https://github.com/pydantic/pydantic) | Validação e serialização de dados | o WorkbenchSnapshot de 31 campos roda sobre ele |
| [httpx](https://github.com/encode/httpx) | Cliente HTTP assíncrono | todo o roteamento de protocolos sidecar ↔ gateway de LLM |

### 🤖 Protocolos LLM

| Projeto | Propósito |
|---|---|
| [openai-python](https://github.com/openai/openai-python) | Cliente compatível com OpenAI / Anthropic / Gemini (roteamento de 5 protocolos) |

### 🧠 Treino & memória

| Projeto | Propósito |
|---|---|
| [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs) | Agendamento de revisões na curva de esquecimento do FSRS · alimenta o `TrainingCardState` |
| [qdrant-client](https://github.com/qdrant/qdrant-client) | Recuperação vetorial da memória semântica (com fallback sentence-transformer) |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | Parsing de PDF (preview Tier A da biblioteca) |
| [trafilatura](https://github.com/adbar/trafilatura) | Extração de conteúdo web (ingest de recursos) |
| [markitdown](https://github.com/microsoft/markitdown) | Conversão documento → Markdown (preview Tier B da biblioteca) |

### ⚛️ Núcleo do frontend

| Projeto | Propósito |
|---|---|
| [React](https://github.com/facebook/react) | UI do workbench na barra lateral |
| [Vite](https://github.com/vitejs/vite) | Ferramenta de build + dev server |
| [Zustand](https://github.com/pmndrs/zustand) | Gerenciamento de estado do workbench |
| [Zod](https://github.com/colinhacks/zod) | Validação de tipos em runtime |

### 🎨 Renderização

| Projeto | Propósito |
|---|---|
| [react-markdown](https://github.com/remarkjs/react-markdown) | Renderização de Markdown |
| [remark-gfm](https://github.com/remarkjs/remark-gfm) | Extensões GFM (tabelas, task lists) |
| [remark-math](https://github.com/remarkjs/remark-math) · [rehype-katex](https://github.com/remarkjs/rehype-katex) · [KaTeX](https://github.com/KaTeX/KaTeX) | Renderização de matemática |
| [Shiki](https://github.com/shikijs/shiki) | Destaque de código (gramáticas TextMate do VS Code) |
| [Mermaid](https://github.com/mermaid-js/mermaid) | Diagramas e fluxogramas |
| [@tanstack/react-table](https://github.com/TanStack/table) | Tabelas da biblioteca / fila de treino |

### 📄 Preview

| Projeto | Propósito |
|---|---|
| [mammoth](https://github.com/mwilliamson/mammoth.js) · [docx-preview](https://github.com/VolodymyrBaydalka/docx-preview) | Renderização rica de DOCX (Tier A) |
| PDF.js (empacotado) | Renderização rica de PDF (Tier A) |

### 🧪 Testes & qualidade

| Projeto | Propósito |
|---|---|
| [pytest](https://github.com/pytest-dev/pytest) · [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) | Servidor: 159 arquivos / 1.649 casos |
| [Hypothesis](https://github.com/HypothesisWorks/hypothesis) | Testes de propriedade (planner / evaluator / scheduler) |
| [ruff](https://github.com/astral-sh/ruff) | Lint + format para Python (E/F/I/B, py312, 100 colunas) |
| [pyright](https://github.com/microsoft/pyright) | Checagem estática de tipos para Python |
| [TypeScript](https://github.com/microsoft/TypeScript) | strict mode, zero warnings |
| [Playwright](https://github.com/microsoft/playwright) | E2E + matriz de experiência com 200 cenários |

### 📦 Empacotamento & distribuição

| Projeto | Propósito |
|---|---|
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | Freeze do sidecar em binário único (6 plataformas, manifest com sha256) |

### 💡 Inspiração de metodologia

| Projeto | Inspiração |
|---|---|
| [open-spaced-repetition/fsrs4anki](https://github.com/open-spaced-repetition/fsrs4anki) | O paper original do FSRS e a implementação de referência |
| [obra/superpowers](https://github.com/obra/superpowers) | A disciplina de coaching "workflows obrigatórios, não sugestões" |
| [HKUDS/CLI-Anything](https://github.com/HKUDS/CLI-Anything) | A ambição de "tornar todo software agent-native" |

### 🎨 Ativos visuais

| Projeto | Propósito |
|---|---|
| [dora-image](https://github.com/AI-yyf/trainer/tree/main/assets) | Todas as imagens deste README (veja `assets/MASCOT.md` / `BANNER_PROMPT.md` / `FEATURE_PROMPTS.md`) |
| DeepSeek official moe girl | referência de proporções chibi / tendência cel-shading |
| Pieter Bruegel, *A Torre de Babel* | referência de composição de ensemble com campos esquerda-direita |
| Rembrandt, *A Ronda Noturna* | referência de contraste chiaroscuro 7:1 |
| Studio Ghibli character design | olhos grandes com três pontos de luz, expressões contidas |

---

## Licença

[MIT](LICENSE)

---

## Como citar o Trainer

Se o Trainer ajudou o seu fluxo de trabalho, fique à vontade para citá-lo no seu blog / paper / palestra:

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

**// Treine sua IA · Cresça com sua IA**

`v1.0.3` · Feito com café, FSRS, 24 funções puras, 3.328 testes e um coração que se recusa a escrever código por você.

</div>
