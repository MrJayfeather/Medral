import math

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import QEvent, QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QRadialGradient

# Violet range the blobs cycle through (design system v2)
_PALETTE = [QColor("#6C63FF"), QColor("#A78BFA"), QColor("#4c46b8")]

_TICK_MS = 33
_TICK_S = _TICK_MS / 1000.0


def _lerp_hsv(c1: QColor, c2: QColor, t: float) -> QColor:
    """Interpolate two colors in HSV space (shortest hue path)."""
    h1, s1, v1 = c1.hueF(), c1.saturationF(), c1.valueF()
    h2, s2, v2 = c2.hueF(), c2.saturationF(), c2.valueF()
    # hueF() is -1 for achromatic colors — borrow the other hue
    if h1 < 0.0:
        h1 = h2 if h2 >= 0.0 else 0.0
    if h2 < 0.0:
        h2 = h1
    d = h2 - h1
    if d > 0.5:
        d -= 1.0
    elif d < -0.5:
        d += 1.0
    return QColor.fromHsvF(
        (h1 + d * t) % 1.0,
        s1 + (s2 - s1) * t,
        v1 + (v2 - v1) * t,
    )


class BackgroundWidget(QWidget):
    """Aurora backdrop: large soft radial blots drifting on slow (8-12 s)
    sinusoid cycles, each smoothly cycling its hue through the violet
    palette.  Rendered behind all content; animation stops while the
    window is minimized or hidden.
    """

    # cx, cy, ax, ay, phx, phy, drift periods x/y (s), r_frac, alpha,
    # color phase offset, full palette loop period (s)
    _CFG = [
        (0.18, 0.28, 0.10, 0.07, 0.00, 1.00,  9.0, 12.0, 0.55, 34, 0.0, 26.0),
        (0.78, 0.62, 0.08, 0.11, 2.09, 0.50, 12.0,  8.5, 0.62, 26, 1.0, 34.0),
        (0.48, 0.88, 0.12, 0.06, 4.19, 3.00,  8.0, 11.0, 0.48, 22, 2.0, 30.0),
        (0.32, 0.50, 0.07, 0.10, 1.05, 4.20, 11.0,  9.5, 0.42, 24, 1.5, 38.0),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        self._orbs = [
            {"cx": c[0], "cy": c[1], "ax": c[2], "ay": c[3],
             "px": c[4], "py": c[5],
             "sx": 2 * math.pi * _TICK_S / c[6],
             "sy": 2 * math.pi * _TICK_S / c[7],
             "r": c[8], "alpha": c[9],
             "cp": c[10],
             "cs": len(_PALETTE) * _TICK_S / c[11]}
            for c in self._CFG
        ]

        self._watched = None   # top-level window we listen to for minimize

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ── pause while nothing is on screen ──────────────────────────────────

    def showEvent(self, event) -> None:
        super().showEvent(event)
        win = self.window()
        if win is not None and win is not self._watched:
            if self._watched is not None:
                self._watched.removeEventFilter(self)
            self._watched = win
            win.installEventFilter(self)
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == QEvent.Type.WindowStateChange and obj is self._watched:
            try:
                if obj.isMinimized():
                    self._timer.stop()
                elif self.isVisible() and not self._timer.isActive():
                    self._timer.start()
            except RuntimeError:
                pass
        return False

    # ── animation ─────────────────────────────────────────────────────────

    def _tick(self) -> None:
        win = self.window()
        if win is not None and win.isMinimized():
            self._timer.stop()   # eventFilter restarts it on restore
            return
        n = len(_PALETTE)
        for o in self._orbs:
            o["px"] += o["sx"]
            o["py"] += o["sy"]
            o["cp"] = (o["cp"] + o["cs"]) % n
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        dim = min(w, h)
        n = len(_PALETTE)

        for o in self._orbs:
            x = (o["cx"] + math.sin(o["px"]) * o["ax"]) * w
            y = (o["cy"] + math.sin(o["py"]) * o["ay"]) * h
            r = o["r"] * dim

            i = int(o["cp"]) % n
            col = _lerp_hsv(_PALETTE[i], _PALETTE[(i + 1) % n],
                            o["cp"] - int(o["cp"]))

            core = QColor(col)
            core.setAlpha(o["alpha"])
            mid = QColor(col)
            mid.setAlpha(int(o["alpha"] * 0.45))
            edge = QColor(col)
            edge.setAlpha(0)

            grad = QRadialGradient(x, y, r)
            grad.setColorAt(0.0, core)
            grad.setColorAt(0.55, mid)
            grad.setColorAt(1.0, edge)

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawEllipse(QPointF(x, y), r, r)

        p.end()
