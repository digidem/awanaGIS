"""Provider registry for the API-key connection method.

Built-in providers are pre-configured with their chat endpoint, wire format
(``anthropic`` or ``openai``), a sensible current default model, and the
customary environment variable for the key. The ``Custom`` pseudo-provider lets
the user set their own base URL and format.
"""

BUILT_INS = [
    {
        "id": "tinfoil",
        "label": "Tinfoil (private inference)",
        "base_url": "https://inference.tinfoil.sh/v1",
        "format": "openai",
        "default_model": "deepseek-v4-1-flash",
        "key_env": "TINFOIL_API_KEY",
        # GET /models is unauthenticated, so it cannot validate a key.
        "models_public": True,
    },
    {
        "id": "anthropic",
        "label": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "format": "anthropic",
        "default_model": "claude-opus-4-8",
        "key_env": "ANTHROPIC_API_KEY",
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "format": "openai",
        "default_model": "gpt-4.1",
        "key_env": "OPENAI_API_KEY",
    },
    {
        "id": "groq",
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "format": "openai",
        "default_model": "llama-3.3-70b-versatile",
        "key_env": "GROQ_API_KEY",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "format": "openai",
        "default_model": "anthropic/claude-sonnet-4",
        "key_env": "OPENROUTER_API_KEY",
    },
    {
        "id": "gemini",
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "format": "openai",
        "default_model": "gemini-2.0-flash",
        "key_env": "GOOGLE_API_KEY",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "format": "openai",
        "default_model": "deepseek-chat",
        "key_env": "DEEPSEEK_API_KEY",
    },
    {
        "id": "mistral",
        "label": "Mistral",
        "base_url": "https://api.mistral.ai/v1",
        "format": "openai",
        "default_model": "mistral-large-latest",
        "key_env": "MISTRAL_API_KEY",
    },
    {
        "id": "xai",
        "label": "xAI (Grok)",
        "base_url": "https://api.x.ai/v1",
        "format": "openai",
        "default_model": "grok-3-beta",
        "key_env": "XAI_API_KEY",
    },
    {
        "id": "ollama",
        "label": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "format": "openai",
        "default_model": "llama3.1",
        "key_env": "",
    },
]

BY_ID = {p["id"]: p for p in BUILT_INS}


def get_provider(provider_id):
    """Return a provider dict, or None."""
    return BY_ID.get(provider_id)


def all_providers():
    """Return the built-in provider list (for UI dropdowns)."""
    return list(BUILT_INS)


def pick_default_model(provider_id, models, current=""):
    """Choose the model to preselect once a provider's model list arrives.

    Keeps ``current`` when the provider lists it; otherwise falls back to the
    provider's default model when listed, else the first listed model. With an
    empty list there is nothing to choose from, so ``current`` (or the
    provider default) is returned unchanged.
    """
    models = list(models or [])
    current = (current or "").strip()
    provider = get_provider(provider_id) or {}
    default = provider.get("default_model", "")
    if not models:
        return current or default
    if current and current in models:
        return current
    if default and default in models:
        return default
    return models[0]


def fetch_models(fmt, base_url, key, provider_id=None):
    """List models from a provider endpoint; ``(models, error)``.

    Blocking network call: run it off the UI thread. Doubles as a connection
    test (a bad key or URL comes back as the error).
    """
    if fmt == "anthropic":
        from .anthropic_http import AnthropicHttpClient

        client = AnthropicHttpClient(api_key=key or None, base_url=base_url or None)
    else:
        from .openai_http import OpenAIHttpClient

        client = OpenAIHttpClient(api_key=key or None, base_url=base_url or None)
        models, err = client.list_models()
        provider = get_provider(provider_id) or {}
        if not err and provider.get("models_public"):
            # The listing needs no key, so prove the key works with a probe.
            probe_err = client.check_key(pick_default_model(provider_id, models))
            if probe_err:
                return [], probe_err
        return models, err
    return client.list_models()
