# Explore your team's memory

Open Developer Studio, connect with your private bearer and choose a named
project. The project is an existing Loomline `Task`; its internal ID is still
available for API calls and copying. The name is the primary navigation label.
Choose **Memory Graph** to explore the records FalkorDB actually persisted.

The graph is a bounded view of one authorized project. It is not a picture of
the whole database, a model's hidden reasoning or a reconstructed transcript.
An empty project correctly has no memories or provenance paths yet. Follow
[START_HERE](getting-started.md) to record the first memory, or
[Connect your agent](connect-agents.md) to let your own agent invoke the tools.

## Find and inspect a memory

1. Select the project and open **Memory Graph**. Start with the displayed
   project name and memory labels rather than raw technical IDs.
2. Select a memory node. Its details identify its class, assertion, current
   status, content, author and timestamps when those properties exist.
3. Open the memory's provenance. Follow the source turn/session, actual
   supporting and challenging evidence, lifecycle events and related handoffs.
   A memory without supporting evidence is shown without an evidence edge.
4. Select an edge to read its relationship name and plain-English meaning.
   Neighbor highlighting helps follow one real path through a busy graph.
5. Use zoom, pan and **Fit graph** to change the view. Filtering or focusing changes
   the records displayed; it does not edit or delete graph data.
6. Open **Graph Query** to inspect the read-only operation that retrieved this
   view. Keep the query inspector and selected records together when explaining
   a result to a teammate or judge.

The default **Memory paths** mode emphasizes authors, source turns, memory,
evidence and handoffs. Choose **All project records** to include loaded task
membership, claims and diagnostic events. “All” still means this bounded view,
not the entire project or tenant. **Jump to a record** and **Inspect a
relationship** provide keyboard-accessible selection alongside the canvas.
Use **Expand connected records** to request a bounded neighborhood, or
**Load older memories** for the next page.

The default page starts with two memories and their actual provenance paths.
Context and diagnostic records may also be loaded but are displayed separately
in **All project records**. The visible and loaded counts describe different
sets. At the 250-record browser cap, **Next memory page · reset view** replaces
the current view so the cursor remains usable. Expanding a record switches to
the bounded all-record view; it does not scan the entire tenant.

On a narrow screen, use the selected record's details and filters to
inspect a smaller neighborhood rather than trying to read every edge at once.
Technical IDs and `loom://` memory references remain available for copying.

## What the nodes mean

| Displayed record | Actual FalkorDB label | What it establishes |
|---|---|---|
| Project | `Task` | The authorized collaboration scope, name and status. |
| Agent | `Agent` | A server-provisioned identity. Being authorized does not prove it contributed. |
| Session | `Session` | A persisted execution context owned by one agent; not live presence. |
| Explicit turn | `Turn` | Content deliberately recorded through Loomline, not the client's complete private conversation. |
| Episode, fact/hypothesis/decision, procedure | `Memory` | The class/assertion/status properties distinguish the three memory lifecycles. |
| Evidence | `Evidence` | Recorded content, source reference and observation time. It is attributed evidence, not automatic truth certification. |
| Work claim | `WorkClaim` | Current work key, principal owner, lease and version. It does not lock a filesystem. |
| Handoff | `Handoff` | Durable assignment and versioned status: open, accepted, done or cancelled. |
| Lifecycle event | `MemoryEvent` | An actual recorded memory/claim/handoff change and actor. |
| Entity | `Entity` | A domain subject/dependency only when the task contains one. |
| MCP activity | `MCPCall` | Tool, authenticated actor/session, safe outcome/error and timing; no secret or tool-argument payload. |

The explorer does not invent separate `Hypothesis`, `Procedure`, `Challenge`
or `Project` database labels. A challenge is the actual
`Memory → CHALLENGED_BY → Evidence` relationship plus its lifecycle event.
Not every node type exists on every project.

## Follow authentic relationships

| Path or relationship | Plain-English interpretation |
|---|---|
| `Task → ASSIGNED_TO → Agent` | This identity is authorized for this project. |
| `Agent → HAS_SESSION → Session → HAS_TURN → Turn` | This agent owned the session where this explicit turn was recorded. |
| `Task → HAS_MEMORY → Memory` | The memory belongs to this project. |
| `Agent → CREATED → Memory` | This authenticated author created the memory. |
| `Memory → DERIVED_FROM → Turn` | The memory cites this recorded source turn. |
| `Memory → SUPPORTED_BY → Evidence` | This evidence was attached as support. |
| `Memory → CHALLENGED_BY → Evidence` | This evidence was attached as a challenge; inspect the current status and events. |
| `Memory → SUPERSEDES → Memory` | A replacement links back to an earlier memory; inspect each record's actual status. |
| `Handoff → REFERS_TO → Memory` | This handoff explicitly references the memory. |
| `Handoff → ASSIGNED_TO → Agent` | This identity is the handoff recipient. |
| `Memory → ABOUT → Entity → DEPENDS_ON → Entity` | The task contains an explicit subject/dependency path. |
| `MemoryEvent → RECORDS / ANNOUNCES_HANDOFF` | The event explicitly targets the linked record. |
| `MCPCall → IN_SESSION → Session` | This recorded tool call ran in that persisted session. |

The graph displays actual returned edges. Shared project membership alone is
not a direct “used this memory” edge. A claim's current owner is a property;
the explorer does not manufacture an ownership relationship. Evidence source
metadata is a property, not a fictional `Evidence → Turn` edge. The complete
implemented schema is in [GRAPH_MODEL](graph-model.md).

## Understand who participated

The collaboration overview separates:

- **Authorized agents:** enabled identities assigned to the project.
- **Contributors:** identities with recorded work activity in the inspected
  project, rather than identities with only an assignment or an empty session.
- **Sessions:** historical runs; their existence does not mean the application
  is connected now.
- **Recent recorded activity:** timestamped events within the returned window,
  rather than a live-presence indicator.

Client names/framework metadata are self-declared. A principal named `codex`
does not prove a Codex binary executed the call. Explicit `TEST-CLIENT` content
and synthetic task markers identify test activity where stored; old records
without those markers remain unverified rather than being guessed real.

The owner separately confirmed the historical Codex CLI + Antigravity CLI run.
That confirmation is distinct from automated protocol tests. Do not present an
independent MCP test session as a real vendor application run.

## Read the collaboration timeline honestly

The overview timeline assembles persisted memories, explicit turns, handoffs,
claim events and recorded MCP calls. Expand an item to inspect its actual
record, actor, timestamp and evidence basis. A completed handoff and its
transition events can show continuity across sessions even after both original
processes have stopped.

A recorded successful `get_context` call establishes that an authenticated
session requested context. MCP audit deliberately does not store arguments or
output, so it cannot alone prove the exact memories that model received or
which one caused an edit. A later agent-authored turn saying it used earlier
context is **reported use**. Source links, evidence links and handoff references
are **persisted relationships**. Do not merge those two kinds of evidence.

To explain an actual memory-to-action sequence:

1. Select Agent A's source-linked decision/observation and inspect its content.
2. Follow the actual source/session/author edges to establish who recorded it.
3. Inspect Agent B's recorded retrieval activity and explicit explanation of
   what it learned, if that explanation exists.
4. Inspect B's resulting memory, source and evidence rather than assuming an
   action occurred because both agents appear in the same project.
5. Follow any actual handoff reference and its versioned transition history.
6. Inspect the fresh session's recovery/verification records, if present.

This lets a reviewer distinguish “the graph persisted these facts,” “the agent
reported using these facts” and “this particular action has independent recorded
evidence.” If the linkage is missing, say so. Loomline does not infer causality
from proximity in time or visual position on the canvas.

## Inspect how FalkorDB retrieved the view

**Graph Query** shows backend-defined parameterized Cypher, safe bound scope
parameters, row counts and the returned records. These are the operations used
for the current view, not an editable Cypher console. Every graph request first
checks the credential task allowlist and enabled task membership in the
server-selected tenant graph.

The read-only graph endpoint is:

```text
GET /v1/tasks/{task_id}/graph
```

It accepts `limit` (1–40 memory anchors), an opaque `before` cursor and optional
`agent_id`, `memory_class`, `relationship`, timezone-qualified `since`, or
`focus` on an actual project node, with `focus_type` when needed. Node `key`
values include the real label and ID so two labels with the same raw ID remain
distinct. Edge endpoints use those keys; raw IDs/types remain available. A raw
focus ID that is ambiguous across labels requires its type. The response
includes real `nodes`, `edges`,
the selected memory IDs, `next_cursor`, executed `queries` and explicit
`bounds`. Authentication belongs in the bearer header, never the URL.

Filters choose the primary memories and related context. Linked author/source
and other necessary neighboring records can still appear, so an agent filter
is not a claim that every visible node was authored by that agent. Selecting a
relationship filters the matching path/view; absence can mean “not in this
bounded view,” not “does not exist anywhere.”

Context recall is a separate public SDK operation, `get_context`/`recall`; it
returns typed bounded memory plus coordination/history context for agents.
The visualization is a projection for human inspection, not proof that its
entire visible result was injected into a model. Known memory references can
also be resolved or traced directly through the authorized API.

## Work with large projects

The server caps a graph response at **250 nodes and 400 edges**, with up to
**40 primary memory anchors**, bounded two-hop expansion and at most eight
context records per supported contextual type. The returned bounds/truncation
metadata makes omitted records explicit. The API default is 20 primary
memories; Studio begins with four to keep the first view readable, then lets
you load older memories or expand a neighborhood.
The browser never requests an entire tenant graph.

Use a narrower author, memory class, relationship or time filter; select a
record and focus its neighborhood; or load an older memory page using the
returned cursor. A dense or truncated result is a reason to explore smaller
paths, not to interpret missing edges as deleted data. Filters and cursor scope
must remain consistent; start a fresh page after changing filters.

The collaboration endpoint is also bounded:
`GET /v1/tasks/{task_id}/collaboration`. Its response supplies the overview,
authorized identities, contributors, real timeline evidence and query metadata.
Counts and activity are historical observations rather than live connectivity.

## Permissions, privacy and common empty states

- A **viewer** can inspect authorized project graphs, provenance and timeline,
  but cannot create sessions, memories, claims, handoffs or model requests.
- A working agent sees only its tenant and allowed assigned projects. A copied
  task/node ID never grants access; inaccessible records return a safe error.
- The default stack binds loopback. No arbitrary Cypher execution or public
  token-file read endpoint is provided.
- A disconnected browser needs a valid bearer entered in the masked field.
  Studio keeps it only in page memory; reload/disconnect clears it.
- An empty project needs a first real memory. No incident or demo entities are
  fabricated to decorate its graph.
- A record outside the current page/filter may need focused retrieval or a
  known URI. A retired procedure may be absent from active context while still
  resolvable as history.

Private source/evidence prose can itself contain sensitive project information.
Review what is visible before sharing a screenshot even though tokens are
excluded. Use [STUDIO_AUTH](security.md) for provisioning, viewer setup and
revocation, and [FINAL_USER_ACCEPTANCE_REPORT](verification.md)
for measured correctness, isolation, browser checks and remaining limitations.
