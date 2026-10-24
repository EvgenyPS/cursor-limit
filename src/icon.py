# FILE: src/icon.py
# PURPOSE: Иконка трея из cursor-ico.svg — без чёрного фона, стрелка = цвет лимита.
# WHY: Логотип Cursor как маркер; % usage красит центральную стрелку (green→red).

from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from .config import ROOT_DIR
from .traffic_color import smooth_traffic_rgb

# Грани куба затемнены относительно оригинала SVG — стрелка-индикатор читается лучше
_CUBE_FILLS = {
    "#72716d": (58, 57, 54, 255),   # было ~114
    "#55544f": (40, 39, 36, 255),   # было ~85
    "#43413c": (28, 27, 24, 255),   # было ~67
}


def _svg_path() -> Path | None:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "cursor-ico.svg")
        candidates.append(Path(sys.executable).resolve().parent / "cursor-ico.svg")
    candidates.append(ROOT_DIR / "cursor-ico.svg")
    for p in candidates:
        if p.is_file():
            return p
    return None


def _cubic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    steps: int = 8,
) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        x = (
            u**3 * p0[0]
            + 3 * u**2 * t * p1[0]
            + 3 * u * t**2 * p2[0]
            + t**3 * p3[0]
        )
        y = (
            u**3 * p0[1]
            + 3 * u**2 * t * p1[1]
            + 3 * u * t**2 * p2[1]
            + t**3 * p3[1]
        )
        out.append((x, y))
    return out


def _parse_path_points(d: str) -> list[tuple[float, float]]:
    """Парсер path d: M/L/H/V/C/Z (+ относительные) — достаточно для cursor-ico.svg."""
    tokens = re.findall(
        r"[MmLlHhVvCcZz]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", d
    )
    pts: list[tuple[float, float]] = []
    i = 0
    cmd = "M"
    cx = cy = 0.0
    start = (0.0, 0.0)

    def _num() -> float:
        nonlocal i
        v = float(tokens[i])
        i += 1
        return v

    while i < len(tokens):
        t = tokens[i]
        if re.fullmatch(r"[MmLlHhVvCcZz]", t):
            cmd = t
            i += 1
            if cmd in "Zz":
                if pts and pts[0] != pts[-1]:
                    pts.append(pts[0])
                cx, cy = start
            continue

        if cmd in "Mm":
            x, y = _num(), _num()
            if cmd == "m":
                x, y = cx + x, cy + y
            cx, cy = x, y
            start = (cx, cy)
            pts.append((cx, cy))
            cmd = "L" if cmd == "M" else "l"
        elif cmd in "Ll":
            x, y = _num(), _num()
            if cmd == "l":
                x, y = cx + x, cy + y
            cx, cy = x, y
            pts.append((cx, cy))
        elif cmd in "Hh":
            x = _num()
            if cmd == "h":
                x = cx + x
            cx = x
            pts.append((cx, cy))
        elif cmd in "Vv":
            y = _num()
            if cmd == "v":
                y = cy + y
            cy = y
            pts.append((cx, cy))
        elif cmd in "Cc":
            x1, y1 = _num(), _num()
            x2, y2 = _num(), _num()
            x, y = _num(), _num()
            if cmd == "c":
                x1, y1 = cx + x1, cy + y1
                x2, y2 = cx + x2, cy + y2
                x, y = cx + x, cy + y
            pts.extend(_cubic((cx, cy), (x1, y1), (x2, y2), (x, y)))
            cx, cy = x, y
        else:
            i += 1
    return pts


def _extract_colored_paths(svg_text: str) -> list[tuple[str, list[tuple[float, float]]]]:
    out: list[tuple[str, list[tuple[float, float]]]] = []
    for m in re.finditer(r"<path\b([^>]*)/>", svg_text, flags=re.IGNORECASE):
        attrs = m.group(1)
        dm = re.search(r'\bd="([^"]+)"', attrs)
        fm = re.search(r'\bfill="([^"]+)"', attrs)
        if not dm or not fm:
            continue
        fill_l = fm.group(1).strip().lower()
        if fill_l in {"black", "#000", "#000000"}:
            continue
        # Чёрный фон — это <rect>, path с black не ждём; на всякий случай
        pts = _parse_path_points(dm.group(1))
        if len(pts) >= 3:
            out.append((fill_l, pts))
    return out


def _accent_pair(
    rgb: tuple[int, int, int],
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    bright = (rgb[0], rgb[1], rgb[2], 255)
    dim = (
        max(0, int(rgb[0] * 0.72)),
        max(0, int(rgb[1] * 0.72)),
        max(0, int(rgb[2] * 0.72)),
        255,
    )
    return bright, dim


def make_icon(level: str = "ok", percent: float = 0.0) -> Image.Image:
    """SVG-логотип на прозрачном фоне; центральная стрелка = цвет лимита."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if level == "error":
        accent_rgb = (120, 120, 128)
    else:
        accent_rgb = smooth_traffic_rgb(percent)
    arrow_bright, arrow_dim = _accent_pair(accent_rgb)

    svg_file = _svg_path()
    if svg_file is None:
        draw.polygon([(32, 8), (56, 32), (32, 56), (8, 32)], fill=arrow_bright)
        return img

    paths = _extract_colored_paths(svg_file.read_text(encoding="utf-8"))
    # Масштаб по bbox содержимого — без «воздуха» у краёв иконки
    all_pts = [p for _, pts in paths for p in pts]
    if not all_pts:
        return img
    min_x = min(x for x, _ in all_pts)
    max_x = max(x for x, _ in all_pts)
    min_y = min(y for _, y in all_pts)
    max_y = max(y for _, y in all_pts)
    bw = max(max_x - min_x, 1e-6)
    bh = max(max_y - min_y, 1e-6)
    # 0–1 px запас, чтобы антиалиас не обрезался
    pad = 1.0
    scale = min((size - 2 * pad) / bw, (size - 2 * pad) / bh)
    ox = (size - bw * scale) / 2 - min_x * scale
    oy = (size - bh * scale) / 2 - min_y * scale

    def _map(pt: tuple[float, float]) -> tuple[float, float]:
        return (pt[0] * scale + ox, pt[1] * scale + oy)

    for fill, pts in paths:
        scaled = [_map(p) for p in pts]
        if fill in {"white", "#ffffff"}:
            color = arrow_bright
        elif fill == "#d6d5d2":
            color = arrow_dim
        else:
            color = _CUBE_FILLS.get(fill, (100, 100, 100, 255))
        draw.polygon(scaled, fill=color)

    return img
