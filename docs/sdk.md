# Loomline Python SDK 0.1.0

Public memory contract 0.1: [full semantics](memory-contract.md). Install `pip install -e packages/loomline-sdk`; import `LoomlineClient` / `AsyncLoomlineClient` from `loomline`. Core dependencies HTTPX 0.28.1 and Pydantic >=2.11.4,<3; tested Python 3.12. All I/O is authenticated HTTP. SDK does not read environment files, import the backend, access FalkorDB directly, or require a model.

## Client and records

`LoomlineClient(base_url, token=..., timeout=30, max_attempts=3, transport=None)` is a context manager; `close()` releases its HTTP pool. Async equivalent uses `async with`, awaited calls and `aclose()` (`close` alias). Session contexts do not close the enclosing client or delete server history. Base URL rejects userinfo/query/fragment, redirects are disabled, proxy environment is not implicitly trusted. Token repr is redacted. Keep tokens out of URLs and source.

Responses are JSON-compatible `Record` dictionaries with attribute access. Receipt `.id` aliases `memory_id`, `session_id`, `turn_id`, `handoff_id` or `event_id`. `.reference` retains the server URI. `.outcome` derives CREATED/REPLAYED from mutation response status, without altering equality or the JSON payload; ignore outcome on ordinary reads. Full memory reads are validated against `MemoryRecord`: id, reference, task_id, class (`memory_class` attribute alias), assertion_type, status, content, created_by, source_turn_id, optional session_id, version, support/challenges and optional wire fields. `MemoryInput` validates the class/assertion/status matrix and procedure steps before HTTP.

## Operation surface (sync and async)

| Group | Methods |
|---|---|
| Discovery | `health()`, `whoami()`, `capabilities()`, `model_status()`, `list_scopes()` |
| Tasks | `list_tasks(after=None, limit=50)`, `create_task(title, assigned_agent_ids=..., synthetic=False, template='blank', operation_id=None)`, `agents(task_id)` |
| Sessions | `start_session(task_id, operation_id=None)`, `session(task_id, operation_id=None)`, `register_framework(session_id, framework, framework_version, operation_id=None)`, `list_sessions(task_id, after=None, limit=100)` |
| Conversation | `record_turn(session_id, role, content, tool_name=None, tool_call_id=None, operation_id=None)`, `get_history(task_id, before=None, limit=20)`, `session_turns(session_id, after_seq=0, limit=100)` |
| Memory | `remember(task_id, session_id=..., source_turn_id=..., memory_class=..., assertion_type=..., status=..., content=..., operation_id=None, evidence_ids=..., entity_ids=..., steps=..., supersedes_id=...)` |
| Convenience | `observe`, `remember_episode`, `remember_fact`, `hypothesize`, `propose_procedure`; content is positional after task_id, references/source are keyword arguments |
| Read | `recall` / `get_context(task_id, query=None, limit=10, entity_id=None)`, `get_memory(task_id, memory_id)`, `resolve(memory_reference)`, `trace(memory_reference)`, `decision_context(task_id, entity_id='checkout')` |
| Evidence | `record_evidence(task_id, content=..., source_type=..., source_ref=..., observed_at=..., operation_id=None)`, `challenge` / `support(task_id, memory_id, evidence_id=..., reason=..., expected_version=..., operation_id=None)` |
| Lifecycle | `approve_procedure` / `retire` / `supersede(task_id, memory_id, expected_version=..., reason=..., operation_id=None)` |
| Coordination | `handoff(task_id, to_agent_id, description, related_memory_ids=..., operation_id=None)`, `get_handoff(task_id, handoff_id)`, `accept_handoff` / `complete_handoff` / `cancel_handoff(task_id, handoff_id, expected_version=..., operation_id=None)` |
| Notifications | `subscribe(task_id, enabled=True, operation_id=None)`, `get_inbox(after=None, task_id=None, limit=100)`, `mark_inbox_read(inbox_id, operation_id=None)` |
| Recovery | `operation_status(task_id, operation_id)`, `resume_task(task_id, cursor=None, limit=10)`, `context_pack(task_id, goal=..., max_tokens=2048, memory_classes=('episodic','semantic','procedural'))`, `changes_since(task_id, cursor=None, limit=50)`, `watch(task_id, cursor=None, poll_interval=1, max_polls=None)` |
| Iteration | `iter_history(task_id, before=None, limit=100)`, `iter_sessions(task_id, after=None, limit=100)`, `iter_inbox(after=None, task_id=None, limit=100)`; async counterparts are async generators |
| Optional reasoning | `reason(task_id, session_id, goal=..., purpose='investigate', operation_id=None)`; server-selected role/model, validated JSON action; requires live configuration. `include_shared_memory=False` is restricted to `purpose='continuity_trial'` for the explicit comparison. `infer` retains legacy demo behavior. |

`source_type`, identifiers, field bounds and role permissions are enforced by the server's actual OpenAPI schema. `create_task` requires coordinator; `template='checkout'` requires synthetic=True and is an opt-in lab fixture, never the default for developer tasks. Framework metadata is self-declared session metadata, not a live presence attestation.

## Friendly sessions and provenance

```python
with client.session(task_id) as session:
    observation = session.observe("The build passed", operation_id="build17_observation")
    hypothesis = session.hypothesize("Deployment might explain the regression")
    source = session.record_turn("tool", "Visible result of a real tool")
    fact = session.remember_fact("Tool returned 5xx", source_turn_id=source.turn_id)
```

An omitted source creates a visible source turn first, then memory. These are separate writes; a failed memory leaves its source turn intact. For retry across process crashes, persist the same operation ID. The corresponding source-turn operation is deterministically derived from it. Explicit source IDs must belong to the actor's owned task session. Public system/developer roles are rejected; hidden model reasoning is never a source.

Facts are authored semantic observations, not automatic truth certification. Hypotheses start proposed; support adds evidence and a new version without promoting them. A challenge preserves original support and marks the claim disputed. Only coordinators publish decisions/procedures and approve procedures. Retirement applies to supported procedural transitions. To supersede, create a real replacement using supersedes_id, then perform the separate authorized CAS transition on the original. No deletion endpoint is offered.

## Durable continuity

`resume_task` reads bounded historical turns/context and starts a new owned session; it never copies another agent's identity/checkpoint. Its `cursor` is the history `before` cursor, not a change-feed cursor. Page older history explicitly if needed. Recall uses bounded graph/task/substring filtering, not embeddings. Bundles are per-query snapshots, not one multi-query transaction.

Context packs rank goal-term overlap, approved/disputed status, actual graph evidence links, recency and ID. They preserve source/reference/status/support/challenge labels and mark retrieved data untrusted. Budgets 256–8192 use ceil(UTF-8 JSON bytes / 3), an approximation, not a provider tokenizer guarantee. A budget too small even for metadata raises ValidationError. Truncation is explicit.

```python
cursor = load_your_checkpoint()  # None for first delivery
for batch in client.watch(task_id, cursor=cursor):
    apply_events_idempotently(batch["items"])  # deduplicate event IDs
    cursor = batch.ack()
    save_your_checkpoint(cursor)
```

Acknowledgment is local: callers must persist the returned cursor themselves. Until ack, abandoned batches are delivered again on restart. Versioned task event sequences are allocated atomically with modifying queries and survive gateway/router interruptions. Cursors are opaque, tenant/task-bound. Wrong scope -> INVALID_CURSOR, future -> CURSOR_AHEAD, incompatible version -> CURSOR_EXPIRED. Valid current cursors do not automatically expire because no retention deletion runs. Old pre-platform unsequenced events remain in history/trace, outside the new changes feed. Notification fanout is separately eventual/at least once; direct recall does not wait for it.

## Retry/error behavior

Each intent ID and normalized body is built once before retries. Same intent replays the stored receipt; changed payload conflicts. 429/502/503/504 have bounded backoff and Retry-After handling; provider NIM errors are not blindly retried by the SDK. Network loss on a task-scoped mutation first tries operation lookup, then retries the identical intent. If outcome stays unknown, `CommitOutcomeUnknown.operation_id` supports later resolution. Global task creation/turn paths lack a task-path lookup, but their repeated operation IDs remain replay-safe. Never invent a new operation ID merely to overcome uncertainty.

Exceptions: `AuthenticationError` (401), `AuthorizationError` (403), `NotFoundError` (404), `ConflictError` (409), `ValidationError` (400/422 or local input), `RateLimitError` (429), `CommitOutcomeUnknown`, `ServiceUnavailable`, base `LoomlineError`. Safe `.code`, `.status_code`, `.operation_id` are available; headers, bearer strings, raw request/provider bodies are not included. Close/cancel async generators and clients normally; no background watcher thread is started.
