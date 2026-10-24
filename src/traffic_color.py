# FILE: src/traffic_color.py
# PURPOSE: Плавный светофор green→yellow→red по % использования.
# WHY: Один алгоритм для status bar, иконки трея и UI.

from __future__ import annotations


def smooth_traffic_rgb(percent: float) -> tuple[int, int, int]:
    """0–50 green→yellow, 50–85 yellow→orange, 85–100 → red."""
    p = max(0.0, min(100.0, float(percent)))
    green = (34, 197, 94)
    yellow = (234, 179, 8)
    orange = (249, 115, 22)
    red = (239, 68, 68)

    def _lerp(
        a: tuple[int, int, int], b: tuple[int, int, int], t: float
    ) -> tuple[int, int, int]:
        t = max(0.0, min(1.0, t))
        return (
            int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t),
        )

    if p <= 50:
        return _lerp(green, yellow, p / 50.0)
    if p <= 85:
        return _lerp(yellow, orange, (p - 50.0) / 35.0)
    return _lerp(orange, red, (p - 85.0) / 15.0)


def smooth_traffic_hex(percent: float) -> str:
    r, g, b = smooth_traffic_rgb(percent)
    return f"#{r:02x}{g:02x}{b:02x}"
