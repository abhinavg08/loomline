# Tested framework integrations

FalkorDB remains the sole durable shared-memory engine. Framework agents use only the public Loomline HTTP SDK; they have neither a DB password nor a provider key. All NVIDIA inference goes through the authenticated gateway's shared role-key/quota manager. SDK storage also works entirely without inference.

## Compatible environments

| Component | Verified version / execution |
|---|---|
| Core SDK | loomline-sdk 0.1.0, Python 3.12.15 Windows / 3.12.10 Linux Docker |
| LangChain | 1.4.6, langchain-core 1.6.12, actual `create_agent().invoke()` |
| LangGraph | 1.2.16, actual compiled `StateGraph.invoke()` |
| CrewAI | 1.15.28, actual Agent, Task, BaseTool and `Crew.kickoff()` |
| Custom Python | core SDK, fresh process/session recovery |
| Model | nvidia/nemotron-3.5-super-vl-120b-a12b at NVIDIA hosted NIM |

Do not install all frameworks into the backend environment: CrewAI's dependency versions differ. `requirements.lock.txt` is the backend lock; `requirements.frameworks.lock.txt` is the separate exact optional-framework lock (pywin32 conditional on Windows). Both passed pip check. Python 3.13 is metadata-permitted but has not been tested. Linux framework Docker image was built and its four-agent offline relay passed against actual FalkorDB.

```powershell
python -m venv .venv-platform
./.venv-platform/Scripts/python.exe -m pip install -r requirements.frameworks.lock.txt -e "packages/loomline-sdk[all]"
# Or install a single optional adapter in a fresh environment:
python -m pip install -e "packages/loomline-sdk[langchain]"
python -m pip install -e "packages/loomline-sdk[langgraph]"
python -m pip install -e "packages/loomline-sdk[crewai]"
```

Docker alternative requires no host framework installation: `docker compose --profile app build integrations`. Onboard private identities with `docker compose --profile app run --rm --build operator`, then recreate the gateway to refresh auth-file binding. `integrations` mounts only framework bearer credentials and artifacts; no .env, provider/DB credentials, backend code or DB driver is installed there. Its only network entry is outbound HTTP to the gateway; no host ports are published.

## Real framework entry points

`examples.framework_worker` uses four distinct private principals: platform_langchain/investigator, platform_langgraph/verifier, platform_crewai/coordinator, platform_custom/verifier. It loads only the selected framework token from the private token file (or explicit LOOM_AGENT_TOKEN). Provider role and key are selected server-side. It disables third-party telemetry and automatic dotenv loading before framework imports. Use only synthetic inputs in recordings.

The simplest reproducible fixture is `python -m examples.interop_lab --offline --branch upstream --pause-after crewai`; it prints the new task/report IDs. Individual entry points below require that actual lab task with its entities, approved procedure and task assignments; use fresh tasks to avoid conflicting existing state.

```powershell
python -m examples.framework_worker langchain --task TASK_ID --live-nvidia
python -m examples.framework_worker langgraph --task TASK_ID --branch upstream --live-nvidia
python -m examples.framework_worker crewai --task TASK_ID --live-nvidia
python -m examples.framework_worker custom --task TASK_ID --live-nvidia
```

Prefix with `docker compose --profile app run --rm integrations` to use the container. Substitute `--offline` for a visibly labelled deterministic **framework policy**, never a fabricated provider response. The native framework runtimes/tools and all FalkorDB commits still execute in offline mode. Full coordinator command creates the fixture and runs these workers in the correct order:

```powershell
python -m examples.interop_lab --offline --branch upstream
python -m examples.interop_lab --offline --branch deployment
python -m examples.interop_lab --live-nvidia --branch upstream --pause-after crewai
docker compose --profile app restart gateway
python -m examples.interop_lab --resume artifacts/platform/TASK_ID.json
python -m examples.verify_lab artifacts/platform/TASK_ID.json
```

## How the model controls actions

`loomline.integrations.langchain.memory_tools(client, task_id, session_id)` returns real typed StructuredTools for recall, remember, trace, handoff and challenge. `run_agent` invokes recall and a real create_agent loop using `GatewayPlannerModel`. Actual NIM JSON is strictly validated by the gateway, then translated into a LangChain tool-call envelope; a successful persisted remember action is required before reporting PASS. The final static tool acknowledgment is not represented as a second model response.

`loomline.integrations.langgraph.workflow(client, task_id, session_id)` builds/compiles recall -> analyze -> publish nodes. Analyze calls NIM; publish executes support or challenge selected by the actual validated output, using evidence IDs/current versions. The synthetic branch is supplied before analysis. Native graph/checkpoint state stays private to that run; later workers recover only public SDK data.

`loomline.integrations.crewai.run_crew` constructs actual Agent/Task/Crew and BaseTool objects with a custom `GatewayCrewLLM(BaseLLM)`. It uses a bounded ReAct loop: shared recall, real NIM coordinator proposal, an authorized SDK handoff tool, and result acknowledgment. The handoff tool consults actual approved procedure steps and commits a source/evidence-linked decision plus durable assignment. Crew memory/cache/tracing are disabled. Internal framework control strings are not a manufactured thought log and are never shown as model reasoning.

The custom Python worker starts a new SDK session, recovers historical turns plus all three memory classes and open work, asks NIM to identify the assigned handoff/approved procedure, then performs version-checked accept/complete calls. Wrong IDs, missing evidence, invalid status or stale versions fail rather than being replaced with guessed success.

NVIDIA native tool-calling/JSON-schema enforcement is **not** assumed. This is a validated JSON planner plus native framework tool executor, permitted by the platform contract. Framework adapters are first examples for these pinned versions, not universal checkpoint interchange. The generic SDK is independent of incident domain entities; the supplied reasoning examples deliberately use the synthetic Checkout scenario.

## Proof and failure semantics

Successful live upstream task: `task_2b904df1dbe4378f3ab6fb44`. Actual model proposals, per-call attempt/latency/quota metadata, native runtime/tool names, PIDs, independent identities, session/source IDs and graph relationships were checked by `examples.verify_lab`. Files in `artifacts/platform` are local private engineering evidence, excluded from exports. Failed initial verifier/recovery outputs were rejected and retained as safe diagnostics; successful retries do not erase the failed attempts.

`python -m examples.continuity_comparison --live-nvidia` creates two equivalent offline native-framework fixtures and launches fresh live custom agents with the identical goal/model/settings. Only historical context access is withheld in one arm. The model may request missing context or complete a grounded handoff; neither outcome is forced. The observed single pair requested context without history and completed with history. It measures completion/source grounding; zero repeated investigation steps occurred in either arm. One pair is illustrative, not statistical. Task IDs naturally differ. This is a controlled gateway context ablation, not a throughput or general model-quality benchmark.

## Optional dependency security limitation

The 2026-10-17 pip-audit run reports **six advisory records in two optional framework packages** (one Chroma advisory appears twice). Four unique Chroma advisories affect chromadb 1.5.9; the auditor lists no fixed version. `mcp` 1.28.1 has CVE-2026-59951, fixed in 1.30.0, but CrewAI pins `mcp~=1.28.1` (<1.29). Forcing the fixed version would violate its dependency contract; no such override was made. See the [upstream MCP advisory](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-84m7-p3x7-pcfv).

The affected paths are Chroma server collection/model APIs and a stateful MCP Streamable HTTP server; see the [reviewed Chroma advisory](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c). Loomline uses neither: Crew memory=False, no Chroma collections or MCP transports are constructed, and the client image exposes no server ports. These dormant dependencies are isolated from the backend/core SDK, whose lock audit passed. This is a reachability assessment, **not** a clean vulnerability audit or proof that the packages are fixed. Keep the optional environment local; review/upgrade the upstream CrewAI dependency set before exposing additional services. The exact auditor reports are `artifacts/platform/dependency-audit-frameworks.json` and `dependency-audit-frameworks-final.json`.
