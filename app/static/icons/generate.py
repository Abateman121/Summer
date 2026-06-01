"""Generate the PWA app icons using only the Python standard library.

Creates three PNGs in this directory:
  - icon-192.png    (192x192)  PWA icon
  - icon-512.png    (512x512)  PWA icon
  - apple-touch-icon.png (180x180)  iOS home screen icon

Design: a warm yellow/amber sun on a cream background. No fonts required —
everything is drawn as pixels so the result is reproducible and the file is
tiny.
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

# Brand colors
BG = (255, 250, 240)         # cream
SUN = (245, 158, 11)         # amber
SUN_DARK = (217, 119, 6)     # amber-dark

OUT_DIR = Path(__file__).resolve().parent


def make_png(width: int, height: int, pixels: list[tuple[int, int, int]]) -> bytes:
    """Encode an RGB pixel grid as a PNG. pixels is a list of (r,g,b) rows."""
    # PNG signature
    out = bytearray(b"\x89PNG\r\n\x1a\n")

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    # IHDR
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    out += chunk(b"IHDR", ihdr)

    # IDAT (raw scanlines: each row starts with filter byte 0, then RGB triples)
    raw = bytearray()
    for row in pixels:
        raw.append(0)  # filter: none
        for r, g, b in row:
            raw.append(r)
            raw.append(g)
            raw.append(b)
    out += chunk(b"IDAT", zlib.compress(bytes(raw), 9))

    # IEND
    out += chunk(b"IEND", b"")
    return bytes(out)


def in_circle(x: int, y: int, cx: float, cy: float, r: float) -> bool:
    dx = x + 0.5 - cx
    dy = y + 0.5 - cy
    return dx * dx + dy * dy <= r * r


def in_ring(x: int, y: int, cx: float, cy: float, r_outer: float, r_inner: float) -> bool:
    dx = x + 0.5 - cx
    dy = y + 0.5 - cy
    d2 = dx * dx + dy * dy
    return r_inner * r_inner <= d2 <= r_outer * r_outer


def draw_sun(size: int) -> list[tuple[int, int, int]]:
    """Render a sun-with-rays icon at the given size (square)."""
    pixels: list[tuple[int, int, int]] = []
    cx, cy = size / 2, size / 2
    # Sun core: 22% of size radius
    core_r = size * 0.22
    # Rays: 12 rays from 26% to 46% of size radius
    ray_inner = size * 0.26
    ray_outer = size * 0.46

    for y in range(size):
        row: list[tuple[int, int, int]] = []
        for x in range(size):
            if in_circle(x, y, cx, cy, core_r):
                # Core gradient: brighter in the middle
                d = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5
                t = d / core_r
                r = int(SUN[0] * (1 - t * 0.3) + 255 * t * 0.3)
                g = int(SUN[1] * (1 - t * 0.3) + 240 * t * 0.3)
                b = int(SUN[2] * (1 - t * 0.3) + 200 * t * 0.3)
                row.append((r, g, b))
            elif in_ring(x, y, cx, cy, ray_outer, ray_inner):
                # Check if it's actually on a ray (12 rays)
                dx = x + 0.5 - cx
                dy = y + 0.5 - cy
                import math

                angle = math.atan2(dy, dx)
                ray_idx = int(((angle + math.pi) / (2 * math.pi)) * 12) % 12
                # Ray width: only every other 30-deg slice is "on" (actually 12 rays means 15deg each, half ray, half gap)
                # A nicer look: rays are 8 deg wide, gaps are 22 deg wide
                local = ((angle + math.pi) / (2 * math.pi)) * 12
                frac = local - int(local)
                on_ray = frac < (8 / 30)
                if on_ray:
                    row.append(SUN_DARK)
                else:
                    row.append(BG)
            else:
                row.append(BG)
        pixels.append(row)
    return pixels


def main() -> int:
    for size, name in [
        (192, "icon-192.png"),
        (512, "icon-512.png"),
        (180, "apple-touch-icon.png"),
    ]:
        png = make_png(size, size, draw_sun(size))
        out_path = OUT_DIR / name
        out_path.write_bytes(png)
        print(f"  wrote {out_path.name} ({len(png)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
