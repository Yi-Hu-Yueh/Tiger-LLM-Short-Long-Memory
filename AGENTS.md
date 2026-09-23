# Tiger Short/Long Memory - Codex Project Instructions

## Mandatory Memory Governance

Before analyzing, modifying, testing, or reviewing any memory-related behavior in this repository, you MUST read all three approved governance files completely:

1. `MEMORY_CONSISTENCY_SPEC.md` — consistency invariants.
2. `MEMORY_SEMANTIC_CONTRACTS.md` — semantic state and mutation contracts.
3. `MEMORY_ACCEPTANCE_SUITE.md` — authoritative acceptance policy.

This requirement applies to any work involving:

- short-term conversation context
- current long-term memory
- historical memory
- stable memory IDs
- ADD / UPDATE / DELETE / NOOP
- Pending Memory Proposal
- Confirm / Cancel
- personal-memory queries
- memory rendering
- memory consistency
- user/session isolation
- persistence
- migration
- revision handling
- fail-closed behavior
- memory firewall
- DeepSeek memory prompts
- memory-related UI behavior

All three are `APPROVED_PROJECT_GOVERNANCE`. Their responsibilities differ, and none may be silently ignored.

For any architecture, schema, migration, runtime, prompt, validation, proposal, history, rendering, or test implementation task involving typed memory, Codex MUST also read `MEMORY_IMPLEMENTATION_GAP_PLAN.md` completely and calculate its fresh SHA256 before editing. The plan is `APPROVED_IMPLEMENTATION_PLAN` for the typed engine, schema, persistence architecture, implementation history, and sequencing where it has not been superseded; it is not governance and never outranks the three documents above.

For any task that changes or reviews the model-facing protocol, Semantic IR, deterministic compiler, prompt/schema boundary, or DeepSeek semantic output structure, Codex MUST also read `MEMORY_LLM_BOUNDARY_SIMPLIFICATION_PLAN.md` completely and calculate its fresh SHA256 before editing. That document is `APPROVED_BOUNDARY_SIMPLIFICATION_PLAN`. It supersedes `MEMORY_IMPLEMENTATION_GAP_PLAN.md` only where the older plan specifies the model-facing 13-key protocol or assigns deterministically derivable internal protocol work to DeepSeek. It does not supersede behavioral governance or the approved typed canonical engine/persistence architecture.

## Mandatory Architecture D Governance

Any future work on Semantic IR v2, source grounding, claim-shape compilation, Count/Set authority, Slot Registry, entity identity, deterministic risk classification, semantic-write confirmation, immutable proposal identity, or the model-facing write boundary MUST first read and apply `POLICY-15` through `POLICY-23` in all three approved governance documents. Such work MUST report the affected grounding, claim-shape, ontology, risk, semantic-confirmation, and benchmark contract IDs in addition to the normal invariant, semantic-contract, and acceptance-case evidence.

Architecture D requires the ordered boundary `Semantic IR v2 constrained slot/entity extraction -> structural validation -> application-owned unique exact literal resolution -> exact source-grounding validation -> Slot Registry resolution -> deterministic claim-shape compiler -> Architecture B typed-precondition resolver -> deterministic Risk Engine -> AUTO_COMMIT_ALLOWED atomic commit or HUMAN_REVIEW_REQUIRED Pending Semantic Confirmation -> local Confirm/Correct/Cancel -> atomic commit`. For ontology-managed explicit literal operands, the model selects the exact non-empty `claimed_literal`; the application MUST derive the authoritative current-turn, zero-based, half-open Python/Unicode-code-point `source_start/source_end` only when that exact literal occurs exactly once. Zero occurrences MUST fail closed as `LITERAL_NOT_FOUND`; multiple occurrences MUST fail closed as `LITERAL_AMBIGUOUS`; the application MUST NOT choose the first occurrence. Model-authored offsets are not authoritative for ontology constrained IR. Codex MUST NOT compile an explicit literal operand unless this application-derived span passes exact validation. Grounding MUST NOT use fuzzy matching, Unicode/case/punctuation/whitespace normalization, translation, aliases, keyword rules, NLP interpretation, regex semantic inference, inferred spans, prefix/suffix repair, retry, a second or judge model, or external knowledge unless later approved governance expressly changes that rule.

Grounding proves provenance, not semantic correctness. A wrong-but-exact model-selected literal may resolve uniquely and pass grounding while remaining a model-semantic error candidate; Codex MUST NOT automatically correct, expand, trim, or otherwise rewrite it. Each required operand resolves independently, and any unresolved or ambiguous operand fails the entire executable changed write closed without partial grounding.

For `CARDINALITY_ASSERTION` only, the model-selected exact `claimed_literal` MAY be either the numeral token itself or the exact contiguous numeral-plus-directly-associated-classifier quantity phrase when that selection preserves the asserted cardinality represented separately by model-semantic `canonical_value` (for example `五` or `五位`). This is a model/human-oracle semantic judgment, not an application parser rule. The application MUST preserve the selected literal exactly and MUST NOT strip classifiers, normalize, expand, repair, or deterministically decide that two such strings express the same number. This narrow allowance does not authorize arbitrary surrounding noun phrases and does not apply to Scalar/Record boundaries such as R05 `色。`.

Any required grounding failure MUST fail closed before compilation and leave Current, History, revision, Proposal, and failed-turn persistence unchanged. Default diagnostics MUST NOT expose raw user text, raw operands, source slices, API secrets, or a full IR payload.

Codex MUST stop on an unresolved Architecture D governance conflict. Codex MUST NOT implement or enable Semantic IR v2 unless the current on-disk hashes of the approved governance documents have been freshly calculated and the documents contain a mutually consistent approved Architecture D state. Semantic IR v1 remains a manual deployment/configuration rollback path only until separately retired; it MUST NOT be an automatic per-turn fallback.

## Mandatory Slot Registry, Risk, and Semantic Confirmation Governance

`POLICY-18 — Risk-Classified Model-Derived Semantic Writes` establishes this HARD application guarantee:

> **NO MODEL-DERIVED SEMANTIC WRITE ENTERS CURRENT WITHOUT EITHER DETERMINISTIC LOW-RISK AUTHORIZATION OR EXPLICIT HUMAN CONFIRMATION.**

Every fully validated model-derived candidate that would change authoritative Current MUST be classified by the application-owned deterministic Risk Engine. `AUTO_COMMIT_ALLOWED` is permitted only for a registry-approved slot/operation after every `POLICY-21` condition passes; `HUMAN_REVIEW_REQUIRED` is the default and uses the existing user/session/base-revision-bound Pending Semantic Confirmation path. Model confidence, prose, or self-reported risk MUST NOT authorize commit. Confirm and Cancel require zero provider calls. A deterministic structured Correct MAY remain local and zero-call, but it MUST create a new immutable payload or version identity; natural-language correction is a new semantic turn and MAY use that turn's single provider call.

Proposal purpose and destructive effect are distinct. The proposal representation MUST explicitly expose `purpose=SEMANTIC_CONFIRMATION` and `destructive=true|false`, or an equally explicit representation. One fully rendered proposal and one explicit Confirm MAY simultaneously confirm the interpretation and authorize destructive effects; a mandatory double-confirm flow requires a later governance decision. `NOOP`, `READ`, `TARGET_NOT_FOUND`, `ABSTAIN`, `FREEFORM`, and incomplete `CLARIFY` do not create semantic-write proposals.

Production proposal auto-confirm is forbidden. `AUTO_COMMIT_ALLOWED` is a separate deterministic risk route, not auto-confirm, and remains disabled for every production slot until the frozen benchmark passes and a separate implementation task explicitly enables eligible policies. An automated acceptance harness MAY resolve a `HUMAN_REVIEW_REQUIRED` proposal only after independently verifying exact equality with the complete expected proposal oracle, and that path MUST be test-only and unreachable from production.

`POLICY-19 — Immutable Semantic Proposal Payload Identity` requires normalized persisted canonical fields, not an alternative inferred or duplicate payload representation. A typed CREATE proposal allocates and persists its final application-generated `memory_id` at proposal creation; ontology-managed proposals also persist registry-derived `slot_id`, `registry_version`, applicable `entity_id`, `semantic_key`, and `display_label` plus exact state/operation/arguments, purpose, destructive flag, payload version, scope, and base revision. `target_memory_id` remains NULL for CREATE. Confirm MUST use that persisted payload without regenerating identity, metadata, operands, or semantics.

`POLICY-20` makes the immutable/versioned Canonical Slot Registry application-owned. For ontology-managed slots, the model selects a supplied canonical `slot_id` or `UNKNOWN_SLOT`; it MUST NOT authoritatively generate free-form `semantic_key` or `display_label`. The application derives typed family, value type, allowed operations, canonical `semantic_key`, `display_label`, and risk policy. Stable `memory_id` remains lineage identity, `slot_id` is semantic schema, and application-generated `entity_id` identifies a real-world instance. Ordinals such as first/second/third are not entity IDs.

Registry version `1` exact display labels are governed by the authoritative table in `MEMORY_CONSISTENCY_SPEC.md`. Implementations MUST use exact lookup: `semantic_key` equals the canonical `slot_id`, and `display_label` equals the Registry-v1 table value. Runtime translation, algorithmic derivation from slot text, user-prose derivation, fuzzy/alias matching, and model-generated replacements are forbidden. Changing any canonical label requires an explicit registry-version/governance change. Entity names remain separate presentation data and MUST NOT be embedded in a generic slot definition.

`UNKNOWN_SLOT`, ontology extension, ambiguous target/entity, destructive operations, semantic correction, representation or state-family transitions, conflicting state, unsupported operations, and record-schema uncertainty MUST NOT auto-commit. Registry self-modification is forbidden. Default risk output is always `HUMAN_REVIEW_REQUIRED`; no model confidence may authorize commit.

Before production auto-commit is enabled, the model, parameters, prompt, registry/version, risk rules, held-out dataset, and procedure MUST be frozen. DeepSeek v4 Pro is benchmarked first. The benchmark requires at least 600 preregistered auto-eligible turns, zero unsafe auto-commits, zero forbidden-risk auto-commits, slot/operand/protocol error each at most 1%, Human Review at most 35%, and safe automatic completion at least 65%.

> After the frozen ontology/risk benchmark, if ANY unsafe auto-commit occurs, any forbidden-risk write auto-commits, or at least 65% safe automatic completion cannot be achieved without weakening safety rules, the project MUST STOP pursuing automatic semantic memory and retain only Human-Reviewed Memory mode. The held-out dataset and thresholds MUST NOT be changed, thresholds relaxed, or ad-hoc prompt exceptions added after results are observed. A materially new architecture or model requires a separately approved evaluation.

`POLICY-23 — Post-Benchmark Human-Reviewed Product Mode` is now ACTIVE for the current model/architecture. The frozen run `freeze-v1.2-6fb6d482f9b2142c53ca` was permanently locked at ordinal 122 after `HB-OFFICE-100` produced one validated `AUTO_ELIGIBLE` semantic mismatch and therefore one `unsafe_auto_commit`. For this current architecture/model, production `AUTO_COMMIT_ALLOWED` is superseded and MUST NOT be reachable. Every model-derived changed write that survives structure/grounding/ontology/preconditions MUST route to `HUMAN_REVIEW_REQUIRED` and an immutable Semantic Confirmation Proposal; deterministic `NOOP`, `TARGET_NOT_FOUND`, `READ`, `CLARIFY`, `FREEFORM`, `ABSTAIN`, and other governed non-write/fail-closed outcomes remain non-write. The Risk Engine remains useful as a deterministic guardrail and explanation layer, but it cannot authorize production auto-commit under this product mode. Re-enabling automatic semantic memory requires a materially new architecture or model, a separate governance approval, and a new independently frozen benchmark; it cannot reinterpret or erase the archived failed run.

Any work on the retained product MUST identify itself as `HUMAN_REVIEWED_MEMORY_ASSISTANT`. Benchmark execution for the archived automatic path is read-only/locked. Code that adds, enables, or exposes production auto-commit for the current architecture/model is a governance violation and MUST be rejected before implementation.

Any rendered-proposal/commit-payload mismatch MUST fail closed. Future implementation MUST NOT invent another proposal payload representation or begin runtime work until the current governance hashes, including `POLICY-19`, are approved.

## Required Pre-Work Check

Before changing any memory-related file, you MUST:

1. Read `AGENTS.md` completely.
2. Read all three governance documents completely.
3. Calculate and record SHA256 for all three governance documents.
4. Identify affected invariant IDs, semantic contract IDs, and acceptance case IDs.
5. Detect governance conflicts before editing.
6. Classify the task.
7. Stop and report a blocker before implementation if a governance conflict remains unresolved.

For a relevant typed-memory implementation task, additionally:

8. Read `MEMORY_IMPLEMENTATION_GAP_PLAN.md` completely.
9. Calculate and record its SHA256.
10. Identify affected implementation phase(s).

For a relevant Semantic IR/compiler/model-boundary task, additionally:

11. Read `MEMORY_LLM_BOUNDARY_SIMPLIFICATION_PLAN.md` completely.
12. Calculate and record its fresh SHA256.
13. Identify the affected boundary-plan phase(s), model responsibilities, application-derived responsibilities, and compiler mappings.
14. Confirm that semantic repair is not introduced and record the manual rollback-path status.
15. Identify every affected `MSC-GROUND-*`, `MSC-CLAIM-*`, and Count/Set single-authority contract.
16. Verify all required explicit literal operands are structurally and exactly grounded before compilation.
17. Verify the current governance hashes reflect the approved Architecture D state before implementing IR v2.
18. Verify every model-derived changed transition routes through the deterministic Risk Engine; every auto route satisfies all low-risk requirements; every other changed write routes to Human Review; production proposal auto-confirm is absent; and rendered proposal identity equals the confirm payload.
19. Report every affected `MSC-ONTOLOGY-*`, `MSC-RISK-*`, and benchmark/STOP contract plus ontology/risk acceptance IDs.

Do NOT modify memory behavior first and reconcile the specification afterward.

## Prohibited Memory Design Regressions

Unless `MEMORY_CONSISTENCY_SPEC.md` is explicitly revised first, you MUST NOT reintroduce:

- free-text memory identity
- regex-based subject identity
- Chinese copula parsing for identity
- substring/value-overlap identity
- semantic string reconciliation in Python
- complete-memory snapshot replacement
- heuristic reconstruction of omitted memories
- another LLM call for semantic repair
- parser-based fixes for individual conversational examples

## Change-Control Rule

For every memory-related code change:

1. Name the affected invariant(s).
2. Preserve all unrelated invariants.
3. Add or update regression tests.
4. Prefer structural/state-machine fixes over one-example prompt patches.
5. Fail closed when a safe state transition cannot be determined.

If the requested behavior requires changing an invariant, update
`MEMORY_CONSISTENCY_SPEC.md` first and clearly report the specification change.

## Mandatory Pre-Work Hash Evidence

For every memory-related task, before editing any memory-related file run:

```powershell
Get-FileHash .\MEMORY_CONSISTENCY_SPEC.md -Algorithm SHA256
Get-FileHash .\MEMORY_SEMANTIC_CONTRACTS.md -Algorithm SHA256
Get-FileHash .\MEMORY_ACCEPTANCE_SUITE.md -Algorithm SHA256
```

For a relevant typed-memory implementation task, also run:

```powershell
Get-FileHash .\MEMORY_IMPLEMENTATION_GAP_PLAN.md -Algorithm SHA256
```

For a relevant Semantic IR/compiler/model-boundary task, also run:

```powershell
Get-FileHash .\MEMORY_LLM_BOUNDARY_SIMPLIFICATION_PLAN.md -Algorithm SHA256
```

Never hardcode these hashes as permanent expected values. Calculate them afresh on every task.

# Verification Evidence

For every memory-related task, before editing any memory-related file, Codex MUST:

1. Read `AGENTS.md` and all three governance documents completely.
2. Run all three mandatory hash commands from the repository root.
3. Record every actual SHA256 returned.
4. Identify every affected specification invariant, using IDs such as:
   - INV-01
   - INV-05
   - INV-11
   - etc.
5. Identify every affected semantic contract ID and acceptance case ID.
6. Determine whether the requested task conflicts with any approved governance document.
7. Classify the requested change before editing code.

The allowed classifications are:

1. Implementation fix that preserves the current specification.
2. Specification-changing behavior.
3. Model-semantic limitation with no safe deterministic implementation fix.

Codex MUST NOT modify any memory-related code before completing these pre-work checks.

If any approved governance document is:

- missing,
- unreadable,
- malformed,
- internally contradictory for the requested task,
- or disagrees with another governance document or directly conflicts with the requested change,

Codex MUST STOP and report a blocker before modifying any code.

# Governance Authority and Conflict Rule

- `MEMORY_CONSISTENCY_SPEC.md` is authoritative for consistency invariants.
- `MEMORY_SEMANTIC_CONTRACTS.md` is authoritative for semantic state and mutation contracts.
- `MEMORY_ACCEPTANCE_SUITE.md` is authoritative for approved acceptance behavior.
- `MEMORY_LLM_BOUNDARY_SIMPLIFICATION_PLAN.md` is authoritative for the approved model-facing Semantic IR and deterministic-compiler design after the three governance documents are satisfied.
- `MEMORY_IMPLEMENTATION_GAP_PLAN.md` is authoritative for the previously approved typed-engine architecture/history and implementation sequencing where it is not superseded by the boundary plan.

Authority order:

1. `MEMORY_CONSISTENCY_SPEC.md`
2. `MEMORY_SEMANTIC_CONTRACTS.md`
3. `MEMORY_ACCEPTANCE_SUITE.md`
4. `MEMORY_LLM_BOUNDARY_SIMPLIFICATION_PLAN.md` for the approved model-facing boundary/compiler design
5. `MEMORY_IMPLEMENTATION_GAP_PLAN.md` for the previously approved typed-engine architecture/history and implementation sequencing where not superseded

The implementation MUST conform to all three. If they disagree about requested memory behavior: **STOP**. Do NOT choose one silently. Do NOT modify production code. Report the conflict and require user resolution. Reconcile governance before implementation.

If either implementation/design plan conflicts with any governance document, **STOP**. Do not silently implement the plan. Explicitly reconcile the conflict in the appropriate authoritative governance documents and then synchronize the plans before implementation. If the two plans disagree only about the model-facing protocol, `MEMORY_LLM_BOUNDARY_SIMPLIFICATION_PLAN.md` supersedes the older 13-key boundary. If they disagree about user-visible semantics, state authority, or safety behavior, **STOP** and reconcile governance; supersession MUST NOT be used to choose a behavioral meaning silently.

Do NOT implement a memory behavior first and attempt to justify or reconcile the specification afterward.

If requested behavior requires changing an existing invariant:

1. classify the task as specification-changing,
2. explain the conflict,
3. reconcile all affected governance documents first,
4. identify changed invariant, semantic contract, and acceptance case IDs,
5. verify the three documents are internally consistent,
6. only then modify implementation code in a separate authorized task.

Do not silently reinterpret the specification.

# Mandatory Final Report Evidence

Every memory-related task MUST include all of the following fields in the final report:

- `MEMORY_CONSISTENCY_SPEC.md read: YES`
- `MEMORY_CONSISTENCY_SPEC.md SHA256: <actual hash>`
- `MEMORY_SEMANTIC_CONTRACTS.md read: YES`
- `MEMORY_SEMANTIC_CONTRACTS.md SHA256: <actual hash>`
- `MEMORY_ACCEPTANCE_SUITE.md read: YES`
- `MEMORY_ACCEPTANCE_SUITE.md SHA256: <actual hash>`
- for relevant typed-memory implementation tasks, `MEMORY_IMPLEMENTATION_GAP_PLAN.md read: YES`
- for relevant typed-memory implementation tasks, `MEMORY_IMPLEMENTATION_GAP_PLAN.md SHA256: <actual hash>`
- for relevant typed-memory implementation tasks, `Affected implementation phases: <phase list>`
- for relevant Semantic IR/compiler/model-boundary tasks, `MEMORY_LLM_BOUNDARY_SIMPLIFICATION_PLAN.md read: YES`
- for relevant Semantic IR/compiler/model-boundary tasks, `MEMORY_LLM_BOUNDARY_SIMPLIFICATION_PLAN.md SHA256: <actual hash>`
- for relevant Semantic IR/compiler/model-boundary tasks, `Affected boundary-plan phase: <phase list>`
- for relevant Semantic IR/compiler/model-boundary tasks, `Model responsibilities changed: <list or NONE>`
- for relevant Semantic IR/compiler/model-boundary tasks, `Application-derived responsibilities changed: <list or NONE>`
- for relevant Semantic IR/compiler/model-boundary tasks, `Compiler mappings affected: <list or NONE>`
- for relevant Semantic IR/compiler/model-boundary tasks, `Semantic repair introduced: NO` unless governance explicitly changes
- for relevant Semantic IR/compiler/model-boundary tasks, `Rollback-path status: <status>`
- `Affected invariants: <INV-xx list>`
- `Affected semantic contracts: <MSC-... list>`
- `Affected acceptance cases: <case list>`
- `Task classification: implementation-preserving / specification-changing / model-semantic limitation`
- `Governance conflict found: YES / NO`
- `Specification changed: YES / NO`
- `Semantic contracts changed: YES / NO`
- `Acceptance suite changed: YES / NO`
- `Files changed: <list>`
- `Tests executed: <commands>`
- `Test result: <result>`
- `Deterministic guarantees affected: <list or NONE>`
- `Model-semantic limitations affected: <list or NONE>`
- `Real DeepSeek verification performed: YES / NO`
- `Paid DeepSeek calls: <number>`
- `Remaining blocker: <text or NONE>`

If these fields are absent, the memory-related task MUST be considered incomplete.

# Evidence Integrity

Codex MUST NOT claim any governance document was read merely because `AGENTS.md` references it.

The reported SHA256 values MUST be obtained by actually running all three commands:

Get-FileHash .\MEMORY_CONSISTENCY_SPEC.md -Algorithm SHA256
Get-FileHash .\MEMORY_SEMANTIC_CONTRACTS.md -Algorithm SHA256
Get-FileHash .\MEMORY_ACCEPTANCE_SUITE.md -Algorithm SHA256

before implementation.

Do NOT:

- invent the SHA256,
- copy it from an older report,
- reuse a SHA256 from a previous task without running the command again,
- assume any governance document is unchanged.

If any governance document changes during a task:

1. report all original governance SHA256 values,
2. make only the authorized governance changes,
3. run all three SHA256 commands again,
4. report all new SHA256 values,
5. list changed invariant, semantic contract, and acceptance case IDs,
6. explain why each governance change was required.

# Verification Semantics

Codex MUST clearly distinguish between:

- deterministic application verification,
- offline/mock verification,
- real DeepSeek verification,
- manual UI verification.

Codex MUST NEVER report:

- mocked success as real DeepSeek success,
- prompt-only compliance as application-enforced consistency,
- model-semantic compliance as deterministic application behavior,
- offline success as live API success,
- a direct memory UPDATE as verification of a Pending Proposal flow,
- a model-selected answer mode as mathematically deterministic routing.

If a behavior depends on DeepSeek making a semantic decision, state that dependency explicitly.

# Deterministic vs Model-Semantic Guarantees

Codex MUST distinguish these two categories.

## Deterministic Application Guarantees

Examples include:

- stable memory IDs,
- SQLite ownership checks,
- user isolation,
- session isolation,
- revision checking,
- atomic transactions,
- operation validation,
- history lineage,
- proposal Confirm/Cancel state transitions,
- database-rendered values after valid memory IDs are selected,
- fail-closed behavior.

These may be described as application-enforced only when the implementation actually enforces them.

## Model-Semantic Behavior

Examples include:

- choosing ADD versus UPDATE versus NOOP,
- choosing the correct existing memory ID,
- choosing whether a question is a personal-memory query,
- deciding whether clarification is required,
- understanding arbitrary natural-language intent.

These MUST NOT be described as deterministic application guarantees unless the application independently enforces them.

# Prohibited Memory Design Regressions

Unless `MEMORY_CONSISTENCY_SPEC.md` is intentionally changed first, Codex MUST NOT reintroduce:

- free-text memory identity,
- regex-based subject identity,
- Chinese copula parsing for memory identity,
- substring-based identity,
- shared-value identity,
- value-overlap identity,
- semantic string reconciliation in Python,
- complete-memory snapshot replacement,
- heuristic reconstruction of omitted memories,
- heuristic correction-target inference,
- parser-based fixes for one conversational example,
- another LLM call solely for semantic repair,
- a second judge model solely to validate memory semantics,
- silent application-side rewriting of DeepSeek memory decisions,
- claims that free-form model replies are authoritative over committed SQLite memory.

# Stable Identity Rule

Stable `memory_id` is the authoritative identity of a memory lineage.

Codex MUST NOT replace stable ID semantics with:

- textual similarity,
- semantic overlap,
- subject strings,
- shared values,
- regex parsing,
- token overlap.

UPDATE must preserve the existing memory ID.

History must remain associated with that lineage.

DELETE must target the explicit stable memory ID and must not affect unrelated lineages.

# Current / History / Proposal Authority

Codex MUST preserve these distinctions:

- Current Memory = authoritative committed current persistent state.
- Historical Memory = previous committed state.
- Pending Proposal = proposed but uncommitted change.
- Recent Conversation = contextual conversation state, not authoritative persistent state.
- Free-form model wording = not authoritative persistent state.

Pending Proposal MUST NOT be represented as Current Memory before Confirm.

Historical Memory MUST NOT be represented as Current Memory.

Recent Conversation MUST NOT silently overwrite committed Current Memory.

# Pending Proposal Rules

Pending Proposal is the deterministic confirmation mechanism.

When a memory mutation requires confirmation:

- the same DeepSeek response requesting confirmation should include the proposal,
- the proposal must contain one concrete validated ADD, UPDATE, or DELETE,
- Current Memory remains unchanged until Confirm,
- Confirm must apply the stored proposal locally,
- Confirm must require zero DeepSeek calls,
- Cancel must remove the proposal locally,
- Cancel must require zero DeepSeek calls,
- stale proposals must fail closed,
- proposals are user-scoped,
- proposals are session-scoped.

For model-derived semantic writes under `POLICY-18`:

- every candidate that would change Current requires deterministic Risk Engine classification;
- only `AUTO_COMMIT_ALLOWED` candidates satisfying every `POLICY-21` condition may bypass a proposal and commit atomically;
- every other changed candidate is `HUMAN_REVIEW_REQUIRED` and requires a Pending Semantic Confirmation proposal;
- proposal purpose and destructive effect MUST be represented separately;
- the rendered proposal MUST completely and deterministically identify the exact stored target, registry-derived slot/entity metadata, typed operation, canonical proposed state/operand, destructive flag, purpose, and base revision that Confirm will apply;
- Confirm MUST revalidate user, session, proposal identity, pending status, base revision, authoritative Current, typed preconditions, and exact payload identity before one atomic commit;
- a deterministic typed `NOOP` bypasses proposal creation because it cannot change Current;
- Correct MUST NOT silently alter a displayed or confirmed payload; it must create a new immutable proposal payload/version or submit a fully rendered structured Correct-and-Confirm action;
- one explicit Confirm MAY cover both semantic interpretation and destructive authorization;
- production proposal auto-confirm is prohibited; deterministic low-risk auto-commit is separate and cannot be enabled before the frozen benchmark passes and a separate implementation task authorizes it.

Codex MUST NOT reintroduce the old pattern:

assistant proposes a change
→ user says "好" / "yes"
→ DeepSeek semantically reconstructs the proposal again

as the authoritative confirmation protocol.

# Personal-Memory Query Consistency

Codex MUST preserve the memory-query consistency rules defined by `MEMORY_CONSISTENCY_SPEC.md`.

When personal-memory values are rendered deterministically from SQLite after valid memory IDs are selected:

- raw contradictory model wording must not replace the stored value,
- historical values must come from validated historical records,
- unknown personal facts must not be guessed.

Codex MUST also preserve the documented limitation:

DeepSeek may still choose the wrong answer mode or wrong relevant memory ID unless a future stricter routing mechanism is implemented.

Do NOT describe answer-mode routing as fully application-deterministic if the model still selects it.

# Change-Control Enforcement

For every memory-related task:

1. Read `AGENTS.md` and all three governance documents completely.
2. Obtain all three SHA256 values.
3. Identify affected invariants, semantic contracts, and acceptance cases.
4. Classify the requested change.
5. Check for governance conflict and stop before production edits if unresolved.
6. Preserve unrelated governance requirements.
7. Make the smallest structurally correct change.
8. Add or update regression tests when implementation changes.
9. Run deterministic tests when applicable.
10. Clearly separate mock, live, and manual verification.
11. Report all required evidence.

Prefer:

- structural invariants,
- stable IDs,
- state machines,
- deterministic validation,
- fail-closed behavior,

over:

- one-example prompt patches,
- narrow regex fixes,
- natural-language heuristics in Python.

# Model-Semantic Limitation Rule

If a problem is fundamentally caused by probabilistic DeepSeek semantic reasoning and cannot be deterministically enforced under the current architecture:

Codex MUST NOT introduce a fragile Python natural-language heuristic merely to make one manual example pass.

Instead:

1. identify the affected invariant,
2. identify the semantic limitation,
3. determine whether the specification already accepts the limitation,
4. report the limitation clearly,
5. propose a structural change only if justified by the specification.

# Testing Requirements

## Automated Database Safety

For every automated test, smoke test, local HTTP verification, migration test, or test-runner verification: NEVER use the default production database; NEVER open `memory.db`, `final_acceptance.db`, or the active normal-chat database through SQLite. Use an explicit temporary or dedicated test database and classify its canonical path as safe before any SQLite connection or file mutation. Record protected-database SHA256 values before and after verification when relevant. If it is unclear whether a database is protected, STOP.

Memory-related code changes MUST run the project's required automated test command.

At minimum, when applicable:

python -W error::ResourceWarning -m unittest -v test_app.py

Codex MUST report the actual result.

If live DeepSeek testing is needed:

- minimize paid calls,
- respect the requested call cap,
- do not retry beyond the cap merely to obtain a passing result,
- report failed or unverified live behavior truthfully.

# Manual UI Verification

If a task includes UI behavior, distinguish:

- code inspection,
- automated UI-related test,
- local HTTP smoke test,
- actual manual/browser interaction.

Do not call a code-level assertion a manual browser verification.

# Repository Scope

These instructions apply to:

D:\0TIGER\6months\PythonAPIDevelopment\Tiger-Short-Long-Memory

and all subdirectories unless a more specific `AGENTS.md` explicitly overrides them.

All three approved governance documents apply according to the authority split above.

# Final Validation for Memory-Related Tasks

Before final reporting:

1. Re-read `AGENTS.md` and all three governance documents completely.
   For a relevant typed-memory implementation task, also re-read `MEMORY_IMPLEMENTATION_GAP_PLAN.md` completely.
   For a relevant Semantic IR/compiler/model-boundary task, also re-read `MEMORY_LLM_BOUNDARY_SIMPLIFICATION_PLAN.md` completely.
2. Confirm all Markdown code fences are balanced.
3. Confirm the final task diff contains only authorized files.
4. Run all three mandatory SHA256 commands and record the actual hashes.
   For a relevant typed-memory implementation task, also calculate and record the plan SHA256.
   For a relevant Semantic IR/compiler/model-boundary task, also calculate and record the boundary-plan SHA256.
5. Recheck affected invariant, semantic contract, and acceptance case IDs.
6. Confirm no unresolved governance contradiction remains.
7. Confirm deterministic guarantees are distinguished from model-semantic limitations.
8. Confirm paid/live verification claims match actual calls.

Do NOT run any paid DeepSeek API call.

Do NOT rebuild the ZIP.
