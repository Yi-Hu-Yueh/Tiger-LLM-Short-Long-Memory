# Operations

## Runtime prerequisites

- Windows with Python 3.14-compatible standard library support.
- A DeepSeek API key for live chat.
- Local access to the project directory.
- Port `18080` available on localhost when using `start.cmd`.

No frontend framework, vector service, or third-party runtime package is
required by the browser prototype.

## Startup

From the project root:

```bat
set DEEPSEEK_API_KEY=your-key
start.cmd
```

Open `http://127.0.0.1:18080/`.

`start.cmd` changes to the project directory and runs `python app.py --port
18080`. The configured endpoint and model remain the existing DeepSeek chat
completions endpoint and `deepseek-v4-pro`.

For managed operational validation, `MemoryOperationsManager` requires:

- distinct core and audit database paths;
- an environment in `development`, `test`, or `production`;
- an environment-marker file whose content exactly matches that environment;
- valid SQLite integrity and the supported schema version;
- required proposal and audit tables;
- only the approved users;
- protected-filename rules appropriate to the environment.

Startup fails closed if any check fails. Validation does not silently create a
missing database.

## Shutdown

Stop the foreground process with `Ctrl+C`. Runtime database work uses
short-lived context-managed connections. The operations manager additionally
probes that core and audit databases can acquire and roll back a short write
transaction, checkpoints WAL state, clears runtime handles, and verifies
cleanup. Repeated shutdown is idempotent.

## Database safety

Protected databases include `memory.db`, `final_acceptance.db`,
`memory_after_restore_baseline.db`, and `real40_v2.db`. Tests, smoke runs, and
recovery drills must use explicit temporary or dedicated test databases.
Protected databases should be hashed before and after read-only release
verification and must not be opened through SQLite by test tooling.

## Backup

`MemoryRecoveryService` creates paired SQLite backups for a dedicated core and
audit database plus a manifest containing:

- recovery ID and creation time;
- core and audit filenames and SHA-256 hashes;
- per-user revision metadata;
- proposal count;
- audit sequence.

The recovery gate deliberately rejects protected production filenames. Use it
for explicit test or staging databases. A production backup of `memory.db`
requires a separately approved operator procedure; do not rename or copy a
protected database into the recovery gate merely to bypass this restriction.

## Restore

For an admitted dedicated database:

1. List and select an existing recovery point.
2. Verify its manifest, file hashes, SQLite integrity, revisions, proposal
   count, audit sequence, and user isolation.
3. Restore into staging files.
4. Verify staged integrity.
5. Create rollback copies of the live dedicated databases.
6. Replace both databases using SQLite backup operations.
7. Re-run integrity verification.
8. On any failure, restore the rollback copies.

Never restore over a protected production database using the test recovery
service.

## Recovery and integrity checks

Integrity verification checks SQLite integrity, non-negative revisions, one
active canonical slot per scope, valid proposal references, required revision
rows, audit sequence ordering, and the approved user scope. A corrupted
manifest or hash mismatch blocks restore.

## Observability

The audit/metrics layer exposes deterministic counters for memory writes,
validation failures, proposals, and expirations. Latency categories include
extraction, validation, commit, context retrieval, and decision generation.

`ObservabilityService` evaluates:

- `HEALTHY`: no corruption or isolation failure and thresholds remain normal;
- `WARNING`: elevated failure ratio, rollback count, or latency;
- `CRITICAL`: corruption, isolation failure, or repeated rollback failure.

Alerts include `MEMORY_CORRUPTION`, `USER_ISOLATION_FAILURE`,
`HIGH_FAILURE_RATE`, `HIGH_LATENCY`, and `REPEATED_ROLLBACK_FAILURE`.

## Testing

Required deterministic regression:

```bat
python -W error::ResourceWarning -m unittest -v test_app.py
```

Focused Phase 5B benchmark-tool tests:

```bat
python -W error::ResourceWarning -m unittest -v test_memory_benchmark.py
```

The extended offline suite uses pytest when available:

```bat
D:\python3.11.3\python.exe -W error::ResourceWarning -m pytest -q
```

Real-provider tests are disabled by default and must not be enabled as part of
routine release verification. Mock/offline success is not real DeepSeek proof.

## Troubleshooting

### Startup reports a missing or invalid database

Confirm the configured path and environment marker. Do not let a validation
command create an empty replacement. Check the SQLite file using an approved
copy, not a protected production database.

### Unsupported schema version

Stop. Do not edit `PRAGMA user_version` manually. Use the tested application
migration path on an isolated copy and preserve the pre-migration backup.

### Pending proposal cannot be confirmed

Check user, session, proposal identity, status, base revision, and Current
preconditions. Stale proposals intentionally fail closed and must not be forced.

### Provider, JSON, or schema error

The attempted turn should leave conversation and all memory authority layers
unchanged. Correct provider configuration or input and start a new turn; do not
manually insert a partial message or memory row.

### Memory answer appears semantically wrong

Separate deterministic rendering from model selection. SQLite rendering can be
correct while the model chose the wrong intent or valid ID. Do not add a
case-specific parser or fuzzy identity repair.

### Health is CRITICAL

Stop writes, preserve database and audit hashes, collect privacy-safe reason
codes, and perform integrity checks on approved copies. Do not continue after a
corruption or isolation alert.

