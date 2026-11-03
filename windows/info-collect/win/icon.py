#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
icon.py —— 纯 Python 生成托盘图标（.ico）

为什么不用 Pillow：
    项目至今零第三方依赖，打包成 exe 时依赖越少越不容易翻车。
    一个图标而已，自己拼字节就够了——ICO 本质就是几个 BMP 套个目录。

为什么先按 4 倍画再缩小：
    没有抗锯齿的话，圆角会变成台阶。用 4×4 超采样取平均，等于手写了一遍
    SSAA。40 行代码换一个不难看的图标，划算。

生成的图标含义：深色圆角方块 + 三根递增的柱子 = "统计"。
"""

from __future__ import annotations

import struct
from pathlib import Path

SIZES = (16, 20, 24, 32, 48)
SS = 4                      # 超采样倍数


# ---------------------------------------------------------------- 绘制

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _draw(size: int) -> list[list[tuple[int, int, int, int]]]:
    """在 size×size 的网格上画图，返回 RGBA 二维数组（非预乘）。"""
    n = size * SS
    bg_top = (48, 120, 235)      # 上：钢蓝
    bg_bot = (0, 158, 150)       # 下：青绿
    radius = n * (0.18 if size <= 20 else 0.22)

    px: list[list[tuple[int, int, int, int]]] = []
    for y in range(n):
        row = []
        t = y / max(1, n - 1)
        bg = (
            int(_lerp(bg_top[0], bg_bot[0], t)),
            int(_lerp(bg_top[1], bg_bot[1], t)),
            int(_lerp(bg_top[2], bg_bot[2], t)),
        )
        for x in range(n):
            # 圆角矩形：把点压到圆角中心再算距离
            cx = min(max(x, radius), n - 1 - radius)
            cy = min(max(y, radius), n - 1 - radius)
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if d > radius:
                row.append((0, 0, 0, 0))
            else:
                row.append((bg[0], bg[1], bg[2], 255))
        px.append(row)

    # 三根柱子：宽度、间距按比例算，高度递增。
    # 小尺寸（16/20）必须把柱子加粗，否则缩下来会糊成一团白雾。
    small = size <= 20
    pad = n * (0.16 if small else 0.20)
    inner = n - pad * 2
    bar_w = inner / (3.4 if small else 4.2)
    gap = (inner - bar_w * 3) / 2
    heights = (0.40, 0.64, 0.88) if small else (0.42, 0.66, 0.90)
    base = n - pad
    for i, h in enumerate(heights):
        x0 = pad + i * (bar_w + gap)
        x1 = x0 + bar_w
        y0 = base - inner * h
        r = bar_w * 0.28
        for y in range(int(y0), int(base)):
            for x in range(int(x0), int(x1) + 1):
                # 柱子顶端也做小圆角，不然看着像个方块
                if y < y0 + r:
                    cx = min(max(x, x0 + r), x1 - r)
                    if ((x - cx) ** 2 + (y - (y0 + r)) ** 2) ** 0.5 > r:
                        continue
                if 0 <= y < n and 0 <= x < n:
                    px[y][x] = (255, 255, 255, 255)
    return px


def _downsample(px: list[list[tuple[int, int, int, int]]], target: int):
    """SS×SS 区块取平均。透明像素按 alpha 加权，避免边缘发黑。"""
    n = len(px)
    out = []
    for ty in range(target):
        row = []
        for tx in range(target):
            r = g = b = a = 0
            for dy in range(SS):
                for dx in range(SS):
                    pr, pg, pb, pa = px[ty * SS + dy][tx * SS + dx]
                    r += pr * pa
                    g += pg * pa
                    b += pb * pa
                    a += pa
            if a == 0:
                row.append((0, 0, 0, 0))
            else:
                row.append((r // a, g // a, b // a, a // (SS * SS)))
        out.append(row)
    return out


# ---------------------------------------------------------------- 写文件

def _ico_image(size: int) -> bytes:
    """单张 32bpp 图标：BITMAPINFOHEADER + XOR 位图 + AND 掩码。"""
    px = _downsample(_draw(size), size)

    header = struct.pack(
        "<IiiHHIIiiII",
        40,                 # biSize
        size,               # biWidth
        size * 2,           # biHeight（XOR + AND 两张叠在一起，所以是两倍）
        1,                  # biPlanes
        32,                 # biBitCount
        0,                  # biCompression = BI_RGB
        0, 0, 0, 0, 0,      # sizeImage / 分辨率 / 调色板
    )

    # XOR 位图：BGRA，行序从下到上
    xor = bytearray()
    for y in range(size - 1, -1, -1):
        for x in range(size):
            r, g, b, a = px[y][x]
            xor += bytes((b, g, r, a))

    # AND 掩码：1bpp，1 = 透明。行必须 4 字节对齐
    row_bytes = ((size + 31) // 32) * 4
    and_mask = bytearray()
    for y in range(size - 1, -1, -1):
        row = bytearray(row_bytes)
        for x in range(size):
            if px[y][x][3] < 128:
                row[x // 8] |= 0x80 >> (x % 8)
        and_mask += row

    return header + bytes(xor) + bytes(and_mask)


def build_ico(path: Path, sizes: tuple[int, ...] = SIZES) -> Path:
    images = [_ico_image(s) for s in sizes]

    out = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))   # 目录头
    offset = 6 + 16 * len(sizes)
    for s, img in zip(sizes, images):
        out += struct.pack(
            "<BBBBHHII",
            s if s < 256 else 0,   # 256 要写成 0
            s if s < 256 else 0,
            0, 0,                  # 调色板数、保留位
            1, 32,                 # planes、bpp
            len(img), offset,
        )
        offset += len(img)
    for img in images:
        out += img

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path


def ensure_icon(path: Path) -> Path:
    """有就直接用，没有就生成一份。"""
    if path.exists() and path.stat().st_size > 100:
        return path
    return build_ico(path)


def png_bytes(size: int) -> bytes:
    """仅供开发时预览用：把同一套像素写成 PNG（标准库 zlib 就够）。"""
    import zlib

    px = _downsample(_draw(size), size)
    raw = bytearray()
    for y in range(size):
        raw.append(0)                       # filter type 0
        for x in range(size):
            r, g, b, a = px[y][x]
            raw += bytes((r, g, b, a))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


if __name__ == "__main__":
    import sys

    out = Path(__file__).resolve().parent / "infocollect.ico"
    build_ico(out)
    print(f"已生成：{out}  ({out.stat().st_size} 字节)")
    for s in SIZES:
        print(f"  含 {s}x{s}")

    # 生成预览图，方便肉眼确认
    for s in (16, 32, 48):
        p = out.with_name(f"_preview_{s}.png")
        p.write_bytes(png_bytes(s))
        print(f"  预览：{p.name}")
