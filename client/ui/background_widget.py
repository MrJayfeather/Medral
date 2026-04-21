import math
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import QTimer, Qt, QPointF
from PyQt6.QtGui import QPainter, QRadialGradient, QColor


class BackgroundWidget(QWidget):
    """Slowly drifting purple orbs — rendered behind all content."""

    _CFG = [
        # cx, cy, ax, ay, px, py, sx, sy, r_frac, rgba
        (0.20, 0.30, 0.14, 0.10, 0.00, 1.00, 0.0006, 0.0004, 0.38, (108, 99, 255, 38)),
        (0.75, 0.65, 0.12, 0.16, 2.09, 0.50, 0.0004, 0.0006, 0.44, (167, 139, 250, 26)),
        (0.50, 0.85, 0.18, 0.08, 4.19, 3.00, 0.0007, 0.0005, 0.28, (108, 99, 255, 20)),
        (0.30, 0.50, 0.10, 0.14, 1.05, 4.20, 0.0005, 0.0003, 0.24, (167, 139, 250, 22)),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        self._orbs = [
            {"cx": c[0], "cy": c[1], "ax": c[2], "ay": c[3],
             "px": c[4], "py": c[5], "sx": c[6], "sy": c[7],
             "r": c[8], "rgba": c[9]}
            for c in self._CFG
        ]

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        for o in self._orbs:
            o["px"] += o["sx"]
            o["py"] += o["sy"]
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        dim = min(w, h)

        for o in self._orbs:
            x = (o["cx"] + math.sin(o["px"]) * o["ax"]) * w
            y = (o["cy"] + math.sin(o["py"]) * o["ay"]) * h
            r = o["r"] * dim

            rgba = o["rgba"]
            grad = QRadialGradient(x, y, r)
            grad.setColorAt(0.0, QColor(rgba[0], rgba[1], rgba[2], rgba[3]))
            grad.setColorAt(1.0, QColor(rgba[0], rgba[1], rgba[2], 0))

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawEllipse(QPointF(x, y), r, r)

        p.end()
