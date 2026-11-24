"""Security, privacy, credential redaction, and fingerprinting helpers for SMP exports."""

from __future__ import annotations

import hashlib
import os
import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

VENDOR_COMMIT = "34715788e94718d036a58f9992d7ef69b9ecf3d5"

EXPORT_POLICIES = (
    "allow",
    "warn_online",
    "warn_license",
    "restricted",
    "blocked_sensitive",
)

_SENSITIVITY_BLOCKED = {
    "blocked",
    "blocked_sensitive",
    "confidential",
    "isolated_peoples",
    "isolated",
    "sacred",
    "high",
}

_SENSITIVITY_RESTRICTED = {
    "restricted",
    "sensitive",
    "indigenous_restricted",
    "medium",
}

_ONLINE_PROVIDERS = {
    "wms",
    "wmts",
    "xyz",
    "wcs",
    "wfs",
    "arcgisfeatureserver",
    "arcgismapserver",
    "vectortile",
    "xyzvectortiles",
    "tms",
}

_LICENSE_WARN_DOMAINS_OR_KEYWORDS = (
    "mapbox",
    "googleapis.com",
    "mt0.google",
    "mt1.google",
    "mt2.google",
    "mt3.google",
    "virtualearth.net",
    "bing.com",
    "tile.openstreetmap.org",
    "openstreetmap.org",
    "arcgisonline.com",
    "services.arcgisonline",
    "cartocdn.com",
    "stamen.com",
    "thunderforest.com",
    "here.com",
    "planet.com",
    "maxar.com",
    "digitalglobe.com",
)

_SECRET_QUERY_KEYS = re.compile(
    r"^(?:token|key|api[-_]?key|secret|password|passwd|pwd|auth|authcfg|"
    r"access[-_]?token|bearer|signature|sig|session|jwt|client[-_]?secret)$",
    re.IGNORECASE,
)

_KEY_VALUE_SECRET_RE = re.compile(
    r"(\b(?:password|passwd|pwd|token|secret|api[-_]?key|apikey|access[-_]?token|authcfg)\s*=\s*)"
    r"('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|[^\s&;]+)",
    re.IGNORECASE,
)

_URL_USERINFO_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^/@\s]+@)")
_INNER_URL_RE = re.compile(r"https?://[^\s&'\"]+", re.IGNORECASE)


def _quote_preserve_stars(s, safe, encoding, errors):
    return quote(s, safe=safe + "*", encoding=encoding, errors=errors)


def _redact_url_string(url):
    """Redact userinfo and secret query parameters from a single HTTP/HTTPS/URI string."""
    cleaned = _URL_USERINFO_RE.sub(r"\1***@", url)
    try:
        parts = urlsplit(cleaned)
    except ValueError:
        return cleaned

    netloc = parts.netloc
    if "@" in netloc:
        _, host = netloc.rsplit("@", 1)
        netloc = f"***@{host}"

    if parts.query:
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        redacted_pairs = []
        for k, v in pairs:
            if _SECRET_QUERY_KEYS.match(k):
                redacted_pairs.append((k, "***"))
            elif v.lower().startswith(("http://", "https://")):
                redacted_pairs.append((k, _redact_url_string(v)))
            else:
                redacted_pairs.append((k, v))
        query = urlencode(redacted_pairs, quote_via=_quote_preserve_stars)
    else:
        query = ""

    return urlunsplit((parts.scheme, netloc, parts.path, query, "***" if parts.fragment and _SECRET_QUERY_KEYS.match(parts.fragment.split("=", 1)[0]) else parts.fragment))


def redact_uri(uri):
    """Strip credentials, passwords, and API tokens from a QGIS layer source URI."""
    if not uri:
        return ""
    text = str(uri)

    # First redact any key=value secrets (PostGIS / GDAL / QGIS connection strings).
    def _kv_sub(match):
        prefix = match.group(1)
        val = match.group(2)
        if val.startswith(("'", '"')) and len(val) >= 2 and val[-1] == val[0]:
            return f"{prefix}{val[0]}***{val[0]}"
        return f"{prefix}***"

    text = _KEY_VALUE_SECRET_RE.sub(_kv_sub, text)

    # Redact URL userinfo (scheme://user:pass@host) everywhere.
    text = _URL_USERINFO_RE.sub(r"\1***@", text)

    # If the whole string is a URL, parse and redact query tokens cleanly.
    if text.lower().startswith(("http://", "https://")):
        return _redact_url_string(text)

    # QGIS WMS/XYZ URIs often embed `url=https://...` (sometimes percent-encoded).
    if "url=" in text.lower():
        segments = text.split("&")
        out_segments = []
        for seg in segments:
            if "=" in seg:
                k, v = seg.split("=", 1)
                if _SECRET_QUERY_KEYS.match(k.strip()):
                    out_segments.append(f"{k}=***")
                    continue
                if k.strip().lower() == "url":
                    decoded = unquote(v)
                    redacted = _redact_url_string(decoded)
                    out_segments.append(f"{k}={redacted}")
                    continue
            out_segments.append(seg)
        text = "&".join(out_segments)

    # Redact any remaining embedded http(s) URLs and Bearer tokens.
    text = _INNER_URL_RE.sub(lambda m: _redact_url_string(m.group(0)), text)
    text = re.sub(r"(?i)\bBearer\s+[^\s&'\"]+", "Bearer ***", text)
    return text


def _safe_call(obj, attr, default=None):
    val = getattr(obj, attr, None)
    if callable(val):
        try:
            return val()
        except Exception:
            return default
    return default if val is None else val


def layer_source_uri(layer):
    """Return raw layer source URI (internal use only; never expose unredacted)."""
    return _safe_call(layer, "source", "") or _safe_call(layer, "publicSource", "") or ""


def is_online_layer(layer):
    """Return True if the layer fetches data over a network provider or URL."""
    provider = str(_safe_call(layer, "providerType", "") or "").strip().lower()
    if provider in _ONLINE_PROVIDERS:
        return True
    src = layer_source_uri(layer).lower()
    if "http://" in src or "https://" in src or "/vsicurl/" in src:
        return True
    return False


def layer_attribution(layer):
    """Extract attribution/rights metadata from a QGIS layer if available."""
    meta = _safe_call(layer, "metadata")
    if meta is not None:
        rights = _safe_call(meta, "rights")
        if isinstance(rights, (list, tuple)) and rights:
            joined = "; ".join(str(r).strip() for r in rights if str(r).strip())
            if joined:
                return joined
    attr = _safe_call(layer, "attribution", "")
    if isinstance(attr, str) and attr.strip():
        return attr.strip()
    return ""


def _custom_prop(layer, key):
    fn = getattr(layer, "customProperty", None)
    if callable(fn):
        try:
            val = fn(key)
            if val is not None and str(val).strip() != "":
                return str(val).strip()
        except Exception:
            pass
    return None


def layer_sensitivity(layer):
    """Return normalized sensitivity custom property on ``layer`` if set, else None."""
    for prop_key in ("awanagis/sensitivity", "agenticgis/sensitivity", "gisbr/sensitivity", "sensitivity"):
        sens = _custom_prop(layer, prop_key)
        if sens:
            return sens.lower()
    return None


def classify_layer_policy(layer):
    """Classify a layer into an SMP export_policy value.

    Returns one of: ``allow``, ``warn_online``, ``warn_license``,
    ``restricted``, ``blocked_sensitive``.
    """
    sens = layer_sensitivity(layer)
    if sens and sens in _SENSITIVITY_BLOCKED:
        return "blocked_sensitive"

    for prop_key in ("awanagis/export_policy", "agenticgis/export_policy", "gisbr/export_policy"):
        explicit = _custom_prop(layer, prop_key)
        if explicit:
            norm = explicit.lower()
            if norm in ("deny", "block", "blocked"):
                return "blocked_sensitive"
            if norm in EXPORT_POLICIES:
                return norm

    if sens and sens in _SENSITIVITY_RESTRICTED:
        return "restricted"

    if is_online_layer(layer):
        src_lower = layer_source_uri(layer).lower()
        attr_lower = layer_attribution(layer).lower()
        if any(kw in src_lower or kw in attr_lower for kw in _LICENSE_WARN_DOMAINS_OR_KEYWORDS):
            return "warn_license"
        if attr_lower:
            return "warn_license"
        return "warn_online"

    return "allow"


def visible_layers_in_render_order(project):
    """Return visible layers in exact QGIS render order (top-to-bottom)."""
    root = project.layerTreeRoot()
    visible_nodes = [
        node for node in root.findLayers()
        if node.isVisible() and node.layer() is not None
    ]
    visible_layers = [node.layer() for node in visible_nodes]

    has_custom = getattr(root, "hasCustomLayerOrder", None)
    custom_order = getattr(root, "customLayerOrder", None)
    if callable(has_custom) and has_custom() and callable(custom_order):
        visible_ids = {layer.id() for layer in visible_layers}
        ordered = [
            layer for layer in custom_order()
            if layer is not None and layer.id() in visible_ids
        ]
        seen = {layer.id() for layer in ordered}
        ordered.extend(layer for layer in visible_layers if layer.id() not in seen)
        return ordered
    return visible_layers


def _hash_memory_or_edited_features(layer, max_features=100_000):
    """Compute a deterministic digest of vector features (bounded by max_features).

    Returns ``(digest_str, complete_bool)``.
    """
    try:
        count = int(layer.featureCount())
    except Exception:
        return "count=unknown", False

    try:
        ext = layer.extent()
        ext_str = f"{ext.xMinimum():.8f},{ext.yMinimum():.8f},{ext.xMaximum():.8f},{ext.yMaximum():.8f}"
    except Exception:
        ext_str = "extent=unknown"

    if count > max_features:
        return f"count={count}:ext={ext_str}:unbounded", False

    h = hashlib.sha256()
    h.update(f"count={count}:ext={ext_str}\n".encode("utf-8"))
    try:
        for feat in layer.getFeatures():
            geom = feat.geometry()
            wkb = bytes(geom.asWkb()) if geom is not None and not geom.isNull() else b""
            h.update(f"id={feat.id()}:attrs={repr(feat.attributes())}:".encode("utf-8", "ignore"))
            h.update(hashlib.sha256(wkb).digest())
            h.update(b"\n")
        return h.hexdigest(), True
    except Exception:
        return f"count={count}:ext={ext_str}:err", False


def compute_project_fingerprint(project, layers):
    """Compute a strict fingerprint of project CRS + ordered layer styles/content.

    Returns ``(fingerprint_hex, cache_safe_bool)``.
    ``cache_safe`` is False when layers are online, have unsaved edit buffers, or
    are too large in memory to hash completely (preventing stale cache reuse).
    """
    digest = hashlib.sha256()
    cache_safe = True

    crs = _safe_call(project, "crs")
    authid = _safe_call(crs, "authid", "") if crs is not None else ""
    digest.update(f"project_crs={authid}\n".encode("utf-8", "ignore"))

    for idx, layer in enumerate(layers):
        lid = _safe_call(layer, "id", "")
        lname = _safe_call(layer, "name", "")
        provider = str(_safe_call(layer, "providerType", "") or "")
        src = layer_source_uri(layer)
        policy = classify_layer_policy(layer)
        sensitivity = layer_sensitivity(layer) or ""
        opacity = _safe_call(layer, "opacity")
        blend = _safe_call(layer, "blendMode")
        subset = _safe_call(layer, "subsetString", "")
        is_mod = bool(_safe_call(layer, "isModified", False))
        labels_enabled = bool(_safe_call(layer, "labelsEnabled", False))

        mtime = None
        if src:
            local_path = src.split("|", 1)[0]
            if os.path.exists(local_path):
                try:
                    mtime = os.path.getmtime(local_path)
                except OSError:
                    mtime = None

        renderer_sig = ""
        renderer = _safe_call(layer, "renderer")
        if renderer is not None:
            dump = _safe_call(renderer, "dump")
            rtype = _safe_call(renderer, "type")
            renderer_sig = f"{rtype}:{dump or ''}"

        label_sig = ""
        if labels_enabled:
            labeling = _safe_call(layer, "labeling")
            if labeling is not None:
                ltype = _safe_call(labeling, "type", "")
                settings = _safe_call(labeling, "settings")
                field_name = getattr(settings, "fieldName", "") if settings is not None else ""
                is_expr = getattr(settings, "isExpression", False) if settings is not None else False
                label_sig = f"{ltype}:{field_name}:{is_expr}"

        style_mgr = _safe_call(layer, "styleManager")
        current_style = _safe_call(style_mgr, "currentStyle", "") if style_mgr is not None else ""

        feature_sig = ""
        if provider.lower() == "memory" or is_mod:
            feature_sig, complete = _hash_memory_or_edited_features(layer)
            if not complete or is_mod:
                cache_safe = False

        if is_online_layer(layer):
            cache_safe = False

        record = (
            f"{idx}|id={lid}|name={lname}|prov={provider}|src={src}|mtime={mtime}|"
            f"policy={policy}|sens={sensitivity}|opacity={opacity}|blend={blend}|subset={subset}|"
            f"mod={is_mod}|labels={labels_enabled}:{label_sig}|"
            f"style={current_style}|renderer={renderer_sig}|feat={feature_sig}\n"
        )
        digest.update(record.encode("utf-8", "ignore"))

    return digest.hexdigest(), cache_safe


def renderer_source_sha256():
    """Return SHA-256 of the vendored ``comapeo_smp_generator.py`` module."""
    gen_path = os.path.join(os.path.dirname(__file__), "vendor", "comapeo_smp_generator.py")
    h = hashlib.sha256()
    with open(gen_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
