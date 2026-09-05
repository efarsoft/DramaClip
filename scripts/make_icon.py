"""生成应用图标 desktop/build/icon.ico（多尺寸）。

设计：深蓝紫渐变圆角方块 + 蓝青色播放三角 + 橙色高光条（剪辑标记意象）。
用法：.venv/Scripts/python.exe scripts/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "desktop" / "build" / "icon.ico"
SIZE = 256


def base_canvas() -> Image.Image:
    """256px 主画布：垂直渐变底 + 圆角裁切。"""
    top = (30, 34, 62)
    bottom = (18, 20, 38)
    img = Image.new("RGBA", (SIZE, SIZE))
    for y in range(SIZE):
        t = y / (SIZE - 1)
        color = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
        for x in range(SIZE):
            img.putpixel((x, y), color)
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=52, fill=255)
    img.putalpha(mask)
    return img


def draw_mark(img: Image.Image) -> None:
    """播放三角（蓝青渐变）+ 上方橙色剪辑标记条。"""
    draw = ImageDraw.Draw(img)

    # 剪辑标记条：顶部斜置圆角条（场记板意象）
    bar = Image.new("RGBA", (150, 34), (0, 0, 0, 0))
    ImageDraw.Draw(bar).rounded_rectangle([0, 0, 149, 33], radius=16, fill=(255, 176, 68, 255))
    bar = bar.rotate(-14, expand=True)
    img.alpha_composite(bar, (58, 34))

    # 播放三角：双圆角矩形偏移成柔和三角；简化用多边形 + 抗锯齿超采样
    tri = Image.new("RGBA", (SIZE * 2, SIZE * 2), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(tri)
    points = [(150 * 2, 112 * 2), (112 * 2, 82 * 2), (112 * 2, 142 * 2)]
    tdraw.polygon(points, fill=(96, 178, 255, 255))
    tri = tri.resize((SIZE, SIZE), Image.LANCZOS)
    img.alpha_composite(tri, (0, 20))


def main() -> None:
    img = base_canvas()
    draw_mark(img)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(f"icon 已生成: {OUT}")


if __name__ == "__main__":
    main()
