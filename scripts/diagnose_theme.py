"""Diagnostic script to test color extraction from pet images."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.services.theme_generator import ThemeGenerator
from core.utils.color_utils import hex_to_rgb, is_light_color


def diagnose_image(image_path: str):
    """Diagnose color extraction from an image."""
    print(f"\n=== Diagnosing: {image_path} ===\n")

    generator = ThemeGenerator()

    # Extract palette
    palette = generator.extract_palette(image_path)
    print(f"Extracted palette ({len(palette)} colors):")
    for i, color in enumerate(palette):
        r, g, b = hex_to_rgb(color)
        light = "light" if is_light_color(color) else "dark"
        print(f"  {i}: {color} (RGB: {r},{g},{b}) [{light}]")

    # Show what each method selects
    print("\nSelection results:")
    primary = generator._select_primary(palette)
    print(f"  _select_primary: {primary}")

    background = generator._select_background(palette)
    print(f"  _select_background: {background}")

    secondary = generator._select_secondary(palette, primary)
    print(f"  _select_secondary: {secondary}")

    accent = generator._select_accent(palette, primary, secondary)
    print(f"  _select_accent: {accent}")

    # Generate theme
    theme = generator.generate_theme(palette, "Diagnosis")
    print(f"\nGenerated theme primary: {theme['primary']}")
    print(f"Generated theme background: {theme['background']}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        diagnose_image(sys.argv[1])
    else:
        print("Usage: python diagnose_theme.py <image_path>")
        print("Example: python diagnose_theme.py data/user_assets/pets/pet_idle.gif")
