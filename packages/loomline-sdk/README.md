# Loomline SDK 0.1.0

Framework-independent, authenticated shared memory over the Loomline HTTP API.
Core dependencies are **HTTPX and Pydantic**: no backend, FalkorDB driver, model
provider or framework import is required. Sync `LoomlineClient` and async
`AsyncLoomlineClient` use the same memory/coordination contract.

Start the server with the source distribution's [START_HERE](../../docs/getting-started.md).
Provision your own task-scoped `python_agent` identity using
[Connect Your Agent](../../docs/connect-agents.md#custom-python-agents). From the
source root, install in your own Python **3.12** environment:

```text
python -m pip install ./packages/loomline-sdk
```

Python 3.13 is allowed by package metadata but was not the verified runtime.
The SDK does not implicitly load `.env`, credential files or environment tokens;
your application explicitly supplies its private credential. For the generated
connection profile, this example makes a real source-linked memory and read:

```python
import json
from pathlib import Path
from loomline import LoomlineClient

folder = Path(".secrets/connections/python_agent")
profile = json.loads((folder / "host.profile.json").read_text())
credential = (folder / profile["token_file"]).read_text().strip()
with LoomlineClient(profile["base_url"], token=credential) as client:
    with client.session(profile["task_id"]) as session:
        receipt = session.remember_episode("The agent completed its memory check.")
    memory = client.resolve(receipt.reference)
    print(memory.reference)
    print(memory.content)
```

Run it from the source root after provisioning that identity. Another session
or independently authenticated assigned agent can resolve the same URI. The
SDK talks to the authorized gateway; durable storage is real FalkorDB. No model
is needed to write, retrieve or inspect memory.

Session conveniences create a visible source turn and then its memory as
**two separate writes**. Supply an owned `source_turn_id` to reuse an existing
turn; stable `operation_id` values support retry/recovery. Full memory reads
are distinct from immutable commit receipts. Conflicting versions/intents fail;
an uncertain mutation is not replaced by an invented success or new intent.
Client representations redact the bearer. Keep private content/tokens out of
logs, source, URLs and shared screenshots.

The API supports episodic observations, semantic facts/hypotheses/decisions,
proposed/approved/retired procedures, evidence and challenges, provenance,
cross-session history, exclusive leased claims and versioned handoffs. Reads
are bounded and tenant/task authorized. A read-only viewer can inspect but
cannot create a session. The [memory contract](../../docs/memory-contract.md)
defines lifecycle, idempotency, cursor and consistency semantics.

Optional extras `[langchain]`, `[langgraph]`, `[crewai]` and `[all]` supply native
integrations. These are SDK/framework adapters, not MCP installations. The
[framework guide](../../docs/connect-agents.md#native-python-frameworks) includes
separate installs, the executable four-runtime lab, optional NVIDIA setup and
upstream dependency-security limitations. Keep optional frameworks separate
from the backend and standalone MCP environments. Use core-only installation
when frameworks are unnecessary.

Explore actual returned relationships in
[Memory Graph](../../docs/memory-graph.md). Executed release checks and
remaining limitations are in the
[acceptance report](../../docs/verification.md).
