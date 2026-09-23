# Release Freeze

- Validated release date: 2026-09-23 (Asia/Taipei)
- Status: **RELEASE CANDIDATE VALIDATED**
- Product: **Enterprise-oriented Human-Reviewed Memory Assistant Prototype**
- Runtime mode: `HUMAN_REVIEWED_MEMORY_ASSISTANT`
- Frozen automatic benchmark: `freeze-v1.2-6fb6d482f9b2142c53ca`, stopped
  at `HB-OFFICE-100` (ordinal 122) after one unsafe auto-commit.

## Architecture status

The validated release uses DeepSeek `deepseek-v4-pro` as a semantic proposal
generator, application-owned structural and grounding validation, a Canonical
Slot Registry, typed preconditions, and a deterministic risk guardrail.
Every model-derived changed write in this product mode requires an immutable
Pending Semantic Confirmation Proposal and explicit local Confirm before a
short atomic SQLite commit. Current, History, revision, proposals, recent
conversation, and audit evidence have distinct authority and scope.

## Final automated evidence

| Gate | Result |
|---|---|
| `python -W error::ResourceWarning -m unittest -v test_app.py` | PASS — 20/20 |
| `D:\python3.11.3\python.exe -W error::ResourceWarning -m pytest -q` | PASS — 177 passed, 9 skipped, 477 subtests passed |
| `python -m py_compile` for app, Semantic IR, release/evaluation/operations/recovery/security, and related tests | PASS |
| Markdown files, links, and fences | PASS |
| Protected database file hashes before/after | identical |

Real-provider flags were disabled for the Phase 5F offline regression. The
persisted Phase 2B real DeepSeek report is historical live evidence and was
not rerun. Phase 5F paid DeepSeek calls: `0`.

Fresh on-disk governance/design SHA-256 at this freeze:

| File | SHA-256 |
|---|---|
| `MEMORY_CONSISTENCY_SPEC.md` | `611703142B24F16ADBE4F3EFE576865E7E22E77DB67FD1A1761C23D861359217` |
| `MEMORY_SEMANTIC_CONTRACTS.md` | `6BAC8944E3127D80D0CA3BE29C78A3EB2AACB06D32DD47026C0BE3031C1E2A26` |
| `MEMORY_ACCEPTANCE_SUITE.md` | `790BDC004EFC12C1C56425A8E602AF4D17381B823B0CDC2813F05118A99D96E2` |
| `MEMORY_IMPLEMENTATION_GAP_PLAN.md` | `1B85B4959B9ED72C6083111344A2842EFC5EE992B7E14652497B162E280DE83D` |
| `MEMORY_LLM_BOUNDARY_SIMPLIFICATION_PLAN.md` | `D9D4C9047BEA54B0177B0A6199102C1D33F4DF2AE1530B47D084E7F29F32D86E` |

## Manual acceptance evidence

The user-supplied Phase 5E handoff reports PASS for basic memory,
cross-session retrieval, replace/update, forget, state transition,
correction, `user1`/`user2` isolation, prompt-injection handling, restart
persistence, Pending Proposal restart, duplicate Confirm, and backup/restore.
The restore observations are `BEFORE=2`, `AFTER_DAMAGE=0`,
`AFTER_RESTORE=2`, integrity `valid=True`. A direct stale-proposal UI exercise
is N/A because a Pending Proposal blocks further normal input; automated
stale/conflict tests provide that validation. Phase 5F did not repeat the
manual browser run.

## Known limitations

This remains a two-user localhost SQLite prototype. Local bounded soak does
not establish distributed capacity, and no long-duration multi-machine soak
was performed. Natural-language model choices remain probabilistic. There is
no Vector DB memory, automatic Skill learning, self-learning Agent, or
LangGraph dependency. Bonsai 2 27B was unavailable for comparison. The
prototype is not a fully proven enterprise production deployment. See
[Final Project Status](docs/FINAL_PROJECT_STATUS.md) for the complete limits.

## Frozen areas and future work

The following release behavior is frozen: Memory Core semantics;
Current/History lifecycle; user isolation; proposal lifecycle and local
Confirm/Cancel; audit and recovery behavior; validator safety boundary; and
the disabled production automatic-commit route. A future change to any of
these areas requires a new validation phase and the approved governance
change-control process.

Permitted future work includes documentation corrections, independent
operational evaluation, capacity/security studies, and separately governed
architecture or model research. A materially new automatic-memory approach
requires separate approval and a new frozen benchmark; the archived failed
run cannot be resumed or reclassified.

This freeze records a release decision. It does not create a Git commit, tag,
archive, or deployment.
