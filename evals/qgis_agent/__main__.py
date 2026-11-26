"""Run explicitly configured live model evaluations."""
import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from .cases import CASES
from .runner import run_case


def supervise(command, output, timeout, identity):
    process = subprocess.Popen(command, start_new_session=True)
    try:
        code = process.wait(timeout=timeout)
        status = 'error' if code else None
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        status = 'timeout'
    report = output / 'run.json'
    if status and (status == 'timeout' or not report.exists()):
        output.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(dict(identity, status=status, turns=[], artifacts=[],
                                          checks=[{'id': 'runner', 'status': 'blocked', 'detail': status}]),
                                     ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True, choices=sorted(CASES))
    parser.add_argument('--output', required=True, help='New output directory; repeated runs use numbered children')
    parser.add_argument('--provider', required=True, help='Configured AwanaGIS API provider')
    parser.add_argument('--model', required=True, help='Explicit model identifier')
    parser.add_argument('--variant', default='baseline')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--plugin-path', help='Installed CoMapeo Map Builder plugin directory')
    parser.add_argument('--timeout', type=float, default=900)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    if args.repeat < 1:
        parser.error('--repeat must be positive')
    output = Path(args.output).resolve()
    if args.worker:
        trace = run_case(args.case, output, args.provider, args.model, args.variant, plugin_path=args.plugin_path)
        return 0 if trace['status'] == 'completed' else 1
    if output.exists():
        parser.error('--output must not exist')
    if args.repeat > 1:
        output.mkdir(parents=True)
    failed = False
    for index in range(1, args.repeat + 1):
        target = output if args.repeat == 1 else output / f'run-{index:02}'
        command = [sys.executable, '-m', __package__, '--worker', '--case', args.case,
                   '--output', str(target), '--provider', args.provider, '--model', args.model,
                   '--variant', args.variant]
        if args.plugin_path:
            command.extend(['--plugin-path', args.plugin_path])
        status = supervise(command, target, args.timeout, {'case': args.case, 'variant': args.variant,
                                                           'backend': {'provider': args.provider, 'model': args.model}})
        failed = failed or bool(status)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
