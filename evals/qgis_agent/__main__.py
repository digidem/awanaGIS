"""Run explicitly configured live model evaluations."""
import argparse
import json
import os
import signal
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .cases import CASES
from .runner import backend_record, run_case


def _write_supervisor_report(parent_fd, output, status, identity, detail):
    payload = json.dumps(
        dict(
            identity,
            status=status,
            turns=[],
            artifacts=[],
            checks=[{'id': 'runner', 'status': 'blocked', 'detail': detail}],
        ),
        ensure_ascii=False,
        indent=2,
    ) + '\n'
    if parent_fd is None:
        output.mkdir(parents=True, exist_ok=True)
        (output / 'run.json').write_text(payload, encoding='utf-8')
        return
    out_fd = None
    try:
        try:
            st = os.lstat(output.name, dir_fd=parent_fd)
            if not stat.S_ISDIR(st.st_mode):
                return
        except FileNotFoundError:
            os.mkdir(output.name, mode=0o755, dir_fd=parent_fd)
        out_fd = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            st = os.lstat('run.json', dir_fd=out_fd)
        except FileNotFoundError:
            st = None
        if st is not None:
            if status != 'timeout' or not stat.S_ISREG(st.st_mode):
                return
            os.unlink('run.json', dir_fd=out_fd)
        fd = os.open('run.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=out_fd)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(payload)
    except OSError:
        return
    finally:
        if out_fd is not None:
            os.close(out_fd)


_PRESERVED_ENV_KEYS = frozenset({
    'HOME',
    'LANG',
    'LC_ALL',
    'LC_CTYPE',
    'PATH',
    'PYTHONPATH',
    'PYTHONDONTWRITEBYTECODE',
    'QGIS_CUSTOM_CONFIG_PATH',
    'QT_QPA_PLATFORM',
    'TMPDIR',
    'XDG_CACHE_HOME',
    'XDG_CONFIG_HOME',
    'XDG_DATA_HOME',
    'XDG_RUNTIME_DIR',
})


def _scrubbed_worker_env(provider, key_env):
    """Pass only runtime variables and the single credential needed by the worker."""
    from .runner import provider_key_env

    allowed = set(_PRESERVED_ENV_KEYS)
    needed_key = provider_key_env(provider, key_env)
    if needed_key:
        allowed.add(needed_key)
    env = {}
    for name, value in os.environ.items():
        if (
            name in allowed
            or name.startswith('AWANAGIS_')
            or name.startswith('QGIS_')
            or name.startswith('QT_')
        ):
            env[name] = value
    return env


def supervise(command, output, timeout, identity, env=None):
    output = Path(output)
    parent_fd = None
    if os.name == 'posix' and hasattr(os, 'O_NOFOLLOW') and hasattr(os, 'O_DIRECTORY'):
        output.parent.mkdir(parents=True, exist_ok=True)
        parent_fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        process = subprocess.Popen(command, start_new_session=True, env=env)
        detail = None
        try:
            code = process.wait(timeout=timeout)
            status = 'error' if code else None
            if status:
                detail = f'Worker exited with code {code} before writing a report'
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            status = 'timeout'
            detail = f'Worker passed the {timeout:g} second deadline and was killed'
        if status:
            _write_supervisor_report(parent_fd, output, status, identity, detail)
        return status
    finally:
        if parent_fd is not None:
            os.close(parent_fd)


def parse_args(argv=None, parser=None):
    if parser is None:
        parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True, choices=sorted(CASES))
    parser.add_argument('--output', required=True, help='New output directory; repeated runs use numbered children')
    parser.add_argument('--provider', required=True, help='Configured AwanaGIS API provider')
    parser.add_argument('--model', required=True, help='Explicit model identifier')
    parser.add_argument('--base-url', metavar='URL', help='OpenAI-compatible custom endpoint base URL')
    parser.add_argument('--key-env', metavar='NAME', help='Environment variable holding the custom endpoint API key')
    parser.add_argument('--variant', default='baseline')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--plugin-path', help='Installed CoMapeo Map Builder plugin directory')
    parser.add_argument('--timeout', type=float, default=900)
    parser.add_argument('--allow-pyqgis', action='store_true',
                        help='Allow run_pyqgis inside an isolated sandbox (or set AWANAGIS_EVAL_ISOLATED=1)')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    if args.repeat < 1:
        parser.error('--repeat must be positive')
    if (args.base_url is None) != (args.key_env is None):
        parser.error('--base-url and --key-env must be given together')
    if args.base_url is not None:
        if args.provider != 'custom':
            parser.error('--base-url requires --provider custom')
        try:
            parsed = urlsplit(args.base_url)
            host = parsed.hostname
        except ValueError:
            parser.error('--base-url must be a valid absolute URL with a host')
        if not host:
            parser.error('--base-url must include a host')
        if parsed.username is not None or parsed.password is not None:
            parser.error('--base-url must not contain user information')
        if parsed.fragment or '#' in args.base_url:
            parser.error('--base-url must not contain a fragment')
        if parsed.query or '?' in args.base_url:
            parser.error('--base-url must not contain a query string')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and host in ('127.0.0.1', 'localhost')):
            parser.error('--base-url must use https, or http with host 127.0.0.1 or localhost')
    return args


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    args = parse_args(argv, parser)
    raw_output = Path(args.output)
    allow_pyqgis = bool(args.allow_pyqgis or os.environ.get('AWANAGIS_EVAL_ISOLATED') == '1')
    if args.worker:
        output = raw_output.resolve()
        trace = run_case(args.case, output, args.provider, args.model, args.variant, plugin_path=args.plugin_path,
                         base_url=args.base_url, key_env=args.key_env, allow_pyqgis=allow_pyqgis)
        return 0 if trace['status'] == 'completed' else 1
    if os.path.lexists(raw_output) or raw_output.exists():
        parser.error('--output must not exist')
    output = raw_output.resolve()
    if output.exists():
        parser.error('--output must not exist')
    if args.repeat > 1:
        output.mkdir(parents=True)
    failed = False
    identity = {'case': args.case, 'variant': args.variant,
                'backend': backend_record(args.provider, args.model, args.base_url)}
    if args.base_url is not None:
        identity['key_env'] = args.key_env
    worker_env = _scrubbed_worker_env(args.provider, args.key_env)
    if allow_pyqgis:
        worker_env['AWANAGIS_EVAL_ISOLATED'] = '1'
    for index in range(1, args.repeat + 1):
        target = output if args.repeat == 1 else output / f'run-{index:02}'
        command = [sys.executable, '-m', __package__, '--worker', '--case', args.case,
                   '--output', str(target), '--provider', args.provider, '--model', args.model,
                   '--variant', args.variant]
        if args.plugin_path:
            command.extend(['--plugin-path', args.plugin_path])
        if args.base_url is not None:
            command.extend(['--base-url', args.base_url, '--key-env', args.key_env])
        if allow_pyqgis:
            command.append('--allow-pyqgis')
        status = supervise(command, target, args.timeout, identity, env=worker_env)
        failed = failed or bool(status)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
