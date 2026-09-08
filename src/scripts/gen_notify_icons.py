"""웹 푸시 알림 전용 아이콘 생성.

기존 icon-192.png(파란 "AFT" 정사각 글자 로고)를 알림에 그대로 쓰면
88px 크기로 본문을 절반 잡아먹는다(Claude Design 스펙 "푸시 알림 디자인"
D절 - 실측). 알림에는 별도로 작은 아이콘을 쓴다:
  - notify-bell-192.png  빈자리 상태를 뜻하는 초록 종 (showNotification icon)
  - badge-anchor-96.png  흰색 단색 실루엣, 투명 배경 (showNotification badge,
                          안드로이드 상태바용 - 색을 넣으면 검은 사각으로 뭉갠다)

Run: python -m scripts.gen_notify_icons
"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
ICON_DIR = ROOT / 'img' / 'icons'
ICON_DIR.mkdir(parents=True, exist_ok=True)

# .bell-toggle.bell-on / .fleet-master-toggle.all-on 에서 쓰는 것과 같은
# 초록 계열(oklch(0.52 0.1 168) 근사치) - 알림 아이콘이 화면 속 "켜짐" 색과
# 같아 보이게 한다.
BELL_TOP = (46, 145, 122)     # 위쪽(밝은 쪽)
BELL_BOTTOM = (23, 110, 128)  # 아래쪽(어두운 쪽) - 대각선 그라디언트


def _draw_bell(draw: ImageDraw.ImageDraw, cx: int, cy: int, w: int, fill):
    """단순화한 종 모양 실루엣. w = 종 몸통 폭 기준."""
    body_top = cy - w * 0.55
    body_bottom = cy + w * 0.32
    # 종 몸통(위는 좁고 아래로 갈수록 넓어지는 돔 형태) - 폴리곤으로 근사
    points = []
    import math
    steps = 24
    for i in range(steps + 1):
        t = i / steps
        angle = math.pi * (1 - t)   # pi -> 0 (왼쪽 아래 -> 오른쪽 아래, 위쪽 돔)
        rx = w * 0.5 * (0.35 + 0.65 * math.sin(angle * 0.5) ** 0.6)
        x = cx + math.cos(angle) * w * 0.5
        y = body_top + (body_bottom - body_top) * (1 - math.sin(angle)) * 0.9 + w * 0.15
        points.append((x, y))
    # 종 아래 테두리(넓은 받침)
    rim_w = w * 0.62
    points += [
        (cx + rim_w, body_bottom),
        (cx + rim_w * 1.08, body_bottom + w * 0.1),
        (cx - rim_w * 1.08, body_bottom + w * 0.1),
        (cx - rim_w, body_bottom),
    ]
    draw.polygon(points, fill=fill)
    # 추(clapper)
    clapper_r = w * 0.09
    draw.ellipse([cx - clapper_r, body_bottom + w * 0.14 - clapper_r,
                  cx + clapper_r, body_bottom + w * 0.14 + clapper_r], fill=fill)
    # 꼭지 고리
    knob_r = w * 0.07
    draw.ellipse([cx - knob_r, body_top - w * 0.12 - knob_r,
                  cx + knob_r, body_top - w * 0.12 + knob_r], outline=fill, width=max(2, int(w * 0.06)))


def make_notify_icon(size: int = 192):
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 둥근 사각 배경 대각선 그라디언트 (다른 아이콘 타일과 톤 맞춤)
    radius = int(size * 0.24)
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    grad = Image.new('RGBA', (size, size))
    for y in range(size):
        t = y / (size - 1)
        r = int(BELL_TOP[0] + (BELL_BOTTOM[0] - BELL_TOP[0]) * t)
        g = int(BELL_TOP[1] + (BELL_BOTTOM[1] - BELL_TOP[1]) * t)
        b = int(BELL_TOP[2] + (BELL_BOTTOM[2] - BELL_TOP[2]) * t)
        for x in range(size):
            grad.putpixel((x, y), (r, g, b, 255))
    img.paste(grad, (0, 0), mask)

    _draw_bell(draw, size // 2, int(size * 0.53), int(size * 0.46), (255, 255, 255, 255))

    out_path = ICON_DIR / f'notify-bell-{size}.png'
    img.save(out_path, optimize=True)
    print(f'Generated {out_path}')


def make_badge_icon(size: int = 96):
    """투명 배경, 흰색 실루엣만. OS가 자체 배경색을 입힌다."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _draw_bell(draw, size // 2, int(size * 0.55), int(size * 0.62), (255, 255, 255, 255))
    out_path = ICON_DIR / f'badge-anchor-{size}.png'
    img.save(out_path, optimize=True)
    print(f'Generated {out_path}')


def main():
    make_notify_icon(192)
    make_badge_icon(96)


if __name__ == '__main__':
    main()
