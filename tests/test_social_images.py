#!/usr/bin/env python3
"""Tests for the generated social images.

The Instagram image was rendered on a 1080x1920 (9:16) canvas, which is a
Stories ratio. scripts/post_to_instagram.py publishes a *feed* post, and the
feed crops anything taller than 4:5 — so 570px were discarded, taking the
header off the top and the #10 leaderboard row off the bottom.
"""
import unittest
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

REPO_ROOT = Path(__file__).resolve().parent.parent

# Instagram feed: 1.91:1 landscape through 4:5 portrait. Anything taller than
# 4:5 (aspect < 0.8) is centre-cropped.
MIN_FEED_ASPECT = 0.8
OG_SIZE = (1200, 630)


@unittest.skipIf(Image is None, "Pillow not installed")
class InstagramImageTests(unittest.TestCase):
    def test_not_taller_than_4_by_5(self):
        with Image.open(REPO_ROOT / "ig-image.png") as img:
            w, h = img.size
        self.assertGreaterEqual(
            w / h, MIN_FEED_ASPECT,
            f"ig-image.png is {w}x{h} (aspect {w/h:.3f}); the Instagram feed "
            f"crops anything below {MIN_FEED_ASPECT}, cutting off the header and #10",
        )

    def test_is_exactly_the_4_by_5_canvas(self):
        with Image.open(REPO_ROOT / "ig-image.png") as img:
            self.assertEqual(img.size, (1080, 1350))


@unittest.skipIf(Image is None, "Pillow not installed")
class OpenGraphImageTests(unittest.TestCase):
    def test_og_image_is_1200x630(self):
        with Image.open(REPO_ROOT / "og-image.png") as img:
            self.assertEqual(img.size, OG_SIZE)


class GeneratorTests(unittest.TestCase):
    def test_generator_renders_the_ratio_the_test_expects(self):
        """Keep the generator and this suite from drifting apart."""
        src = (REPO_ROOT / "scripts" / "generate_og_image.py").read_text()
        self.assertIn("1080, 1350", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
