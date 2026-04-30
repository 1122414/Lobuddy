"""Unified theme system for Lobuddy - design tokens, presets, and QSS generation.

All UI components should use this module instead of hardcoding colors.
Theme changes propagate instantly through signals.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar

from PySide6.QtCore import QObject, Signal

from core.storage.theme_repo import ThemeRepository

logger = logging.getLogger(__name__)


# ============================================================================
# Theme Token Dataclass
# ============================================================================

@dataclass
class ThemeColors:
    """All design tokens for a theme. Each theme preset provides one instance."""

    # Base
    background: str                # Main window background
    surface: str                   # Card/section surface
    surface_soft: str              # Subtle surface variation

    # Primary accent
    primary: str                   # Main brand color: buttons, header bg, highlights
    primary_soft: str              # Light tint of primary for hover/highlight
    primary_text: str              # Text on primary backgrounds (usually white)
    primary_hover: str             # 主色悬浮态 (lighter than primary)
    primary_active: str            # 主色按下态 (darker than primary)
    secondary: str                 # 辅助色
    accent: str                    # 强调色
    card: str                      # 卡片背景色
    divider: str                   # 分割线色
    info: str                      # 信息色
    on_primary: str                # 主色上的文字色 (usually white or dark)
    on_accent: str                 # 强调色上的文字色

    # Text hierarchy
    text: str                      # Primary text
    text_secondary: str            # Secondary / muted text
    text_muted: str                # Tertiary / disabled text

    # Borders & dividers
    border: str                    # Standard border
    border_focus: str              # Focus ring color

    # Semantic
    success: str                   # Positive / done
    warning: str                   # Caution
    danger: str                    # Error / delete

    # Shadows (RGBA)
    shadow_light: str              # Subtle shadow for cards/panels
    shadow_medium: str             # Stronger shadow for floating elements

    # Pet-specific
    pet_status_ok: str             # Pet "OK/idle" status color
    pet_status_busy: str           # Pet "busy/running" status color
    pet_mood_bg: str               # Mood bubble background
    pet_mood_text: str             # Mood bubble text

    # Companion panel specific
    header_bg: str                 # Panel header background
    header_text: str               # Panel header text
    msg_user_bg: str               # User message bubble background
    msg_user_text: str             # User message bubble text
    msg_bot_bg: str                # Bot message bubble background
    msg_bot_text: str              # Bot message bubble text
    msg_bot_border: str            # Bot message bubble border
    chat_bg: str                   # Chat area background
    input_bg: str                  # Input area background
    input_border: str              # Input border
    input_focus_border: str        # Input focus border

    # Quick action menu
    quick_btn_bg: str              # Quick action button background
    quick_btn_border: str          # Quick action button border
    quick_btn_hover_bg: str        # Quick action button hover
    quick_btn_close_bg: str        # Close button background
    quick_btn_close_text: str      # Close button text

    # Settings
    settings_group_bg: str         # Settings section background
    settings_preview_bg: str       # Preview area background
    settings_preview_border: str   # Preview area border

    # Radii
    radius_sm: int = 10            # Small: buttons, inputs
    radius_md: int = 14            # Medium: cards
    radius_lg: int = 20            # Large: panels
    radius_xl: int = 24            # Extra large: floating windows


# ============================================================================
# Theme Presets
# ============================================================================

class ThemePreset(str, Enum):
    """Available built-in theme presets."""
    COZY_ORANGE = "cozy_orange"
    SAKURA_PINK = "sakura_pink"
    MINT_GREEN = "mint_green"
    NIGHT_COMPANION = "night_companion"
    CUSTOM = "custom"


# -- Preset Definitions -------------------------------------------------------

PRESET_THEMES: dict[ThemePreset, ThemeColors] = {
    ThemePreset.COZY_ORANGE: ThemeColors(
        background="#FFF8EF",
        surface="#FFFFFF",
        surface_soft="#FFF1DF",
        primary="#FF8A3D",
        primary_soft="#FFD8B8",
        primary_text="#FFFFFF",
        primary_hover="#FF9E54",
        primary_active="#E67A2D",
        secondary="#5B8DEF",
        accent="#FF6B9D",
        card="#FFFFFF",
        divider="#F1D9C0",
        info="#5B8DEF",
        on_primary="#FFFFFF",
        on_accent="#FFFFFF",
        text="#4A2E1F",
        text_secondary="#6B4E3D",
        text_muted="#A0846C",
        border="#F1D9C0",
        border_focus="#FF8A3D",
        success="#8BCF7A",
        warning="#F5B84B",
        danger="#FF7B7B",
        shadow_light="rgba(124, 76, 32, 0.10)",
        shadow_medium="rgba(124, 76, 32, 0.18)",
        pet_status_ok="#8BCF7A",
        pet_status_busy="#FF8A3D",
        pet_mood_bg="#FFF1DF",
        pet_mood_text="#4A2E1F",
        header_bg="#FF8A3D",
        header_text="#FFFFFF",
        msg_user_bg="#FF8A3D",
        msg_user_text="#FFFFFF",
        msg_bot_bg="#FFFFFF",
        msg_bot_text="#4A2E1F",
        msg_bot_border="#F1D9C0",
        chat_bg="#FFF7ED",
        input_bg="#FFF7ED",
        input_border="#F1D9C0",
        input_focus_border="#FF8A3D",
        quick_btn_bg="#FFFFFF",
        quick_btn_border="#F1D9C0",
        quick_btn_hover_bg="#FFF1DF",
        quick_btn_close_bg="#FEE2E2",
        quick_btn_close_text="#EF4444",
        settings_group_bg="#FFF7ED",
        settings_preview_bg="#FFF7ED",
        settings_preview_border="#F1D9C0",
    ),
    ThemePreset.SAKURA_PINK: ThemeColors(
        background="#FFF5F7",
        surface="#FFFFFF",
        surface_soft="#FFE8EC",
        primary="#F48FB1",
        primary_soft="#FCE4EC",
        primary_text="#FFFFFF",
        primary_hover="#F8A5C2",
        primary_active="#D9789E",
        secondary="#7E57C2",
        accent="#FFD54F",
        card="#FFFFFF",
        divider="#F0CFD7",
        info="#42A5F5",
        on_primary="#FFFFFF",
        on_accent="#1A1A2E",
        text="#4A2633",
        text_secondary="#6E3B4A",
        text_muted="#A07A85",
        border="#F0CFD7",
        border_focus="#F48FB1",
        success="#A5D6A7",
        warning="#FFCC80",
        danger="#EF9A9A",
        shadow_light="rgba(166, 80, 100, 0.10)",
        shadow_medium="rgba(166, 80, 100, 0.16)",
        pet_status_ok="#A5D6A7",
        pet_status_busy="#F48FB1",
        pet_mood_bg="#FFE8EC",
        pet_mood_text="#4A2633",
        header_bg="#F48FB1",
        header_text="#FFFFFF",
        msg_user_bg="#F48FB1",
        msg_user_text="#FFFFFF",
        msg_bot_bg="#FFFFFF",
        msg_bot_text="#4A2633",
        msg_bot_border="#F0CFD7",
        chat_bg="#FFF5F7",
        input_bg="#FFF5F7",
        input_border="#F0CFD7",
        input_focus_border="#F48FB1",
        quick_btn_bg="#FFFFFF",
        quick_btn_border="#F0CFD7",
        quick_btn_hover_bg="#FFE8EC",
        quick_btn_close_bg="#FFCDD2",
        quick_btn_close_text="#D32F2F",
        settings_group_bg="#FFF5F7",
        settings_preview_bg="#FFF5F7",
        settings_preview_border="#F0CFD7",
    ),
    ThemePreset.MINT_GREEN: ThemeColors(
        background="#F5FAF7",
        surface="#FFFFFF",
        surface_soft="#E6F4EC",
        primary="#66BB6A",
        primary_soft="#C8E6C9",
        primary_text="#FFFFFF",
        primary_hover="#81C784",
        primary_active="#4CAF50",
        secondary="#5C6BC0",
        accent="#FF7043",
        card="#FFFFFF",
        divider="#D4E8D8",
        info="#42A5F5",
        on_primary="#FFFFFF",
        on_accent="#FFFFFF",
        text="#2E3D30",
        text_secondary="#4A5E4D",
        text_muted="#7D8F80",
        border="#D4E8D8",
        border_focus="#66BB6A",
        success="#81C784",
        warning="#FFB74D",
        danger="#E57373",
        shadow_light="rgba(50, 100, 55, 0.10)",
        shadow_medium="rgba(50, 100, 55, 0.16)",
        pet_status_ok="#81C784",
        pet_status_busy="#66BB6A",
        pet_mood_bg="#E6F4EC",
        pet_mood_text="#2E3D30",
        header_bg="#66BB6A",
        header_text="#FFFFFF",
        msg_user_bg="#66BB6A",
        msg_user_text="#FFFFFF",
        msg_bot_bg="#FFFFFF",
        msg_bot_text="#2E3D30",
        msg_bot_border="#D4E8D8",
        chat_bg="#F5FAF7",
        input_bg="#F5FAF7",
        input_border="#D4E8D8",
        input_focus_border="#66BB6A",
        quick_btn_bg="#FFFFFF",
        quick_btn_border="#D4E8D8",
        quick_btn_hover_bg="#E6F4EC",
        quick_btn_close_bg="#FFEBEE",
        quick_btn_close_text="#D32F2F",
        settings_group_bg="#F5FAF7",
        settings_preview_bg="#F5FAF7",
        settings_preview_border="#D4E8D8",
    ),
    ThemePreset.NIGHT_COMPANION: ThemeColors(
        background="#2B2430",
        surface="#36303A",
        surface_soft="#423B47",
        primary="#FF9E80",
        primary_soft="#4A3A3A",
        primary_text="#1A1A2E",
        primary_hover="#FFB299",
        primary_active="#E67A5C",
        secondary="#7E57C2",
        accent="#FFD54F",
        card="#36303A",
        divider="#4A3E50",
        info="#42A5F5",
        on_primary="#1A1A2E",
        on_accent="#1A1A2E",
        text="#E8DFE4",
        text_secondary="#B8A8B5",
        text_muted="#7A6E7A",
        border="#4A3E50",
        border_focus="#FF9E80",
        success="#81C784",
        warning="#FFB74D",
        danger="#EF5350",
        shadow_light="rgba(0, 0, 0, 0.30)",
        shadow_medium="rgba(0, 0, 0, 0.45)",
        pet_status_ok="#81C784",
        pet_status_busy="#FF9E80",
        pet_mood_bg="#423B47",
        pet_mood_text="#E8DFE4",
        header_bg="#423B47",
        header_text="#E8DFE4",
        msg_user_bg="#FF9E80",
        msg_user_text="#1A1A2E",
        msg_bot_bg="#36303A",
        msg_bot_text="#E8DFE4",
        msg_bot_border="#4A3E50",
        chat_bg="#2B2430",
        input_bg="#36303A",
        input_border="#4A3E50",
        input_focus_border="#FF9E80",
        quick_btn_bg="#36303A",
        quick_btn_border="#4A3E50",
        quick_btn_hover_bg="#423B47",
        quick_btn_close_bg="#4A2828",
        quick_btn_close_text="#EF5350",
        settings_group_bg="#36303A",
        settings_preview_bg="#36303A",
        settings_preview_border="#4A3E50",
    ),
}


# ============================================================================
# Theme Manager (Singleton)
# ============================================================================

class ThemeManager(QObject):
    """Manages current theme and notifies listeners on changes."""

    theme_changed = Signal(ThemeColors)

    _instance: ClassVar[ThemeManager | None] = None

    def __init__(self):
        super().__init__()
        self._preset: ThemePreset = ThemePreset.COZY_ORANGE
        self._custom_colors: dict[str, str] = {}
        self._current: ThemeColors = PRESET_THEMES[ThemePreset.COZY_ORANGE]
        self._user_theme_id: str | None = None

    @classmethod
    def instance(cls) -> ThemeManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def current(self) -> ThemeColors:
        return self._current

    @property
    def preset(self) -> ThemePreset:
        return self._preset

    @property
    def custom_overrides(self) -> dict[str, str]:
        return dict(self._custom_colors)

    def set_preset(self, preset: ThemePreset) -> None:
        """Switch to a built-in theme preset."""
        self._preset = preset
        self._custom_colors = {}
        self._current = PRESET_THEMES[preset]
        self.theme_changed.emit(self._current)

    def set_custom(self, overrides: dict[str, str]) -> None:
        """Apply custom theme overrides on top of the current preset."""
        self._preset = ThemePreset.CUSTOM
        self._custom_colors = dict(overrides)
        base = PRESET_THEMES[ThemePreset.COZY_ORANGE]
        merged = ThemeColors(**{**base.__dict__, **overrides})
        self._current = merged
        self.theme_changed.emit(self._current)

    def apply_theme(self, preset: ThemePreset, custom_overrides: dict[str, str] | None = None) -> None:
        """Apply a theme from stored configuration."""
        if custom_overrides:
            self._preset = preset
            self._custom_colors = dict(custom_overrides)
            base = PRESET_THEMES.get(preset, PRESET_THEMES[ThemePreset.COZY_ORANGE])
            merged = ThemeColors(**{**base.__dict__, **custom_overrides})
            self._current = merged
        else:
            self._preset = preset
            self._custom_colors = {}
            self._current = PRESET_THEMES.get(preset, PRESET_THEMES[ThemePreset.COZY_ORANGE])
        self.theme_changed.emit(self._current)

    def load_user_theme(self, theme_id: str) -> bool:
        """Load and apply a user theme from database."""
        try:
            repo = ThemeRepository()
            theme_data = repo.get_by_id(theme_id)
            if not theme_data:
                return False

            colors = json.loads(theme_data["colors_json"])
            self._preset = ThemePreset.CUSTOM
            self._custom_colors = colors
            base = PRESET_THEMES[ThemePreset.COZY_ORANGE]
            merged = ThemeColors(**{**base.__dict__, **colors})
            self._current = merged
            self._user_theme_id = theme_id
            self.theme_changed.emit(self._current)
            return True
        except Exception as e:
            logger.error(f"Failed to load user theme {theme_id}: {e}")
            return False

    def save_current_as_user_theme(self, name: str, source: str = "manual") -> str | None:
        """Save current theme as a user theme."""
        try:
            import uuid
            repo = ThemeRepository()
            theme_id = f"user_{uuid.uuid4().hex[:8]}"
            colors = self._custom_colors if self._custom_colors else self._current.__dict__
            repo.save(theme_id, name, colors, source)
            return theme_id
        except Exception as e:
            logger.error(f"Failed to save user theme: {e}")
            return None

    def delete_user_theme(self, theme_id: str) -> bool:
        """Delete a user theme."""
        try:
            repo = ThemeRepository()
            return repo.delete(theme_id)
        except Exception as e:
            logger.error(f"Failed to delete user theme {theme_id}: {e}")
            return False

    def get_user_themes(self) -> list[dict[str, object]]:
        """Get all user themes."""
        try:
            repo = ThemeRepository()
            return repo.get_all()
        except Exception as e:
            logger.error(f"Failed to get user themes: {e}")
            return []

    @property
    def user_theme_id(self) -> str | None:
        """Get current user theme ID if applicable."""
        return getattr(self, '_user_theme_id', None)


# ============================================================================
# Style Generation Helpers
# ============================================================================

def generate_button_style(
    theme: ThemeColors,
    *,
    size: str = "normal",
    variant: str = "primary",
) -> str:
    """Generate QSS for a button based on theme.

    Args:
        theme: Current theme colors
        size: 'sm', 'normal', or 'lg'
        variant: 'primary', 'secondary', or 'ghost'
    """
    if variant == "primary":
        bg = theme.primary
        text = theme.primary_text
        hover_bg = theme.primary_hover
        pressed_bg = theme.primary_active
    elif variant == "secondary":
        bg = theme.surface
        text = theme.text
        hover_bg = theme.surface_soft
        pressed_bg = theme.surface
    else:  # ghost
        bg = "transparent"
        text = theme.text_secondary
        hover_bg = theme.surface_soft
        pressed_bg = theme.surface_soft

    size_map = {"sm": (8, 12), "normal": (10, 16), "lg": (14, 22)}
    py, px = size_map.get(size, (10, 16))

    return (
        f"QPushButton {{"
        f"  background: {bg};"
        f"  color: {text};"
        f"  border: 1px solid {theme.border};"
        f"  border-radius: {theme.radius_sm}px;"
        f"  padding: {py}px {px}px;"
        f"  font-size: 13px;"
        f"  font-weight: bold;"
        f"}}"
        f" QPushButton:hover {{"
        f"  background: {hover_bg};"
        f"}}"
        f" QPushButton:pressed {{"
        f"  background: {pressed_bg};"
        f"  color: {text};"
        f"}}"
    )


def generate_input_style(theme: ThemeColors) -> str:
    """Generate QSS for a line edit input."""
    return (
        f"QLineEdit {{"
        f"  background: {theme.input_bg};"
        f"  border: 1px solid {theme.input_border};"
        f"  border-radius: {theme.radius_sm}px;"
        f"  padding: 8px 16px;"
        f"  font-size: 13px;"
        f"  color: {theme.text};"
        f"}}"
        f" QLineEdit:focus {{"
        f"  background: {theme.surface};"
        f"  border-color: {theme.input_focus_border};"
        f"}}"
    )


def generate_card_style(theme: ThemeColors, *, hoverable: bool = False) -> str:
    """Generate QSS for a card container."""
    base = (
        f"QWidget#card {{"
        f"  background: {theme.surface};"
        f"  border: 1px solid {theme.border};"
        f"  border-radius: {theme.radius_md}px;"
        f"}}"
    )
    if hoverable:
        base += (
            f" QWidget#card:hover {{"
            f"  background: {theme.surface_soft};"
            f"  border-color: {theme.primary};"
            f"}}"
        )
    return base


def generate_scrollbar_style(theme: ThemeColors) -> str:
    """Generate QSS for vertical scrollbar."""
    return (
        f"QScrollBar:vertical {{"
        f"  width: 8px;"
        f"  background: transparent;"
        f"}}"
        f" QScrollBar::handle:vertical {{"
        f"  background: {theme.border};"
        f"  border-radius: 4px;"
        f"  min-height: 30px;"
        f"}}"
    )


def generate_context_menu_style(theme: ThemeColors) -> str:
    """Generate QSS for right-click context menu."""
    return (
        f"QMenu {{"
        f"  background: {theme.surface};"
        f"  border: 1px solid {theme.border};"
        f"  border-radius: {theme.radius_sm}px;"
        f"  padding: 4px;"
        f"}}"
        f" QMenu::item {{"
        f"  padding: 8px 16px;"
        f"  border-radius: 6px;"
        f"  color: {theme.text};"
        f"}}"
        f" QMenu::item:selected {{"
        f"  background: {theme.surface_soft};"
        f"  color: {theme.primary};"
        f"}}"
    )


def generate_panel_style(theme: ThemeColors) -> str:
    """Generate QSS for the main panel container."""
    return (
        f"QWidget#container {{"
        f"  background: {theme.surface};"
        f"  border-radius: {theme.radius_lg}px;"
        f"  border: 1px solid {theme.border};"
        f"}}"
    )


def generate_chat_bubble_style(theme: ThemeColors, *, is_user: bool) -> str:
    """Generate QSS for a chat message bubble."""
    if is_user:
        return (
            f"QLabel {{"
            f"  background: {theme.msg_user_bg};"
            f"  color: {theme.msg_user_text};"
            f"  padding: 10px 14px;"
            f"  border-radius: {theme.radius_md}px;"
            f"  border-bottom-right-radius: 4px;"
            f"}}"
        )
    else:
        return (
            f"QLabel {{"
            f"  background: {theme.msg_bot_bg};"
            f"  color: {theme.msg_bot_text};"
            f"  padding: 10px 14px;"
            f"  border-radius: {theme.radius_md}px;"
            f"  border-bottom-left-radius: 4px;"
            f"  border: 1px solid {theme.msg_bot_border};"
            f"}}"
        )


def generate_tooltip_style(theme: ThemeColors) -> str:
    """Generate QSS for tooltips."""
    return (
        f"QToolTip {{"
        f"  background: {theme.surface};"
        f"  color: {theme.text};"
        f"  border: 1px solid {theme.border};"
        f"  border-radius: {theme.radius_sm}px;"
        f"  padding: 6px 10px;"
        f"  font-size: 12px;"
        f"}}"
    )
