# Lobuddy Domain Context

Lobuddy is a proactive desktop companion that combines emotional presence, recoverable task
execution, local memory, and review-gated capability evolution.

## Language

**Companion Intervention**:
A rate-limited, explainable care message triggered from privacy-filtered local signals.
_Avoid_: Notification, popup

**Companion Check-in**:
A user-authored, time-limited choice of current mood, energy, and desired support.
_Avoid_: Emotion detection, diagnosis, permanent mood memory

**Computer Use Plan**:
A user-authorized, bounded desktop goal with an action budget and recoverable status.
_Avoid_: Macro, automation script

**Desktop Observation**:
A short-lived screen and native-control reading that is deleted or expires before later actions.
_Avoid_: Screenshot record, screen history

**Screen Region Ask**:
A user-initiated visual question over one explicitly selected, expiring screen crop.
_Avoid_: Screen monitoring, automatic screenshot, saved screen history

**Semantic Target**:
A visible desktop element grounded by a label, role, bounds, and evidence source.
_Avoid_: Coordinate, selector

**Action Checkpoint**:
A privacy-safe record binding one input action to its Desktop Observation, Semantic Target, and
expected outcome.
_Avoid_: Log entry, step

**Visual Verification**:
Fail-closed evidence that the outcome recorded before an action is visibly true afterward.
_Avoid_: Success guess, completion message

**Task Run**:
A durable attempt to fulfill one user request, with session attribution, timing, prediction,
ordered progress, outcome, and retry lineage.
_Avoid_: Chat turn, background job

**Run Update**:
An append-only, privacy-safe change in a Task Run such as queued, started, progress, interrupted,
completed, or failed.
_Avoid_: Debug log, transcript

**Work Stage**:
A keyed, dependency-aware unit of privacy-safe progress inside one Task Run, with an estimated
duration, measured elapsed time, and user-visible waiting reason.
_Avoid_: Action Checkpoint, tool log, todo item

**Critical Work Path**:
The longest estimated remaining dependency chain among unresolved Work Stages, used only to
explain likely waiting time.
_Avoid_: Execution guarantee, replay plan, critical score

**Model Usage Evidence**:
Content-free prompt, completion, and cached-token evidence owned by one Task Run. It is either
provider-measured, explicitly locally estimated, or unavailable.
_Avoid_: Cost guess, billing record, prompt log

**Recovery Review**:
A freshness-bound, content-minimized explanation shown before a retry, covering stable Run Updates,
possible prior side effects, expired grants, required fresh inputs, and the safeguards of the new
Task Run.
_Avoid_: Resume prompt, replay plan, retry confirmation

**Structured Memory**:
A sanitized, typed fact or experience retained locally for future conversations.
_Avoid_: Chat history, transcript

**Memory Revision**:
An append-only, content-minimized reason for learning, confirming, correcting, retiring, restoring,
or forgetting a Structured Memory.
_Avoid_: Edit log, chat transcript

**Memory Portability Package**:
A schema-versioned, integrity-checked local export of selected Structured Memory whose imported
contents are untrusted and inactive until the user reviews them.
_Avoid_: Database backup, prompt bundle, chat export

**Grounded Recall**:
A per-task selection of active Structured Memory supported by current-request overlap, prompt
budget, scope, and content-minimized usage evidence.
_Avoid_: Hidden prompt dump, transcript replay, semantic guess

**Memory Recall Receipt**:
An idempotent, content-minimized link between one Structured Memory and the Task Run that used it,
with an optional explicit user judgment.
_Avoid_: Prompt log, response evaluation, automatic confidence update

**Relationship Rhythm**:
A user-visible, content-minimized projection of governed Structured Memory, explicit care
feedback, the current Companion Check-in, and task-grounded pet growth evidence.
_Avoid_: Relationship score, emotion profile, behavior diagnosis

**Personality Evolution**:
An append-only, task-grounded transition between pet personality snapshots that the user may
explicitly restore without downgrading permanent progress.
_Avoid_: User profile, emotion model, capability revocation

**Data Control**:
A current-session, content-minimized projection of what Lobuddy may observe, retain, send to a
configured model, or execute, with narrow actions that revoke each grant or retained surface.
_Avoid_: Permission dump, settings mirror, privacy promise

**Codex Pet Package**:
A validated `pet.json` and spritesheet pair installed in the Codex pet directory and mapped to
Lobuddy's visible work states.
_Avoid_: Skin, avatar image

**Codex Built-in Pet**:
A read-only pet spritesheet already installed inside Codex Desktop, materialized into Lobuddy's
private compatibility cache before it becomes a Codex Pet Package.
_Avoid_: Bundled Lobuddy artwork, copied repository asset, remote catalog item

**Skill Candidate**:
A sanitized capability proposal extracted from successful work and inactive until user approval.
_Avoid_: Self-modification, installed skill

**Skill Evaluation**:
A content-addressed, deterministic report produced from an isolated package projection without
executing candidate instructions or accessing the network.
_Avoid_: Runtime sandbox, confidence score

**Skill Behavior Simulation**:
A deterministic, side-effect-free replay of a Skill Candidate's declared tool plan using synthetic
receipts for permitted, refused, and unknown tools.
_Avoid_: Skill execution, fake end-to-end test, runtime sandbox

**Skill Candidate Revision**:
An immutable, sanitized version of a Skill Candidate's proposed content, used for exact evaluation
binding and human-readable comparison before approval.
_Avoid_: Installed skill version, mutable draft buffer

## Relationships

- A **Computer Use Plan** contains zero or more **Action Checkpoints**.
- Every executed **Action Checkpoint** belongs to exactly one fresh **Desktop Observation**.
- A **Desktop Observation** exposes zero or more **Semantic Targets**.
- A **Screen Region Ask** uses only its explicit crop, never a hidden full-screen
  **Desktop Observation**.
- A **Screen Region Ask** crop is deleted after task completion, cancellation, replacement,
  expiry, or shutdown and is never written into conversation or **Structured Memory** storage.
- A successful **Action Checkpoint** requires **Visual Verification** before another action.
- A **Task Run** has one or more ordered **Run Updates**.
- Admitting a Task Run to the serial queue atomically reserves exactly one worker. A worker cannot
  become idle while admitted work exists, and concurrent enqueue never creates competing workers.
- Every admitted Task Run receives a terminal outcome. Queue clear or application shutdown
  safe-stops both active and waiting Task Runs; it never silently drops them.
- A Task Result belongs to exactly one Task Run. A foreign result is rejected before persistence;
  the current run receives a content-free controlled failure and the other run remains untouched.
- A safe-stopped Task Run is `cancelled`, not failed. It creates an interrupted Run Update,
  remains explicitly retryable, and does not trigger failure-oriented Companion Intervention.
- A **Task Run** has zero or more **Work Stages** projected from keyed Run Updates. Their
  dependency keys are immutable, must refer to earlier Work Stages in the same Task Run, and
  cannot form a cycle.
- A **Work Stage** cannot run or succeed until every dependency has succeeded. Waiting and failed
  stages may be retried through new Run Updates without erasing earlier evidence.
- A **Work Stage** records only a safe label, status, dependencies, timing, and bounded detail.
  Tool arguments, raw results, commands, file contents, and screen pixels never enter it.
- A **Critical Work Path** is recalculated from current dependency and timing evidence. It may
  explain an estimate but never authorizes execution or promises a completion time.
- Provider-reported **Model Usage Evidence** wins over local estimation. An estimate remains
  labeled as an estimate; unavailable usage is never displayed as a measured zero.
- Cached tokens are a subset of prompt tokens and are not added to total tokens. Tool-result
  text already included by the provider is not counted a second time.
- **Model Usage Evidence** belongs to exactly one Task Run. Session totals and future Task Run
  budgets are derived views; no prompt, response, tool argument, or price is stored in it.
- Monetary cost is unavailable unless an explicit, versioned price source is configured.
  Lobuddy does not guess a currency amount from a model name.
- A retry creates a new **Task Run** linked to the prior attempt; it never mutates or silently
  replays the prior attempt.
- An interrupted **Task Run** is safe-stopped after restart and requires an explicit retry.
- Every retry requires a current **Recovery Review** and an explicit acknowledgement. If its
  Task Run, Computer Use Plan, Action Checkpoint, tool trace, or approval evidence changes, the
  review becomes stale and must be regenerated.
- A **Recovery Review** may explain prior evidence but never converts it into replay instructions.
  The new Task Run receives new Computer Use Plans, fresh Desktop Observations, and new grants.
- Computer Use Plans belong to exactly one Task Run. Process restart and recovery both revoke
  active grants without deleting Action Checkpoints.
- A **Companion Intervention** may use preferences derived from explicit feedback,
  not screen content.
- A **Companion Check-in** may influence companion tone and suppress proactive care, but it is
  never inferred from a **Desktop Observation**.
- Only the latest **Companion Check-in** may be retained; it expires automatically and can be
  revoked immediately. Privacy mode keeps it in memory only.
- A **Structured Memory** has zero or more ordered **Memory Revisions**.
- A **Memory Revision** may retain hashes and reasons after permanent forgetting, but never the
  forgotten content.
- A **Memory Portability Package** contains only portable Structured Memory fields. It excludes
  chat, source sessions and messages, Task Runs, screen pixels, known credential patterns,
  last-use evidence, and forgotten content.
- Importing a **Memory Portability Package** creates new local IDs and append-only Memory
  Revisions in one atomic write. Every imported Structured Memory starts in review state and
  cannot enter Grounded Recall until the user confirms it.
- A **Memory Portability Package** is size- and count-bounded, integrity-checked before preview,
  rechecked before import, and idempotent by content fingerprint. Privacy mode refuses the write.
- A **Grounded Recall** contains only active, unexpired, scope-compatible **Structured Memory**;
  the current request or correction always wins.
- A **Memory Recall Receipt** stores only Task Run and session IDs, memory ID and type, a bounded
  selection reason, contributed character count, the selected memory-version timestamp, event
  timestamps, and explicit feedback. It never stores the request, response, memory content, tool
  result, or screen evidence.
- Each Structured Memory has at most one **Memory Recall Receipt** per Task Run. Conversation
  summaries are not reviewable Structured Memory and do not receive a receipt.
- “Helpful” and “not relevant” feedback are final evidence about one receipt. They never silently
  alter Structured Memory content, confidence, lifecycle state, or future permissions.
- Explicit “inaccurate” feedback atomically records the receipt judgment, pauses the Structured
  Memory in review state, and appends a content-minimized Memory Revision. It never invents a
  correction or restores itself automatically.
- If Structured Memory changed after the Task Run, the old receipt remains visible but cannot
  mutate or evaluate the newer version.
- A **Relationship Rhythm** may summarize Structured Memory and Memory Revisions, but creating or
  correcting a memory still crosses the governed memory write Interface.
- A **Relationship Rhythm** may show explicit care feedback and the latest Companion Check-in,
  never observations or inferred emotions. Muting, snoozing, and Check-in state remain revocable.
- Pet growth in a **Relationship Rhythm** is task evidence about the companion, never a
  description of the user. It may open real **Personality Evolution** history and restoration.
- Each successful task creates at most one **Personality Evolution** revision by task ID. A
  revision retains only task ID, difficulty, trait deltas, counters, snapshots, and a minimized
  reason; it never retains task input or result content.
- Restoring **Personality Evolution** appends a new revision and changes only personality traits
  and their evidence counters. Level, EXP, appearance, and unlocked abilities remain permanent.
- Privacy mode or disabled memory injection produces no **Grounded Recall**. Its visible evidence
  contains counts and types, never memory titles or content.
- **Data Control** reports policy, counts, and expiry only; it never reproduces conversation,
  **Structured Memory**, screen pixels, typed text, or secrets.
- Privacy mode in **Data Control** suppresses **Grounded Recall**, long-term memory writes, detailed
  foreground-app observation, and **Skill Candidate** extraction. Local chat retention remains an
  independent, explicitly visible choice.
- Revoking a **Computer Use Plan** through **Data Control** pauses active plans and clears their
  authorization without deleting **Action Checkpoints** or **Task Runs**.
- Clearing a Screen Region Ask through **Data Control** deletes only temporary selected pixels.
  Clearing chat removes only persisted messages; **Structured Memory** remains separately governed.
- A **Codex Pet Package** may express all nine standard Codex atlas actions. Lobuddy maps waiting,
  execution, review, success, failure, click greeting, and growth celebration without changing
  the underlying task state.
- A **Codex Built-in Pet** is discovered from a bounded local ASAR index. Lobuddy never edits the
  Codex installation or commits its artwork; activation still requires a local package with path,
  byte-size, image-magic, atlas-dimension, and full-decode validation.
- A **Skill Candidate** may use sanitized workflow evidence but never private **Structured Memory**.
- Every approved **Skill Candidate** requires a passing **Skill Evaluation** for its exact content
  hash; changing the proposal makes the old evaluation stale.
- Every automatic **Skill Candidate** must pass a **Skill Behavior Simulation** that covers its
  declared tools, an ordered terminal verification, and synthetic refusal for side-effectful tools.
- A **Skill Behavior Simulation** never invokes a real tool Adapter, reads a file, writes a file,
  runs a command, or opens a network connection.
- Every content change creates a new **Skill Candidate Revision**; a **Skill Evaluation** belongs to
  exactly one revision, and approval always targets the latest revision.

## Example dialogue

> **Dev:** “Can the Agent click the save button from coordinates it remembered?”
> **Domain expert:** “No. It needs a fresh **Desktop Observation**, must bind the click to a
> **Semantic Target**, and cannot continue until **Visual Verification** closes that
> **Action Checkpoint**.”

> **Dev:** “Can we use the image from a community pet card directly?”
> **Domain expert:** “Not as an avatar image. Adopt it as a validated **Codex Pet Package**, then
> map its standard animation rows to Lobuddy's work states.”
>
> **Dev:** “Can Lobuddy ship a copy of the pets found inside my Codex installation?”
> **Domain expert:** “No. A **Codex Built-in Pet** stays a read-only local source. Lobuddy may
> materialize a validated private cache for use on this machine, but it does not modify Codex or
> add that artwork to the repository.”
>
> **Dev:** “Can restoring an older companion personality remove a previously unlocked ability?”
> **Domain expert:** “No. **Personality Evolution** restoration only appends a personality
> snapshot transition. Permanent level, EXP, appearance, and ability progress are unchanged.”

> **Dev:** “Can permanent forgetting keep the old sentence so the timeline looks complete?”
> **Domain expert:** “No. The **Memory Revision** keeps the reason and content hashes, while the
> forgotten **Structured Memory** content is removed.”
>
> **Dev:** “Can an imported memory immediately enter the next prompt because its package says it
> was active?”
> **Domain expert:** “No. A **Memory Portability Package** is untrusted input. Imported content
> receives a new ID, loses original conversation provenance, and waits for explicit confirmation
> before it can participate in **Grounded Recall**.”
> **Dev:** “Can a short question receive every old memory because the prompt still has room?”
> **Domain expert:** “No. **Grounded Recall** still requires current-request evidence, active
> lifecycle state, matching scope, and one shared prompt budget. The UI only shows what types and
> how many memories were used.”

> **Dev:** “Can Lobuddy automatically run an unfinished task again after the app restarts?”
> **Domain expert:** “No. The old **Task Run** receives an interrupted **Run Update**. An explicit
> **Recovery Review** must explain prior evidence and revoked grants before an acknowledged retry
> creates a linked new **Task Run**, so side effects are never silently repeated.”
>
> **Dev:** “Can closing the app just remove tasks that were still waiting in the queue?”
> **Domain expert:** “No. Every admitted **Task Run** receives an explicit safe-stop outcome.
> Waiting and active work become cancelled, not failed, and nothing is silently replayed.”
>
> **Dev:** “Can the UI infer a dependency because two tool calls happened one after another?”
> **Domain expert:** “No. A **Work Stage** dependency must be explicit and persisted. Sequence
> alone is not dependency. The **Critical Work Path** explains only those recorded relationships.”

> **Dev:** “Can we show a price by looking at the configured model name?”
> **Domain expert:** “No. First preserve **Model Usage Evidence** and its source. Without an
> explicit versioned price source, show measured or estimated tokens—not a guessed currency.”

> **Dev:** “Can one ‘not relevant’ click lower the memory’s confidence automatically?”
> **Domain expert:** “No. A **Memory Recall Receipt** describes one Task Run. Only explicit
> ‘inaccurate’ feedback pauses that Structured Memory; correction and confirmation remain
> user-governed actions.”

> **Dev:** “The candidate has high model confidence. Can we enable it immediately?”
> **Domain expert:** “No. Confidence explains the proposal source; approval still needs a
> content-matched **Skill Evaluation** and an explicit user decision. The evaluation projects the
> package in isolation but does not execute its instructions.”

> **Dev:** “Can we run the candidate once in a temporary folder to see if it works?”
> **Domain expert:** “No. Use a **Skill Behavior Simulation** with synthetic tool receipts. It can
> prove declared ordering, refusal handling, and terminal verification without executing the
> candidate or granting filesystem, command, computer-control, or network capability.”

> **Dev:** “The proposal changed after review. Can the old green report still approve it?”
> **Domain expert:** “No. Save a new **Skill Candidate Revision**, show the line-level difference,
> and require a **Skill Evaluation** bound to that latest revision.”

> **Dev:** “The user has kept an editor open for an hour. Can we mark them as stressed?”
> **Domain expert:** “No. A **Desktop Observation** can support a rest reminder, never an emotion
> claim. Mood and desired support only come from a user-authored **Companion Check-in**.”

> **Dev:** “Can a quick visual question reuse the last Computer Use screenshot?”
> **Domain expert:** “No. Start a **Screen Region Ask** from a crop the user selects now. Its
> pixels expire independently and do not grant permission for any computer action.”

> **Dev:** “Can the privacy indicator just say everything is private?”
> **Domain expert:** “No. Open **Data Control** and explain each effective surface. Privacy mode may
> stop memory and learning while local chat retention remains enabled, so that distinction must be
> visible and independently revocable.”

## Flagged ambiguities

- “step” previously meant both an intended action and persisted evidence; use
  **Action Checkpoint** only after an action attempt has been recorded.
- “memory” previously included chat history; **Structured Memory** is sanitized, typed, and
  independently governed.
- “memory backup” may imply a restorable database image; a **Memory Portability Package** is a
  bounded, review-gated content transfer and never restores internal IDs or provenance.
- “memory context” previously implied an authoritative dump; **Grounded Recall** is a bounded,
  fallible selection whose evidence never exposes memory content.
- “memory feedback” means an explicit judgment on one **Memory Recall Receipt**, not an inferred
  reward signal, hidden response score, or permission to rewrite Structured Memory.
- “relationship trend” may imply a score or inferred profile; **Relationship Rhythm** only
  projects explicit, separately governed evidence and its current limitations.
- “history” in the memory console means ordered **Memory Revisions**, not conversation history.
- “task” names the user request; **Task Run** names one concrete attempt to fulfill it.
- “progress” shown to users comes from ordered **Run Updates**, not transient UI strings.
- “step” in a task card means a projected **Work Stage**; it is not an Action Checkpoint and does
  not retain tool arguments or desktop evidence.
- “critical path” means the current **Critical Work Path** estimate, not permission to execute,
  replay, or skip approval.
- “model usage” means per-Task Run **Model Usage Evidence**. “Measured” is reserved for provider
  evidence; local tokenization is always shown as an estimate.
- “continue” after failure means a reviewed, linked new Task Run; a **Recovery Review** never
  resumes the old process or reuses its grants.
- “skill sandbox” can imply command execution; the current **Skill Evaluation** is intentionally
  non-executing package and policy evaluation.
- “skill behavior test” may imply real execution; **Skill Behavior Simulation** only replays a
  declared tool plan with synthetic receipts and cannot prove third-party runtime compatibility.
- “skill version” may mean an installed SkillRecord version; use **Skill Candidate Revision** for
  pre-approval proposal changes.
- “Codex pet” may mean a public catalog listing or an installed package; only a validated,
  locally installed **Codex Pet Package** may drive the desktop companion.
- “user state” may mean observed activity or explicitly shared feelings; only a
  **Companion Check-in** may carry mood and support intent.
- “look at my screen” may mean a one-off **Screen Region Ask** or an authorized
  **Desktop Observation**; neither implies permission to perform an action.
- “privacy” may mean session-level memory suppression or deletion of retained data; **Data Control**
  must show those as separate states and actions.
