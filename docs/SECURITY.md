# Security

## Product security posture

The active product is a `HUMAN_REVIEWED_MEMORY_ASSISTANT`. The archived frozen
benchmark observed an unsafe auto-commit at case `HB-OFFICE-100`, ordinal 122.
The stop rule is therefore active: production automatic semantic writes are
disabled and the archived run is locked.

No model-derived changed write may enter Current Memory without an explicit
human confirmation of the exact persisted proposal. Deterministic non-write
results remain local and do not require a proposal.

## Fail-closed design

The following conditions produce no partial memory or conversation mutation:

- provider or network failure;
- invalid provider envelope, JSON, schema, or field type;
- unknown, foreign, ambiguous, or stale target;
- failed exact-literal grounding;
- unsupported operation or typed precondition;
- capacity or length-limit violation;
- memory-firewall rejection or rejection of a configured sensitive attribute;
- revision conflict;
- proposal/render/commit identity mismatch;
- SQLite write failure.

Remote calls occur before the short SQLite write transaction. Database
exceptions roll back the complete transaction.

## Human-reviewed memory policy

- The model proposes semantics; it never writes the database.
- The application validates structure, ownership, grounding, registry identity,
  operation compatibility, and authoritative preconditions.
- A changed candidate becomes a user/session/revision-bound immutable proposal.
- Confirm and Cancel use zero provider calls.
- Confirm commits only the persisted payload after transaction-time
  revalidation.
- Correct cannot silently edit a displayed proposal; it creates a new identity.
- Destructive effects are clearly identified in the proposal.
- Human confirmation authorizes the proposed effect but does not prove that the
  model's interpretation is objectively correct.

## User and session isolation

The prototype admits only `user1` and `user2`. Every read, write, proposal,
confirmation, cancellation, audit query, and clear-user operation is scoped in
the application and database. A memory or proposal owned by one user cannot be
accessed through the other user. Recent conversation and proposals are also
session-scoped; Current and History are user-scoped for cross-session recall.

UI filtering is not treated as a security boundary. Backend ownership checks
remain authoritative.

## Sensitive-data handling

The Phase 1B validator and Phase 4D evaluator reject configured attribute
names, including API keys, passwords, tokens, credentials, secrets,
credit-card data, and identity numbers. These gates do not establish a
universal classifier or a product prohibition on arbitrary sensitive personal
facts. Normal-chat changed writes still require structural validation and
explicit human review. Prompt-injection markers and attempts to bypass
confirmation are rejected by the applicable boundary. A rejected candidate
creates no Current Memory and no executable proposal.

The optional API-key input is sent to the localhost service for the provider
request. It must not be persisted or logged. Operators should prefer an
environment variable and must never package secrets in a release archive.

## Memory is data, not instruction

Stored memory is untrusted user data. It cannot override system or developer
instructions, alter validation policy, modify the Slot Registry, or authorize
a tool or database write. Reference documents and quoted instructions do not
become memory unless the outer user request independently supplies an admitted,
validated candidate.

## Exact grounding boundary

For sourceable literal operands, the model selects an exact `claimed_literal`.
The application accepts it only when it occurs exactly once in the canonical
current-turn text and derives authoritative Unicode-code-point offsets. Zero or
multiple occurrences fail closed. The application does not normalize, fuzzy
match, translate, select the first occurrence, or repair the model's choice.

Grounding proves provenance only. A wrong-but-exact literal can still be a
model-semantic error and must not be described as deterministic semantic truth.

## Audit privacy

Audit fields and details are restricted to bounded safe tokens and reason
codes. Audit records must not include raw user text, raw operands, source
slices, API secrets, credentials, or a full Semantic IR payload. Audit queries
are user-scoped. The audit database is separate from Memory Core state.

## Operational protections

- The HTTP service binds to `127.0.0.1`.
- Startup validation checks environment markers, SQLite integrity, schema
  version, required tables, user scope, and core/audit path separation.
- Non-production environments reject protected database filenames.
- Tests use explicit temporary databases and never open protected production
  databases through SQLite.
- Recovery points include hashes and are verified before restore.
- Corruption or isolation failure is a CRITICAL observability condition.

## Residual risks

- A model can choose a wrong-but-valid intent, slot, target, claim shape, or
  literal.
- Human reviewers can confirm an incorrect proposal.
- Localhost exposure is not a substitute for operating-system account security.
- This prototype has no external authentication, encryption-at-rest layer, or
  multi-tenant authorization system.
- A materially new model or automatic-write architecture requires separate
  governance and a new frozen evaluation.
