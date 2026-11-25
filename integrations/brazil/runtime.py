"""QGIS Processing provider lifecycle management for AwanaGIS Brazil.

Provider registration happens strictly during plugin ``initGui()`` / ``unload()``
and never at module import time. Any separately installed ``gisbr`` plugin
provider is left completely untouched.
"""

import threading

_PROVIDER_ID = "awanagis_brazil"
_LOCK = threading.Lock()
_REGISTERED_PROVIDER = None


def provider_id():
    """Return the unique QGIS Processing provider ID for AwanaGIS Brazil."""
    return _PROVIDER_ID


def register_brazil_provider():
    """Register the vendored ``awanagis_brazil`` provider if not already active.

    Returns the active provider instance or ``None`` if QGIS Processing
    registry is unavailable.
    """
    global _REGISTERED_PROVIDER
    from qgis.core import QgsApplication
    from .vendor.gisbr.provider import GeobrProvider

    with _LOCK:
        registry = QgsApplication.processingRegistry()
        if registry is None:
            return None
        existing = registry.providerById(_PROVIDER_ID)
        if existing is not None:
            _REGISTERED_PROVIDER = existing
            return existing
        provider = GeobrProvider()
        if registry.addProvider(provider):
            _REGISTERED_PROVIDER = provider
            return provider
        return None


def unregister_brazil_provider():
    """Remove only the ``awanagis_brazil`` provider registered by this plugin."""
    global _REGISTERED_PROVIDER
    from qgis.core import QgsApplication

    with _LOCK:
        registry = QgsApplication.processingRegistry()
        if registry is None:
            _REGISTERED_PROVIDER = None
            return False
        target = _REGISTERED_PROVIDER or registry.providerById(_PROVIDER_ID)
        if target is None:
            _REGISTERED_PROVIDER = None
            return False
        removed = False
        try:
            removed = bool(registry.removeProvider(target))
        except Exception:
            removed = False
        _REGISTERED_PROVIDER = None
        return removed
