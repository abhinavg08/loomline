"""Filesystem-only checks; no fake protocol server or database responses."""
import json
import os
from pathlib import Path
import secrets
import shutil

import pytest

from loomline_mcp.config import load_profile
from loomline_mcp.docker_entrypoint import stage_profile


def mounted_identity(tmp_path, **changes):
    root = tmp_path / 'single identity'
    root.mkdir()
    token = secrets.token_urlsafe(32)
    (root / 'agent.token').write_text(token)
    if os.name != 'nt':
        (root / 'agent.token').chmod(0o777)
    value = {'base_url': 'http://gateway:8000', 'task_id': 'task_filesystem_unit',
             'token_file': 'agent.token', 'allow_procedure_approval': False}
    value.update(changes)
    profile = root / 'docker.profile.json'
    profile.write_text(json.dumps(value))
    return root, profile, token


def test_readonly_mount_is_staged_privately_without_changing_host(tmp_path, capsys):
    root, profile, token = mounted_identity(tmp_path)
    original_profile = profile.read_bytes()
    original_mode = (root / 'agent.token').stat().st_mode
    staged = stage_profile(profile, source_root=root, temporary_root=tmp_path)
    try:
        loaded, credential = load_profile(staged)
        assert credential == token and loaded.task_id == 'task_filesystem_unit'
        assert loaded.token_file == 'agent.token'
        assert profile.read_bytes() == original_profile
        assert (root / 'agent.token').stat().st_mode == original_mode
        assert staged.parent != root and staged.parent.parent == tmp_path
        if os.name != 'nt':
            assert staged.parent.stat().st_mode & 0o777 == 0o700
            assert staged.stat().st_mode & 0o777 == 0o600
            assert (staged.parent / 'agent.token').stat().st_mode & 0o777 == 0o600
        assert capsys.readouterr().out == ''
    finally:
        shutil.rmtree(staged.parent)


def test_mount_cannot_point_to_another_identity_or_absolute_credential(tmp_path):
    root, profile, _ = mounted_identity(tmp_path)
    original = json.loads(profile.read_text())
    for token_file in ('../other/agent.token', '/tmp/agent.token', 'C:\\secrets\\agent.token',
                       'nested/agent.token', '..', ''):
        profile.write_text(json.dumps({**original, 'token_file': token_file}))
        with pytest.raises(ValueError, match='RELATIVE_IDENTITY_TOKEN_REQUIRED'):
            stage_profile(profile, source_root=root, temporary_root=tmp_path)
    with pytest.raises(ValueError, match='MOUNTED_PROFILE_REQUIRED'):
        stage_profile(root / 'different.json', source_root=root, temporary_root=tmp_path)
    assert not list(tmp_path.glob('loomline-mcp-*'))


def test_invalid_or_oversized_mounts_fail_before_private_staging(tmp_path):
    root, profile, _ = mounted_identity(tmp_path)
    original = profile.read_text()
    profile.write_text('x' * 16385)
    with pytest.raises(ValueError, match='INVALID_MOUNTED_PROFILE'):
        stage_profile(profile, source_root=root, temporary_root=tmp_path)
    profile.write_text(original)
    for value in ('x' * 1025, 'embedded whitespace', ''):
        (root / 'agent.token').write_text(value)
        with pytest.raises(ValueError, match='INVALID_CREDENTIAL_FILE'):
            stage_profile(profile, source_root=root, temporary_root=tmp_path)
    assert not list(tmp_path.glob('loomline-mcp-*'))


def test_symlink_credentials_are_rejected(tmp_path):
    root, profile, token = mounted_identity(tmp_path)
    outside = tmp_path / 'outside.token'
    outside.write_text(token)
    credential = root / 'agent.token'
    credential.unlink()
    try:
        credential.symlink_to(outside)
    except OSError:
        pytest.skip('Host account cannot create symlinks; Linux packaged check exercises this guard')
    with pytest.raises(ValueError, match='MOUNTED_IDENTITY_TOKEN_REQUIRED'):
        stage_profile(profile, source_root=root, temporary_root=tmp_path)
    assert not list(tmp_path.glob('loomline-mcp-*'))
