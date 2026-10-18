"""Stage a single mounted identity privately before starting the stdio server.

Windows Docker bind mounts expose synthetic POSIX permissions. The original
profile loader intentionally rejects world-readable credentials, so copy only
the explicitly mounted identity into an ephemeral 0700/0600 container directory
instead of relaxing that check or changing host credential permissions.
"""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile

from .config import Profile


def stage_profile(profile_path, *, source_root=Path('/run/loomline'), temporary_root=None):
    root = Path(source_root)
    source = Path(profile_path)
    if root.is_symlink() or source.is_symlink() or source != root / 'docker.profile.json':
        raise ValueError('MOUNTED_PROFILE_REQUIRED')
    if not source.is_file() or not 0 < source.stat().st_size <= 16384:
        raise ValueError('INVALID_MOUNTED_PROFILE')
    profile = Profile.model_validate_json(source.read_text(encoding='utf-8-sig'))
    token_name = PurePosixPath(profile.token_file)
    # This mount must contain one identity, never an absolute host token path,
    # symlink, parent traversal, or a sibling identity's private directory.
    if len(token_name.parts) != 1 or token_name.is_absolute() or token_name.name in ('.', '..') or '\\' in profile.token_file or ':' in profile.token_file:
        raise ValueError('RELATIVE_IDENTITY_TOKEN_REQUIRED')
    token_source = root / token_name.name
    if token_source.is_symlink() or not token_source.is_file() or token_source.resolve().parent != root.resolve():
        raise ValueError('MOUNTED_IDENTITY_TOKEN_REQUIRED')
    if not 0 < token_source.stat().st_size <= 1024:
        raise ValueError('INVALID_CREDENTIAL_FILE')
    token = token_source.read_text(encoding='utf-8').strip()
    if not token or any(character.isspace() for character in token):
        raise ValueError('INVALID_CREDENTIAL_FILE')
    private = Path(tempfile.mkdtemp(prefix='loomline-mcp-', dir=temporary_root))
    try:
        private.chmod(0o700)
        credential = private / 'agent.token'
        with os.fdopen(os.open(credential, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as output:
            output.write(token)
        staged = private / 'profile.json'
        value = profile.model_dump()
        value['token_file'] = 'agent.token'
        with os.fdopen(os.open(staged, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as output:
            output.write(json.dumps(value))
        return staged
    except BaseException:
        shutil.rmtree(private)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['serve', 'doctor', 'preflight'], nargs='?', default='serve')
    parser.add_argument('--profile', default='/run/loomline/docker.profile.json')
    args = parser.parse_args(argv)
    try:
        staged = stage_profile(args.profile)
        launcher = [sys.executable, '-m', 'loomline_mcp.preflight', '--profile', str(staged)] if args.command == 'preflight' else \
                   [sys.executable, '-m', 'loomline_mcp', args.command, '--profile', str(staged)]
        os.execv(sys.executable, launcher)
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and str(error).isupper() and str(error).replace('_', '').isalnum() else type(error).__name__.upper()
        print(json.dumps({'status': 'FAIL', 'code': code,
                          'guidance': 'Check the single-identity Docker mount and generated private profile. No credentials were printed.'}), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
