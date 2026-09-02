#!/usr/bin/env python3
"""Tests for the generated site icons.

The icons previously carried a one-pixel fringe along the blue/red seam: they
were produced by downscaling a large raster, and a resampling filter that rings
at a hard edge overshoots to colours outside the range of both halves (the seam
read (245, 63, 31), darker and more saturated than either side). Two other
defects rode along: the maskable icons were a small square floating on a navy
field, which Android crops to a tiny square inside a circle, and favicon.svg
was a 256px bitmap wrapped in an <svg> so it could never render crisply.

These assert the properties that were violated, not the generator's internals.
"""
import unittest
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

REPO_ROOT = Path(__file__).resolve().parent.parent

US_BLUE = (59, 130, 246)
CN_RED = (239, 68, 68)
WHITE = (255, 255, 255)

# Mirrors MIN_SIZE_FOR_MARK in scripts/generate_icons.py.
MIN_SIZE_FOR_MARK = 48

ICONS = [
    "favicon-16x16.png", "favicon-32x32.png", "favicon-48x48.png",
    "favicon-64x64.png", "favicon-96x96.png", "favicon-128x128.png",
    "favicon-256x256.png", "favicon-512x512.png", "apple-touch-icon.png",
    "web-app-manifest-192x192.png", "web-app-manifest-512x512.png",
    "maskable-192x192.png", "maskable-512x512.png",
]


@unittest.skipIf(Image is None, "Pillow not installed")
class SeamTests(unittest.TestCase):
    def test_seam_is_a_hard_two_colour_edge(self):
        """No blended or overshot pixels where blue meets red.

        Checked in a band above the VS so the glyph's antialiasing (which is
        legitimate) does not mask a genuine seam artifact.
        """
        for name in ICONS:
            with self.subTest(icon=name):
                img = Image.open(REPO_ROOT / name).convert("RGB")
                w, h = img.size
                for y in range(0, max(1, h // 12)):
                    self.assertEqual(img.getpixel((w // 2 - 1, y)), US_BLUE, f"{name} y={y}")
                    self.assertEqual(img.getpixel((w // 2, y)), CN_RED, f"{name} y={y}")

    def test_no_colours_outside_the_palette(self):
        """Ringing shows up as colours that are in neither half nor the mark."""
        allowed_error = 2
        for name in ICONS:
            with self.subTest(icon=name):
                img = Image.open(REPO_ROOT / name).convert("RGB")
                w, h = img.size
                for x in range(0, w, max(1, w // 40)):
                    for y in range(0, h, max(1, h // 40)):
                        px = img.getpixel((x, y))
                        # A pixel must be blue, red, white, or a blend of white
                        # with one of them (the antialiased glyph edge).
                        ok = any(
                            all(abs(px[i] - base[i]) <= allowed_error for i in range(3))
                            for base in (US_BLUE, CN_RED, WHITE)
                        ) or all(
                            min(base[i], WHITE[i]) - allowed_error <= px[i] <= max(base[i], WHITE[i]) + allowed_error
                            for base in (US_BLUE, CN_RED)
                            for i in range(3)
                        ) or any(
                            all(min(base[i], WHITE[i]) - allowed_error <= px[i] <= max(base[i], WHITE[i]) + allowed_error
                                for i in range(3))
                            for base in (US_BLUE, CN_RED)
                        )
                        self.assertTrue(ok, f"{name} at ({x},{y}) has stray colour {px}")


@unittest.skipIf(Image is None, "Pillow not installed")
class MarkTests(unittest.TestCase):
    def test_mark_present_at_large_sizes_and_absent_at_small(self):
        for name in ICONS:
            with self.subTest(icon=name):
                img = Image.open(REPO_ROOT / name).convert("RGB")
                w, h = img.size
                has_white = any(
                    img.getpixel((x, y)) == WHITE
                    for x in range(0, w, 2) for y in range(0, h, 2)
                )
                if w >= MIN_SIZE_FOR_MARK:
                    self.assertTrue(has_white, f"{name} ({w}px) should carry the VS mark")
                else:
                    self.assertFalse(has_white, f"{name} ({w}px) should omit the VS mark")


@unittest.skipIf(Image is None, "Pillow not installed")
class MaskableTests(unittest.TestCase):
    def test_maskable_icons_are_full_bleed(self):
        """A maskable icon is cropped to a circle, so it must reach every edge.

        The old ones were a small square on a navy field and rendered as a tiny
        square inside the launcher's circle.
        """
        for name in ("maskable-192x192.png", "maskable-512x512.png"):
            with self.subTest(icon=name):
                img = Image.open(REPO_ROOT / name).convert("RGB")
                w, h = img.size
                corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
                for x, y in corners:
                    self.assertIn(
                        img.getpixel((x, y)), (US_BLUE, CN_RED),
                        f"{name} corner ({x},{y}) is not part of the design — not full-bleed",
                    )


class SvgTests(unittest.TestCase):
    def test_favicon_svg_is_vector_not_an_embedded_bitmap(self):
        svg = (REPO_ROOT / "favicon.svg").read_text()
        self.assertNotIn("base64", svg, "favicon.svg embeds a bitmap instead of vector shapes")
        self.assertIn("<rect", svg)

    def test_favicon_svg_uses_the_team_colours(self):
        svg = (REPO_ROOT / "favicon.svg").read_text().lower()
        self.assertIn("#3b82f6", svg)
        self.assertIn("#ef4444", svg)


class ManifestTests(unittest.TestCase):
    def test_every_manifest_icon_exists(self):
        import json
        manifest = json.loads((REPO_ROOT / "site.webmanifest").read_text())
        for icon in manifest.get("icons", []):
            path = REPO_ROOT / icon["src"].lstrip("/")
            self.assertTrue(path.exists(), f"manifest references missing icon {icon['src']}")

    def test_manifest_icon_sizes_match_the_files(self):
        import json
        if Image is None:
            self.skipTest("Pillow not installed")
        manifest = json.loads((REPO_ROOT / "site.webmanifest").read_text())
        for icon in manifest.get("icons", []):
            path = REPO_ROOT / icon["src"].lstrip("/")
            declared = icon["sizes"].split("x")[0]
            with Image.open(path) as img:
                self.assertEqual(
                    str(img.size[0]), declared,
                    f"{icon['src']} is {img.size[0]}px but the manifest declares {icon['sizes']}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
