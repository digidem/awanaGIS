"""Decide whether an AI backend is configured (pure logic, no Qt).

The chat dock shows its provider setup screen instead of the chat when this
returns False.
"""

import os

from .. import config as config_mod
from ..backends import providers


def provider_needs_key(provider):
    """True when the provider (a registry dict or None) needs an API key."""
    return provider is None or bool(provider.get("key_env"))


def is_backend_configured(config, environ=None):
    """Whether ``config`` holds enough to talk to a model.

    API-key mode needs a base URL (provider default or override) and a key
    (saved, or from the provider's environment variable, as the backend does);
    key-less providers such as Ollama need no key. Custom mode needs its base
    URL. CLI modes are always treated as configured, as before.
    """
    environ = os.environ if environ is None else environ
    mode = config.get("connection_mode")
    if mode in (config_mod.MODE_CLI_TOOL, config_mod.MODE_SUBSCRIPTION):
        return True
    if mode == config_mod.MODE_CUSTOM:
        return bool((config.get("custom_base_url") or "").strip())
    provider = providers.get_provider(config.get("provider"))
    base_url = (config.get("api_base_url") or "").strip() or (provider or {}).get("base_url", "")
    if not base_url:
        return False
    if not provider_needs_key(provider):
        return True
    key = (config.get("api_key") or "").strip()
    if not key and provider:
        key = (environ.get(provider["key_env"], "") or "").strip()
    return bool(key)
