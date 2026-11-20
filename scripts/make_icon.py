"""Generate the desktop app icon from the brand artwork (branding/bakery_logo.svg).

Writes src/soundmanager/assets/icon.ico (multi-size) and icon.png.
Run from the repo root:  .venv\\Scripts\\python scripts\\make_icon.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "branding" / "bakery_logo.svg"
ASSETS = ROOT / "src" / "soundmanager" / "assets"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def render(renderer: QSvgRenderer, size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(p, QRectF(0, 0, size, size))
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
    renderer = QSvgRenderer(str(SOURCE))
    if not renderer.isValid():
        print(f"Invalid SVG: {SOURCE}", file=sys.stderr)
        return 1
    ASSETS.mkdir(parents=True, exist_ok=True)
    images = [(s, png_bytes(render(renderer, s))) for s in SIZES]
    write_ico(ASSETS / "icon.ico", images)
    (ASSETS / "icon.png").write_bytes(images[-1][1])
    print(f"Wrote {ASSETS / 'icon.ico'} and icon.png from {SOURCE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
