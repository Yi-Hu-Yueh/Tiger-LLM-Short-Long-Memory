# Validation Report

## Evidence boundary

This document summarizes the validation artifacts currently present in the
repository and the Phase 5E manual acceptance handoff supplied for Phase 5F.
Results are classified as deterministic/offline, persisted live evidence,
user-reported manual evidence, or not rerun. Mock success is not represented as
real DeepSeek success. Phase 5F changes documentation only.

The current product status is `HUMAN_REVIEWED_MEMORY_ASSISTANT`. The frozen
automatic-memory benchmark is permanently stopped after one unsafe
auto-commit. That failure is preserved; it is not reinterpreted as a pass.

## Phase history

| Phase | Objective | Result | Key validation evidence |
|---|---|---|---|
| 1A | Deterministic SQLite Memory Core | PASS — offline | Bi-temporal versions, single Current, correction, idempotency, concurrency, rollback, restart, and forget/history behavior in `test_memory_core.py`. |
| 1B | LLM memory-boundary framework | PASS — offline | Existing 50-case boundary dataset covers basic facts, replacement, corrections, time, negative/third-party/ambiguous input, control, injection, sensitive data, and schema rejection. |
| 1C-R | Extraction hardening | PASS — implementation/offline; live not rerun | Canonical attribute registry, two-stage/context-aware extraction, strict JSON handling, one repair retry, normalization, and separate extraction/safety scoring. Real-provider behavior remains model-semantic. |
| 1D | Memory runtime integration | PASS — offline | Extractor → validator → Phase 1A core, cross-session retrieval, replacement, correction, forget, rejection, extraction failure, rollback, idempotency, and restart persistence. |
| 1E-R | State-transition hardening | PASS — offline; live not rerun | Twenty transition fixtures cover replacement, correction, same-value `no_op`, future plans, ambiguity, and historical facts with current context. |
| 2A | Context and answer-generation gate | PASS — offline/mock; live not rerun | Current-only formatting, relevant-memory use, missing-memory behavior, History isolation, and memory-injection resistance. |
| 2B | Multi-turn memory behavior | PASS — persisted live evidence and current offline regression | `phase2b_full_report.json` records DeepSeek `deepseek-v4-pro`, 10/10 conversations and 6/6 critical conversations, 60 calls, 44,447 tokens. This historical evidence was not rerun in Phase 5C. |
| 2C | Conflict and long-conversation stress | PASS — offline/mock; live not rerun | Long-turn stability, repeated replacements, correction chains, forget/rebuild, user isolation, and duplicate-event behavior. |
| 3A | Memory-aware decision gate | PASS — offline/mock; live not rerun | Relevant preference/location use, irrelevant-memory exclusion, no invented preference, Current-over-History behavior, and forgotten-memory exclusion. |
| 3B-R | Tool action plus semantic confirmation | PASS — offline | Tools return candidates only; validator and proposal service mediate changes. Failed tools and sensitive writes do not mutate Current. |
| 3C | Proposal lifecycle and conflict gate | PASS — offline | Pending, Confirm, Reject, Cancel, Expire, duplicate Confirm, stale revision, competing proposals, and user isolation. |
| 3D | Audit and observability evidence | PASS — offline | Append-only audit events, safe details, lifecycle coverage, write/validation counters, latency metrics, failure observability, and user-scoped queries. |
| 3E | Recovery and disaster safety | PASS — offline | Paired backup manifests, hashes, integrity checks, staged restore, rollback, proposal/audit recovery, corruption rejection, and user isolation. |
| 3F | Production-readiness evaluation | PASS — offline | Deterministic correctness, safety, reliability, performance collection, failure reporting, and manual-flow simulation using temporary databases. |
| 4A | Runtime hardening | PASS — offline | Concurrent reads/proposals/confirms, 100-operation stress, rollback and failure injection, cleanup, and strict ResourceWarning verification. |
| 4B-R | Approved-scope soak | PASS — offline | `user1` 1,000-operation lifecycle soak, 500 operations each for `user1`/`user2`, competing proposals, failure injection, integrity, isolation, and cleanup metrics. |
| 4C | Observability and alerting | PASS — offline | Deterministic metrics aggregation, HEALTHY/WARNING/CRITICAL evaluation, corruption/isolation/failure-rate/latency alerts, and reproducible reports. |
| 4D | Security and privacy | PASS — offline | API key/password/token rejection, prompt-injection blocking, proposal/memory/audit isolation, audit-secret exclusion, and fail-closed rollback. |
| 4E | Operational lifecycle | PASS — offline | Startup integrity/schema/environment checks, missing/corrupt/unsupported storage rejection, shutdown cleanup, protected-name rules, and restart persistence. |
| 5A | Release-candidate validation | PASS — offline | Regression, governance-hash mismatch detection, security/recovery regression rejection, deterministic reporting, and human-reviewed product-lock verification. |
| 5B | Model benchmark framework | PASS — tooling/offline | 70 unchanged validated cases, provider-neutral metrics, mock execution, deterministic report, and unavailable Bonsai handling. DeepSeek was not rerun; Bonsai 2 27B was `NOT_AVAILABLE`; no comparative recommendation was made. |
| 5C | Architecture documentation and release package | PASS — documentation/offline | Architecture, memory model, security, operations, validation history, README, and release checklist were produced; 20/20 strict tests and 177 passed/9 skipped extended tests. |
| 5E | Final manual UI/runtime acceptance | PASS — user-reported manual handoff | Listed scenarios and backup/restore counts are recorded below; no Phase 5F browser or provider rerun. |
| 5F | Final release freeze and closure gate | PASS — documentation/offline, with Phase 5E handoff | 20/20 strict tests; 177 passed/9 skipped extended tests; compilation, Markdown, governance hashes, runtime hashes, and protected database hashes verified. |

## Frozen automatic-memory benchmark

This benchmark is distinct from the Phase 5B comparison framework.

- Freeze: `freeze-v1.2-6fb6d482f9b2142c53ca`
- Planned: 660 turns
- Completed before mandatory stop: 122
- Stop case: `HB-OFFICE-100`
- Unsafe auto-commits: 1
- Result: **FAIL — automatic semantic memory stopped**
- Consequence: production auto-commit remains unreachable; the Human-Reviewed
  Memory Assistant is the retained product direction.

The remaining 538 turns must not be run to rescue the frozen architecture.

## Current Phase 5C verification

Phase 5C validation records are completed after documentation generation:

- Markdown/file consistency: PASS
- Main strict regression: PASS — 20/20
- Extended offline regression: PASS — 177 passed, 9 skipped, 477 subtests passed
- Protected database hashes: unchanged
- Runtime files changed: none
- Governance files changed: none
- Paid DeepSeek calls: 0

## Phase 5E manual acceptance handoff

The Phase 5F request supplies the final Phase 5E manual acceptance result. The
following is **user-reported manual UI/runtime evidence**, not a Phase 5F
rerun or a newly generated provider result. The handoff reports PASS for:

| Manual scenario | Phase 5E handoff result |
|---|---|
| Basic memory and same-user cross-session retrieval | PASS, reported |
| Replace/update, state transition, and correction | PASS, reported |
| Forget | PASS, reported |
| `user1`/`user2` isolation | PASS, reported |
| Prompt-injection boundary | PASS, reported |
| Restart persistence, including a Pending Proposal | PASS, reported |
| Duplicate Confirm | PASS, reported |
| Backup/Restore | PASS, reported |

The supplied backup/restore observations are `BEFORE = 2`,
`AFTER_DAMAGE = 0`, `AFTER_RESTORE = 2`, and integrity `valid = True`.
Stale-proposal direct UI exercise is **N/A** because a Pending Proposal
intentionally blocks subsequent normal input. Automated stale/conflict tests
provide that evidence; the UI scenario is not marked as manually executed.

Sensitive-data handling is not stated as a blanket prohibition on arbitrary
personal or sensitive facts. The configured Phase 1B/4D validators reject
specific credential-like and other enumerated attributes; normal-chat memory
changes remain subject to structural validation and explicit human review.
The Phase 5E handoff does not establish a universal sensitive-data classifier.

## Phase 5F final regression

- `python -W error::ResourceWarning -m unittest -v test_app.py`: PASS, 20/20.
- `D:\python3.11.3\python.exe -W error::ResourceWarning -m pytest -q`:
  PASS, 177 passed, 9 skipped, 477 subtests passed. Real-provider flags were
  disabled for this offline run.
- `python -m py_compile app.py semantic_ir_v2.py memory_release.py
  memory_evaluation.py memory_operations.py memory_recovery.py
  memory_security.py test_app.py test_memory_release.py`: PASS.
- Strict `ResourceWarning`: PASS. No paid DeepSeek call was made in Phase 5F.
- Protected database hashes: unchanged across Phase 5F verification.
- Governance documents and runtime source: unchanged.

## Interpretation limits

- Offline/mock gates verify deterministic application behavior and expected
  provider contracts; they do not establish real-model semantic accuracy.
- The persisted Phase 2B report is historical live evidence, not a Phase 5F
  rerun.
- The Phase 5E manual outcomes are a user-supplied handoff; this document does
  not claim independent Phase 5F browser observation.
- Human confirmation prevents silent writes but does not guarantee objective
  semantic correctness.
- Phase 5B did not compare DeepSeek with Bonsai because Bonsai 2 27B was not
  available.
