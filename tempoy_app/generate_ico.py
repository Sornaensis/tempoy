"""Generate a Windows .ico file from the hourglass SVG icon."""
import os
import struct
import sys

def generate_ico(svg_path: str, ico_path: str) -> bool:
    """Render SVG to multiple sizes and write a Windows .ico file."""
    from PySide6.QtCore import QBuffer, QIODevice, QSize, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])

    renderer = QSvgRenderer(svg_path)
    if not renderer.isValid():
        return False

    sizes = [16, 24, 32, 48, 64, 128, 256]
    png_data = []

    for size in sizes:
        img = QImage(QSize(size, size), QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        renderer.render(painter)
        painter.end()

        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        png_data.append(bytes(buf.data()))

    # Write ICO: header + directory entries + PNG payloads
    with open(ico_path, "wb") as f:
        # ICONDIR header
        f.write(struct.pack("<HHH", 0, 1, len(sizes)))

        # ICONDIRENTRY table
        offset = 6 + 16 * len(sizes)
        for size, data in zip(sizes, png_data):
            dim = 0 if size >= 256 else size
            f.write(struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset))
            offset += len(data)

        # Image data
        for data in png_data:
            f.write(data)

    return True


if __name__ == "__main__":
    svg = os.path.join(os.path.dirname(__file__), "assets", "hourglass.svg")
    ico = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(svg), "hourglass.ico")
    if generate_ico(svg, ico):
        print(ico)
    else:
        sys.exit(1)
