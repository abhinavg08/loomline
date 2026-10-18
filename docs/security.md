# Studio identity and secure onboarding

The **operator** is the trusted person running this Loomline server. They run
local Docker commands and control its private registry and database. There is
no public unrestricted token-generation endpoint.

A **bearer token** identifies one provisioned agent in one tenant. Anyone with
it can act as that identity. The server chooses the FalkorDB tenant graph from
its authenticated registry, checks enabled project assignment, then enforces
the credential's task allowlist. A task ID or `loom://` reference alone grants
no access. Independent agents need distinct identities and tokens.

A fresh bootstrap also generates a unique Compose project name in `.env`.
That installation owns its `<project-name>_graph_data` persistent volume;
separate extracted directories receive different names. Re-running bootstrap
keeps existing configuration and database ownership unchanged.

## First connection

Complete [Start here](getting-started.md) through Docker startup, then run in the
**host terminal at your extracted release directory**:

```text
docker compose --profile app run --rm operator python -m scripts.onboard bootstrap
```

It writes the existing initial coordinator bearer to `.secrets/operator.token`
only if absent, refuses a mismatched existing file, and prints its location,
identity and Studio URL. It never prints the token or creates a shared default
password. It does not configure an AI coding application.

Copy without printing in Windows PowerShell:

```powershell
Set-Clipboard -Value (Get-Content -Raw -LiteralPath ./.secrets/operator.token).Trim()
```

On macOS use `pbcopy < .secrets/operator.token`; on Linux use an installed
clipboard utility such as `wl-copy < .secrets/operator.token` or a trusted
local password manager. Paste into Studio's masked **Loomline bearer token**
field and connect. Clear the clipboard afterward (`Set-Clipboard -Value ''`
on Windows). Keep the field masked and out of recordings.

Studio keeps the bearer only in the current page's memory and sends it in an
`Authorization: Bearer` header. It is not a URL parameter, browser storage
entry, analytics value or copied public setup example. Disconnect clears the
authenticated state; reload requires connecting again. No browser endpoint
reads private token files.

The initial unrestricted coordinator is the installation operator. Do not give
it to every coding agent; issue restricted credentials below.

## Named projects and least privilege

```text
docker compose --profile app run --rm operator python -m scripts.onboard project --name "Website collaboration" --description "Implement and independently verify a website" --status active
```

Copy the returned `project_id`; `PROJECT_ID` below means that generated value.
Projects reuse the existing Task object, retaining stable IDs and API behavior.

| Role | Appropriate use |
| --- | --- |
| `viewer` | Inspect assigned project memories, evidence, graph, history, agents and coordination. All authenticated non-GET/HEAD/OPTIONS requests fail with `403 READ_ONLY_IDENTITY` before execution. No sessions, memories, inference, claims, handoff transitions or inbox acknowledgements can be created. |
| `investigator` / `verifier` | Independently authenticated working agents with existing memory and coordination permissions. A role does not prove which vendor application is running. |
| `coordinator` | Working coordinator. Creating new projects requires an unrestricted coordinator. The portable task-scoped credentials below cannot create unrelated projects; procedure approval is separately restricted and denied for these new identities. |

Create a read-only viewer:

```text
docker compose --profile app run --rm operator python -m scripts.onboard identity --project PROJECT_ID --name studio_reader --role viewer
docker compose --profile app run --rm operator python -m scripts.onboard verify --name studio_reader
```

Privately copy `.secrets/connections/studio_reader/agent.token` into Studio:

```powershell
Set-Clipboard -Value (Get-Content -Raw -LiteralPath ./.secrets/connections/studio_reader/agent.token).Trim()
```

A viewer is for read-only Studio, SDK and HTTP access. **Do not use it for an
MCP coding agent**: MCP initialization records a persistent session and is a
write. The configuration generator refuses viewer MCP profiles.

Create a separate working identity for each actual agent:

```text
docker compose --profile app run --rm operator python -m scripts.onboard identity --project PROJECT_ID --name coding_agent --role investigator
docker compose --profile app run --rm operator python -m scripts.onboard verify --name coding_agent
```

Provisioning issues a cryptographically random bearer, stores its hash in the
private registry, creates the real enabled Agent and ASSIGNED_TO relationship
in FalkorDB, and mirrors the hashed registry into the gateway's existing
directory mount. The new identity is restricted to the selected project and
cannot approve procedures. No gateway restart is needed.

Private file locations are explicit:

- `.secrets/NAME.token`: original operator-issued credential file.
- `.secrets/connections/NAME/agent.token`: credential copy for this connection.
- `.secrets/connections/NAME/host.profile.json`: host SDK endpoint, project and
  relative token filename, without an embedded bearer.
- `.secrets/connections/NAME/docker.profile.json`: internal Compose endpoint,
  same project and relative token filename.
- `connection --name NAME --host-root ACTUAL_CHECKOUT` generates token-free
  MCP JSON and Codex TOML there. You personally import it into your existing
  application; Loomline does not install or modify that application.

Names start with a lowercase letter and use lowercase letters, digits, `_`
and `-`. Commands refuse existing identities and profiles. Unix private files
are created 0600; bootstrap with your actual UID/GID as shown in Start here.
Do not make token files world-readable to work around ownership. Windows
users should keep the extracted directory under their account's private ACLs.

## Revoke and replace

Run from the host terminal in the extracted directory:

```text
docker compose --profile app run --rm operator python -m scripts.onboard revoke --name studio_reader
```

This disables the identity in FalkorDB and removes its hashed credential. The
old bearer fails its next authenticated request, including from an open Studio
page. Other authorized identities retain access to its sessions, turns,
memories, evidence and handoffs. Private token files remain as local historical
material; no user data or coding-agent configuration is deleted.

Disconnect Studio, create a **new name**, and privately connect with its token:

```text
docker compose --profile app run --rm operator python -m scripts.onboard identity --project PROJECT_ID --name studio_reader_2 --role viewer
```

The operator can securely retire revoked token copies under their backup
policy. Do not overwrite another identity or rotate provider keys during
ordinary onboarding. NVIDIA role keys are separate server-side credentials.

## Errors and boundaries

| Response | Meaning and action |
| --- | --- |
| `401 UNAUTHENTICATED` | Missing, invalid or revoked bearer. Use an active identity from this installation. |
| `404 NOT_FOUND` | Wrong tenant, task allowlist, disabled assignment or unavailable record. The server does not reveal which inaccessible object exists. Ask the operator to check the project. |
| `403 READ_ONLY_IDENTITY` | A viewer tried a mutation. Use a separate working identity for that action. |
| `403 TASK_SCOPED_PRINCIPAL` | A restricted coordinator tried unrelated task creation. Use the installation operator. |
| Network / service error | Check Docker health and logs separately; do not keep reissuing credentials for a stopped gateway. |

Default ports bind to loopback. Remote deployment needs TLS, controlled
network access, backups and appropriate operations policy. The trusted
operator container has database/registry access. The separate MCP service
passes untrusted coding clients only their own profile/token directory,
without database credentials, provider keys or other agents' tokens. To handle
Windows bind mounts, it copies this one mounted identity to an ephemeral 0700
directory with 0600 files, then starts the same stdio package. It leaves the
host files untouched and preserves the normal strict permission checks.

## Verification

`tests/test_studio_viewer.py` verifies actual provision/revoke, all mutation
guards, trace/history reads, task allowlists and tenant isolation against real,
uniquely owned FalkorDB graphs. `tests/test_onboard.py` covers fresh bootstrap
uniqueness/idempotence, real scoped identities and sessions, viewer denial,
revocation retaining history, private file protection and JSON/TOML paths with
spaces. Packaged installation acceptance is recorded separately in
[the user acceptance report](verification.md).
