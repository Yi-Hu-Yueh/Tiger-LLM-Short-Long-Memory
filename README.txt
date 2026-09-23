Tiger Short/Long Memory - DeepSeek Prototype
=============================================

Status
------
The approved six-phase typed-memory implementation is complete. The production
runtime uses schema version 4 and enables the structured vNext typed protocol by
default (`TYPED_MEMORY_PROTOCOL_ENABLED=True`). The architecture remains a local
SQLite prototype for user1 and user2; it does not use embeddings, a vector
database, a semantic parser, a repair model, or a second judge model.

Requirements and startup
------------------------
Python 3.14.7 and a DeepSeek API key are required for live chat. No third-party
packages are used. Set DEEPSEEK_API_KEY, run start.cmd, and open
http://127.0.0.1:18080/. The service binds only to localhost. The optional UI key
field is sent only to the local service and is never stored or logged.

The configured model remains deepseek-v4-pro, thinking is disabled, the existing
DeepSeek endpoint is unchanged, and each normal chat turn uses at most one model
call. Confirm and Cancel use zero model calls.

Authoritative state and identity
--------------------------------
Current Memory is the authoritative committed persistent state. Each lineage is
identified only by its stable, application-generated memory_id. semantic_key is
descriptive routing metadata and is never a replacement for memory_id or a basis
for fuzzy merging. Typed canonical state is authoritative; rendered text is a
deterministic presentation rather than a second authoritative value.

The supported typed families are:

- Scalar: one typed value; CREATE_SCALAR, SET_VALUE, REASSERT_NOOP and
  DELETE_MEMORY.
- Set: unique typed items; CREATE_SET, ADD_ITEM, REMOVE_ITEM, REPLACE_SET and
  DELETE_MEMORY. Relation membership is represented through Set state.
- Count: an integer from 0 through 1,000,000,000; CREATE_COUNT, SET_COUNT,
  admitted INCREMENT/DECREMENT and DELETE_MEMORY.
- Record: typed fields; CREATE_RECORD, SET_FIELD, DELETE_FIELD and
  DELETE_MEMORY.

DeepSeek remains responsible for interpreting natural language, choosing the
state type, operation, evidence class, target memory_id, operands and read IDs.
The application deterministically validates that structured decision, applies
the finite transition algebra, enforces ownership and policy gates, stores
History, updates revision, and renders validated SQLite records.

Current, History, revision and atomic turns
-------------------------------------------
An actual Current change preserves the lineage ID where applicable, archives a
complete typed predecessor, and increments the per-user revision once. Read,
Clarification, Proposal creation, Cancel, NOOP, REASSERT_NOOP, provider failure,
validation failure and rolled-back database work do not increment revision.

A model/network call occurs before any SQLite write transaction. After the full
provider envelope, JSON, vNext schema, operation, evidence, firewall and answer
route have passed validation, one short BEGIN IMMEDIATE transaction commits the
user message, Current/History change or control state, revision change and
assistant message. Any database error rolls back the complete turn. A failed
user message is not stored and cannot enter the next recent-context request.

Pending Proposal and destructive operations
-------------------------------------------
REMOVE_ITEM, DELETE_FIELD, and Scalar/Set/Count/Record DELETE_MEMORY are
destructive. They cannot direct-commit. An exact operation first becomes a
user/session-scoped Pending Proposal with a base revision. Current, History and
revision remain unchanged until local Confirm.

Confirm revalidates ownership, Session, revision, type and transition, then
atomically applies the stored operation, archives the predecessor when
applicable, updates revision, removes the Proposal, and stores the fixed reply.
Cancel atomically removes the Proposal and stores the fixed reply without
changing Current, History or revision. Both paths make zero DeepSeek calls, and
replay or stale revision attempts fail closed.

Removing the last Set item produces the same lineage with explicit `[]`.
Deleting the last Record field produces the same lineage with explicit `{}`.
Neither operation implies DELETE_MEMORY.

Clarification
-------------
Clarification is persisted separately from Current Memory and Pending Proposal.
It is non-authoritative, user/session scoped, revision guarded, expiring, and
records the operation candidate, known arguments and exact missing fields. A
continuation must cite the active clarification ID and may fill only those
missing fields. An unrelated request is handled independently and cannot be
silently consumed as a clarification answer.

The browser shows Clarification in a separate panel while leaving normal input
enabled. A Pending Proposal remains visually separate and disables normal input
until Confirm or Cancel resolves it.

Count safety
------------
A count-only memory does not infer arithmetic from an anonymous membership
event. For example, committed count 4 plus "one member left" causes no
DECREMENT, no executable Proposal and no revision change without admitted
concrete evidence. A later read remains 4. An explicit authoritative assertion
such as "the current count is 3" may use SET_COUNT after normal validation.

Legacy coexistence and conversion
---------------------------------
Legacy free-text Current and History records remain readable beside typed rows.
There is no bulk conversion and Python never parses legacy prose to guess a
type, slot, roster, count or record.

A legacy lineage converts only after an explicit update when DeepSeek selects
the exact existing memory_id and provides a complete valid typed target and
operation. The conversion transaction preserves memory_id and ownership,
archives the full legacy predecessor, writes typed Current, increments revision,
and commits both messages atomically. Exact typed-registry conflicts and unsafe
or incomplete mappings fail closed. Rollback leaves the legacy lineage intact.

Personal-memory reads and known limitation
------------------------------------------
For a structured READ decision, DeepSeek selects supplied Current memory IDs
and/or History IDs. The application validates ownership and renders exact
SQLite-backed values with Current and History clearly distinguished. Unknown
personal memory uses the fixed local reply. Reads do not mutate Current,
History, revision, Proposal or Clarification.

This does not make natural-language routing deterministic. DeepSeek can still
choose FREEFORM for a personal-memory question or select a wrong-but-valid
relevant ID. Once valid IDs are selected, value rendering is deterministic; the
selection itself remains a documented model-semantic limitation.

Browser controls
----------------
Enter and the Send button use one guarded sendMessage path. Shift+Enter inserts
a newline. Empty/whitespace input does not send, and Enter during IME composition
does not submit. A shared request-in-flight guard prevents duplicate Enter/click
submission. Requests capture user, Session, Proposal where applicable, and
request/context generations so late responses cannot redraw another visible
context. User switching, New Session and Clear User Data are disabled while a
request is in flight.

Schema and migration
--------------------
Schema version 4 adds nullable typed Current/History/Proposal fields and the
memory_clarifications table while retaining legacy columns. v2/v3 upgrades use
a SQLite backup named with `.pre-v4.bak` (or a numbered non-overwriting variant),
run transactionally, and are idempotent. Migration never guesses typed content.
Tests and restore drills use temporary databases; the real memory.db is not used
for exploratory upgrades.

Limits
------
- user1 and user2 only.
- 20 Current memories per user.
- Scalar strings and Set items: at most 160 Unicode characters.
- Set: at most 50 unique items.
- Record: at most 20 fields; field names at most 80 characters; scalar values at
  most 160 characters.
- Serialized typed canonical state: at most 4,096 UTF-8 bytes.
- User input: at most 4,000 characters.
- Model output: at most 4,096 tokens.
- Recent context: six user/assistant turns, at most 12 messages and about 12,000
  characters.
- History: the latest 10 predecessors per user.

Verification and acceptance
---------------------------
Run:

    python -W error::ResourceWarning -m unittest -v test_app.py

The suite contains exactly 20 offline/mock contract-class tests. It verifies
deterministic application behavior and mocked structured semantic decisions; it
is not a real DeepSeek semantic acceptance run.

MEMORY_ACCEPTANCE_SUITE.md defines the authoritative 20 manual/semantic cases
and distinguishes HARD, OPTIONAL and HARD SAFETY requirements. OPTIONAL safe
degradation is not the same as full semantic success. TEST_RESULTS.txt records
the final automated evidence, the 20-case acceptance checklist, the SX-01 to
SX-42 traceability matrix, restore-drill evidence, and any verification that was
not executed.
