# Structured Memory V2 — validated local MVP

Structured Memory V2 is a separate localhost interface for **explicit structured fields**, typed deterministic operations, and SQLite persistence. It does not interpret arbitrary natural-language memory requests and does not require DeepSeek. It is not an enterprise production deployment.

## Launch

From the repository root, with the project's Python interpreter:

```bat
D:\0TIGER\6months\PythonAPIDevelopment\venv_multi_query\Scripts\python.exe structured_app.py --db data\structured_ui\structured_memory.db --port 18081
```

Open `http://127.0.0.1:18081/`. The server binds to localhost by default and prints the selected database path. For validation, always pass a dedicated disposable `--db` path; never use a protected chat or release database. Stop the server with Ctrl+C. Restart with the **same** `--db` path to retrieve committed state. Prepared, unconfirmed UI tokens are ephemeral and are not restart-persistent.

## Supported operations and authority

- Select `user1` or `user2`; each user's lists, reads, and writes are isolated.
- Scalar: create, update, same-value no-op, Read Current, and Read Previous. A changed update preserves the stable `memory_id`; Previous is the immediate committed predecessor and never falls back to Current.
- Named collection: create, add, remove, re-add, list members, and count active members. A member identity is scoped to its collection; counts are derived from active named memberships.
- Count-only collection: create with an explicit non-negative declared count and read that count. It has no named members, and member actions are unavailable/rejected. Changing the declared count is not supported in this MVP.
- Changed operations require Prepare → preview → explicit Confirm. Cancel, stale Confirm, invalid ownership, and duplicate Confirm do not commit a change. The UI does not send model requests.

Stable `memory_id` is lineage identity. Semantic keys and entity IDs are structured descriptors, not substitutes for the stable ID; two entities may use the same key independently. Current and History are committed SQLite state. A preview is not Current.

## Validation and limits

The S3 release gate used an isolated disposable database, a long browser session, a clean server restart, and read-only post-restart inspection. `structured_integrity.check_structured_integrity(path)` opens an **existing non-protected** database in SQLite read-only mode and checks SQLite integrity, required schema objects, scalar and membership predecessor chains, current-version uniqueness, ownership, collection scope, and count-only identity safety. It never creates or repairs a database.

Run the focused offline regressions with the project interpreter:

```bat
python -W error::ResourceWarning -m pytest -q tests/test_memory_v2_core.py
python -W error::ResourceWarning -m pytest -q tests/test_structured_app.py
python -W error::ResourceWarning -m pytest -q tests/test_structured_collections.py
python -W error::ResourceWarning -m pytest -q tests/test_structured_release.py
```

This release excludes arbitrary natural-language memory mutation and read routing. The failed V2-1A semantic-adapter experiment is **not** imported, integrated, or part of the release. The Structured Memory V2 feature scope is frozen after S3: bug fixes only unless a new phase is explicitly approved; no case-by-case semantic features or adapter integration.
