"""Canonical design tokens for the AwanaGIS UI, backed by ``gui.brand``.

Resolves Awana Digital's light theme (Cream / Dark Burgundy / Burgundy) or
derives dark surfaces dynamically from the active QGIS/Qt ``QPalette``.
``DOCK_*`` and ``DIALOG_*`` module-level exports are preserved so existing
widget imports continue working cleanly.
"""

from . import brand as _brand

# ── Active semantic token snapshot ───────────────────────────────────────────
# Tokens are resolved once at import time, so a QGIS theme switch only takes
# effect after restarting QGIS (or reloading the plugin).
_TOKENS = _brand.resolve_semantic_tokens()

DOCK_CANVAS = _TOKENS["canvas"]
DOCK_SURFACE = _TOKENS["surface"]
DOCK_SURFACE_2 = _TOKENS["surface_2"]
DOCK_BORDER = _TOKENS["border"]
DOCK_BORDER_SOFT = _TOKENS["border_soft"]
DOCK_TEXT = _TOKENS["text"]
DOCK_TEXT_2 = _TOKENS["text_2"]
DOCK_TEXT_3 = _TOKENS["text_3"]
DOCK_TEXT_4 = _TOKENS["text_4"]
DOCK_ACCENT = _TOKENS["accent"]
DOCK_ACCENT_DIM = _TOKENS["accent_dim"]
DOCK_ACCENT_HOV = _TOKENS["accent_hov"]
DOCK_ACCENT_TEXT = _TOKENS["accent_text"]
DOCK_BLUE = _TOKENS["blue"]
DOCK_PURPLE = _TOKENS["text_3"]
DOCK_WARN = _TOKENS["warn"]
DOCK_SUCCESS = _TOKENS["success"]
DOCK_DANGER = _TOKENS["danger"]
DOCK_DANGER_BG = _TOKENS["danger_bg"]
DOCK_DANGER_BORDER = _TOKENS["danger_border"]
DOCK_DANGER_TEXT = _TOKENS["danger_text"]
DOCK_CODE_GREEN = _TOKENS["code_green"]
DOCK_HIGHLIGHT = _TOKENS["highlight"]
DOCK_HIGHLIGHT_FG = _TOKENS["highlight_fg"]
DOCK_CHART_START = _TOKENS["chart_start"]
DOCK_CHART_END = _TOKENS["chart_end"]

DIALOG_SURFACE = DOCK_CANVAS
DIALOG_SURFACE_2 = DOCK_SURFACE
DIALOG_SURFACE_HOV = DOCK_SURFACE_2
DIALOG_INPUT_BG = _TOKENS["input_bg"]
DIALOG_BORDER = DOCK_BORDER
DIALOG_BORDER_SOFT = DOCK_BORDER_SOFT
DIALOG_TEXT = DOCK_TEXT
DIALOG_TEXT_2 = DOCK_TEXT_2
DIALOG_TEXT_3 = DOCK_TEXT_3
DIALOG_ACCENT = DOCK_ACCENT
DIALOG_ACCENT_HOV = DOCK_ACCENT_HOV
DIALOG_ACCENT_TEXT = DOCK_ACCENT_TEXT
DIALOG_BLUE = DOCK_BLUE
DIALOG_WARN = DOCK_WARN
DIALOG_SUCCESS = DOCK_SUCCESS
DIALOG_DANGER = DOCK_DANGER


def active_tokens(palette=None):
    """Return fresh semantic tokens for the active QGIS/Qt palette."""
    return _brand.resolve_semantic_tokens(palette=palette)


def curved_scrollbar_qss(
    tokens=None,
    *,
    thickness=10,
    handle_radius=4,
    include_horizontal=False,
    selector_prefix="",
):
    """Widget-scoped curved-corner floating pill scrollbar QSS."""
    return _brand.curved_scrollbar_qss(
        tokens or _TOKENS,
        thickness=thickness,
        handle_radius=handle_radius,
        include_horizontal=include_horizontal,
        selector_prefix=selector_prefix,
    )


# ── Font stacks ──────────────────────────────────────────────────────────────
# Prose uses Public Sans (body), titles Tomorrow (display), captions Space
# Grotesk (caption), falling back gracefully to QGIS's native UI font. Code
# stays monospace.
MONO_STACK = "'JetBrains Mono','SF Mono','Menlo','Consolas','DejaVu Sans Mono','Courier New',monospace"


def display_font(size=15, weight=None):
    """QFont for headings/titles using Tomorrow with QGIS UI fallback."""
    return _brand.make_role_font("display", fs(size), weight=weight)


def body_font(size=12, weight=None):
    """QFont for body/chat prose using Public Sans with QGIS UI fallback."""
    return _brand.make_role_font("body", fs(size), weight=weight)


def caption_font(size=11, weight=None):
    """QFont for compact labels/captions using Space Grotesk with QGIS UI fallback."""
    return _brand.make_role_font("caption", fs(size), weight=weight)


def ui_font(size=12, weight=None):
    """QFont for interface text: body role (Public Sans / QGIS UI fallback) at ``size`` px."""
    return body_font(size, weight=weight)


def mono_font(size=12):
    """QFont for code/paths: the platform's fixed-width font at ``size`` px."""
    from qgis.PyQt.QtGui import QFontDatabase
    from ..core.qt_compat import FIXED_FONT
    font = QFontDatabase.systemFont(FIXED_FONT)
    font.setPixelSize(fs(size))
    return font


def sans_family(role="body"):
    """CSS family for prose: brand role family with QGIS UI sans-serif fallback."""
    return _brand.font_stack_css(role)


# ── Font scale ───────────────────────────────────────────────────────────────
FONT_SCALE_MIN = 0.75
FONT_SCALE_MAX = 2.0
_user_scale = None
_qgis_ratio = None


def clamp_font_scale(value):
    try:
        return min(FONT_SCALE_MAX, max(FONT_SCALE_MIN, float(value)))
    except (TypeError, ValueError):
        return 1.0


def set_font_scale(value):
    """Override the cached plugin scale (Settings dialog calls this on save)."""
    global _user_scale
    _user_scale = clamp_font_scale(value)


def qgis_font_ratio():
    """QGIS's font size (Options → General) relative to the OS default size."""
    try:
        from qgis.PyQt.QtGui import QFontDatabase
        from qgis.utils import iface
        from ..core.qt_compat import GENERAL_FONT
        system_pt = QFontDatabase.systemFont(GENERAL_FONT).pointSizeF()
        qgis_pt = float(iface.defaultStyleSheetOptions().get("fontPointSize") or system_pt)
        return min(3.0, max(0.5, qgis_pt / system_pt))
    except Exception:
        return 1.0


def fs(size):
    """Scale a base font size by QGIS's font size and the plugin ``font_scale``.

    Read lazily on first use so importing this module never touches QGIS state.
    """
    global _qgis_ratio
    if _qgis_ratio is None:
        _qgis_ratio = qgis_font_ratio()
    if _user_scale is None:
        try:
            from ..config import Config
            set_font_scale(Config().get("font_scale"))
        except Exception:
            set_font_scale(1.0)
    return max(1, round(size * _qgis_ratio * _user_scale))
