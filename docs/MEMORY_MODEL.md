# Memory Model

## Authority layers

The system keeps five concepts separate:

1. **Current Memory** — authoritative committed persistent state.
2. **History** — committed predecessors of a stable lineage; never Current.
3. **Pending Semantic Confirmation** — an immutable proposed mutation; never
   Current before Confirm.
4. **Clarification and recent conversation** — session-scoped context, not
   authoritative long-term state.
5. **Audit** — immutable operational evidence, not memory content.

## Ledger and bi-temporal core

`memory_core.py` implements the isolated Phase 1A structured ledger:

- `memory_events` is the immutable logical event ledger with an idempotency
  key and request hash.
- `structured_facts` stores fact versions.
- `valid_from` and `valid_to` describe when a fact is true in the modeled
  world.
- `system_from` and `system_to` describe when the system recorded that version.
- A partial unique index permits only one open Current fact for a
  `(user_id, subject, attribute)` tuple.

This distinguishes a backdated correction from the time at which it was
entered. Event replay with the same payload is idempotent; reusing an event ID
with another payload is rejected.

The browser runtime in `app.py` uses its schema-v6 `MemoryStore`, stable
lineages, explicit Current/History tables, and per-user revision. The Phase 1A
ledger is used by the boundary and integration gates; it does not replace the
runtime store.

## Typed Current state

| Family | Canonical shape | Representative operations |
|---|---|---|
| Scalar | `{"value": scalar}` | `CREATE_SCALAR`, `SET_VALUE`, `REASSERT_NOOP`, `DELETE_MEMORY` |
| Set | `{"items": [...]}` | `CREATE_SET`, `ADD_ITEM`, `REMOVE_ITEM`, `REPLACE_SET`, `DELETE_MEMORY` |
| Count | `{"value": integer}` | `CREATE_COUNT`, `SET_COUNT`, admitted deltas, `DELETE_MEMORY` |
| Record | `{"fields": {...}}` | `CREATE_RECORD`, `SET_FIELD`, `DELETE_FIELD`, `DELETE_MEMORY` |

Relation membership is represented through Set state; there is no separate
relation table. Removing the last Set item yields explicit `[]`. Removing the
last Record field yields explicit `{}`. Neither operation implicitly deletes
the lineage.

## Stable identity

- `memory_id` is the only authoritative lineage identity.
- UPDATE preserves `memory_id` and archives the complete predecessor.
- DELETE targets one explicit lineage and cannot affect unrelated lineages.
- Text similarity, shared values, subject parsing, aliases, and fuzzy matching
  are not identity mechanisms.
- Registry-managed metadata is exact and versioned; it does not replace
  `memory_id`.

## History

History contains complete committed predecessor state for the same lineage.
It is written only when a confirmed operation actually changes Current.
Same-value reassertions, reads, proposals, cancellation, clarification, and
failed turns do not create History. A confirmed whole-memory forget removes the
target Current lineage and its linked History according to project policy.

## Revision model

Each user has an authoritative revision:

- Increment exactly once when committed Current state actually changes.
- Do not increment for reads, clarification, proposal creation, cancellation,
  `NOOP`, validation failure, provider failure, or rollback.
- A provider turn and a proposal both capture a base revision.
- A mismatched revision rejects the commit rather than overwriting newer state.

## Proposal lifecycle

An immutable semantic proposal records the complete commit identity, including
proposal, user, session, base revision, purpose, destructive flag, payload
version, target or preallocated CREATE `memory_id`, registry metadata, state
type, operation, and canonical arguments.

```text
PENDING_REVIEW -> CONFIRMED
PENDING_REVIEW -> REJECTED
PENDING_REVIEW -> CANCELLED
PENDING_REVIEW -> EXPIRED
```

- Creation never changes Current, History, or revision.
- Confirm reuses the persisted payload; it does not reconstruct semantics from
  prose and makes zero provider calls.
- Correct creates a new immutable proposal identity.
- Reject, Cancel, and Expire do not mutate Current.
- Duplicate Confirm is idempotent where the service exposes idempotent replay;
  conflicting or stale confirmation cannot overwrite newer state.

## Conversation state

Recent messages are scoped by `user_id + session_id`. Long-term memory is
scoped by user and may be retrieved from a new session. A new session does not
inherit the previous session's recent messages or pending proposal. Failed
turns are atomic: their user message must not be persisted into the next
request context.

## Audit model

`memory_audit.py` stores append-only events in a separate SQLite database.
SQLite triggers reject UPDATE and DELETE of audit events. Events carry safe
identifiers, status, entity ID, and bounded reason-code details. The audit store
does not contain raw secret values and is queried by user scope.

Tracked events include proposal creation/confirmation/rejection/expiration,
memory creation/update/rejection, and validation failure. Counters and latency
observations are aggregated by the observability service without changing
memory semantics.

## Limits

- Current memories: 20 per user.
- Scalar strings and Set items: 160 Unicode characters.
- Set items: 50.
- Record fields: 20; field names: 80 characters.
- Count: integer from 0 through 1,000,000,000.
- Serialized typed state: 4,096 UTF-8 bytes.
- User input: 4,000 characters.
- Output budget: 4,096 tokens.
- Recent context: six user/assistant turns, no more than 12 messages and about
  12,000 characters.
- Rendered History: latest 10 predecessors per user.

