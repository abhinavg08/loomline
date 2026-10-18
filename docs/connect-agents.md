# Connect your agent

Loomline supplies durable memory and coordination. Your coding application's
existing model continues to run in that application. MCP makes tools available;
the agent must actually call them to save or retrieve anything. A connected
server does not automatically capture conversations, code changes or terminal
output.

Complete [START_HERE](getting-started.md) first. You need a healthy Docker
installation, the extracted Loomline directory, a named project, and its printed
`project_id`. Run all operator commands below **from that directory on the
server's host computer**. They run a trusted local operator container; there is
no public token-issuance endpoint.

## Choose your path

| Agent or runtime | Connection | Continue here |
|---|---|---|
| OpenAI Codex CLI | Local stdio MCP | [Codex](#openai-codex-cli) |
| Google Antigravity CLI | Local stdio MCP | [Antigravity CLI](#google-antigravity-cli) |
| Google Antigravity IDE | Local stdio MCP | [Antigravity IDE](#google-antigravity-ide) |
| Claude Code | Local stdio MCP | [Claude Code](#claude-code) |
| Another MCP client | Local stdio MCP | [Generic MCP](#another-compatible-mcp-client) |
| Custom Python | Authenticated HTTP SDK | [Python](#custom-python-agents) |
| LangChain | Native tools and `create_agent` | [LangChain](#langchain) |
| LangGraph | Native compiled state graph | [LangGraph](#langgraph) |
| CrewAI | Native `Agent`, `Task`, `BaseTool`, `Crew` | [CrewAI](#crewai) |

Use a **different identity for every independent contributor**, including IDE
and CLI instances if you want separate attribution. Sessions sharing a bearer
share one principal and the same work-claim authority. A read-only Studio viewer
cannot initialize MCP because initialization records a session.

## Prepare one independently authenticated MCP connection

The default adapter runs in Docker: **no host Python, Node or Conda is needed**.
Docker must be available to the coding application's environment. Build the
adapter once before opening the client:

```text
docker compose --profile app build mcp
```

Choose a connection name, for example `codex`. Replace `PROJECT_ID` below with
the ID printed when you created your named project. This provisions a fresh
token, an enabled graph identity and assignment to that project. The credential
is restricted to this project and cannot approve procedures.

```text
docker compose --profile app run --rm operator python -m scripts.onboard identity --project PROJECT_ID --name codex --role investigator
docker compose --profile app run --rm operator python -m scripts.onboard verify --name codex
```

Generate configuration using the **actual extracted directory on this host**.
PowerShell:

```powershell
docker compose --profile app run --rm operator python -m scripts.onboard connection --name codex --host-root "$PWD"
```

macOS/Linux:

```sh
docker compose --profile app run --rm operator python -m scripts.onboard connection --name codex --host-root "$(pwd)"
```

The command stages `.secrets/connections/codex/mcp_config.json` and `codex.toml`.
These contain launch settings and a private-profile directory **without the
bearer value**. Only this identity's private directory is mounted read-only into
the adapter. Its startup copies the selected token/profile into a private
container-local directory with restrictive file permissions, including on
Windows bind mounts. It receives neither operator credentials nor database or
NVIDIA keys. Existing profiles and credentials are never overwritten. Use a new
name if one already exists.

The generated command is `docker`. Its arguments include `compose`, an absolute
`--project-directory` selected by you, `run --rm --no-deps -T mcp`, and the
container's `/run/loomline/docker.profile.json`. Its environment selects only
this connection's private directory. Absolute project selection makes it
independent of the coding application's working directory. `-T` preserves
stdio rather than allocating a terminal. Do not use `up` as the MCP command.

Docker must be visible to the coding application's PATH; check `docker version`
in that environment. Restart an IDE after installing Docker if it inherited an
older PATH. You may replace `command: "docker"` with your own actual absolute
Docker executable path; no author-specific executable path is required.

### Independent Docker protocol check

Before registering the coding application, test initialization, tool discovery,
authenticated identity and the memory-contract resource with an independent
standard MCP client. Use your connection name instead of `codex` below.

PowerShell:

```powershell
$env:LOOM_MCP_DIRECTORY = './.secrets/connections/codex'
try {
  docker compose --profile app run --rm --no-deps -T mcp preflight --profile /run/loomline/docker.profile.json
} finally {
  Remove-Item Env:LOOM_MCP_DIRECTORY -ErrorAction SilentlyContinue
}
```

macOS/Linux:

```sh
LOOM_MCP_DIRECTORY='./.secrets/connections/codex' docker compose --profile app run --rm --no-deps -T mcp preflight --profile /run/loomline/docker.profile.json
```

Expected output includes `PASS`, the 27 discovered tools, your actual identity,
project and new session. This creates persistent test-client session/activity;
it does not prove a vendor application ran. Use a new project/profile, not
immutable historical collaboration evidence. The initial `onboard verify`
command checks HTTP authorization only and does not initialize MCP.

If you also installed the optional host MCP package, its configuration loader
can exercise the generated Docker JSON with an explicit local-trust flag:

```text
python -m loomline_mcp.preflight --config .secrets/connections/codex/mcp_config.json --allow-local-docker
```

Use that environment's interpreter and review the local checkout/Compose file
before granting this flag. It accepts the constrained generated launch shape,
not arbitrary Docker commands. Without the flag, native preflight requires its
own exact Python interpreter and restricted native settings.

For a native host adapter instead, install Python 3.12 and the separate locked
MCP environment described under [native installation](#optional-native-mcp-installation).
Do not install the CrewAI lock into that environment.

### OpenAI Codex CLI

**Prerequisite:** your existing installed/authenticated Codex CLI, plus the
Docker connection prepared above with name `codex`. Loomline does not install,
sign in to, launch or change Codex for you.

Merge the generated `codex.toml` into your user `~/.codex/config.toml` or the
intended project's `.codex/config.toml`, preserving unrelated settings. On
Windows the user file is beneath `$env:USERPROFILE`. The generated
`[mcp_servers.loomline]` specifies `command`, `args` and an environment table.
Alternatively, register that same command using `codex mcp add`. Inspect with
`codex mcp list`, then `/mcp` in the CLI. These formats and configuration scopes
follow [official OpenAI documentation](https://developers.openai.com/codex/mcp/),
checked 2026-10-18.

Run the [first-memory experiment](#verify-a-real-mcp-memory) inside Codex. Match
`loomline_whoami` against your newly provisioned `codex` identity and project.
To disconnect, remove only this Loomline table or set `enabled = false`, then
restart the client connection. Removing client configuration does not revoke
the bearer or erase its graph history.

### Google Antigravity CLI

**Prerequisite:** your existing installed/authenticated Antigravity CLI. Prepare
a separate connection named `antigravity_cli` using the common commands above.

Merge its generated `mcp_config.json` under `mcpServers` in the coding
workspace's `.agents/mcp_config.json`. Global configuration is
`~/.gemini/config/mcp_config.json`; Windows uses the same path beneath
`$env:USERPROFILE`. Keep other servers. Google documents this format and local
stdio `command`, `args`, `env` and optional `cwd`. Use `/mcp` to reload/inspect
the connection. [Google MCP documentation](https://antigravity.google/docs/mcp),
checked 2026-10-18.

Run the [first-memory experiment](#verify-a-real-mcp-memory) and check the
`antigravity_cli` identity. To disconnect, set this entry's `disabled` field to
`true` or remove only its Loomline entry, then reload. Use a separately
provisioned identity if the IDE is also running independently.

### Google Antigravity IDE

**Prerequisite:** your existing installed/authenticated Antigravity IDE. Prepare
the separate connection `antigravity_ide` using the common commands.

Merge that connection's generated JSON into workspace `.agents/mcp_config.json`
or the global file above. In the agent panel choose **MCP Servers → Manage MCP
Servers → View raw config**, preserve unrelated entries and reload the server.
This is the IDE configuration route in
[Google's official MCP guide](https://antigravity.google/docs/mcp).

Run the [first-memory experiment](#verify-a-real-mcp-memory) from its agent
panel. Confirm identity `antigravity_ide`, rather than the CLI's identity. To
disconnect, disable/remove only this entry and reload. Sharing the global
configuration between surfaces can also share an identity; workspace scope
and separate names avoid that ambiguity.

### Claude Code

**Prerequisite:** your existing installed/authenticated Claude Code. Prepare a
connection named `claude` with the common operator commands.

Merge its generated `mcp_config.json` contents into `.mcp.json` at your coding
project root. This is project scope; protect the machine-specific file from
version control. For private local scope, use `claude mcp add --transport stdio
--scope local` with the generated executable/arguments/environment, instead of
editing the project's file. Local scope is stored in `~/.claude.json`, scoped
to the current project. Inspect with `claude mcp list` and `/mcp`. These follow
[Anthropic's MCP documentation](https://code.claude.com/docs/en/mcp), checked
2026-10-18.

The generated JSON is local stdio: `command: "docker"`, an argument array and
`env.LOOM_MCP_DIRECTORY`. It is not a remote HTTP server or Claude Desktop-only
configuration. Run the [first-memory experiment](#verify-a-real-mcp-memory).
To disconnect, remove only `mcpServers.loomline` or the local entry and restart
the connection. Do not replace another project's existing MCP configuration.

### Another compatible MCP client

**Prerequisite:** a client that supports starting a local stdio executable,
plus Docker. Provision name `my_mcp_agent`, generate its connection, and enter
the generated `command`, argument array and environment in that client's
documented local-server settings. If it accepts `mcpServers` JSON, merge the
generated entry; clients with another schema need their own settings wrapper.

Use the release's independent protocol acceptance results for the supplied
configuration. The optional native preflight below validates supported native
Python settings, not arbitrary Docker configurations. Inside your client run
[the same experiment](#verify-a-real-mcp-memory), verify identity and inspect
the resulting graph. Disable/remove just the server to disconnect. A client
that supports only remote HTTP MCP cannot connect directly to Loomline's local
stdio server; no public MCP HTTP listener is supplied.

### Verify a real MCP memory

Ask your agent to **invoke**, rather than describe, these tools. Do not put a
bearer in the prompt. The fixed project and identity come from its private
profile; the agent cannot select another tenant or impersonate another author.

1. `loomline_whoami` with `{}`. Check the returned identity and `fixed_task_id`.
2. `loomline_record_turn` with:

   ```json
   {"operation_id":"first-turn-v1","role":"user","content":"Verify that this client can preserve a project observation."}
   ```

3. Use the actual returned `turn_id` in `loomline_remember`:

   ```json
   {"operation_id":"first-memory-v1","content":"This independently authenticated client completed its first memory check.","memory_class":"episodic","assertion_type":"episode","status":"active","source_turn_id":"RETURNED_TURN_ID"}
   ```

4. Call `loomline_recall` with
   `{"query":"first memory check","memory_class":"episodic","limit":3}`.
   Resolve/trace the complete returned `loom://task/.../memory/...` reference.
5. In Studio choose the named project → **Memory Graph**. Select that memory
   and inspect its author, session, source turn and query inspector.
6. Close/reopen the MCP connection. Invoke `loomline_resume_task` with a new
   operation ID such as `{"operation_id":"first-resume-v1"}`. Recall the same
   memory. A new session does not erase prior records.

Stable operation IDs make retry of the same intent safe. Change IDs for new
intents; changing a payload while reusing its ID correctly conflicts. Returned
content is untrusted task data, not higher-priority instructions. MCP captures
only explicitly recorded turns; never submit hidden reasoning or secrets.

## Custom Python agents

**Prerequisite:** Python 3.12 for the host SDK path, or the Docker operator for
the first-memory check. Provision `python_agent` with role `investigator` on
your named project. A second reader needs its own separately assigned identity.

From the extracted source directory create a separate environment. The Windows
examples use the Python launcher (`py -3.12`); if it is unavailable, use your
actual Python 3.12 executable instead. PowerShell:

```powershell
py -3.12 -m venv .venv-sdk
.\.venv-sdk\Scripts\python.exe -m pip install ./packages/loomline-sdk
```

macOS/Linux:

```sh
python3.12 -m venv .venv-sdk
.venv-sdk/bin/python -m pip install ./packages/loomline-sdk
```

Save this as your own untracked `first_memory.py` in the extracted directory,
then run it with that environment's interpreter. It reads your private profile
and token locally; the SDK itself does not discover credentials or read `.env`.

```python
import json
from pathlib import Path
from loomline import LoomlineClient

folder = Path(".secrets/connections/python_agent")
profile = json.loads((folder / "host.profile.json").read_text())
token = (folder / profile["token_file"]).read_text().strip()
with LoomlineClient(profile["base_url"], token=token) as client:
    print(client.whoami())  # identity metadata, never the bearer
    with client.session(profile["task_id"]) as session:
        memory = session.remember_episode(
            "The Python agent completed its first memory check."
        )
    print(memory.reference)
    print(client.resolve(memory.reference)["content"])
    print(client.trace(memory.reference))
```

The convenience call commits a source turn followed by its memory as two
separate idempotent writes. A fresh process can resolve the same reference;
another identity must also be assigned to the project. The async client exposes
the same operations. The [memory contract](memory-contract.md)
defines lifecycle and retry semantics; the gateway's `/docs` page lists the
authenticated HTTP operations for bounded recall, history, challenges, claims,
versioned handoffs and recovery cursors. Close the
client/context manager to disconnect; revoke the identity separately.

## Native Python frameworks

The following are **SDK/framework integrations, not MCP installations**.
Frameworks use public authenticated HTTP. They neither access FalkorDB directly
nor receive NVIDIA keys. In the supplied reasoning examples, the gateway calls
NVIDIA NIM using its configured role keys and budgets. A deterministic
`--offline` run still executes native frameworks and real database writes; it
does not demonstrate model inference.

Keep optional dependencies separate from the backend and MCP environment.
The pinned all-framework environment has upstream dependency advisories; read
[the optional framework limitation below](#optional-framework-security-limitation)
before using it beyond this local workflow.

### LangChain

**Prerequisite:** Python 3.12 and your model runtime if building your own agent.
Provision `langchain_agent` as an `investigator` on your named project.
PowerShell:

```powershell
py -3.12 -m venv .venv-langchain
.\.venv-langchain\Scripts\python.exe -m pip install "./packages/loomline-sdk[langchain]"
.\.venv-langchain\Scripts\python.exe -m pip check
```

macOS/Linux:

```sh
python3.12 -m venv .venv-langchain
.venv-langchain/bin/python -m pip install './packages/loomline-sdk[langchain]'
.venv-langchain/bin/python -m pip check
```

Load its `host.profile.json` and
`agent.token` as in the Python example, using folder
`.secrets/connections/langchain_agent`.

`loomline.integrations.langchain.memory_tools(client, task_id, session_id)`
returns native `StructuredTool` objects for recall, source-linked memory,
trace, challenge and handoff. Supply these tools to your own
`langchain.agents.create_agent(model, tools=tools)`. Record a source turn in
your owned session and give its ID to the memory tool. Invoking a recall tool
manually verifies its SDK/database path; it is not a model execution claim.

For the complete, executable **native `create_agent` reasoning** example, run
the [four-framework lab below](#run-the-complete-native-framework-lab). Its
investigator retrieves real context and must successfully execute the planned
memory tool before reporting PASS. In Studio inspect the resulting LangChain
session and source-linked hypothesis. For your generic named project, verify
identity plus a source-linked memory using the SDK example; do not run the
incident-specific lab worker against an unprepared blank task. Stop your agent
and close its SDK client to disconnect.

### LangGraph

**Prerequisite:** Python 3.12. Provision `langgraph_agent` as a `verifier` on the
same named project. Use its own private profile. PowerShell:

```powershell
py -3.12 -m venv .venv-langgraph
.\.venv-langgraph\Scripts\python.exe -m pip install "./packages/loomline-sdk[langgraph]"
.\.venv-langgraph\Scripts\python.exe -m pip check
```

macOS/Linux:

```sh
python3.12 -m venv .venv-langgraph
.venv-langgraph/bin/python -m pip install './packages/loomline-sdk[langgraph]'
.venv-langgraph/bin/python -m pip check
```

A custom `StateGraph` node can call `client.get_context(task_id)`;
a publish node can record its own source turn and memory through the same
SDK. Pass references and bounded context between nodes, not another principal's
credential.

The supplied `loomline.integrations.langgraph.workflow` compiles actual
**recall → analyze → publish** nodes. Its analyzer uses the gateway planner;
publish applies the selected support/challenge to an existing hypothesis and
evidence using current versions. It intentionally requires the prepared lab
fixture. Execute it via the [complete lab](#run-the-complete-native-framework-lab),
then inspect the disputed/supported hypothesis and evidence edges in Studio.
For an independent new project, the SDK first-memory/read check establishes
scope before wiring your own node logic. Closing a graph run does not erase
shared sessions or memories; close its SDK client normally.

### CrewAI

**Prerequisite:** Python 3.12, an isolated environment and review of the optional
dependency limitation. Provision `crewai_agent` as a task-restricted
`coordinator` on the named project. This permits coordination/decision actions
without granting procedure approval. PowerShell:

```powershell
py -3.12 -m venv .venv-crewai
.\.venv-crewai\Scripts\python.exe -m pip install "./packages/loomline-sdk[crewai]"
.\.venv-crewai\Scripts\python.exe -m pip check
```

macOS/Linux:

```sh
python3.12 -m venv .venv-crewai
.venv-crewai/bin/python -m pip install './packages/loomline-sdk[crewai]'
.venv-crewai/bin/python -m pip check
```

Load only this connection's profile/token. `loomline.integrations.crewai.memory_tools`
constructs native `BaseTool` instances; `run_crew` constructs real
`Agent`/`Task`/`Crew` and calls `Crew.kickoff()`. The supplied crew keeps
`memory=False`, `cache=False`, `tracing=False`; durable shared memory is
FalkorDB. Its handoff tool requires an approved procedure and fixture entities.

Run the [complete lab](#run-the-complete-native-framework-lab) to exercise that
prepared scenario and inspect its decision, consulted procedure and handoff.
Use ordinary SDK source-linked memories for your generic project until your
own crew tools/policies are wired. Do not mistake an imported adapter for an
executed crew. Stop the crew and close its SDK client to disconnect.

### Run the complete native framework lab

This reproducible example provisions **four separately authenticated framework
identities** and creates its own clearly marked synthetic Checkout task. It
does not change your ordinary project or the preserved owner collaboration.
From the release directory:

```text
docker compose --profile app run --rm --build operator python -m scripts.platform_setup
docker compose --profile app build integrations
docker compose --profile app run --rm integrations python -m examples.interop_lab --offline --branch upstream
```

The lab runs LangChain → LangGraph → CrewAI → fresh custom Python, checks four
distinct identities/sessions and verifies committed memory/evidence/handoff
records. It prints a new task ID, Studio URL and report path. Follow that URL
to inspect **Memory Graph**, source turns, challenges and completed handoff.

For real NVIDIA reasoning, the server operator must privately configure all
three role keys and enable live inference in `.env`, then recreate the gateway.
Run the same lab command with `--live-nvidia` instead of `--offline`. A missing
key, authentication failure or quota failure stops the live run; no offline
response is substituted. Existing coding applications still use their own
model runtime; these NVIDIA settings apply to the supplied framework lab.
For interruption recovery, add `--pause-after crewai` to the lab command. The
printed report path is `artifacts/platform/TASK_ID.json`. After restarting the
gateway, run the same integrations service with
`python -m examples.interop_lab --resume artifacts/platform/TASK_ID.json`, then
`python -m examples.verify_lab artifacts/platform/TASK_ID.json`. Use the actual
returned task/report path. Do not rename or modify the saved mode to fabricate
a live result.

### Optional framework security limitation

The pinned versions exercised by the supplied lab are LangChain 1.4.6,
langchain-core 1.6.12, LangGraph 1.2.16 and CrewAI 1.15.28 on Python 3.12. Their
locks are separate from the backend and standalone MCP package.

The optional all-framework lock retains `chromadb==1.5.9` and `mcp==1.28.1`,
which the prior dependency audit reported with six advisory records across
five unique identifiers. CrewAI constrains MCP to `~=1.28.1`, so forcing a newer
version breaks its declared dependency contract. This is not a clean
production-security result for that optional environment. The standalone
Loomline MCP service uses its separate MCP 2.2.0 lock.

The supplied CrewAI workflow disables memory/cache/tracing, starts no Chroma
server or collections and starts no optional stateful MCP HTTP server. All
shared memory uses FalkorDB through the SDK. That limits the affected paths
used by this local example; it does not fix or remove the advisory packages.
Review upstream compatibility before exposing additional services. This
release's exact executed dependency checks and remaining risks belong in
[the acceptance report](verification.md).

For a smaller non-framework check from a second named-project identity,
provision `project_reader` on that same `PROJECT_ID`, then run:

```text
docker compose --profile app run --rm operator python -m scripts.onboard recall --name project_reader --query "first memory check"
```

This is a read-only SDK retrieval under a separate bearer, not a framework or
model execution claim. It is useful before configuring a vendor application's
tool permissions.

## Optional native MCP installation

Use Python 3.12 in a dedicated environment if you prefer a host MCP process.
PowerShell:

```powershell
py -3.12 -m venv .venv-mcp
```

macOS/Linux:

```sh
python3.12 -m venv .venv-mcp
```

Run the next commands using `.venv-mcp/Scripts/python.exe` on Windows or
`.venv-mcp/bin/python` on macOS/Linux:

```text
python -m pip install -r requirements.mcp.lock.txt
python -m pip install --no-build-isolation --no-deps ./packages/loomline-sdk ./packages/loomline-mcp
python -m pip check
python -m loomline_mcp doctor --profile .secrets/connections/codex/host.profile.json
```

For your chosen client, set `command` to that interpreter's **actual absolute
path**, `args` to `["-m", "loomline_mcp"]`, `cwd` to your extracted directory,
and `env.LOOM_MCP_PROFILE` to the actual absolute private profile path.
That profile's relative `agent.token`
resolves beside it. The equivalent manual server command is:

```text
python -m loomline_mcp --profile .secrets/connections/codex/host.profile.json
```

It waits for MCP JSON-RPC on stdin; a quiet terminal is expected. Do not type
ordinary chat into it. A token-free native `mcpServers` JSON with the fields
above can be checked using that same interpreter:

```text
python -m loomline_mcp.preflight --config YOUR_STAGED_NATIVE_CONFIG.json
```

Without `--allow-local-docker`, preflight accepts only its own exact Python executable,
`-m loomline_mcp`, an existing absolute `cwd` and the restricted environment
keys. It initializes a real session: use a disposable/new task, not immutable
historical evidence. It is an independent client, not vendor-application proof.

## Troubleshooting and secure disconnection

| Symptom | Check or action |
|---|---|
| `docker` missing inside the coding application | Verify Docker is in that application's environment/PATH. A WSL client needs a WSL-accessible checkout and Docker integration; generate configuration from that environment rather than copying Windows paths. |
| Server exits before tool discovery | Build `mcp` first, keep Docker running, check generated project directory and `.secrets/connections/NAME`, then check `docker compose --profile app ps`. |
| Connection name already exists | Reuse its files or choose a new name. Provisioning refuses to overwrite credentials. |
| `401 UNAUTHENTICATED` | Wrong, missing or revoked token. Run `onboard verify --name NAME`. Reconnect with an active private identity; never paste the token into a support report. |
| `404 NOT_FOUND` | The record is absent or outside tenant, task allowlist or enabled membership. Ask the operator to verify assignment. IDs alone grant no access. |
| `403 READ_ONLY_IDENTITY` | A viewer attempted a write/session. Give the working agent its own authorized identity. |
| `409` during a claim/handoff/lifecycle change | Refresh actual state and expected version; respect the current lease/owner. Do not invent a success receipt or change an uncertain intent's operation ID. |
| Recall did not find an old procedure | Recall is bounded and omits retired procedures. Resolve its known complete memory URI to inspect history. |
| Memory URI rejected | Use `loom://task/<task_id>/memory/<memory_id>`, not a bare ID, evidence URI, turn URI or session URI. |
| New session looks empty | Explicitly call context/history/resume. Loomline does not import the application's private transcript or checkpoint. |
| Gateway just crashed | The single-writer lease can take about 30 seconds to expire. Check health; do not delete locks, graphs or volumes. |

Client removal and credential revocation are separate. To revoke a connection
you operate, run from the release directory:

```text
docker compose --profile app run --rm operator python -m scripts.onboard revoke --name NAME
```

History is retained. Provision a **new name** for replacement; no credential is
overwritten. Remove/disable the old client entry and reconnect with the new
generated settings. Remote gateway access requires HTTPS and deliberate server
deployment configuration; the default Compose stack binds only loopback.

## What has and has not been verified

Release acceptance uses independent MCP clients, actual authenticated SDK calls
and real FalkorDB persistence. Generated configuration/protocol success does
not attest which vendor application binary ran. The owner separately confirms
the earlier genuine Codex CLI + Antigravity CLI collaboration and fresh Codex
recovery. Claude Code, Antigravity IDE and a genuine three-application mission
still need the owner's manual checks. See
[FINAL_USER_ACCEPTANCE_REPORT](verification.md) for this
release's executed results and remaining limitations.
