# Start here: your first shared memory

Loomline lets independently authenticated agents share lasting memories and
coordinate work. FalkorDB stores memories, source turns, evidence and their
relationships. Developer Studio lets you inspect that state in your browser.

You need **Docker Engine / Docker Desktop with Compose v2**, internet access
for the first build, and free loopback ports **8000** and **6379**. On Windows,
enable Linux containers and WSL 2 in Docker Desktop. No host Python, Node,
Conda or existing AI coding application is needed for this first example.
Git is optional when extracting the release ZIP.

## 1. Extract and open a terminal there

Use any directory you own, including one containing spaces. Run all following
commands from that **extracted Loomline directory on the host computer**.
Do not extract over another installation's secrets or database. Check Docker:

```text
docker version
docker compose version
```

Both must succeed. Start Docker Desktop / Docker Engine first if unavailable.

## 2. Generate private configuration

This runs a standard Python image inside Docker and generates unique local
database and identity credentials. It prints no secrets and preserves an
existing installation's configuration.

**Windows PowerShell:**

```powershell
docker run --rm --mount "type=bind,source=$($PWD.Path),target=/work" --workdir /work python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db python scripts/init_local.py
```

**macOS / Linux:**

```sh
docker run --rm --user "$(id -u):$(id -g)" --mount "type=bind,source=$(pwd),target=/work" --workdir /work python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db python scripts/init_local.py
```

Expected: `Local configuration ready; credentials were not printed.`
`.env` contains private server configuration; `.secrets` contains private
identities. The macOS/Linux `--user` option preserves host ownership of 0600
files. Never commit or share these locations.

Each new `.env` also receives a unique `COMPOSE_PROJECT_NAME`, such as
`loomline-<random suffix>`. Its containers and `loomline-<random suffix>_graph_data`
volume belong to this installation. A second extraction therefore cannot
silently reuse another installation's memories. Re-running bootstrap preserves
an existing `.env` and its volume name exactly.

The default ports need no edits. If already occupied, change only
`LOOM_API_PORT` and/or `FALKORDB_PORT` in your private `.env` before starting.
For example, `LOOM_API_PORT=8010` gives Studio URL `http://127.0.0.1:8010/`.
NVIDIA credentials are optional; this walkthrough makes no model calls.

## 3. Start the platform

```text
docker compose --profile app up -d --build --wait
docker compose --profile app ps
```

The first build downloads dependencies and compiles Studio. Wait for
`falkordb`, `gateway` and `router` to be healthy. Open **http://127.0.0.1:8000/**.
The gateway serves Studio. FalkorDB persists in this Compose project's named
`graph_data` volume, which survives container restarts.

## 4. Connect to Studio as the operator

The operator is the trusted person running this server. Locate the initial
coordinator's bearer without printing it:

```text
docker compose --profile app run --rm operator python -m scripts.onboard bootstrap
```

Expected JSON includes `"status": "READY"`, `"private_token_file":
".secrets/operator.token"`, and your `studio_url`. Copy privately:

**Windows PowerShell:**

```powershell
Set-Clipboard -Value (Get-Content -Raw -LiteralPath ./.secrets/operator.token).Trim()
```

**macOS:** `pbcopy < .secrets/operator.token`.

**Linux:** `wl-copy < .secrets/operator.token` or
`xclip -selection clipboard < .secrets/operator.token`, if that utility is
installed. A trusted local password manager/editor is another option.

Paste into Studio's masked **Loomline bearer token** field and connect. Clear
your clipboard afterward (`Set-Clipboard -Value ''` on Windows). The browser
keeps the bearer only in this page's memory: disconnect or reload requires a
new connection. Never paste a bearer into a chat, URL, screenshot or prompt.

## 5. Create a named project

Use Studio as coordinator or run:

```text
docker compose --profile app run --rm operator python -m scripts.onboard project --name "My first project" --description "Learn how agents share memory" --status active
```

Expected output includes `"status": "CREATED"`, a generated `project_id` and
a Studio link. **Copy the returned project ID** for the following commands:
`PROJECT_ID` is a placeholder, not a built-in demo task. Projects reuse the
existing Task objects and retain their stable API IDs.

Select **My first project** in Studio. An empty project correctly has no
memories, contributors or graph activity yet.

## 6. Give an agent its own identity

```text
docker compose --profile app run --rm operator python -m scripts.onboard identity --project PROJECT_ID --name first_agent --role investigator
docker compose --profile app run --rm operator python -m scripts.onboard verify --name first_agent
```

Provisioning creates an actual enabled FalkorDB Agent and project assignment,
a unique bearer, a task allowlist and private connection profiles. Verification
reports identity and project access; it does not claim a coding application
has connected. Use separate identities for independently attributable agents.

## 7. Write and retrieve a real memory

```text
docker compose --profile app run --rm operator python -m scripts.onboard first-memory --name first_agent --content "Project decision: run tests before accepting a handoff."
```

Expected: `"status": "COMMITTED_AND_RETRIEVED"`, a session ID, source turn ID,
memory ID and `loom://task/.../memory/...` reference. This is a real SDK write
and subsequent authorized FalkorDB retrieval. You supplied the sentence; it is
not a fabricated model response or AI reasoning result.

An independent identity can retrieve that state after the writing process ends:

```text
docker compose --profile app run --rm operator python -m scripts.onboard identity --project PROJECT_ID --name second_agent --role verifier
docker compose --profile app run --rm operator python -m scripts.onboard verify --name second_agent
docker compose --profile app run --rm operator python -m scripts.onboard recall --name second_agent --query "handoff"
```

`verify` checks authenticated project access; `recall` returns the actual shared
memory and its source metadata under the second identity. Follow
[Connect your agent](docs/AGENT_SETUP.md) for MCP/SDK and new-session workflows.

## 8. Explore the memory graph

In Studio, select the project and open **Memory Graph**. Fit the graph to the
screen, select your memory, then inspect author, session, source turn and
status. Open provenance and **Graph Query** to see the fixed authorized
traversal returning persisted FalkorDB records. The [graph guide](docs/MEMORY_GRAPH_GUIDE.md)
explains filtering and expansion. An empty graph means no recorded data yet.

## 9. Connect an existing AI application

Build the Docker MCP adapter once:

```text
docker compose --profile app build mcp
```

Generate a token-free configuration using this machine's actual checkout path:

**Windows PowerShell:**

```powershell
docker compose --profile app run --rm operator python -m scripts.onboard connection --name first_agent --host-root "$($PWD.Path)"
```

**macOS / Linux:**

```sh
docker compose --profile app run --rm operator python -m scripts.onboard connection --name first_agent --host-root "$(pwd)"
```

Generated private files are `.secrets/connections/first_agent/mcp_config.json`
and `codex.toml`. They contain commands and paths, **not bearer values**. The
MCP container receives only that identity's read-only profile/token directory,
then stages a private 0600 ephemeral copy to handle Windows bind permissions.
It receives no other agents' credentials, database password or provider keys. You personally
import the generated configuration; Loomline does not modify your application.

[Connect your agent](docs/AGENT_SETUP.md) covers Codex CLI, Antigravity CLI/IDE,
Claude Code, generic MCP, custom Python, LangChain, LangGraph and CrewAI.
Python framework integrations use the SDK rather than MCP. Tools must actually
be invoked: registering an MCP server does not automatically record work.

## Read-only Studio access

```text
docker compose --profile app run --rm operator python -m scripts.onboard identity --project PROJECT_ID --name studio_reader --role viewer
```

Privately copy `.secrets/connections/studio_reader/agent.token` into Studio.
This viewer can inspect only its assigned project and cannot mutate it, invoke
NVIDIA or initialize a write-producing MCP session. See [Studio authentication](docs/STUDIO_AUTH.md)
for roles, token handling, revocation and replacement.

## Restart, stop and troubleshoot

```text
docker compose --profile app restart
docker compose --profile app ps
docker compose --profile app logs --tail 80 gateway router
docker compose --profile app down
```

`down` without `-v` retains the database volume. **Do not use `down -v` when
you need those memories.** Back up both the volume and private configuration
before moving an established installation.

| Symptom | What to check |
| --- | --- |
| Cannot connect to Docker | Start Docker Desktop / Docker Engine; confirm Linux containers and `docker version`. |
| Port already allocated | Stop the conflicting service or choose free ports in `.env`, then rerun `up`. |
| Gateway unhealthy after a hard kill | Allow the prior 30-second gateway lease to expire, inspect logs and retry. One gateway worker per namespace is required. |
| `401 UNAUTHENTICATED` | Use this installation's active private bearer, not its file path. |
| Project missing / `404 NOT_FOUND` | Identity still needs enabled project assignment and the correct allowlist. Check the returned project ID. |
| `403 READ_ONLY_IDENTITY` | Viewer protection is working; use a separately provisioned agent for writes. |
| Name/configuration already exists | Reuse that configuration or choose a new identity; commands refuse to overwrite credentials. |
| MCP cannot read profile on Linux | Bootstrap as your host UID/GID as shown above; do not make bearer files world-readable. |
| Tools listed but no memories | Ask the agent to identify itself, record a turn/memory and recall it. Discovery alone records no work. |
| NVIDIA unavailable | Core memory does not need NVIDIA. Live framework workflows need private role keys and separate verification. |

For a clean new machine share the **source release ZIP**, never your working
`.env`, `.secrets`, generated profiles or volume. Bootstrap creates a separate
installation with fresh credentials and no original user data.
