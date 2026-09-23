# Structured Memory V2 release status

Classification: **Validated Structured Memory V2 Local MVP**. This status applies only to the explicit structured UI → typed deterministic operations → V2 core → SQLite path. It is not a claim of natural-language memory conformance or enterprise production readiness.

| Gate | Result |
| --- | --- |
| Structured Memory V2 | PASS |
| Deterministic Core (V2-0R) | PASS — 12/12 strict tests |
| Structured Scalar UI (S1) | PASS — 19/19 strict tests |
| Structured Collection UI (S2) | PASS — 26/26 strict tests |
| S3 release integration | PASS — 3/3 strict tests |
| Persistence / restart | PASS — same isolated DB, fresh browser session |
| End-to-end manual browser acceptance | PASS — one long structured session, no reset |
| SQLite and V2 read-only integrity | PASS — no issues |
| ResourceWarning strict mode | PASS — all 60 relevant tests |
| Changed-Python `py_compile` | PASS |
| Natural-language semantic adapter | NOT INCLUDED — failed V2-1A experiment remains separate |
| DeepSeek | NOT REQUIRED — 0 calls |

Manual release evidence: user1 scalar release anchor retained `A → B → C` under one `memory_id` after restart, with Current `C` and Previous `B`; an unrelated scalar and two same-key entities remained independent. Named collections retained a shared member in both scopes after remove/re-add in only one; active counts were 3 and 1. The count-only collection retained declared count 4 without named identities or enabled member actions. Cancel, duplicate add, and stale confirmation caused no unintended mutation. Equivalent entity/key and collection/member descriptors under user2 remained isolated. Final browser reads did not change the disposable DB's SHA256. The disposable S3 DB was deleted after validation.

Feature scope is frozen: no new semantic features, arbitrary-language adapter integration, or case-specific additions. Only bug fixes are in scope without a separately approved phase. Historical evidence for the failed natural-language architecture is unchanged.
