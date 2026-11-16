# Product Contract (locked)

Trainer is a long-term technical learning coach:

- understands the technology the learner is studying, the project, files and errors;
- explains, guides practice, verifies real results, records trustworthy evidence;
- drives review and long-term skill growth;
- connects browser material, project files, conversation and learning plans.

## Two core engines

Trainer is not a workflow tool, a generic chat client, or a quiz bank. It has two
core engines that share one memory, one long-term goal, one material library and
one evidence record:

- **Teaching Engine** — diagnoses current understanding, chooses an explanation
  strategy for this learner and this knowledge type, asks questions that expose
  real understanding, gives hints in steps instead of complete answers, designs
  inline checks and exercises, reads errors and gaps, adjusts difficulty from
  evidence, and schedules recall and transfer.
- **Preparation Engine** — defines the research questions for an important
  learning target, gathers and compares sources, judges recency and reliability,
  extracts concepts and prerequisites, maps differences between sources, names
  the remaining gaps, designs the teaching order, prepares explanations,
  analogies, misconceptions and acceptance criteria, and proposes plan updates.

The working order is **research → prepare → teach → verify**. Trainer must not
generate large teaching content without preparation behind it, and must state
honestly which part of a claim is sourced, which is its own inference, and which
is still unverified.

ReThink Fund is one teaching strategy among many. Trainer selects by knowledge
type, learner state and stated preference among: ReThink Fund, first principles,
concept-first, example-first, Socratic questioning, stepwise hints, guided
practice, independent challenge and transfer. When the learner explicitly asks
for a direct explanation, explain directly. When the learner has an urgent
blocker, help them get unblocked before prescribing practice.

## Long-term plan and goal governance

- Goals are micro-goals inside the long-term learning plan, not an isolated
  small-task mode. A micro-goal carries its knowledge point, prerequisites,
  expected mastery, key questions, teaching method, acceptance criteria, linked
  materials, evidence and next step.
- Every conversation considers the long-term plan, but no conversation silently
  changes it. Trainer proposes a plan change only on a real gap, prerequisite
  change, direction change or acceptance result, and shows the change and its
  reason for explicit learner confirmation.
- Mastery is never inferred from the learner's self-claim. Only the existing
  verification and evidence paths can attest capability.

## Learning scope

Learning answers three questions and nothing else: progress, quick practice,
long-term plan. Growth evidence is a detail inside progress; it is not a
separate product destination. Practice happens in the Learning conversation
stream with the same message components as Coach; there is no separate complex
training console. The long-term plan distinguishes must-master core knowledge,
extension knowledge and optional research directions, and makes prerequisites,
milestones and stage acceptance criteria visible.

## Training card governance

Two different objects must never be conflated:

- **Instant practice** — the learner asks for a question and gets one inline in
  the conversation. It does not create a permanent training card, does not enter
  the card library, does not change the long-term plan, and is evaluated in the
  same conversation. The learner may explicitly ask to keep it.
- **Formal training card** — a designed, reviewed asset. Candidates can come
  from goal teaching, plan preparation or resource research. A candidate must be
  reviewed and accepted by the learner before it enters the formal library. The
  lifecycle is candidate → learner review → formal library → select/schedule →
  practice → acceptance and evidence → mastered / retrain / archive.

A learner request for practice is not authorization to create a formal card.
The learner decides which cards are worth keeping; the system may propose
candidates but never promote them on its own.

## Resources scope

Resources is Trainer's research and preparation center, not only a library. The
resource tree, reader, versions and hashes stay. The resource composer performs
search, reading, comparison, extraction, synthesis, research-gap discovery,
organization, lesson preparation and plan-advice requests without a mode menu.
Completed research and preparation is stored as a traceable **Research Brief**
library asset: research goal, key questions, sources and citations, findings,
source disagreements, concepts and prerequisites, knowledge structure, teaching
order, explanation strategy, examples and analogies, misconceptions, check
questions, acceptance criteria, open questions and follow-up research. Every key
conclusion points at its resource, version and location; sourced claims, model
inference and unverified assumptions stay distinguishable.

## Skills and entry points

Skills are organized into two domains — Teaching and Preparation — and are
selected and combined by Trainer automatically. The learner is not required to
open a skill or workflow menu. Typed `/` shortcuts remain for experienced users
as an accelerator, not as the primary interaction. User-visible workflow feature
entries are removed; internal execution, confirmation and reliability mechanisms
remain.

Hard boundaries:
- Not an autonomous coding agent. It never ghost-writes business code by default.
- No Coach/Pair/Agent triple execution modes.
- No silent modification of the user's project; writes follow explicit workspace authority.
- Three permanent destinations: Coach, Learning, Resources. Training is a Learning context; Progress belongs to Learning; Settings/History are utilities.
- Local Brain + Remote Hands: identity/memory/plans/evidence stay local; remote work goes through the WorkspaceGateway/Companion with local-only credentials.

## Shared composer

- The Coach, Learning and Resources work contexts use the same composer. Settings and History are utilities.
- The input routes explicit practice, recall, verification and library actions. It shows a confirmation before changing a plan or moving or deleting library entries.
- Drafts and source references retain workspace and session scope. Training answers additionally retain card scope. Coach, Learning and Resources use separate conversation histories within the workspace session.
- Browser capture stages a page or selected text for the visible work context and requires its receipt before draining the queue. A separate learner submission starts model work.
- Queued captures keep the workspace they were created for. New captures follow explicit host focus, and a stopped workspace resumes its queue when it returns.
- Learning reads activity and review timing from persisted records. Only the existing verification and evidence paths can attest capability.
