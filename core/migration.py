"""Opt-in, non-destructive migration helpers from legacy ``AgenticGIS/`` state.

Nothing in this module runs automatically on plugin startup or config load.
All functions are strictly read-only against the legacy ``AgenticGIS/``
``QSettings`` group and never copy credentials, API keys, OAuth tokens, or
security/privilege approvals.
"""

import json
import uuid

from qgis.PyQt.QtCore import QSettings

from .session_store import SCHEMA_VERSION, SETTINGS_KEY, _now

LEGACY_GROUP = "AgenticGIS"
TARGET_GROUP = "AwanaGIS"
LEGACY_SESSIONS_KEY = f"{LEGACY_GROUP}/sessions_json"

# Explicit allowlist of non-secret preference keys that may be imported on opt-in.
SAFE_PREFERENCE_KEYS = (
    "connection_mode",
    "cli_tool",
    "cli_model",
    "provider",
    "model",
    "custom_format",
    "custom_model",
    "system_prompt",
    "max_iterations",
    "main_thread_timeout",
    "processing_timeout",
    "mcp_poll_interval",
    "compaction_model",
    "font_scale",
)

# Secrets, security approvals, and port settings are strictly excluded.
FORBIDDEN_PREFERENCE_KEYS = frozenset({
    "api_key",
    "custom_api_key",
    "external_access_always_allowed",
    "gee_always_allowed",
    "auto_run",
    "confirm_dangerous_calls",
    "mcp_enabled",
    "mcp_port",
    "mcp_host",
    "sessions_json",
})

_FORBIDDEN_SUBSTRINGS = (
    "key",
    "token",
    "secret",
    "password",
    "credential",
    "auth",
    "allowed",
    "auto_run",
    "dangerous",
)


def _is_forbidden_key(name):
    lowered = str(name or "").lower()
    if lowered in FORBIDDEN_PREFERENCE_KEYS:
        return True
    return any(part in lowered for part in _FORBIDDEN_SUBSTRINGS)


def _legacy_keys_present(settings):
    """Return all legacy key suffixes stored under ``AgenticGIS/``."""
    settings.beginGroup(LEGACY_GROUP)
    try:
        return list(settings.childKeys())
    finally:
        settings.endGroup()


def _parse_sessions_payload(raw, *, strict_entries=False):
    """Parse and validate a legacy sessions JSON string without mutating state."""
    if raw is None or raw == "":
        return True, [], None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, RecursionError) as exc:
        return False, [], f"Invalid legacy session JSON: {exc}"
    if not isinstance(data, dict):
        return False, [], "Legacy session payload is not a JSON object."
    sessions = data.get("sessions")
    if not isinstance(sessions, list):
        return False, [], "Legacy session payload is missing a 'sessions' list."

    sanitized = []
    for entry in sessions:
        if not isinstance(entry, dict):
            if strict_entries:
                return False, [], "Session entry is not a JSON object."
            continue
        name = str(entry.get("name") or "").strip()
        history = entry.get("backend_history")
        identity = json.dumps({k: v for k, v in entry.items() if k != "id"},
                              sort_keys=True, separators=(",", ":"), default=str)
        sid = str(entry.get("id") or "").strip() or uuid.uuid5(
            uuid.NAMESPACE_URL, "agenticgis-legacy:" + identity
        ).hex
        created = str(entry.get("created_at") or _now())
        updated = str(entry.get("updated_at") or created)
        events = entry.get("transcript_events")
        state = entry.get("backend_state")
        sanitized.append({
            "id": sid,
            "name": name,
            "created_at": created,
            "updated_at": updated,
            "backend_history": history if isinstance(history, list) else [],
            "transcript_events": events if isinstance(events, list) else [],
            "backend_state": state if isinstance(state, dict) else {},
        })
    return True, sanitized, None


def inspect_legacy_data(settings=None):
    """Inspect legacy ``AgenticGIS/`` settings & sessions without modifying anything."""
    s = settings or QSettings()
    child_keys = _legacy_keys_present(s)
    safe_keys = [
        key for key in SAFE_PREFERENCE_KEYS
        if key in child_keys and not _is_forbidden_key(key)
    ]
    excluded_keys = [
        key for key in child_keys
        if key not in safe_keys and key != "sessions_json"
    ]
    raw_sessions = s.value(LEGACY_SESSIONS_KEY, "")
    sessions_valid, sessions, sessions_error = _parse_sessions_payload(raw_sessions)
    return {
        "has_preferences": bool(safe_keys),
        "preference_keys": safe_keys,
        "excluded_keys": sorted(excluded_keys),
        "has_sessions": bool(sessions),
        "session_count": len(sessions),
        "sessions_valid": sessions_valid,
        "sessions_error": sessions_error,
    }


def import_preferences_from_agenticgis(settings=None, *, overwrite=False):
    """Copy non-secret preferences from ``AgenticGIS/`` into ``AwanaGIS/``.

    Strictly read-only on ``AgenticGIS/``. Never copies API keys, tokens, or
    security/privilege approvals.
    """
    s = settings or QSettings()
    child_keys = set(_legacy_keys_present(s))
    imported = []
    skipped = []
    excluded = sorted(
        key for key in child_keys
        if key != "sessions_json" and (key not in SAFE_PREFERENCE_KEYS or _is_forbidden_key(key))
    )

    for key in SAFE_PREFERENCE_KEYS:
        if key not in child_keys or _is_forbidden_key(key):
            continue
        src_key = f"{LEGACY_GROUP}/{key}"
        dst_key = f"{TARGET_GROUP}/{key}"
        if not overwrite and s.contains(dst_key):
            skipped.append(key)
            continue
        value = s.value(src_key)
        if value is not None:
            s.setValue(dst_key, value)
            imported.append(key)

    s.sync()
    return {
        "ok": True,
        "imported_keys": imported,
        "skipped_keys": skipped,
        "excluded_keys": excluded,
    }


def import_sessions_from_agenticgis(settings=None, *, limit=20):
    """Merge valid chat sessions from ``AgenticGIS/sessions_json`` into ``AwanaGIS/sessions_json``.

    Idempotent by session ID; never modifies or deletes ``AgenticGIS/`` data.
    """
    s = settings or QSettings()
    raw_legacy = s.value(LEGACY_SESSIONS_KEY, "")
    if not raw_legacy:
        return {"ok": True, "imported_count": 0, "skipped_count": 0, "error": None}

    valid, legacy_sessions, err = _parse_sessions_payload(raw_legacy)
    if not valid:
        return {"ok": False, "imported_count": 0, "skipped_count": 0, "error": err}

    raw_target = s.value(SETTINGS_KEY, "")
    target_valid, target_sessions, _ = _parse_sessions_payload(raw_target, strict_entries=True)
    if not target_valid:
        return {"ok": False, "imported_count": 0, "skipped_count": 0,
                "error": "Existing AwanaGIS session data is unreadable; import skipped to avoid overwriting it."}
    target_data = {}
    if raw_target:
        try:
            parsed_target = json.loads(raw_target)
            if isinstance(parsed_target, dict):
                target_data = parsed_target
        except (TypeError, ValueError):
            target_data = {}

    capacity = max(0, int(limit or 20))
    existing_ids = {item["id"] for item in target_sessions}
    candidates = []
    skipped_count = 0
    for session in legacy_sessions:
        if session["id"] in existing_ids:
            skipped_count += 1
            continue
        existing_ids.add(session["id"])
        candidates.append(session)

    # Preserve all existing AwanaGIS sessions first; fill only remaining capacity.
    candidates.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    remaining = max(0, capacity - len(target_sessions))
    retained_legacy = candidates[:remaining]
    dropped_count = max(0, len(candidates) - len(retained_legacy))
    imported_count = len(retained_legacy)

    if imported_count > 0:
        merged = list(target_sessions) + retained_legacy
        merged.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        active_id = target_data.get("active_session_id")
        valid_ids = {item["id"] for item in merged}
        if not isinstance(active_id, str) or active_id not in valid_ids:
            active_id = merged[0]["id"] if merged else None
        payload = {
            "schema_version": SCHEMA_VERSION,
            "active_session_id": active_id,
            "sessions": merged,
        }
        s.setValue(SETTINGS_KEY, json.dumps(payload, separators=(",", ":")))
        s.sync()

    return {
        "ok": True,
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "dropped_count": dropped_count,
        "error": None,
    }


def import_from_agenticgis(
    settings=None,
    *,
    include_preferences=True,
    include_sessions=True,
    overwrite_preferences=False,
    session_limit=20,
):
    """Run opt-in, non-destructive import of non-secret preferences and sessions."""
    s = settings or QSettings()
    pref_result = (
        import_preferences_from_agenticgis(s, overwrite=overwrite_preferences)
        if include_preferences
        else {"ok": True, "imported_keys": [], "skipped_keys": [], "excluded_keys": []}
    )
    sess_result = (
        import_sessions_from_agenticgis(s, limit=session_limit)
        if include_sessions
        else {"ok": True, "imported_count": 0, "skipped_count": 0, "error": None}
    )
    return {
        "ok": bool(pref_result.get("ok") and sess_result.get("ok")),
        "preferences": pref_result,
        "sessions": sess_result,
    }
