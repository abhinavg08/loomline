# Demonstrate Loomline

This walkthrough shows the Track 2 story: independent agents share evolving
knowledge through FalkorDB, coordinate work and recover it in a new session.
Use a fresh named project. No existing private collaboration data is required.

## 1. Start the platform

Follow [Getting started](getting-started.md) through Studio authentication.
Docker is the only host runtime needed. Keep Studio open at the URL reported
by bootstrap; the default is `http://127.0.0.1:8000/`.

## 2. Give two agents their own identities

Run these commands in the repository root:

```text
docker compose --profile app run --rm operator python -m scripts.onboard project --name "Shared-memory demonstration" --description "Independent agents share evidence and recover context" --status active --synthetic
```

Copy the returned `project_id` and replace `PROJECT_ID` below with that value:

```text
docker compose --profile app run --rm operator python -m scripts.onboard identity --project PROJECT_ID --name demo_writer --role investigator
docker compose --profile app run --rm operator python -m scripts.onboard identity --project PROJECT_ID --name demo_reader --role verifier
docker compose --profile app run --rm operator python -m scripts.onboard verify --name demo_writer
docker compose --profile app run --rm operator python -m scripts.onboard verify --name demo_reader
```

Each identity has its own bearer and project-restricted private profile. Token
values stay in `.secrets/`; they are not part of the copied commands.

## 3. Commit and independently recover a memory

```text
docker compose --profile app run --rm operator python -m scripts.onboard first-memory --name demo_writer --content "The implementation must convert milliseconds to seconds before calculating cache expiry."
docker compose --profile app run --rm operator python -m scripts.onboard recall --name demo_reader
```

The writer should report `COMMITTED_AND_RETRIEVED`, a source turn and a
`loom://task/.../memory/...` reference. The reader should recover that memory
under its own identity. These commands execute public SDK operations against
real FalkorDB. They do not invoke a model or prove vendor application execution.

In Studio, select **Shared-memory demonstration → Memory Graph**. Select the
memory and inspect its author, session and explicit source turn. Open
**Graph Query** to see the actual bounded query and returned records.

## 4. Prove persistence

```text
docker compose --profile app stop
docker compose --profile app up -d --wait
docker compose --profile app run --rm operator python -m scripts.onboard recall --name demo_reader
```

The memory and its source must still be present. A new SDK invocation uses a
fresh process; previous process-local memory cannot supply the result. Keep
the named volume intact. Do not run `down -v` or reset a database for this step.

## 5. Show an evolving multi-agent investigation

For a complete native-framework relay, run the
[four-framework lab](connect-agents.md#run-the-complete-native-framework-lab).
It executes **LangChain → LangGraph → CrewAI → fresh custom Python** with four
independent identities. It records a hypothesis, evidence, a challenge, a
procedure-backed decision and a completed versioned handoff.

The default `--offline` mode runs deterministic policies inside the actual
frameworks. All SDK operations and FalkorDB commits are real. The optional
`--live-nvidia` mode uses privately configured role-specific NIM credentials;
it is a separate live model test, not a label for the offline run. Review the
documented optional framework dependency advisories first.

## 6. Connect real coding applications

Use [Connect your agents](connect-agents.md) to provision separate identities
and generate local stdio MCP configuration for Codex, Claude Code or
Antigravity. You configure and launch your own existing applications.

Give each client the same objective:

> Work together on the synthetic cache-expiry exercise in
> `examples/mcp_collaboration`. Before acting, recover Loomline context and
> claim a complementary responsibility. Record observations with source
> evidence, challenge unsupported explanations, and hand off a concrete next
> step. After reconnecting, recover the shared state and independently verify
> the result before completing the handoff. Use separate Git worktrees for
> file changes; shared-memory claims do not lock files.

The [mission](../examples/mcp_collaboration/MISSION.md) defines the deliberately
failing fixture. Its tests are an exercise, separate from the passing product
regression suite. Record genuine tool calls from each application; identity
names and independent protocol tests alone are not software attestation.

## Evidence to capture

| Evidence | What it establishes |
| :--- | :--- |
| Separate `whoami` results | Distinct authenticated principals on one authorized project. |
| Writer receipt + independent recall | A committed memory crosses the agent boundary. |
| Memory trace and graph query | Actual source, author and evidence relationships. |
| Challenge preserving original support | Knowledge evolves without erasing earlier reasoning. |
| Contended claim + complementary claims | Atomic coordination over shared persistent state. |
| Handoff `open v1 → accepted v2 → done v3` | A versioned responsibility transfer. |
| Fresh-session recall after restart | Collective memory outlives a process and session. |

Capture only synthetic task data. Keep credentials, private profiles and provider
responses out of recordings. See [Verification](verification.md) for executed
test results and the exact limits on existing application evidence.
