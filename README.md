# Tiger Short/Long Memory

Tiger Short/Long Memory is a local SQLite prototype for safe short-term and
long-term conversational memory. Its active product mode is a
**Human-Reviewed Memory Assistant**: the model may propose a semantic memory
change, but only an explicit local Confirm can commit that proposal to
authoritative Current Memory.

Production automatic semantic writes are disabled. A frozen held-out benchmark
observed one unsafe auto-commit and triggered the project's mandatory stop rule.

## Architecture summary

```text
User input
  -> DeepSeek semantic extraction
  -> structural / grounding / registry validation
  -> deterministic compiler and typed preconditions
  -> immutable Pending Semantic Confirmation
  -> explicit local Confirm
  -> atomic SQLite Current / History / revision commit
  -> Current-only context
  -> bounded answer, decision, and tool gates
```

The model never writes SQLite directly. Stable `memory_id` identifies a
lineage. Current, History, Pending Proposal, Clarification, recent conversation,
and audit evidence remain separate authority layers.

Detailed documentation:

- [Structured Memory V2 local MVP](docs/STRUCTURED_MEMORY_V2.md)
- [Structured Memory V2 release status](docs/STRUCTURED_MEMORY_V2_RELEASE_STATUS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Memory model](docs/MEMORY_MODEL.md)
- [Security](docs/SECURITY.md)
- [Operations](docs/OPERATIONS.md)
- [Validation report](docs/VALIDATION_REPORT.md)
- [Final project status](docs/FINAL_PROJECT_STATUS.md)
- [Release checklist](RELEASE_CHECKLIST.md)
- [Release freeze](RELEASE_FREEZE.md)

## Quick start

Requirements:

- Windows
- Python 3.14-compatible runtime
- `DEEPSEEK_API_KEY` for live chat

From the project directory:

```bat
set DEEPSEEK_API_KEY=your-key
start.cmd
```

Open `http://127.0.0.1:18080/`.

The runtime uses `deepseek-v4-pro`, the existing DeepSeek chat-completions
endpoint, disabled thinking, and a maximum output budget of 4,096 tokens.
Confirm and Cancel make zero provider calls.

## Testing

Required 20-test regression:

```bat
python -W error::ResourceWarning -m unittest -v test_app.py
```

Phase 5B benchmark-tool tests:

```bat
python -W error::ResourceWarning -m unittest -v test_memory_benchmark.py
```

Extended offline suite when pytest is available:

```bat
D:\python3.11.3\python.exe -W error::ResourceWarning -m pytest -q
```

Real-provider gates are opt-in and disabled by default. Do not treat mock or
offline results as live DeepSeek evidence. Tests must use explicit temporary or
dedicated databases and must not open protected production databases through
SQLite.

## Safety model

- Only `user1` and `user2` are admitted.
- Model-derived changed writes require an immutable proposal and explicit
  human confirmation.
- Confirm revalidates user, session, proposal identity, revision, Current state,
  typed preconditions, and exact persisted payload.
- Provider, schema, validation, firewall, revision, and database failures leave
  the attempted turn unchanged.
- Configured credential-like attributes are rejected by the Phase 1B/4D
  validation gates; the product does not claim universal detection or
  prohibition of arbitrary sensitive personal facts. Prompt-injection
  attempts cannot bypass the memory write boundary.
- No write transaction is held while waiting for the provider.
- Audit details use privacy-safe tokens and must not contain raw secrets.
- Production auto-commit and the archived automatic benchmark are locked.

## Supported memory model

The typed runtime supports Scalar, Set, Count, and Record state. Replacements
preserve stable lineage and archive complete predecessors. Relation membership
is represented through Set state. Same-value reassertions are `NOOP` operations.
Destructive operations are visibly marked and remain pending until Confirm.

## Current limitations

- This is a localhost prototype, not a multi-tenant production service.
- User scope is fixed to `user1` and `user2`.
- Natural-language intent, slot, target, claim-shape, and literal selection
  remain model-semantic and can be wrong while structurally valid.
- Human confirmation is an authorization step, not proof of objective truth.
- No vector database, embeddings, RAG, summary memory, procedural memory,
  LangGraph, multi-agent runtime, or self-learning is included.
- Operational, audit, recovery, decision, action, and benchmark modules are
  focused gates; not every gate is automatically composed into `start.cmd`.
- Bonsai 2 27B was unavailable during Phase 5B, so no DeepSeek-versus-Bonsai
  comparison exists.
- Automatic semantic memory failed its frozen safety benchmark and must remain
  disabled for the current architecture/model.

## Governance

Memory behavior is governed by:

- `MEMORY_CONSISTENCY_SPEC.md`
- `MEMORY_SEMANTIC_CONTRACTS.md`
- `MEMORY_ACCEPTANCE_SUITE.md`

Architecture and implementation plans do not override these documents. Any
future semantic change must follow their change-control process before runtime
code changes.
