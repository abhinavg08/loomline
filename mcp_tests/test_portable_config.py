"""Parser checks do not execute Docker or substitute fake memory storage."""
import json
from pathlib import Path
import shutil
import sys

import pytest

from loomline_mcp.client_config import load_stdio_config


def docker_config(tmp_path):
    checkout = tmp_path / 'portable checkout with spaces'
    checkout.mkdir()
    (checkout / 'docker-compose.yml').write_text('services: {}\n')
    entry = {'command': 'docker', 'args': ['compose', '--project-directory', str(checkout),
             '--profile', 'app', 'run', '--rm', '--no-deps', '-T', 'mcp', '--profile',
             '/run/loomline/docker.profile.json'],
             'env': {'LOOM_MCP_DIRECTORY': './.secrets/connections/codex'}}
    target = tmp_path / 'mcp_config.json'
    def write(value=entry):
        target.write_text(json.dumps({'mcpServers': {'loomline': value}}))
        return target
    return entry, write


def test_generated_docker_configuration_requires_explicit_local_code_trust(tmp_path):
    entry, write = docker_config(tmp_path)
    target = write()
    with pytest.raises(ValueError, match='EXPLICIT_TRUST'):
        load_stdio_config(target)
    if not shutil.which('docker'):
        pytest.skip('This parser-positive check requires Docker on the host PATH')
    result = load_stdio_config(target, allow_local_docker=True)
    assert Path(result.command).resolve() == Path(shutil.which('docker')).resolve()
    assert result.args == entry['args']
    assert result.env == entry['env']
    assert Path(result.cwd).resolve() == Path(entry['args'][2]).resolve()


def test_docker_flags_environment_and_checkout_are_narrowly_allowlisted(tmp_path):
    if not shutil.which('docker'):
        pytest.skip('This parser-negative check requires Docker on the host PATH')
    original, write = docker_config(tmp_path)
    cases = []
    for mutation in (
        lambda entry: entry['args'].append('--privileged'),
        lambda entry: entry['args'].__setitem__(9, 'operator'),
        lambda entry: entry['args'].__setitem__(11, '/other/profile'),
        lambda entry: entry['args'].__setitem__(2, 'relative/checkout'),
        lambda entry: entry['env'].__setitem__('FALKORDB_PASSWORD', 'must_not_be_passed'),
        lambda entry: entry['env'].__setitem__('LOOM_MCP_DIRECTORY', '/another/identity'),
        lambda entry: entry['env'].__setitem__('LOOM_MCP_DIRECTORY', './.secrets/connections/../other'),
        lambda entry: entry.__setitem__('cwd', str(tmp_path)),
        lambda entry: entry.__setitem__('command', str(tmp_path / 'docker.exe')),
    ):
        entry = json.loads(json.dumps(original))
        mutation(entry)
        cases.append(entry)
    for entry in cases:
        with pytest.raises(ValueError):
            load_stdio_config(write(entry), allow_local_docker=True)


def test_native_python_configuration_remains_supported_and_rejects_other_programs(tmp_path):
    entry = {'command': str(Path(sys.executable).resolve()), 'args': ['-m', 'loomline_mcp'],
             'cwd': str(tmp_path), 'env': {'LOOM_MCP_PROFILE': str(tmp_path / 'private.profile.json')}}
    target = tmp_path / 'native.json'
    target.write_text(json.dumps({'mcpServers': {'loomline': entry}}))
    assert load_stdio_config(target).args == ['-m', 'loomline_mcp']
    entry['args'] = ['-c', 'print("not an allowed launcher")']
    target.write_text(json.dumps({'mcpServers': {'loomline': entry}}))
    with pytest.raises(ValueError, match='UNSUPPORTED_LAUNCHER_ARGUMENTS'):
        load_stdio_config(target)
