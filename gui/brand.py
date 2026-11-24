"""Awana Digital brand tokens, typography roles, WCAG contrast checks, and scrollbar styling.

Official palette HEX values and typography role assignments are derived from
``docs/branding/brand-tokens.json`` and ``docs/branding/brand-guide.md``.
Light-mode semantic roles use Awana Cream and Dark Burgundy/Burgundy; dark-mode
surfaces derive dynamically from the active QGIS/Qt ``QPalette``.

All styling helpers are scoped to plugin-owned widgets and never alter global
QGIS application styles or user map symbology.
"""

from types import MappingProxyType

# ── Official immutable Awana Digital brand constants ─────────────────────────

OFFICIAL_PRIMARY = MappingProxyType({
    "dark_burgundy": "#6B0030",
    "burgundy": "#8D003E",
    "earth": "#932D00",
})

OFFICIAL_SECONDARY = MappingProxyType({
    "pink": "#FF60C0",
    "orange": "#FF8D00",
    "pollen": "#FFE460",
    "fungi": "#00D05F",
    "forest": "#148658",
    "cream": "#FDF7EF",
    "river": "#0063A1",
    "sky": "#0094FF",
    "rain": "#B4DDF9",
})

OFFICIAL_PALETTE = MappingProxyType({
    **OFFICIAL_PRIMARY,
    **OFFICIAL_SECONDARY,
})

FONT_ROLES = MappingProxyType({
    "display": "Tomorrow",
    "body": "Public Sans",
    "caption": "Space Grotesk",
})

LIGHT_PROPOSAL = MappingProxyType({
    "primary_surface": OFFICIAL_SECONDARY["cream"],         # #FDF7EF
    "primary_text": OFFICIAL_PRIMARY["dark_burgundy"],      # #6B0030
    "primary_action": OFFICIAL_PRIMARY["burgundy"],         # #8D003E
    "accent_warm": OFFICIAL_PRIMARY["earth"],               # #932D00
    "accent_link": OFFICIAL_SECONDARY["river"],             # #0063A1
    "highlight_on_burgundy": OFFICIAL_SECONDARY["pollen"],  # #FFE460
})

WCAG_AA_NORMAL_MIN = 4.5
WCAG_AA_UI_MIN = 3.0


# ── WCAG 2.x color & contrast utilities ──────────────────────────────────────

def _parse_hex(hex_color):
    cleaned = str(hex_color or "").strip().lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join(ch * 2 for ch in cleaned)
    if len(cleaned) != 6:
        raise ValueError(f"Expected 6-digit hex color, got {hex_color!r}")
    return (
        int(cleaned[0:2], 16),
        int(cleaned[2:4], 16),
        int(cleaned[4:6], 16),
    )


def _format_hex(r, g, b):
    return f"#{max(0, min(255, round(r))):02X}{max(0, min(255, round(g))):02X}{max(0, min(255, round(b))):02X}"


def _blend_hex(hex_a, hex_b, weight_b):
    """Linearly interpolate from *hex_a* (weight 0) to *hex_b* (weight 1)."""
    ra, ga, ba = _parse_hex(hex_a)
    rb, gb, bb = _parse_hex(hex_b)
    t = max(0.0, min(1.0, float(weight_b)))
    return _format_hex(
        ra + (rb - ra) * t,
        ga + (gb - ga) * t,
        ba + (bb - ba) * t,
    )


def relative_luminance(hex_color):
    """Return WCAG 2.x relative luminance in [0.0, 1.0]."""
    channels = []
    for value in _parse_hex(hex_color):
        srgb = value / 255.0
        if srgb <= 0.03928:
            channels.append(srgb / 12.92)
        else:
            channels.append(((srgb + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(fg_hex, bg_hex):
    """Return WCAG 2.x contrast ratio between *fg_hex* and *bg_hex* (>= 1.0)."""
    l1 = relative_luminance(fg_hex)
    l2 = relative_luminance(bg_hex)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def meets_aa_normal(fg_hex, bg_hex, minimum=WCAG_AA_NORMAL_MIN):
    """Return True when normal text contrast meets WCAG AA (>= 4.5:1)."""
    return contrast_ratio(fg_hex, bg_hex) >= minimum


def meets_aa_ui(fg_hex, bg_hex, minimum=WCAG_AA_UI_MIN):
    """Return True when large text / key UI graphics contrast meets >= 3.0:1."""
    return contrast_ratio(fg_hex, bg_hex) >= minimum


def _ensure_contrast(fg_hex, bg_hex, target_hex, min_ratio):
    """Nudge *fg_hex* toward *target_hex* until contrast against *bg_hex* meets *min_ratio*."""
    if contrast_ratio(fg_hex, bg_hex) >= min_ratio:
        return fg_hex
    for step in range(1, 21):
        candidate = _blend_hex(fg_hex, target_hex, step / 20.0)
        if contrast_ratio(candidate, bg_hex) >= min_ratio:
            return candidate
    return target_hex


# ── Palette detection & semantic token derivation ────────────────────────────

def _active_qpalette(palette=None):
    if palette is not None:
        return palette
    try:
        from qgis.PyQt.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            return app.palette()
    except Exception:  # nosec B110
        pass
    return None


def is_dark_palette(palette=None):
    """Return True when the active QGIS/Qt palette uses a dark window background."""
    pal = _active_qpalette(palette)
    if pal is None:
        return False
    try:
        from qgis.PyQt.QtGui import QPalette
        window_color = pal.color(QPalette.ColorRole.Window)
        base_color = pal.color(QPalette.ColorRole.Base)
        return (window_color.lightness() + base_color.lightness()) / 2.0 < 128
    except Exception:
        return False


def _palette_hex(pal, role_name, fallback):
    try:
        from qgis.PyQt.QtGui import QPalette
        role = getattr(QPalette.ColorRole, role_name)
        color = pal.color(role)
        if color.isValid():
            return color.name().upper()
    except Exception:  # nosec B110
        pass
    return fallback


def _light_semantic_tokens():
    """Return Awana Digital Cream + Burgundy light-mode semantic tokens."""
    canvas = OFFICIAL_SECONDARY["cream"]          # #FDF7EF
    surface = "#F7EFE3"
    surface_2 = "#EFE3D1"
    input_bg = "#FCF6ED"
    border = "#927368"                            # 3.16:1 on surface_2 (#EFE3D1), 3.92:1 on Cream (>= 3.0 UI)
    border_soft = "#DECDBD"
    text = OFFICIAL_PRIMARY["dark_burgundy"]      # #6B0030 (11.83:1 on Cream)
    text_2 = "#5A2A3B"                            # 10.79:1 on Cream
    text_3 = "#6D4553"                            # 7.51:1 on Cream
    text_4 = "#734D5B"                            # 6.71:1 on Cream
    accent = OFFICIAL_PRIMARY["burgundy"]         # #8D003E (8.96:1 on Cream)
    accent_hov = OFFICIAL_PRIMARY["dark_burgundy"]
    accent_dim = "#A52258"
    accent_text = OFFICIAL_SECONDARY["cream"]     # #FDF7EF on #8D003E = 8.96:1
    blue = OFFICIAL_SECONDARY["river"]            # #0063A1 (5.98:1 on Cream)
    warn = OFFICIAL_PRIMARY["earth"]              # #932D00 (7.54:1 on Cream)
    # AD Forest (#148658) is 4.31:1 on Cream (passes UI 3:1, below 4.5:1 normal text);
    # use deepened forest #0E6B45 (6.15:1) for readable status text while keeping
    # AD Forest for non-text graphics.
    success = "#0E6B45"
    success_ui = OFFICIAL_SECONDARY["forest"]     # #148658
    danger = OFFICIAL_PRIMARY["burgundy"]         # #8D003E (8.96:1 on Cream)
    return {
        "is_dark": False,
        "canvas": canvas,
        "surface": surface,
        "surface_2": surface_2,
        "input_bg": input_bg,
        "border": border,
        "border_soft": border_soft,
        "text": text,
        "text_2": text_2,
        "text_3": text_3,
        "text_4": text_4,
        "accent": accent,
        "accent_dim": accent_dim,
        "accent_hov": accent_hov,
        "accent_text": accent_text,
        "blue": blue,
        "link": blue,
        "highlight": OFFICIAL_SECONDARY["pollen"],
        "highlight_fg": OFFICIAL_PRIMARY["dark_burgundy"],
        "warn": warn,
        "success": success,
        "success_ui": success_ui,
        "danger": danger,
        "danger_bg": "#FAE6EB",
        "danger_border": "#B05D72",
        "danger_text": OFFICIAL_PRIMARY["dark_burgundy"],
        "code_green": OFFICIAL_PRIMARY["dark_burgundy"],
        "scrollbar_handle": border,
        "scrollbar_handle_hover": OFFICIAL_PRIMARY["dark_burgundy"],
        "chart_start": OFFICIAL_SECONDARY["river"],
        "chart_end": OFFICIAL_PRIMARY["earth"],
    }


def _dark_semantic_tokens(palette):
    """Derive dark-mode tokens dynamically from the active QGIS/Qt ``QPalette``."""
    pal = _active_qpalette(palette)
    if pal is not None and is_dark_palette(pal):
        win_hex = _palette_hex(pal, "Window", "#202020")
        base_hex = _palette_hex(pal, "Base", win_hex)
        alt_hex = _palette_hex(pal, "AlternateBase", win_hex)
        raw_fg = _palette_hex(pal, "WindowText", OFFICIAL_SECONDARY["cream"])
    else:
        win_hex = "#1E1E1E"
        base_hex = "#242424"
        alt_hex = "#2D2D2D"
        raw_fg = OFFICIAL_SECONDARY["cream"]

    canvas = win_hex
    # Keep distinct stepped surfaces relative to the host QPalette window color.
    surface = base_hex if contrast_ratio(base_hex, canvas) >= 1.04 else _blend_hex(canvas, "#FFFFFF", 0.05)
    surface_2 = alt_hex if contrast_ratio(alt_hex, surface) >= 1.05 else _blend_hex(surface, "#FFFFFF", 0.07)
    input_bg = _blend_hex(canvas, "#000000", 0.12) if relative_luminance(base_hex) >= relative_luminance(canvas) else base_hex

    target_light = OFFICIAL_SECONDARY["cream"]
    text = _ensure_contrast(raw_fg, surface_2, target_light, 7.0)
    text_2 = _ensure_contrast(_blend_hex(text, canvas, 0.25), surface_2, target_light, 4.6)
    text_3 = _ensure_contrast(_blend_hex(text, canvas, 0.38), surface_2, target_light, 4.55)
    text_4 = _ensure_contrast(_blend_hex(text, canvas, 0.45), surface_2, target_light, 4.55)

    border = _ensure_contrast(_blend_hex(canvas, text, 0.35), surface_2, target_light, 3.05)
    border_soft = _blend_hex(surface, border, 0.45)

    accent = OFFICIAL_SECONDARY["pollen"]          # #FFE460 (high contrast on dark)
    accent_hov = OFFICIAL_SECONDARY["cream"]       # #FDF7EF
    accent_dim = "#D9C04E"
    accent_text = OFFICIAL_PRIMARY["dark_burgundy"]  # #6B0030 on #FFE460 = 9.90:1

    blue = (
        OFFICIAL_SECONDARY["sky"]
        if meets_aa_normal(OFFICIAL_SECONDARY["sky"], surface_2)
        else OFFICIAL_SECONDARY["rain"]
    )
    warn = (
        OFFICIAL_SECONDARY["orange"]
        if meets_aa_normal(OFFICIAL_SECONDARY["orange"], surface_2)
        else OFFICIAL_SECONDARY["pollen"]
    )
    success = (
        OFFICIAL_SECONDARY["fungi"]
        if meets_aa_normal(OFFICIAL_SECONDARY["fungi"], surface_2)
        else OFFICIAL_SECONDARY["rain"]
    )
    danger = (
        OFFICIAL_SECONDARY["pink"]
        if meets_aa_normal(OFFICIAL_SECONDARY["pink"], surface_2)
        else OFFICIAL_SECONDARY["cream"]
    )

    return {
        "is_dark": True,
        "canvas": canvas,
        "surface": surface,
        "surface_2": surface_2,
        "input_bg": input_bg,
        "border": border,
        "border_soft": border_soft,
        "text": text,
        "text_2": text_2,
        "text_3": text_3,
        "text_4": text_4,
        "accent": accent,
        "accent_dim": accent_dim,
        "accent_hov": accent_hov,
        "accent_text": accent_text,
        "blue": blue,
        "link": blue,
        "highlight": OFFICIAL_SECONDARY["pollen"],
        "highlight_fg": OFFICIAL_PRIMARY["dark_burgundy"],
        "warn": warn,
        "success": success,
        "success_ui": success,
        "danger": danger,
        "danger_bg": _blend_hex(canvas, OFFICIAL_PRIMARY["dark_burgundy"], 0.45),
        "danger_border": OFFICIAL_PRIMARY["burgundy"],
        "danger_text": OFFICIAL_SECONDARY["cream"],
        "code_green": text,
        "scrollbar_handle": border,
        "scrollbar_handle_hover": text_2,
        "chart_start": OFFICIAL_SECONDARY["fungi"],
        "chart_end": OFFICIAL_SECONDARY["orange"],
    }


def resolve_semantic_tokens(palette=None, *, dark=None):
    """Return semantic UI tokens for the active light or dark QGIS theme."""
    if dark is None:
        dark = is_dark_palette(palette)
    if dark:
        return _dark_semantic_tokens(palette)
    return _light_semantic_tokens()


# ── Font roles & graceful OS/QGIS fallback ───────────────────────────────────

def _system_ui_family():
    try:
        from qgis.PyQt.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            family = app.font().family()
            if family:
                return family
    except Exception:  # nosec B110
        pass
    try:
        from qgis.PyQt.QtGui import QFontDatabase
        from ..core.qt_compat import GENERAL_FONT
        family = QFontDatabase.systemFont(GENERAL_FONT).family()
        if family:
            return family
    except Exception:  # nosec B110
        pass
    return "sans-serif"


def _installed_font_families():
    try:
        from qgis.PyQt.QtGui import QFontDatabase
        # Qt 5 uses QFontDatabase().families(); Qt 6 supports static QFontDatabase.families()
        db = QFontDatabase()
        if hasattr(db, "families"):
            return set(db.families())
        return set(QFontDatabase.families())
    except Exception:  # nosec B110
        return set()


def resolve_font_family(role="body", available_families=None):
    """Return the official brand typeface for *role* if installed, else QGIS UI sans."""
    brand_family = FONT_ROLES.get(role, FONT_ROLES["body"])
    families = (
        set(available_families)
        if available_families is not None
        else _installed_font_families()
    )
    if brand_family in families:
        return brand_family
    return _system_ui_family()


def font_stack_css(role="body", available_families=None):
    """Return a CSS ``font-family`` stack prioritizing the brand role with native fallback."""
    brand_family = FONT_ROLES.get(role, FONT_ROLES["body"])
    fallback = _system_ui_family()
    if available_families is not None:
        resolved = resolve_font_family(role, available_families=available_families)
        if resolved == brand_family and brand_family != fallback:
            return f"'{brand_family}','{fallback}',sans-serif"
        return f"'{resolved}',sans-serif" if resolved != "sans-serif" else "sans-serif"
    if fallback and fallback != "sans-serif" and fallback != brand_family:
        return f"'{brand_family}','{fallback}',sans-serif"
    return f"'{brand_family}',sans-serif"


def make_role_font(role, pixel_size, weight=None, available_families=None):
    """Build a ``QFont`` for *role* (``display``, ``body``, or ``caption``)."""
    from qgis.PyQt.QtGui import QFont
    family = resolve_font_family(role, available_families=available_families)
    font = QFont()
    if family and family != "sans-serif":
        font.setFamily(family)
    font.setPixelSize(max(1, int(pixel_size)))
    if weight is not None:
        font.setWeight(weight)
    return font


# ── Floating pill / curved-corner scrollbars ─────────────────────────────────

def curved_scrollbar_qss(
    tokens=None,
    *,
    thickness=10,
    handle_radius=4,
    include_horizontal=False,
    selector_prefix="",
):
    """Return widget-scoped QSS for curved-corner floating pill scrollbars."""
    tok = tokens or resolve_semantic_tokens()
    handle = tok["scrollbar_handle"]
    hover = tok["scrollbar_handle_hover"]
    prefix = f"{selector_prefix} " if selector_prefix else ""
    qss = (
        f"{prefix}QScrollBar:vertical {{"
        f"  background: transparent; width: {thickness}px; margin: 4px 2px 4px 2px; border: none;"
        f"}}"
        f"{prefix}QScrollBar::handle:vertical {{"
        f"  background: {handle}; border-radius: {handle_radius}px; min-height: 28px; margin: 1px;"
        f"}}"
        f"{prefix}QScrollBar::handle:vertical:hover {{ background: {hover}; }}"
        f"{prefix}QScrollBar::add-line:vertical, {prefix}QScrollBar::sub-line:vertical {{"
        f"  width: 0px; height: 0px; background: none; border: none;"
        f"}}"
        f"{prefix}QScrollBar::add-page:vertical, {prefix}QScrollBar::sub-page:vertical {{"
        f"  background: transparent;"
        f"}}"
        f"{prefix}QScrollBar::corner {{ background: transparent; }}"
    )
    if include_horizontal:
        qss += (
            f"{prefix}QScrollBar:horizontal {{"
            f"  background: transparent; height: {thickness}px; margin: 2px 4px 2px 4px; border: none;"
            f"}}"
            f"{prefix}QScrollBar::handle:horizontal {{"
            f"  background: {handle}; border-radius: {handle_radius}px; min-width: 28px; margin: 1px;"
            f"}}"
            f"{prefix}QScrollBar::handle:horizontal:hover {{ background: {hover}; }}"
            f"{prefix}QScrollBar::add-line:horizontal, {prefix}QScrollBar::sub-line:horizontal {{"
            f"  width: 0px; height: 0px; background: none; border: none;"
            f"}}"
            f"{prefix}QScrollBar::add-page:horizontal, {prefix}QScrollBar::sub-page:horizontal {{"
            f"  background: transparent;"
            f"}}"
        )
    return qss
