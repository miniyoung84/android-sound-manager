"""Generate the brand artwork from one set of shapes.

The logo is a two-tier strawberry cake whose candles rise and fall like a sound wave. This
writes the master SVG (branding/bakery_logo.svg) and the Android vector drawables, so every
copy of the logo stays identical. Then run scripts/make_icon.py for the desktop icon.

Run from the repo root:  .venv\\Scripts\\python scripts\\make_brand.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAWABLE = ROOT / "android" / "app" / "src" / "main" / "res" / "drawable"

BACKGROUND = ("#FFE9C9", "#F2B676")  # cream to caramel, top-left to bottom-right
LAUNCHER_SCALE = 0.86  # keeps the art inside the adaptive-icon safe zone (66 of 108 dp)


@dataclass(frozen=True)
class Gradient:
    y1: float
    y2: float
    top: str
    bottom: str


@dataclass(frozen=True)
class Shape:
    d: str
    fill: str | Gradient
    alpha: float = 1.0
    comment: str = ""


def ellipse(cx: float, cy: float, rx: float, ry: float) -> str:
    return f"M{cx - rx},{cy}a{rx},{ry} 0,1 0,{2 * rx},0a{rx},{ry} 0,1 0,{-2 * rx},0z"


def drip(x: float, y: float, h: float, w: float = 5.0) -> str:
    """Flat-topped drip with a round end."""
    r = w / 2
    return f"M{x},{y}h{w}v{h - r}a{r},{r} 0,0 1,{-w},0z"


def candle(cx: float, base: float, h: float, w: float = 3.6) -> str:
    r = 1.2
    return (
        f"M{cx - w / 2},{base}v{-(h - r)}a{r},{r} 0,0 1,{r},{-r}"
        f"h{w - 2 * r}a{r},{r} 0,0 1,{r},{r}v{h - r}z"
    )


def flame(cx: float, base: float, h: float, w: float) -> str:
    return (
        f"M{cx},{base - h}C{cx + w * 0.6},{base - h * 0.5} {cx + w * 0.55},{base} {cx},{base}"
        f"C{cx - w * 0.55},{base} {cx - w * 0.6},{base - h * 0.5} {cx},{base - h}z"
    )


SPONGE = ("#FCE7CC", "#EEBF8B")
FROSTING = ("#F8B3C1", "#E9859B")
CANDLE = "#D65A78"
CANDLE_X = (42, 48, 54, 60, 66)
CANDLE_H = (7, 12, 16, 11, 7)  # the sound wave
CANDLE_BASE = 40

SHAPES = [
    Shape(ellipse(54, 80, 29, 3), "#8A4A1C", 0.22, "shadow"),
    Shape(ellipse(54, 77.5, 32, 3.6), "#FFFAF2", 1.0, "plate"),
    Shape(
        "M25,58h58v15a4,4 0,0 1,-4 4h-50a4,4 0,0 1,-4 -4z",
        Gradient(58, 77, *SPONGE),
        comment="bottom tier",
    ),
    Shape("M25,67h58v2.4h-58z", "#E27C93", comment="jam filling"),
    Shape(
        "M25,58a4,4 0,0 1,4 -4h50a4,4 0,0 1,4 4v3h-58z",
        Gradient(54, 61, *FROSTING),
        comment="bottom frosting",
    ),
    Shape(
        drip(29, 59, 7) + drip(39.5, 59, 10) + drip(52, 59, 6) + drip(63, 59, 9) + drip(74, 59, 6),
        FROSTING[1],
        comment="drips",
    ),
    Shape("M35,44h38v10h-38z", Gradient(44, 54, *SPONGE), comment="top tier"),
    Shape(
        "M35,43.5a3.5,3.5 0,0 1,3.5 -3.5h31a3.5,3.5 0,0 1,3.5 3.5v3h-38z",
        Gradient(40, 46.5, *FROSTING),
        comment="top frosting",
    ),
    Shape(
        drip(38, 45, 6) + drip(48, 45, 8) + drip(58.5, 45, 5) + drip(66, 45, 7),
        FROSTING[1],
        comment="drips",
    ),
    Shape(
        "M30,55.6h16a0.9,0.9 0,0 1,0 1.8h-16a0.9,0.9 0,0 1,0 -1.8z"
        "M39,41.5h12a0.8,0.8 0,0 1,0 1.6h-12a0.8,0.8 0,0 1,0 -1.6z",
        "#FFFFFF",
        0.45,
        "frosting shine",
    ),
    Shape(
        "".join(candle(x, CANDLE_BASE, h) for x, h in zip(CANDLE_X, CANDLE_H, strict=True)),
        CANDLE,
        comment="candles = sound wave",
    ),
    Shape(
        "".join(
            flame(x, CANDLE_BASE - h - 1.2, 5.2, 3.8)
            for x, h in zip(CANDLE_X, CANDLE_H, strict=True)
        ),
        "#FFB547",
        comment="flames",
    ),
    Shape(
        "".join(
            flame(x, CANDLE_BASE - h - 1.4, 2.6, 2.0)
            for x, h in zip(CANDLE_X, CANDLE_H, strict=True)
        ),
        "#FFF1C2",
        comment="flame cores",
    ),
]

# Single-colour version for Android's themed icons: tiers, candles and flames as one shape.
MONOCHROME = (
    "M25,58a4,4 0,0 1,4 -4h50a4,4 0,0 1,4 4v15a4,4 0,0 1,-4 4h-50a4,4 0,0 1,-4 -4z"
    "M25,66h58v2.4h-58z"  # jam line, cut out (even-odd)
    "M35,43.5a3.5,3.5 0,0 1,3.5 -3.5h31a3.5,3.5 0,0 1,3.5 3.5v9h-38z"
    + "".join(
        candle(x, CANDLE_BASE - 1.5, h - 1.5) for x, h in zip(CANDLE_X, CANDLE_H, strict=True)
    )
    + "".join(
        flame(x, CANDLE_BASE - h - 1.2, 5.2, 3.8) for x, h in zip(CANDLE_X, CANDLE_H, strict=True)
    )
)

ROUNDED_BG = (
    "M24,0h60a24,24 0,0 1,24 24v60a24,24 0,0 1,-24 24h-60"
    "a24,24 0,0 1,-24 -24v-60a24,24 0,0 1,24 -24z"
)


def tidy(d: str) -> str:
    """Round float noise (2.2800000000000002 -> 2.28) in path data."""
    return re.sub(r"-?\d+\.\d{4,}", lambda m: f"{round(float(m.group()), 3):g}", d)


def argb(color: str) -> str:
    return "#FF" + color.lstrip("#").upper()


# ----------------------------------------------------------------------------- SVG


def svg() -> str:
    defs, body = [], []
    for i, s in enumerate(SHAPES):
        fill = s.fill
        if isinstance(fill, Gradient):
            gid = f"g{i}"
            defs.append(
                f'    <linearGradient id="{gid}" gradientUnits="userSpaceOnUse" '
                f'x1="0" y1="{fill.y1}" '
                f'x2="0" y2="{fill.y2}">\n'
                f'      <stop offset="0" stop-color="{fill.top}"/>\n'
                f'      <stop offset="1" stop-color="{fill.bottom}"/>\n'
                "    </linearGradient>"
            )
            fill = f"url(#{gid})"
        opacity = f' fill-opacity="{s.alpha}"' if s.alpha < 1 else ""
        body.append(f'  <!-- {s.comment} -->\n  <path d="{tidy(s.d)}" fill="{fill}"{opacity}/>')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 108 108">\n'
        "  <!-- Sound Manager by The Bakery: a strawberry cake whose candles rise and fall like a\n"
        "       sound wave. Generated by scripts/make_brand.py; edit the shapes there. -->\n"
        "  <defs>\n"
        '    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">\n'
        f'      <stop offset="0" stop-color="{BACKGROUND[0]}"/>\n'
        f'      <stop offset="1" stop-color="{BACKGROUND[1]}"/>\n'
        "    </linearGradient>\n" + "\n".join(defs) + "\n  </defs>\n"
        '  <rect id="background" width="108" height="108" rx="24" fill="url(#bg)"/>\n'
        + "\n".join(body)
        + "\n</svg>\n"
    )


# ----------------------------------------------------------------------------- Android

HEADER = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    "<!-- {note} Generated by scripts/make_brand.py. -->\n"
    '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
    '    xmlns:aapt="http://schemas.android.com/aapt"\n'
    '    android:width="108dp"\n'
    '    android:height="108dp"\n'
    '    android:viewportWidth="108"\n'
    '    android:viewportHeight="108">\n'
)


def vector_path(
    d: str, fill: str | Gradient, alpha: float = 1.0, indent: str = "    ", even_odd=False
) -> str:
    attrs = f'{indent}<path\n{indent}    android:pathData="{tidy(d)}"'
    if even_odd:
        attrs += f'\n{indent}    android:fillType="evenOdd"'
    if alpha < 1:
        attrs += f'\n{indent}    android:fillAlpha="{alpha}"'
    if isinstance(fill, Gradient):
        return (
            f"{attrs}>\n"
            f'{indent}    <aapt:attr name="android:fillColor">\n'
            f'{indent}        <gradient android:type="linear" android:startX="0" '
            f'android:startY="{fill.y1}" android:endX="0" android:endY="{fill.y2}">\n'
            f'{indent}            <item android:offset="0" android:color="{argb(fill.top)}" />\n'
            f'{indent}            <item android:offset="1" android:color="{argb(fill.bottom)}" />\n'
            f"{indent}        </gradient>\n"
            f"{indent}    </aapt:attr>\n"
            f"{indent}</path>\n"
        )
    return f'{attrs}\n{indent}    android:fillColor="{argb(fill)}" />\n'


def group(content: str, scale: float) -> str:
    return (
        f'    <group android:pivotX="54" android:pivotY="54" android:scaleX="{scale}" '
        f'android:scaleY="{scale}">\n{content}    </group>\n'
    )


def art(indent: str = "        ") -> str:
    return "".join(vector_path(s.d, s.fill, s.alpha, indent) for s in SHAPES)


def background_gradient() -> str:
    return (
        f'    <path android:pathData="{ROUNDED_BG}">\n'
        '        <aapt:attr name="android:fillColor">\n'
        '            <gradient android:type="linear" android:startX="0" android:startY="0" '
        'android:endX="108" android:endY="108">\n'
        f'                <item android:offset="0" android:color="{argb(BACKGROUND[0])}" />\n'
        f'                <item android:offset="1" android:color="{argb(BACKGROUND[1])}" />\n'
        "            </gradient>\n"
        "        </aapt:attr>\n"
        "    </path>\n"
    )


def main() -> int:
    outputs = {
        ROOT / "branding" / "bakery_logo.svg": svg(),
        DRAWABLE / "ic_launcher_foreground.xml": HEADER.format(
            note="Launcher icon art, scaled into the adaptive-icon safe zone."
        )
        + group(art(), LAUNCHER_SCALE)
        + "</vector>\n",
        DRAWABLE / "ic_launcher_monochrome.xml": HEADER.format(
            note="Single-colour cake for Android's themed icons."
        )
        + group(
            vector_path(MONOCHROME, "#FFFFFF", indent="        ", even_odd=True), LAUNCHER_SCALE
        )
        + "</vector>\n",
        DRAWABLE / "bakery_logo.xml": HEADER.format(note="In-app logo: the full rounded icon.")
        + background_gradient()
        + art("    ")
        + "</vector>\n",
    }
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"Wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
