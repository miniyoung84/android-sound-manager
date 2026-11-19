"""Generate the app icon (src/soundmanager/assets/icon.ico + icon.png).

Run from the repo root:  .venv\\Scripts\\python scripts\\make_icon.py
Each size is drawn separately so the small sizes stay crisp.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter

ASSETS = Path(__file__).resolve().parent.parent / "src" / "soundmanager" / "assets"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Rounded-square background with a diagonal gradient.
    margin = size * 0.04
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor("#6D5DF6"))
    grad.setColorAt(1.0, QColor("#22B8CF"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(rect, size * 0.22, size * 0.22)

    # White waveform bars; fewer, fatter bars at tiny sizes.
    heights = [0.45, 0.8, 0.55] if size <= 24 else [0.3, 0.55, 0.85, 0.6, 1.0, 0.5, 0.28]
    n = len(heights)
    area_w = size * (0.56 if size <= 24 else 0.64)
    bar_w = area_w / (n * 1.6 - 0.6)
    gap = bar_w * 0.6
    max_h = size * 0.56
    x = (size - area_w) / 2
    p.setBrush(QColor("white"))
    for h in heights:
        bh = max(bar_w, max_h * h)
        p.drawRoundedRect(QRectF(x, (size - bh) / 2, bar_w, bh), bar_w / 2, bar_w / 2)
        x += bar_w + gap
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def write_ico(path: Path, images: list[tuple[int, bytes]]) -> None:
    """Multi-resolution .ico with PNG-compressed entries (supported since Windows Vista)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    path.write_bytes(header + entries + blobs)


def main() -> int:
    QGuiApplication(sys.argv)
    ASSETS.mkdir(parents=True, exist_ok=True)
    images = [(s, png_bytes(render(s))) for s in SIZES]
    write_ico(ASSETS / "icon.ico", images)
    (ASSETS / "icon.png").write_bytes(images[-1][1])
    print(f"Wrote {ASSETS / 'icon.ico'} and icon.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
