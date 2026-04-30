"""Color utilities for theme system - contrast validation, color manipulation."""

import colorsys


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color string to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB tuple to hex color string."""
    return f"#{r:02x}{g:02x}{b:02x}"


def relative_luminance(r: int, g: int, b: int) -> float:
    """Calculate relative luminance per WCAG 2.0 formula."""
    def linearize(c: int) -> float:
        c_srgb = c / 255.0
        if c_srgb <= 0.03928:
            return c_srgb / 12.92
        return ((c_srgb + 0.055) / 1.055) ** 2.4
    
    r_lin = linearize(r)
    g_lin = linearize(g)
    b_lin = linearize(b)
    
    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def contrast_ratio(color1: str, color2: str) -> float:
    """Calculate WCAG contrast ratio between two hex colors.
    
    Returns:
        float: Contrast ratio between 1.0 and 21.0
    """
    r1, g1, b1 = hex_to_rgb(color1)
    r2, g2, b2 = hex_to_rgb(color2)
    
    l1 = relative_luminance(r1, g1, b1)
    l2 = relative_luminance(r2, g2, b2)
    
    lighter = max(l1, l2)
    darker = min(l1, l2)
    
    return (lighter + 0.05) / (darker + 0.05)


def get_contrast_level(ratio: float) -> str:
    """Get WCAG compliance level for a contrast ratio.
    
    Returns:
        'AAA' if ratio >= 7.0
        'AA' if ratio >= 4.5
        'A' if ratio >= 3.0
        'FAIL' otherwise
    """
    if ratio >= 7.0:
        return "AAA"
    if ratio >= 4.5:
        return "AA"
    if ratio >= 3.0:
        return "A"
    return "FAIL"


def is_readable(color1: str, color2: str, min_level: str = "AA") -> bool:
    """Check if two colors meet minimum readability requirements."""
    ratio = contrast_ratio(color1, color2)
    level = get_contrast_level(ratio)
    
    level_order = {"FAIL": 0, "A": 1, "AA": 2, "AAA": 3}
    return level_order.get(level, 0) >= level_order.get(min_level, 0)


def suggest_readable_color(
    foreground: str, 
    background: str, 
    target_ratio: float = 4.5,
    adjust_foreground: bool = True
) -> str:
    """Suggest an adjusted color to meet target contrast ratio.
    
    Args:
        foreground: Foreground color hex
        background: Background color hex
        target_ratio: Target contrast ratio (default 4.5 for AA)
        adjust_foreground: If True, adjust foreground; else adjust background
        
    Returns:
        Adjusted hex color string
    """
    r, g, b = hex_to_rgb(foreground if adjust_foreground else background)
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    
    current_ratio = contrast_ratio(foreground, background)
    if current_ratio >= target_ratio:
        return foreground if adjust_foreground else background
    
    # Try darkening or lightening
    bg_r, bg_g, bg_b = hex_to_rgb(background)
    bg_luminance = relative_luminance(bg_r, bg_g, bg_b)
    
    step = 0.05
    max_iterations = 20
    
    for _ in range(max_iterations):
        if bg_luminance > 0.5:
            # Dark background needs lighter foreground
            l = min(1.0, l + step)
        else:
            # Light background needs darker foreground
            l = max(0.0, l - step)
        
        r_new, g_new, b_new = colorsys.hls_to_rgb(h, l, s)
        new_color = rgb_to_hex(
            int(r_new * 255), 
            int(g_new * 255), 
            int(b_new * 255)
        )
        
        if adjust_foreground:
            new_ratio = contrast_ratio(new_color, background)
        else:
            new_ratio = contrast_ratio(foreground, new_color)
        
        if new_ratio >= target_ratio:
            return new_color
    
    # Return best effort
    r_new, g_new, b_new = colorsys.hls_to_rgb(h, l, s)
    return rgb_to_hex(int(r_new * 255), int(g_new * 255), int(b_new * 255))


def lighten(hex_color: str, amount: float = 0.1) -> str:
    """Lighten a color by amount (0.0 to 1.0)."""
    r, g, b = hex_to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    l = min(1.0, l + amount)
    r_new, g_new, b_new = colorsys.hls_to_rgb(h, l, s)
    return rgb_to_hex(int(r_new * 255), int(g_new * 255), int(b_new * 255))


def darken(hex_color: str, amount: float = 0.1) -> str:
    """Darken a color by amount (0.0 to 1.0)."""
    r, g, b = hex_to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    l = max(0.0, l - amount)
    r_new, g_new, b_new = colorsys.hls_to_rgb(h, l, s)
    return rgb_to_hex(int(r_new * 255), int(g_new * 255), int(b_new * 255))


def is_light_color(hex_color: str) -> bool:
    """Check if a color is visually light."""
    r, g, b = hex_to_rgb(hex_color)
    return relative_luminance(r, g, b) > 0.5


def is_dark_color(hex_color: str) -> bool:
    """Check if a color is visually dark."""
    return not is_light_color(hex_color)


def hex_to_rgba(hex_color: str, alpha: float = 1.0) -> str:
    """Convert hex color to rgba() string."""
    r, g, b = hex_to_rgb(hex_color)
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"
