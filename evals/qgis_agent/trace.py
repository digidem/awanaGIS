"""Minimal serializable traces; tool arguments and results are not retained."""
import hashlib
import json
import math
import os
import secrets as secure_random
import string
import time
from pathlib import Path


def _redaction_placeholder(secrets):
    """Choose a marker that cannot recreate a run secret at a replacement boundary."""
    candidates = '*#x-0'
    default = '[redacted]'
    default_safe = all('[' not in secret and ']' not in secret and secret not in default and default not in secret
                       for secret in secrets)
    # Single-character candidate keys retain the established fallback marker.
    candidate_key = any(len(secret) == 1 and secret in candidates for secret in secrets)
    if default_safe and not candidate_key:
        return default
    for character in candidates + string.ascii_letters + string.digits:
        if not any(character in secret for secret in secrets):
            return character * 3
    for _ in range(64):
        marker = secure_random.token_hex(8)
        if not any(marker in secret for secret in secrets):
            return marker
    raise RuntimeError('Unable to choose a secret-free redaction placeholder')


def redact(text, secrets=()):
    run_secrets = tuple(secret for secret in secrets if secret)
    placeholder = _redaction_placeholder(run_secrets)
    for key, value in os.environ.items():
        if len(value) >= 4 and any(word in key.upper() for word in ('API_KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
            text = text.replace(value, '[redacted]')
    for secret in run_secrets:
        text = text.replace(secret, placeholder)
    return text


def event_record(event, started, output_dir=None, secrets=()):
    kind = str(event.type)
    data = event.data if isinstance(event.data, dict) else {}
    if kind in ('text', 'ask_user'):
        # Assistant prose may require human review; do not persist raw tool payloads.
        clean = {key: redact(str(data[key]), secrets) for key in ('text', 'question') if key in data}
    elif kind == 'tool_use':
        arguments = data.get('input', {})
        raw = json.dumps(arguments, sort_keys=True, default=str).encode()
        clean = {'name': str(data.get('name', '')), 'args_sha256': hashlib.sha256(raw).hexdigest()}
        if clean['name'] == 'run_processing' and isinstance(arguments, dict):
            clean['smp_export'] = arguments.get('alg_id') == 'smp:generatesmp'
        if clean['name'] == 'export_layout' and output_dir is not None and isinstance(arguments, dict):
            output, layout_id = arguments.get('output_path'), arguments.get('layout_id')
            if isinstance(output, str) and isinstance(layout_id, str):
                path = Path(output).resolve()
                if path.suffix.lower() == '.pdf' and path.is_relative_to(output_dir):
                    clean['pdf_export'] = {'output': redact(str(path.relative_to(output_dir)), secrets),
                                           'layout_id': redact(layout_id.strip(), secrets)}
    elif kind == 'tool_result':
        result = data.get('result')
        failed = bool(data.get('is_error') or data.get('cancelled') or
                      (isinstance(result, dict) and (result.get('error') or result.get('ok') is False)))
        clean = {'name': str(data.get('name', '')), 'status': 'error' if failed else 'unknown'}
        if clean['name'] == 'ask_user' and data.get('cancelled') and not data.get('is_error'):
            clean['status'] = 'dismissed'
        if 'permission denied' in str(result).casefold():
            clean['permission_denied'] = True
        if isinstance(result, str):
            clean['result_bytes'] = len(result.encode())
        if clean['name'] == 'run_processing' and not failed:
            try:
                payload = json.loads(result) if isinstance(result, str) else result
            except json.JSONDecodeError:
                payload = None
            elapsed = payload.get('elapsed') if isinstance(payload, dict) and payload.get('ok') is True else None
            if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0:
                clean['processing_seconds'] = elapsed
    else:
        clean = {}
    return {'type': kind, 'data': clean, 'elapsed_seconds': time.monotonic() - started}


def smp_export_seconds(events):
    durations = []
    pending_export = False
    for event in events:
        data = event['data']
        if event['type'] == 'tool_use':
            pending_export = data.get('smp_export', False)
        elif event['type'] == 'tool_result':
            if pending_export and 'processing_seconds' in data:
                durations.append(data['processing_seconds'])
            pending_export = False
    return sum(durations) if durations else None


def pdf_exports(events):
    exports = []
    pending = None
    for event in events:
        data = event['data']
        if event['type'] == 'tool_use':
            pending = data.get('pdf_export')
        elif event['type'] == 'tool_result':
            if pending and data.get('name') == 'export_layout' and data.get('status') != 'error':
                exports.append(pending)
            pending = None
    return exports


def artifacts_under(directory):
    directory = Path(directory).absolute()
    if not directory.is_dir() or directory.resolve() != directory:
        return []
    return sorted(str(path.relative_to(directory)) for path in directory.rglob('*')
                  if not path.is_symlink() and path.is_file() and path.resolve().is_relative_to(directory.resolve()))


def _redact_value(value, secrets, placeholder):
    """Redact run secrets before JSON escaping can change their representation."""
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, placeholder)
        return value
    if isinstance(value, (list, tuple)):
        return [_redact_value(item, secrets, placeholder) for item in value]
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            clean_key = _redact_value(key, secrets, placeholder) if isinstance(key, str) else key
            if clean_key in redacted:
                resolved = None
                for suffix in range(2, 1025):
                    candidate = f'{clean_key}#{suffix}'
                    if candidate not in redacted and not any(secret in candidate for secret in secrets):
                        resolved = candidate
                        break
                if resolved is None:
                    for _ in range(64):
                        candidate = f'{placeholder}_{secure_random.token_hex(8)}'
                        if candidate not in redacted and not any(secret in candidate for secret in secrets):
                            resolved = candidate
                            break
                if resolved is None:
                    raise RuntimeError('Unable to resolve secret-free dictionary key collision')
                clean_key = resolved
            redacted[clean_key] = _redact_value(item, secrets, placeholder)
        return redacted
    text = str(value)
    if any(secret in text for secret in secrets):
        for secret in secrets:
            text = text.replace(secret, placeholder)
        return text
    return value


def redact_trace(trace, secrets=()):
    """Return a run-safe trace while preserving trusted endpoint metadata."""
    run_secrets = tuple(secret for secret in secrets if secret)
    if not run_secrets:
        return trace
    placeholder = _redaction_placeholder(run_secrets)
    trusted = ('backend', 'key_env', 'status', 'variant', 'case')
    return {key: value if key in trusted else _redact_value(value, run_secrets, placeholder)
            for key, value in trace.items()}


def write_trace(path, trace, secrets=()):
    trace = redact_trace(trace, secrets)
    payload = json.dumps(trace, ensure_ascii=False, indent=2, default=str) + '\n'
    Path(path).write_text(payload, encoding='utf-8')
    return trace
