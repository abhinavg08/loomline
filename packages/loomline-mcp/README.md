# Loomline MCP 0.1.0

Local **stdio MCP** tools for authenticated shared memory and coordination.
The server uses the public Loomline SDK and gateway; **FalkorDB remains the
authoritative memory engine**. Coding applications retain their own models.
There is no public MCP HTTP listener, arbitrary Cypher, shell/file tool or
provider-inference tool.

Start with the source distribution's [START_HERE](../../docs/getting-started.md), then
[Connect Your Agent](../../docs/connect-agents.md). The portable default runs this
adapter in Docker, with only one selected identity's private token/profile
directory mounted read-only. The operator generates settings using your actual
checkout directory, without configuring your installed coding applications.
Codex CLI, Antigravity CLI/IDE, Claude Code and generic local stdio clients have
separate guided paths.

For a native process, use a separate Python **3.12** environment and install
the SDK plus this package from the source distribution. Do not combine its MCP
2.2.0 lock with the optional CrewAI dependency set. Given an operator-generated
host profile, run with that environment's interpreter:

```text
python -m loomline_mcp doctor --profile .secrets/connections/NAME/host.profile.json
python -m loomline_mcp --profile .secrets/connections/NAME/host.profile.json
```

`doctor` checks HTTP authorization. The second command waits for MCP JSON-RPC
on stdin; stdout is reserved for valid protocol messages. A private profile
selects one task and a token file. Never embed bearer values in public client
settings, commands or URLs.

The 27 tools include identity/context, explicit turns, three typed memory
classes, evidence, challenges/support, lifecycle changes, atomic work claims,
versioned handoffs, inbox and session recovery. Memory writes retain source
turns. Source-turn creation and memory creation are separate idempotent writes.
Claims fence principals and need lease/version checks. Meaningful conversation
turns must be explicitly recorded; complete coding-agent conversations and
hidden reasoning are not automatically captured.

Follow the guide's independent Docker/native protocol check, then invoke
`loomline_whoami`, record a turn and memory, recall/trace its complete memory
URI and inspect it in Studio's Memory Graph. A passing independent client is
not proof that a vendor application ran. Verify a genuine application call in
your own installation and distinguish it from protocol-test activity.

See the [memory contract](../../docs/memory-contract.md),
[graph guide](../../docs/memory-graph.md),
[identity guide](../../docs/security.md) and
[release acceptance report](../../docs/verification.md).
