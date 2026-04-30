"""Theme generator - extract colors from pet images and generate theme drafts."""

import logging
import math
from collections import Counter
from typing import Optional

from core.utils.color_utils import (
    contrast_ratio,
    darken,
    hex_to_rgb,
    is_light_color,
    lighten,
    rgb_to_hex,
    suggest_readable_color,
)

logger = logging.getLogger(__name__)


class ThemeGenerator:
    """Generates theme color palettes from pet images."""

    def __init__(self):
        self._color_count = 8
        self._min_saturation = 0.1
        self._max_colors_to_return = 5

    def extract_palette(self, image_path: str) -> list[str]:
        """Extract dominant colors from an image using quantization.

        Args:
            image_path: Path to the image file

        Returns:
            List of hex color strings, sorted by dominance
        """
        try:
            from PIL import Image

            img = Image.open(image_path)
            if img.mode != "RGB":
                img = img.convert("RGB")

            img = img.resize((150, 150), Image.Resampling.LANCZOS)

            pixels = list(img.getdata())
            quantized = self._quantize_colors(pixels, self._color_count)

            sorted_colors = sorted(
                quantized.items(), key=lambda x: x[1], reverse=True
            )
            return [color for color, _ in sorted_colors[: self._max_colors_to_return]]

        except ImportError:
            logger.warning("Pillow not installed, using fallback color extraction")
            return self._fallback_palette()
        except Exception as e:
            logger.error(f"Color extraction failed: {e}")
            return self._fallback_palette()

    def _quantize_colors(
        self, pixels: list[tuple[int, int, int]], num_colors: int
    ) -> dict[str, int]:
        """Simple color quantization using bucketing."""
        buckets: Counter[str] = Counter()

        for r, g, b in pixels:
            bucket_r = (r // 32) * 32
            bucket_g = (g // 32) * 32
            bucket_b = (b // 32) * 32
            bucket_hex = rgb_to_hex(bucket_r, bucket_g, bucket_b)
            buckets[bucket_hex] += 1

        result: dict[str, int] = {}
        for color, count in buckets.most_common(num_colors):
            result[color] = count

        return result

    def _fallback_palette(self) -> list[str]:
        """Return a default palette when extraction fails."""
        return ["#FF8A3D", "#FFFFFF", "#4A2E1F", "#F1D9C0", "#8BCF7A"]

    def generate_theme(
        self,
        palette: list[str],
        name: str = "Pet Theme",
        source: str = "pet-ui-generated",
    ) -> dict:
        """Generate a complete theme from a color palette.

        Args:
            palette: List of hex colors from image
            name: Theme name
            source: Theme source identifier

        Returns:
            dict with theme colors suitable for ThemeColors
        """
        if len(palette) < 3:
            palette.extend(["#FFFFFF", "#000000", "#808080"][: 3 - len(palette)])

        primary = self._select_primary(palette)
        background = self._select_background(palette)
        text_color = self._select_text(background)

        if contrast_ratio(text_color, background) < 4.5:
            text_color = suggest_readable_color(text_color, background, 4.5)

        secondary = self._select_secondary(palette, primary)
        accent = self._select_accent(palette, primary, secondary)

        on_primary = "#FFFFFF" if is_light_color(primary) else "#1A1A2E"
        on_accent = "#FFFFFF" if is_light_color(accent) else "#1A1A2E"

        surface = lighten(background, 0.03) if is_light_color(background) else darken(background, 0.05)
        surface_soft = lighten(surface, 0.02) if is_light_color(surface) else darken(surface, 0.03)
        card = surface

        primary_hover = lighten(primary, 0.08) if is_light_color(primary) else darken(primary, 0.08)
        primary_active = darken(primary, 0.12) if is_light_color(primary) else lighten(primary, 0.12)
        primary_soft = lighten(primary, 0.25) if is_light_color(primary) else darken(primary, 0.25)

        border = lighten(background, 0.10) if is_light_color(background) else darken(background, 0.10)
        divider = lighten(border, 0.05) if is_light_color(border) else darken(border, 0.05)
        border_focus = primary

        text_secondary = lighten(text_color, 0.15) if is_light_color(background) else darken(text_color, 0.15)
        text_muted = lighten(text_color, 0.30) if is_light_color(background) else darken(text_color, 0.30)

        success = "#8BCF7A"
        warning = "#F5B84B"
        danger = "#FF7B7B"
        info = "#64B5F6"

        shadow_base = primary if is_light_color(primary) else "#000000"
        shadow_light = f"rgba({hex_to_rgb(shadow_base)[0]}, {hex_to_rgb(shadow_base)[1]}, {hex_to_rgb(shadow_base)[2]}, 0.10)"
        shadow_medium = f"rgba({hex_to_rgb(shadow_base)[0]}, {hex_to_rgb(shadow_base)[1]}, {hex_to_rgb(shadow_base)[2]}, 0.18)"

        header_bg = primary
        header_text = on_primary
        msg_user_bg = primary
        msg_user_text = on_primary
        msg_bot_bg = surface
        msg_bot_text = text_color
        msg_bot_border = border
        chat_bg = background
        input_bg = surface
        input_border = border
        input_focus_border = primary

        quick_btn_bg = surface
        quick_btn_border = border
        quick_btn_hover_bg = surface_soft
        quick_btn_close_bg = lighten(danger, 0.3) if is_light_color(background) else darken(danger, 0.3)
        quick_btn_close_text = danger

        settings_group_bg = background
        settings_preview_bg = background
        settings_preview_border = border

        return {
            "background": background,
            "surface": surface,
            "surface_soft": surface_soft,
            "primary": primary,
            "primary_soft": primary_soft,
            "primary_text": on_primary,
            "primary_hover": primary_hover,
            "primary_active": primary_active,
            "secondary": secondary,
            "accent": accent,
            "card": card,
            "divider": divider,
            "info": info,
            "on_primary": on_primary,
            "on_accent": on_accent,
            "text": text_color,
            "text_secondary": text_secondary,
            "text_muted": text_muted,
            "border": border,
            "border_focus": border_focus,
            "success": success,
            "warning": warning,
            "danger": danger,
            "shadow_light": shadow_light,
            "shadow_medium": shadow_medium,
            "pet_status_ok": success,
            "pet_status_busy": primary,
            "pet_mood_bg": surface_soft,
            "pet_mood_text": text_color,
            "header_bg": header_bg,
            "header_text": header_text,
            "msg_user_bg": msg_user_bg,
            "msg_user_text": msg_user_text,
            "msg_bot_bg": msg_bot_bg,
            "msg_bot_text": msg_bot_text,
            "msg_bot_border": msg_bot_border,
            "chat_bg": chat_bg,
            "input_bg": input_bg,
            "input_border": input_border,
            "input_focus_border": input_focus_border,
            "quick_btn_bg": quick_btn_bg,
            "quick_btn_border": quick_btn_border,
            "quick_btn_hover_bg": quick_btn_hover_bg,
            "quick_btn_close_bg": quick_btn_close_bg,
            "quick_btn_close_text": quick_btn_close_text,
            "settings_group_bg": settings_group_bg,
            "settings_preview_bg": settings_preview_bg,
            "settings_preview_border": settings_preview_border,
        }

    def _select_primary(self, palette: list[str]) -> str:
        """Select primary color from palette."""
        for color in palette:
            r, g, b = hex_to_rgb(color)
            saturation = self._calculate_saturation(r, g, b)
            if saturation > 0.3 and not self._is_too_dark(r, g, b):
                return color
        return palette[0] if palette else "#FF8A3D"

    def _select_background(self, palette: list[str]) -> str:
        """Select background color - should be light or very dark."""
        for color in palette:
            if is_light_color(color):
                return color
        for color in palette:
            r, g, b = hex_to_rgb(color)
            if self._is_too_dark(r, g, b):
                return color
        return "#FFF8EF"

    def _select_text(self, background: str) -> str:
        """Select text color based on background."""
        if is_light_color(background):
            return "#4A2E1F"
        return "#E8DFE4"

    def _select_secondary(self, palette: list[str], primary: str) -> str:
        """Select secondary color - complement to primary."""
        for color in palette:
            if color != primary:
                r, g, b = hex_to_rgb(color)
                saturation = self._calculate_saturation(r, g, b)
                if saturation > 0.2:
                    return color
        return lighten(primary, 0.15) if is_light_color(primary) else darken(primary, 0.15)

    def _select_accent(self, palette: list[str], primary: str, secondary: str) -> str:
        """Select accent color - contrasting highlight."""
        for color in palette:
            if color not in (primary, secondary):
                r, g, b = hex_to_rgb(color)
                saturation = self._calculate_saturation(r, g, b)
                if saturation > 0.4:
                    return color
        return "#FF8A3D"

    def _calculate_saturation(self, r: int, g: int, b: int) -> float:
        """Calculate HSL saturation."""
        r_norm, g_norm, b_norm = r / 255.0, g / 255.0, b / 255.0
        max_val = max(r_norm, g_norm, b_norm)
        min_val = min(r_norm, g_norm, b_norm)
        lightness = (max_val + min_val) / 2.0

        if max_val == min_val:
            return 0.0

        delta = max_val - min_val
        if lightness > 0.5:
            return delta / (2.0 - max_val - min_val)
        return delta / (max_val + min_val)

    def _is_too_dark(self, r: int, g: int, b: int) -> bool:
        """Check if a color is too dark for background use."""
        return (r * 0.299 + g * 0.587 + b * 0.114) < 50
