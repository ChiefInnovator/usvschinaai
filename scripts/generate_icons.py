#!/usr/bin/env python3
"""Regenerate every site icon from one vector definition.

The previous icons were produced by downscaling a large raster, which left a
one-pixel fringe along the blue/red seam: a resampling filter that rings at a
hard edge overshoots to colours outside the range of both sides (the seam read
(245, 63, 31), darker and more saturated than either half). Drawing each size
at its native resolution instead means the seam is always exactly two flat
colours meeting on a pixel boundary, at every size.

Run: python scripts/generate_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent

# Team colours, matching the frontend and site.webmanifest theme_color.
US_BLUE = (59, 130, 246)
CN_RED = (239, 68, 68)

# Square favicons / app icons. Every size is even, so the split lands exactly
# on a pixel boundary and needs no antialiasing.
ICON_SIZES = {
    "favicon-16x16.png": 16,
    "favicon-32x32.png": 32,
    "favicon-48x48.png": 48,
    "favicon-64x64.png": 64,
    "favicon-96x96.png": 96,
    "favicon-128x128.png": 128,
    "favicon-256x256.png": 256,
    "favicon-512x512.png": 512,
    "apple-touch-icon.png": 180,
    "web-app-manifest-192x192.png": 192,
    "web-app-manifest-512x512.png": 512,
    # Maskable icons must be full-bleed: the launcher crops them to a circle or
    # squircle. The old ones were a small square on a navy field, so Android
    # rendered a tiny square inside a circle.
    "maskable-192x192.png": 192,
    "maskable-512x512.png": 512,
}

ICO_SIZES = [16, 32, 48, 64, 128, 256]

# Below this the "VS" collapses into a smudge and reads worse than a clean
# split, so small favicons ship as colour only.
MIN_SIZE_FOR_MARK = 48

# Heavy face to match the h1's `font-black italic tracking-tighter`. Arial Black
# has no italic cut, so the glyphs are sheared below.
MARK_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/Library/Fonts/Arial Black.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

MARK_TEXT = "VS"
MARK_ITALIC_SHEAR = 0.18   # ~10 degrees
MARK_HEIGHT_RATIO = 0.46   # cap height as a fraction of the icon
SUPERSAMPLE = 8            # glyph antialiasing only; never the colour seam

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512" role="img" aria-label="US vs China AI">
  <rect x="0" y="0" width="256" height="512" fill="#3b82f6"/>
  <rect x="256" y="0" width="256" height="512" fill="#ef4444"/>
  <text x="256" y="256" fill="#ffffff" text-anchor="middle" dominant-baseline="central"
        font-family="Arial Black, Arial Bold, Helvetica, sans-serif"
        font-weight="900" font-style="italic" font-size="236"
        letter-spacing="-10">VS</text>
</svg>
"""


def _load_mark_font(pixel_size: int):
    for path in MARK_FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, pixel_size)
            except OSError:
                continue
    return None


def _mark_alpha(size: int):
    """Antialiased alpha mask for the VS, or None if no heavy face is present.

    Rendered at SUPERSAMPLE scale and reduced, so the glyph edges are smooth.
    Only this mask is resampled — the colour split underneath is drawn at
    native size, so the seam never picks up the ringing that produced the old
    one-pixel fringe.
    """
    big = size * SUPERSAMPLE
    font = _load_mark_font(int(big * MARK_HEIGHT_RATIO))
    if font is None:
        return None

    layer = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(layer)
    left, top, right, bottom = draw.textbbox((0, 0), MARK_TEXT, font=font)
    draw.text(((big - (right - left)) / 2 - left,
               (big - (bottom - top)) / 2 - top),
              MARK_TEXT, font=font, fill=255)

    # Shear for the italic slant, about the vertical centre so the mark stays
    # centred on the seam.
    offset = MARK_ITALIC_SHEAR * big / 2
    layer = layer.transform(
        (big, big), Image.AFFINE, (1, MARK_ITALIC_SHEAR, -offset, 0, 1, 0),
        resample=Image.BICUBIC,
    )
    return layer.resize((size, size), Image.LANCZOS)


def render(size: int, with_mark: bool = True) -> Image.Image:
    """Draw the split at native resolution — never resize an existing raster."""
    img = Image.new("RGBA", (size, size), US_BLUE + (255,))
    half = size // 2
    img.paste(CN_RED + (255,), (half, 0, size, size))

    if with_mark and size >= MIN_SIZE_FOR_MARK:
        alpha = _mark_alpha(size)
        if alpha is not None:
            white = Image.new("RGBA", (size, size), (255, 255, 255, 255))
            img = Image.composite(white, img, alpha)
    return img


def main() -> None:
    for filename, size in sorted(ICON_SIZES.items()):
        path = REPO_ROOT / filename
        render(size).save(path, "PNG", optimize=True)
        print(f"  wrote {filename} ({size}x{size})")

    # Multi-resolution .ico. Each layer is drawn at its own size rather than
    # letting the encoder downscale one image, so the small layers honour
    # MIN_SIZE_FOR_MARK instead of carrying a smudged VS.
    ico_path = REPO_ROOT / "favicon.ico"
    layers = [render(s) for s in ICO_SIZES]
    layers[-1].save(
        ico_path, "ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=layers[:-1],
    )
    print(f"  wrote favicon.ico ({', '.join(str(s) for s in ICO_SIZES)})")

    # A real vector, not a bitmap wrapped in an <svg>.
    (REPO_ROOT / "favicon.svg").write_text(SVG)
    print("  wrote favicon.svg (vector)")


if __name__ == "__main__":
    main()
