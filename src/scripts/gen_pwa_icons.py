"""Generate PWA icon PNG files.
Creates:
 - img/icons/icon-192.png
 - img/icons/icon-512.png
 - img/icons/maskable-192.png
 - img/icons/maskable-512.png

Run: python -m scripts.gen_pwa_icons
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

THEME_COLOR = (0, 102, 204)  # #0066cc
TEXT_COLOR = (255, 255, 255)
FONT_RATIO = 0.5  # portion of image height
TEXT = "AFT"

SIZES = [192, 512]
ROOT = Path(__file__).resolve().parents[2]  # project root (Ship_web)
ICON_DIR = ROOT / 'img' / 'icons'
ICON_DIR.mkdir(parents=True, exist_ok=True)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    # Try common fonts; fallback to default
    for name in ["arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def make_icon(size: int, maskable: bool = False):
    img = Image.new("RGBA", (size, size), THEME_COLOR + (255,))
    draw = ImageDraw.Draw(img)

    # Optional maskable safe zone circle effect
    if maskable:
        # Add radial gradient-ish border by drawing concentric circles
        import math
        steps = 6
        for i in range(steps):
            alpha = int(40 * (1 - i / steps))
            radius = int(size / 2 - (i * size * 0.04))
            bbox = [size/2 - radius, size/2 - radius, size/2 + radius, size/2 + radius]
            draw.ellipse(bbox, outline=(255, 255, 255, alpha), width=2)

    font_size = int(size * FONT_RATIO)
    font = load_font(font_size)
    text_w, text_h = draw.textsize(TEXT, font=font)
    x = (size - text_w) / 2
    y = (size - text_h) / 2 - size * 0.05

    # Draw subtle shadow
    draw.text((x+2, y+2), TEXT, font=font, fill=(0,0,0,120))
    draw.text((x, y), TEXT, font=font, fill=TEXT_COLOR)

    suffix = 'maskable-' if maskable else ''
    out_path = ICON_DIR / f'{suffix}{size}.png'
    img.save(out_path, optimize=True)
    print(f'Generated {out_path}')


def main():
    for s in SIZES:
        make_icon(s, maskable=False)
        make_icon(s, maskable=True)

if __name__ == '__main__':
    main()
