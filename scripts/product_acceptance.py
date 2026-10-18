"""Resumable clean-package acceptance; all platform services run in fresh Docker.

Examples (run in the source checkout, not a coding application):
  python -m scripts.product_acceptance start --archive artifacts/release/candidate.zip
  python -m scripts.product_acceptance verify --receipt artifacts/release/product_NONCE.json
  python -m scripts.product_acceptance restart --receipt artifacts/release/product_NONCE.json
  python -m scripts.product_acceptance stop --receipt artifacts/release/product_NONCE.json

The stdlib host orchestrator creates a NEW noneditable SDK/MCP verification venv.
No development credentials, profiles, installed application packages, graph data,
or vendor coding applications are reused. Successful services stay up for browser
acceptance until an explicit stop; stop NEVER removes database volumes.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import subprocess
import sys
import time
import traceback
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_IMAGE = 'python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db'


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else json.dumps(value, sort_keys=True).encode()).hexdigest()


def clean_environment():
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('LOOM_', 'FALKORDB_', 'NVIDIA_', 'COMPOSE_'))
           and key not in ('PYTHONPATH', 'PYTHONHOME')}
    env.update(PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_NO_INPUT='1', PYTHONUNBUFFERED='1')
    return env


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def credentials(work):
    values = []
    env = work / '.env'
    if env.exists():
        for line in env.read_text().splitlines():
            key, sep, value = line.partition('=')
            if sep and (key == 'FALKORDB_PASSWORD' or key.endswith('API_KEY')) and value.strip():
                values.append(value.strip().strip('"\''))
    private = work / '.secrets'
    for token in private.rglob('*.token'):
        values.append(token.read_text().strip())
    token_file = private / 'agent_tokens.json'
    if token_file.exists():
        values.extend(json.loads(token_file.read_text()).values())
    return [value for value in values if len(value) >= 8]


def safe_output(work, value):
    text = value if isinstance(value, str) else json.dumps(value)
    if re.search(r'nvapi-[A-Za-z0-9_-]{30,}', text) or any(value in text for value in credentials(work)):
        raise RuntimeError('Credential detected; acceptance output suppressed')
    return text


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.pending')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


class Receipt:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.data = json.loads(self.path.read_text())
        nonce = self.data['nonce']
        self.work = Path(self.data['workspace']).resolve()
        if (not re.fullmatch(r'[a-f0-9]{16}', nonce)
                or self.data['project'] != 'loomline-product-' + nonce
                or self.data['namespace'] != 'release_' + nonce
                or self.work.parent != self.path.parent
                or self.work.name != 'portable install ' + nonce):
            raise RuntimeError('Refusing an unowned acceptance workspace or Compose project')
        self.logs = self.work / 'artifacts/acceptance'
        self.logs.mkdir(parents=True, exist_ok=True)
        self.compose = ['docker', 'compose', '--project-name', self.data['project'], '--profile', 'app']

    def save(self):
        self.data['updated_at'] = datetime.now(timezone.utc).isoformat()
        safe_output(self.work, self.data)
        write_json(self.path, self.data)

    def run(self, name, command, *, cwd=None, timeout=1200, project_names_only=False):
        attempts = self.data.setdefault('attempts', {})
        attempts[name] = attempts.get(name, 0) + 1
        log = self.logs / (name + '-' + str(attempts[name]) + '.log')
        started = time.monotonic()
        result = subprocess.run(command, cwd=cwd or self.work, env=clean_environment(),
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        stdout = result.stdout
        if project_names_only and result.returncode == 0:
            # Resolved Compose JSON contains private environment values. Keep
            # it in memory and expose ONLY the independently resolved names.
            config = json.loads(stdout)
            stdout = json.dumps({'project_name': config['name'],
                                 'graph_volume_name': config['volumes']['graph_data']['name']})
        output = safe_output(self.work, stdout + result.stderr)
        log.write_text(output, encoding='utf-8')
        self.data.setdefault('checks', {})[name] = {
            'status': 'PASS' if result.returncode == 0 else 'FAIL',
            'seconds': round(time.monotonic() - started, 2), 'log': str(log)}
        self.save()
        print(name + ': ' + self.data['checks'][name]['status'], flush=True)
        if result.returncode:
            raise RuntimeError(name + ' failed; inspect its private local acceptance log')
        return stdout

    def onboard(self, name, *arguments):
        output = self.run(name, self.compose + ['run', '--rm', 'operator', 'python', '-m', 'scripts.onboard', *arguments])
        # Compose may build this service's image tag on its first run. BuildKit
        # emits progress before the operator's one JSON result on stdout.
        for match in reversed(list(re.finditer(r'(?m)^\{', output))):
            try:
                value = json.loads(output[match.start():])
                if isinstance(value, dict) and 'status' in value:
                    return value
            except ValueError:
                pass
        raise RuntimeError('Operator command did not return its safe structured result')

    def python(self):
        return self.work / '.venv-product-check' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def new_install(archive, receipt_path=None):
    archive = Path(archive).resolve()
    from .release_safety import allowed, inspect_zip
    report = inspect_zip(archive)
    if report['status'] != 'PASS':
        raise RuntimeError('Source archive failed prohibited-member or credential checks')
    nonce = uuid.uuid4().hex[:16]
    folder = ROOT / 'artifacts/release'
    folder.mkdir(parents=True, exist_ok=True)
    receipt_path = Path(receipt_path).resolve() if receipt_path else folder / ('product_' + nonce + '.json')
    if receipt_path.parent != folder.resolve() or receipt_path.exists():
        raise RuntimeError('Use a new receipt directly under artifacts/release')
    work = folder / ('portable install ' + nonce)
    work.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive) as source:
        if sum(info.file_size for info in source.infolist()) > 100_000_000:
            raise RuntimeError('Source archive exceeds the bounded acceptance extraction budget')
        for info in source.infolist():
            name = info.filename
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or info.external_attr >> 16 & 0o170000 == 0o120000:
                raise RuntimeError('Unsafe source archive member')
            if info.is_dir():
                continue
            if not allowed(name):
                raise RuntimeError('Non-source archive member')
        source.extractall(work)
    if any((work / item).exists() for item in ('.env', '.secrets', '.conda', '.venv', '.venv-mcp', 'frontend/node_modules')):
        raise RuntimeError('Clean package unexpectedly contains private or machine-specific runtime state')
    db_port, api_port = free_port(), free_port()
    while api_port == db_port:
        api_port = free_port()
    value = {'format': 1, 'status': 'CREATED', 'nonce': nonce, 'workspace': str(work),
             'project': 'loomline-product-' + nonce, 'namespace': 'release_' + nonce,
             'database_port': db_port, 'api_port': api_port,
             'studio_url': f'http://127.0.0.1:{api_port}/',
             'archive': {**report, 'sha256': sha(archive.read_bytes())},
             'checks': {}, 'credentials_exported': False,
             'vendor_applications_executed': False,
             'verification_runtime': 'new noneditable SDK/MCP venv; fresh Docker services and volume',
             'provider_inference': 'NOT RUN: source package contains no provider credentials'}
    write_json(receipt_path, value)
    return Receipt(receipt_path)


def start(receipt):
    work = receipt.work
    if not receipt.data.get('configuration_initialized'):
        command = ['docker', 'run', '--rm']
        if os.name != 'nt':
            command += ['--user', str(os.getuid()) + ':' + str(os.getgid())]
        command += ['--mount', 'type=bind,source=' + str(work) + ',target=/work', '--workdir', '/work',
                    BOOTSTRAP_IMAGE, 'python', 'scripts/init_local.py']
        receipt.run('documented-docker-bootstrap', command)
        env = work / '.env'
        generated = json.loads(receipt.run('default-unique-project-and-volume',
                               ['docker', 'compose', '--profile', 'app', 'config', '--format', 'json'], project_names_only=True))
        assert re.fullmatch(r'loomline-[a-f0-9]{16}', generated['project_name'])
        assert generated['graph_volume_name'] == generated['project_name'] + '_graph_data'
        receipt.data['bootstrap_generated_project'] = generated
        text = env.read_text().replace('FALKORDB_PORT=6379', 'FALKORDB_PORT=' + str(receipt.data['database_port']))
        text = text.replace('LOOM_API_PORT=8000', 'LOOM_API_PORT=' + str(receipt.data['api_port']))
        text = text.replace('LOOM_GRAPH_NAMESPACE=demo', 'LOOM_GRAPH_NAMESPACE=' + receipt.data['namespace'])
        # The acceptance harness uses its stricter owned-resource guard prefix,
        # AFTER independently validating the documented bootstrap default.
        text = text.replace('COMPOSE_PROJECT_NAME=' + generated['project_name'], 'COMPOSE_PROJECT_NAME=' + receipt.data['project'])
        env.write_text(text)
        if os.name != 'nt':
            env.chmod(0o600)
        receipt.data['configuration_initialized'] = True
        receipt.save()
    receipt.run('compose-config', receipt.compose + ['config', '--quiet'])
    receipt.run('documented-build-and-health', receipt.compose + ['up', '-d', '--build', '--wait'])
    receipt.run('docker-mcp-build', receipt.compose + ['build', 'mcp'])
    receipt.data['status'] = 'SERVICES_READY'
    receipt.data['services_running'] = True
    receipt.save()


def setup_identities(receipt):
    if not receipt.data.get('bootstrap_ready'):
        ready = receipt.onboard('operator-bootstrap', 'bootstrap')
        assert ready['status'] == 'READY' and ready['secret_printed'] is False
        receipt.data['bootstrap_ready'] = True
        receipt.save()
    if not receipt.data.get('task_id'):
        project = receipt.onboard('named-project', 'project', '--name', 'Clean install — independent client acceptance',
                                  '--description', 'Real SDK and independent MCP protocol verification; no vendor application execution',
                                  '--status', 'active', '--synthetic')
        receipt.data['task_id'] = project['project_id']
        receipt.data['studio_url'] = project['studio_url']
        receipt.save()
    identities = {'accept_writer': 'coordinator', 'accept_reviewer': 'verifier',
                  'accept_third': 'investigator', 'studio_reader': 'viewer'}
    for name, role in identities.items():
        metadata = receipt.work / '.secrets/connections' / name / 'identity.json'
        if not metadata.exists():
            issued = receipt.onboard('identity-' + name, 'identity', '--project', receipt.data['task_id'],
                                     '--name', name, '--role', role)
            assert issued['task_restricted'] is True and issued['secret_printed'] is False
        receipt.onboard('authenticated-' + name, 'verify', '--name', name)
        if role != 'viewer' and not (metadata.parent / 'mcp_config.json').exists():
            generated = receipt.onboard('config-' + name, 'connection', '--name', name, '--host-root', str(receipt.work))
            assert generated['secret_printed'] is False and generated['coding_application_modified'] is False
    receipt.data['identities'] = identities
    receipt.data['viewer_token_file'] = str(receipt.work / '.secrets/connections/studio_reader/agent.token')
    receipt.data['operator_token_file'] = str(receipt.work / '.secrets/operator.token')
    receipt.save()
    if not receipt.data.get('first_memory'):
        result = receipt.onboard('first-memory', 'first-memory', '--name', 'accept_writer', '--content',
                                  'Packaging acceptance: run checks before accepting shared work.')
        assert result['status'] == 'COMMITTED_AND_RETRIEVED'
        receipt.data['first_memory'] = {key: result[key] for key in ('memory_id', 'reference', 'session_id', 'source_turn_id')}
        receipt.save()
    recalled = receipt.onboard('independent-sdk-recall', 'recall', '--name', 'accept_reviewer', '--query', 'Packaging acceptance')
    assert any(memory['id'] == receipt.data['first_memory']['memory_id'] for memory in recalled['memories'])
    receipt.data['checks']['independent-sdk-retrieval'] = {'status': 'PASS', 'memory_id': receipt.data['first_memory']['memory_id']}
    receipt.save()


def verification_runtime(receipt):
    interpreter = receipt.python()
    if not interpreter.exists():
        receipt.run('fresh-verification-venv', [sys.executable, '-m', 'venv', str(interpreter.parent.parent)])
    if not receipt.data.get('verification_packages_installed'):
        receipt.run('fresh-locked-mcp-dependencies', [str(interpreter), '-m', 'pip', 'install', '-r', 'requirements.mcp.lock.txt'])
        receipt.run('fresh-noneditable-sdk-mcp', [str(interpreter), '-m', 'pip', 'install', '--no-build-isolation', '--no-deps',
                                                './packages/loomline-sdk', './packages/loomline-mcp'])
        receipt.run('fresh-runtime-pip-check', [str(interpreter), '-m', 'pip', 'check'])
        receipt.data['verification_packages_installed'] = True
        receipt.save()


def run_worker(receipt, mode):
    verification_runtime(receipt)
    runtime = receipt.logs / 'runtime'
    runtime.mkdir(exist_ok=True)
    receipt.run('independent-protocol-' + mode,
                [str(receipt.python()), str(receipt.work / 'scripts/product_acceptance.py'), '_worker',
                 '--receipt', str(receipt.path), '--mode', mode], cwd=runtime, timeout=240)
    # A separate fresh interpreter writes only safe IDs/counts to this result.
    result = json.loads((receipt.logs / ('worker-' + mode + '.json')).read_text())
    receipt.data.update(worker_results={**receipt.data.get('worker_results', {}), mode: result})
    receipt.save()


def verify(receipt):
    setup_identities(receipt)
    run_worker(receipt, 'verify')
    receipt.data['status'] = 'VERIFIED_AWAITING_BROWSER_AND_RESTART'
    receipt.save()


def restart(receipt):
    if 'verify' not in receipt.data.get('worker_results', {}):
        raise RuntimeError('Run verify successfully before the restart experiment')
    old = receipt.run('database-container-before', receipt.compose + ['ps', '-q', 'falkordb']).strip()
    mounts = json.loads(receipt.run('owned-persistent-volume', ['docker', 'inspect', '--format', '{{json .Mounts}}', old]))
    assert any(mount.get('Name') == receipt.data['project'] + '_graph_data' and mount['Destination'] == '/var/lib/falkordb/data'
               for mount in mounts if mount['Type'] == 'volume')
    receipt.run('graceful-gateway-router-stop', receipt.compose + ['stop', 'router', 'gateway'])
    receipt.run('database-container-replacement', receipt.compose + ['up', '-d', '--force-recreate', '--no-deps', 'falkordb', '--wait'])
    new = receipt.run('database-container-after', receipt.compose + ['ps', '-q', 'falkordb']).strip()
    assert old and new and old != new
    receipt.run('gateway-router-recovery', receipt.compose + ['up', '-d', '--wait'])
    run_worker(receipt, 'recover')
    receipt.data['status'] = 'PASS'
    receipt.data['services_running'] = True
    receipt.data['database_container_replaced'] = True
    receipt.data['persistent_volume_retained'] = True
    receipt.save()


def http_json(base, path, token=None, method='GET', body=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            text = response.read().decode()
            return response.status, json.loads(text) if text.startswith(('{', '[')) else text
    except HTTPError as error:
        text = error.read().decode()
        return error.code, json.loads(text) if text.startswith(('{', '[')) else text


def worker(receipt, mode):
    # This code runs in the NEW installed verification venv, outside checkout
    # import roots. Importing the server/DB/framework packages is not necessary.
    assert importlib.util.find_spec('backend') is None
    assert importlib.util.find_spec('falkordb') is None
    assert importlib.util.find_spec('crewai') is None
    import tomllib
    from loomline import LoomlineClient
    from loomline_mcp.config import load_profile
    from loomline_mcp.client_config import load_stdio_config
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    work = receipt.work
    base = f"http://127.0.0.1:{receipt.data['api_port']}"
    task = receipt.data['task_id']
    state_path = work / '.secrets/acceptance-state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        'observed_at': datetime.now(timezone.utc).isoformat(), 'records': {}}

    def save_state():
        write_json(state_path, state)
        if os.name != 'nt':
            state_path.chmod(0o600)

    save_state()
    def operation(label):
        return 'product_' + receipt.data['nonce'] + '_' + label

    def profile_for(name):
        return work / '.secrets/connections' / name / 'host.profile.json'

    def api_for(name):
        profile, token = load_profile(profile_for(name))
        return LoomlineClient(profile.base_url, token=token)

    @asynccontextmanager
    async def connect(name):
        folder = profile_for(name).parent
        entry = json.loads((folder / 'mcp_config.json').read_text())['mcpServers']['loomline']
        codex = tomllib.loads((folder / 'codex.toml').read_text())['mcp_servers']['loomline']
        assert entry == codex
        parameters = load_stdio_config(folder / 'mcp_config.json', allow_local_docker=True)
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer, read_timeout_seconds=60) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert len(tools.tools) == 27
                yield client

    async def call(client, name, **arguments):
        result = await client.call_tool('loomline_' + name, arguments)
        if result.is_error:
            # Do not echo raw argument bodies, auth configuration or tool text.
            raise RuntimeError('Independent MCP operation rejected: ' + name)
        assert result.structured_content['untrusted_data'] is True
        return result.structured_content['data']

    async def memory(client, label, **arguments):
        if label in state['records']:
            return state['records'][label]
        prior = await client.call_tool('loomline_operation_status', {'operation_id': operation(label)})
        if not prior.is_error:
            existing = prior.structured_content['data']
            value = {'receipt': existing}
        else:
            value = await call(client, 'remember', operation_id=operation(label), **arguments)
        state['records'][label] = value
        save_state()
        return value

    def snapshot():
        with api_for('accept_reviewer') as api:
            records = []
            for reference in [receipt.data['first_memory']['reference'], *state.get('references', [])]:
                record = dict(api.trace(reference))
                # Router delivery metadata is independently asynchronous and is
                # not a mutation of the stored memory/provenance/handoff facts.
                record['events'] = [{key: value for key, value in event.items()
                                     if key not in ('dispatch_status', 'dispatched_at', 'recipient_ids')}
                                    for event in record['events']]
                for collection in ('support', 'challenges', 'entities'):
                    record['memory'][collection].sort(key=lambda item: item['id'])
                record['related_handoffs'].sort(key=lambda item: item['id'])
                records.append(record)
            handoff = dict(api.get_handoff(task, state['handoff_id']))
            handoff['related_memory_ids'].sort()
        return {'traces': records, 'handoff': handoff}

    async def protocol():
        if mode == 'recover':
            async with connect('accept_reviewer') as reviewer:
                identity = await call(reviewer, 'whoami')
                assert identity['session_id'] != state['reviewer_session_before']
                for reference in state['references']:
                    assert (await call(reviewer, 'resolve', reference=reference))['id'] in state['memory_ids']
                assert (await call(reviewer, 'get_handoff', handoff_id=state['handoff_id']))['status'] == 'done'
                history = await call(reviewer, 'get_history', limit=10)
                assert any('Packaging acceptance' in turn['content'] for turn in history['items'])
                resumed = await call(reviewer, 'resume_task', operation_id=operation('recovery_session'))
                assert resumed['new_session_id'] != state['reviewer_session_before']
                assert resumed['context']['handoffs'][0]['status'] == 'done'
                fresh_session = resumed['new_session_id']
            stable = snapshot()
            assert sha(stable) == state['stable_state_sha256']
            return {'status': 'PASS', 'new_session_id': fresh_session,
                    'original_reviewer_session': state['reviewer_session_before'],
                    'stable_state_sha256': sha(stable), 'recovered_handoff_status': 'done',
                    'evidence': 'fresh generated Docker MCP process after gateway and DB container replacement',
                    'vendor_application_execution': False}

        async with connect('accept_writer') as writer, connect('accept_reviewer') as reviewer, connect('accept_third') as third:
            identities = [await call(client, 'whoami') for client in (writer, reviewer, third)]
            assert len({item['identity']['agent_id'] for item in identities}) == 3
            assert all(item['fixed_task_id'] == task for item in identities)
            state['reviewer_session_before'] = identities[1]['session_id']
            save_state()
            assert (await call(reviewer, 'resolve', reference=receipt.data['first_memory']['reference']))['id'] == receipt.data['first_memory']['memory_id']
            if 'support_evidence' not in state:
                evidence = await call(writer, 'add_evidence', operation_id=operation('support_evidence'),
                                      content='Actual operator SDK command committed and independently retrieved the source-linked onboarding episode.',
                                      source_type='tool', source_ref='acceptance:onboard-first-memory', observed_at=state['observed_at'])
                state['support_evidence'] = evidence['evidence_id']; save_state()
            decision = await memory(writer, 'decision', content='Packaging acceptance decision: inspect the source-linked shared memory before completing a handoff.',
                                    memory_class='semantic', assertion_type='decision', status='active', evidence_ids=[state['support_evidence']])
            hypothesis = await memory(writer, 'hypothesis', content='Packaging acceptance test hypothesis: the independent reviewer might be unable to resolve the committed memory.',
                                      memory_class='semantic', assertion_type='hypothesis', status='proposed')
            hypothesis_id = hypothesis['receipt']['memory_id']
            if 'challenge_evidence' not in state:
                resolved = await call(reviewer, 'resolve', reference=receipt.data['first_memory']['reference'])
                assert resolved['created_by'] == 'accept_writer'
                evidence = await call(reviewer, 'add_evidence', operation_id=operation('challenge_evidence'),
                                      content='Actual independent reviewer resolved the writer memory successfully using its distinct task-restricted credential.',
                                      source_type='tool', source_ref='acceptance:reviewer-resolve:' + resolved['id'], observed_at=state['observed_at'])
                state['challenge_evidence'] = evidence['evidence_id']; save_state()
            challenged = await call(reviewer, 'challenge', operation_id=operation('challenge'), memory_id=hypothesis_id,
                                    evidence_id=state['challenge_evidence'], reason='The actual successful authenticated resolve contradicts this test hypothesis.', expected_version=1)
            assert challenged['status'] == 'disputed'
            procedure = await memory(writer, 'procedure', content='Packaging acceptance procedure: verify source and handoff state before completing work.',
                                     memory_class='procedural', assertion_type='procedure', status='proposed',
                                     steps=['Resolve the referenced shared memory as the separate reviewer.', 'Read the source and evidence trace.', 'Complete the accepted handoff only after checks pass.'])
            procedure_id = procedure['receipt']['memory_id']
            owner_token = (work / '.secrets/operator.token').read_text().strip()
            with LoomlineClient(base, token=owner_token) as owner:
                owner.approve_procedure(task, procedure_id, expected_version=1,
                                        reason='Trusted clean-install operator explicitly reviewed the bounded acceptance procedure.', operation_id=operation('approve'))
            if not state.get('claim_contention_passed'):
                key = 'packaged_memory_review'
                results = await asyncio.gather(writer.call_tool('loomline_claim_work', {'operation_id': operation('writer_claim'), 'work_key': key, 'lease_seconds': 300}),
                                               reviewer.call_tool('loomline_claim_work', {'operation_id': operation('reviewer_claim'), 'work_key': key, 'lease_seconds': 300}))
                assert sum(not result.is_error for result in results) == 1
                winner = writer if not results[0].is_error else reviewer
                claim = next(result.structured_content['data'] for result in results if not result.is_error)
                assert claim['confirmed_owned_now']
                await call(winner, 'release_work', operation_id=operation('release_claim'), work_key=key, expected_version=claim['receipt']['version'])
                state['claim_contention_passed'] = True; save_state()
            if 'handoff_id' not in state:
                handoff = await call(writer, 'handoff', operation_id=operation('handoff'), to_agent_id='accept_reviewer',
                                     description='Independent protocol acceptance: inspect real persisted context and provenance, then finish this handoff.',
                                     related_memory_ids=[decision['receipt']['memory_id'], hypothesis_id, procedure_id])
                state['handoff_id'] = handoff['handoff_id']; save_state()
            handoff = await call(reviewer, 'get_handoff', handoff_id=state['handoff_id'])
            if handoff['status'] == 'open':
                await call(reviewer, 'accept_handoff', operation_id=operation('accept'), handoff_id=state['handoff_id'], expected_version=1)
            reference = decision['receipt']['reference']
            trace = await call(reviewer, 'trace', reference=reference)
            assert trace['memory']['created_by'] == 'accept_writer'
            assert trace['source_turn']['id'] == trace['memory']['source_turn_id']
            assert any(item['id'] == state['support_evidence'] for item in trace['memory']['support'])
            assert any(item['id'] == state['handoff_id'] for item in trace['related_handoffs'])
            verified = await memory(reviewer, 'reviewer_episode', content='Packaging acceptance: the independent reviewer resolved the writer memory and verified its source turn, supporting evidence and related handoff through actual MCP calls.',
                                    memory_class='episodic', assertion_type='episode', status='active', evidence_ids=[state['challenge_evidence']])
            handoff = await call(reviewer, 'get_handoff', handoff_id=state['handoff_id'])
            if handoff['status'] == 'accepted':
                done = await call(reviewer, 'complete_handoff', operation_id=operation('complete'), handoff_id=state['handoff_id'], expected_version=2)
                assert done['status'] == 'done'
            recalled = await call(third, 'recall', query='Packaging acceptance', limit=5)
            assert {decision['receipt']['memory_id'], hypothesis_id, procedure_id, verified['receipt']['memory_id']} <= {record['id'] for record in recalled['items']}
            state['references'] = [record['receipt']['reference'] for record in (decision, hypothesis, procedure, verified)]
            state['memory_ids'] = [record['receipt']['memory_id'] for record in (decision, hypothesis, procedure, verified)]
            save_state()

        viewer_profile, viewer_token = load_profile(profile_for('studio_reader'))
        code, graph = http_json(base, '/v1/tasks/' + task + '/graph?focus=' + decision['receipt']['memory_id'] + '&focus_type=Memory', viewer_token)
        assert code == 200 and graph['queries'] and len(graph['nodes']) <= 250 and len(graph['edges']) <= 400
        edge_types = {edge['type'] for edge in graph['edges']}
        assert {'HAS_MEMORY', 'CREATED', 'DERIVED_FROM', 'SUPPORTED_BY', 'REFERS_TO'} <= edge_types
        assert all(query['read_only'] and query['cypher'].startswith('MATCH') for query in graph['queries'])
        assert all(edge['source'] in {node['key'] for node in graph['nodes']} and edge['target'] in {node['key'] for node in graph['nodes']} for edge in graph['edges'])
        write_json(receipt.logs / 'graph-query-proof.json', graph)
        code, collaboration = http_json(base, '/v1/tasks/' + task + '/collaboration', viewer_token)
        assert code == 200 and collaboration['counts']['authorized_agents'] == 5
        assert 'studio_reader' not in {record['id'] for record in collaboration['contributors']}
        write_json(receipt.logs / 'collaboration-proof.json', collaboration)
        assert http_json(base, '/v1/me')[0] == 401
        assert http_json(base, '/v1/me', 'invalid-not-a-real-credential')[0] == 401
        assert http_json(base, '/v1/tasks/' + task + '/sessions', viewer_token, 'POST', {'operation_id': operation('viewer_write')})[0] == 403
        with LoomlineClient(base, token=(work / '.secrets/operator.token').read_text().strip()) as owner:
            if not state.get('private_task'):
                state['private_task'] = owner.create_task('Isolation control — operator only', assigned_agent_ids=['coordinator'], operation_id=operation('private_task')).task_id
                save_state()
        beta = json.loads((work / '.secrets/agent_tokens.json').read_text())['beta:coordinator']
        _, writer_token = load_profile(profile_for('accept_writer'))
        for suffix in ('context', 'graph', 'collaboration'):
            assert http_json(base, '/v1/tasks/' + state['private_task'] + '/' + suffix, writer_token)[0] == 404
            assert http_json(base, '/v1/tasks/' + task + '/' + suffix, beta)[0] == 404
        assert http_json(base, '/v1/tasks/' + task + '/graph?relationship=UNAUTHORIZED_TYPE', viewer_token)[0] == 400
        assert http_json(base, '/v1/tasks/' + task + '/graph?limit=1000', viewer_token)[0] == 400
        for document in ('README', 'START_HERE', 'AGENT_SETUP', 'STUDIO_AUTH', 'GRAPH_MODEL', 'MEMORY_GRAPH_GUIDE'):
            assert http_json(base, '/help/' + document)[0] == 200
        assert http_json(base, '/help/.secrets/operator.token')[0] == 404
        stable = snapshot()
        state['stable_state_sha256'] = sha(stable)
        save_state()
        return {'status': 'PASS', 'tools_discovered_per_client': 27, 'independent_mcp_clients': 3,
                'separate_identities': 3, 'memory_ids': state['memory_ids'],
                'first_memory_id': receipt.data['first_memory']['memory_id'],
                'handoff_id': state['handoff_id'], 'handoff_status': 'done', 'handoff_version': 3,
                'graph_nodes': len(graph['nodes']), 'graph_edges': len(graph['edges']),
                'graph_relationship_types': sorted(edge_types), 'query_inspector_operations': len(graph['queries']),
                'claim_contention': 'one winner; one rejected; successful release',
                'authentication': 'missing/invalid 401; viewer mutation 403',
                'isolation': 'different tenant and unauthorized same-tenant project both 404',
                'stable_state_sha256': sha(stable),
                'configurations': 'generated mcpServers JSON and matching Codex TOML; actual Docker stdio execution',
                'vendor_application_execution': False,
                'model_inference': 'NOT RUN: explicit acceptance inputs, not model responses'}

    result = asyncio.run(protocol())
    safe_output(work, result)
    write_json(receipt.logs / ('worker-' + mode + '.json'), result)
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='phase', required=True)
    p = sub.add_parser('start'); p.add_argument('--archive'); p.add_argument('--receipt')
    for phase in ('verify', 'restart', 'stop'):
        p = sub.add_parser(phase); p.add_argument('--receipt', required=True)
    p = sub.add_parser('_worker'); p.add_argument('--receipt', required=True); p.add_argument('--mode', choices=['verify', 'recover'], required=True)
    args = parser.parse_args()
    if args.phase == 'start' and not args.archive and not args.receipt:
        parser.error('start requires --archive for a new install or --receipt to resume')
    receipt = new_install(args.archive, args.receipt) if args.phase == 'start' and args.archive else Receipt(args.receipt)
    try:
        if args.phase == 'start': start(receipt)
        elif args.phase == 'verify': verify(receipt)
        elif args.phase == 'restart': restart(receipt)
        elif args.phase == 'stop':
            receipt.run('owned-services-stop-no-volume-deletion', receipt.compose + ['down'])
            receipt.data['services_running'] = False; receipt.save()
        else:
            worker(receipt, args.mode)
            return
    except Exception as error:
        # Leave this project's data available for diagnosis/resumption. Do not
        # echo exception arguments: network/client failures may contain inputs.
        receipt.data['status'] = 'FAIL'
        receipt.data['failure'] = type(error).__name__
        frames = traceback.extract_tb(error.__traceback__)
        location = {'file': Path(frames[-1].filename).name, 'line': frames[-1].lineno,
                    'function': frames[-1].name} if frames else None
        receipt.data['failure_location'] = location
        receipt.save()
        print(json.dumps({'status': 'FAIL', 'phase': args.phase, 'receipt': str(receipt.path),
                          'failure_type': type(error).__name__, 'private_logs': str(receipt.logs),
                          'failure_location': location,
                          'services_or_data_deleted': False}), file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps({'status': receipt.data['status'], 'receipt': str(receipt.path),
                      'studio_url': receipt.data['studio_url'], 'workspace': str(receipt.work),
                      'services_running': receipt.data.get('services_running', False),
                      'vendor_applications_executed': False}, indent=2))


if __name__ == '__main__':
    main()
