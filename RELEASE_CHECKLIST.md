# Release Checklist

Checked items have evidence for this release candidate. Phase 5E entries are
based on the user-supplied manual acceptance handoff and were not rerun in
Phase 5F. Offline tests and historical live-provider evidence are identified
separately in [Validation Report](docs/VALIDATION_REPORT.md).

## Governance and architecture

- [x] Product identified as `HUMAN_REVIEWED_MEMORY_ASSISTANT`.
- [x] Production automatic semantic writes disabled; archived frozen
  benchmark remains locked.
- [x] Five governance/design document SHA-256 values freshly recorded;
  governance files unchanged in Phase 5F.
- [x] Runtime source and semantics unchanged in Phase 5F.
- [x] Architecture and limitations documented in
  [Final Project Status](docs/FINAL_PROJECT_STATUS.md) and
  [Release Freeze](RELEASE_FREEZE.md).

## Automated validation

- [x] `python -W error::ResourceWarning -m unittest -v test_app.py`:
  **20/20 PASS**.
- [x] `D:\python3.11.3\python.exe -W error::ResourceWarning -m pytest -q`:
  **177 passed, 9 skipped, 477 subtests passed**. Real-provider flags were
  disabled.
- [x] `python -m py_compile` for final runtime/release/validation modules:
  **PASS**.
- [x] Strict `ResourceWarning` runs: **PASS**.
- [x] `ReleaseValidator` offline regression and governance/security/recovery
  failure-path tests: **PASS** within the extended suite.
- [x] Audit, observability, recovery, operations, security, and bounded soak
  offline tests: **PASS** within the extended suite.
- [x] Markdown files, local links, and code fences checked.

## Live and manual evidence

- [x] Historical real DeepSeek Phase 2B multi-turn gate: persisted report
  records **10/10 conversations and 6/6 critical conversations PASS**.
- [x] Phase 5E manual UI/runtime handoff reports **PASS** for basic memory,
  cross-session retrieval, replacement, state transition, correction, forget,
  user isolation, prompt-injection handling, restart persistence, Pending
  Proposal restart, duplicate Confirm, and backup/restore.
- [x] Phase 5E backup/restore handoff records `BEFORE=2`, `AFTER_DAMAGE=0`,
  `AFTER_RESTORE=2`, integrity `valid=True`.
- [x] Stale/conflicting proposal behavior covered by automated tests. Direct
  UI exercise is **N/A** because Pending Proposal blocks normal input.
- [ ] Real40, Master100, or Bonsai 2 27B comparison for Phase 5F: not run and
  not required by this documentation/freeze task.

## Security and operations

- [x] `user1`/`user2` isolation, prompt-injection boundary, atomic rollback,
  and local proposal confirmation passed automated regressions.
- [x] Configured credential-like attribute rejection and audit privacy passed
  the Phase 4D offline tests. No blanket arbitrary-sensitive-data prohibition
  is claimed.
- [x] Startup/shutdown, recovery, and observability checks passed offline
  regressions.
- [x] Protected database file hashes were identical before and after Phase 5F
  verification; protected databases were not opened through SQLite.
- [ ] New distributable ZIP contents/path/hash: no ZIP rebuild was requested or
  performed in Phase 5F.

## Release decision

- [x] Deterministic tests passed.
- [x] Governance unchanged.
- [x] Security validation passed within its documented offline scope.
- [x] Recovery validated by offline tests and the Phase 5E manual handoff.
- [x] Manual acceptance evidence recorded with its source and scope.
- [x] Documentation and release freeze artifacts completed.
- [x] Remaining Phase 5F release blockers: **NONE** for a validated prototype
  release candidate. Enterprise production deployment remains a separate gate.
