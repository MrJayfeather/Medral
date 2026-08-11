"""Splash screen v2 — the "living wave".

A sound wave built from layered harmonics sweeps across a dark rounded
card (the sweep itself is the progress indicator); the MEDRAL letters pop
in one by one while sparks fly off the wave under each new letter, and
once the word is assembled the wave does a final splash before everything
fades out.

External API matches SplashScreen v1: frameless always-on-top window,
a `closed` signal, and self-closing after ~2.5 s with a fade.
"""

import math
import random

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QPointF
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter,
    QPainterPath, QPen,
)

_ACCENT = (108, 99, 255)    # #6C63FF
_LIGHT  = (167, 139, 250)   # #A78BFA
_TEXT   = (232, 232, 245)   # #e8e8f5

_WORD         = "MEDRAL"
_LETTER_START = 0.20    # s — birth of the first letter
_LETTER_STEP  = 0.18    # s — stagger between letters
_LETTER_ANIM  = 0.25    # s — fade + rise duration per letter
_SPLASH_LEN   = 0.30    # s — final amplitude burst duration
_FADE_AT_MS   = 2000    # ms — when the final fade-out starts
_DT           = 0.016   # s — 60 FPS tick


def _out_cubic(p: float) -> float:
    """OutCubic easing clamped to [0, 1]."""
    p = max(0.0, min(1.0, p))
    return 1.0 - (1.0 - p) ** 3


class SplashScreenV2(QWidget):
    closed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(440, 340)
        self._center()

        self._t      = 0.0     # animation clock, seconds (tick-driven)
        self._alpha  = 255
        self._fading = False

        self._rnd    = random.Random(1337)
        self._phases = [self._rnd.uniform(0.0, math.tau) for _ in range(4)]

        # letter timeline + final splash right after the word is assembled
        self._births   = [_LETTER_START + i * _LETTER_STEP for i in range(len(_WORD))]
        self._spawned  = [False] * len(_WORD)
        self._splash_t = self._births[-1] + _LETTER_ANIM + 0.20

        # particles: [x, y, vx, vy, age, life, size, light_flag]
        self._particles: list = []

        # typography: Syne Bold 34 pt, letter-spacing 6
        self._font = QFont()
        self._font.setFamilies(["Syne", "Segoe UI", "SF Pro Display"])
        self._font.setPointSize(34)
        self._font.setBold(True)
        self._font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 6)

        # pre-computed letter layout (per-letter x, centers, baseline)
        fm = QFontMetrics(self._font)
        total = fm.horizontalAdvance(_WORD) - 6          # drop trailing spacing
        x0 = (self.width() - total) / 2.0
        self._letter_x  = [x0 + fm.horizontalAdvance(_WORD[:i])
                           for i in range(len(_WORD))]
        self._letter_cx = [self._letter_x[i] + fm.horizontalAdvance(_WORD[i]) / 2.0
                           for i in range(len(_WORD))]
        self._baseline = 148 + (fm.ascent() - fm.descent()) / 2.0
        self._wave_y0  = 226.0

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        QTimer.singleShot(_FADE_AT_MS, self._start_fade)

    def _center(self) -> None:
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        self.move(
            geo.x() + (geo.width()  - self.width())  // 2,
            geo.y() + (geo.height() - self.height()) // 2,
        )

    def _start_fade(self) -> None:
        self._fading = True

    # ── simulation ────────────────────────────────────────────────────────

    def _tick(self) -> None:
        self._t += _DT

        # sparks fly off the wave the moment each letter is born
        for i, birth in enumerate(self._births):
            if not self._spawned[i] and self._t >= birth:
                self._spawned[i] = True
                self._spawn_sparks(self._letter_cx[i])

        # particle physics: drift up, gentle pull back, die by age
        alive = []
        for pt in self._particles:
            pt[0] += pt[2] * _DT
            pt[1] += pt[3] * _DT
            pt[3] += 150.0 * _DT
            pt[4] += _DT
            if pt[4] < pt[5]:
                alive.append(pt)
        self._particles = alive

        if self._fading:
            self._alpha = max(0, self._alpha - 10)
            if self._alpha == 0:
                self._timer.stop()
                self.closed.emit()
                self.close()
                return
        self.update()

    def _spawn_sparks(self, x: float) -> None:
        """3-5 short-lived sparks shooting up from the wave below a letter."""
        rnd = self._rnd
        for _ in range(rnd.randint(3, 5)):
            if len(self._particles) >= 30:
                return
            self._particles.append([
                x + rnd.uniform(-8.0, 8.0),           # x
                self._wave_y0 + rnd.uniform(-4.0, 4.0),   # y
                rnd.uniform(-45.0, 45.0),             # vx
                rnd.uniform(-160.0, -80.0),           # vy (upwards)
                0.0,                                  # age
                rnd.uniform(0.35, 0.70),              # life
                rnd.uniform(1.6, 3.2),                # size
                float(rnd.random() < 0.5),            # light color flag
            ])

    def _wave(self, x: float) -> float:
        """Normalized wave height at card x: 3 harmonics + light shimmer."""
        u, t, ph = x * 0.018, self._t, self._phases
        v  = math.sin(u * 1.0 + t * 2.6 + ph[0]) * 0.55
        v += math.sin(u * 2.3 - t * 4.1 + ph[1]) * 0.27
        v += math.sin(u * 4.7 + t * 6.9 + ph[2]) * 0.13
        v += math.sin(u * 9.1 + t * 3.3 + ph[3]) * 0.05
        return v

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        a = self._alpha
        w, h = self.width(), self.height()

        # card background + thin accent border
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(14, 14, 26, a))
        p.drawRoundedRect(0, 0, w, h, 24, 24)
        pen = QPen(QColor(*_ACCENT, int(40 * a / 255)))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, w - 2, h - 2, 23, 23)

        self._paint_wave(p, a, w)
        self._paint_particles(p, a)
        self._paint_letters(p, a)
        p.end()

    def _paint_wave(self, p: QPainter, a: int, w: int) -> None:
        x0, x1 = 26.0, w - 26.0
        span = x1 - x0

        # the wave doubles as the progress bar: it sweeps left → right
        reveal = _out_cubic(self._t / 1.1)
        x_end = x0 + span * reveal
        if x_end - x0 < 8.0:
            return

        # amplitude: grows on intro, doubles at the peak of the final splash
        amp = 15.0 * _out_cubic(self._t / 0.9)
        sp = (self._t - self._splash_t) / _SPLASH_LEN
        if 0.0 <= sp <= 1.0:
            amp *= 1.0 + math.sin(math.pi * sp)

        # sample the wave into a path (~70 points), tapered at card edges
        path = QPainterPath()
        x, first = x0, True
        while True:
            frac = (x - x0) / span
            y = self._wave_y0 + self._wave(x) * amp * math.sin(math.pi * frac)
            if first:
                path.moveTo(x, y)
                first = False
            else:
                path.lineTo(x, y)
            if x >= x_end:
                break
            x = min(x + 6.0, x_end)

        grad = QLinearGradient(x0, 0.0, x1, 0.0)

        # pass 1 — wide translucent stroke: the glow
        grad.setColorAt(0.0, QColor(*_ACCENT, int(55 * a / 255)))
        grad.setColorAt(1.0, QColor(*_LIGHT, int(55 * a / 255)))
        pen = QPen(QBrush(grad), 8.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # pass 2 — thin bright core
        grad.setColorAt(0.0, QColor(*_ACCENT, int(235 * a / 255)))
        grad.setColorAt(1.0, QColor(*_LIGHT, int(235 * a / 255)))
        pen = QPen(QBrush(grad), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawPath(path)

        # glowing head dot while the sweep is still running
        if reveal < 1.0:
            frac = (x_end - x0) / span
            y = self._wave_y0 + self._wave(x_end) * amp * math.sin(math.pi * frac)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(*_LIGHT, int(70 * a / 255)))
            p.drawEllipse(QPointF(x_end, y), 7.0, 7.0)
            p.setBrush(QColor(*_LIGHT, a))
            p.drawEllipse(QPointF(x_end, y), 2.5, 2.5)

    def _paint_particles(self, p: QPainter, a: int) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, _vx, _vy, age, life, size, light in self._particles:
            fade = 1.0 - age / life
            col = _LIGHT if light else _ACCENT
            p.setBrush(QColor(*col, int(200 * fade * a / 255)))
            r = size * fade + 0.6
            p.drawEllipse(QPointF(x, y), r, r)

    def _paint_letters(self, p: QPainter, a: int) -> None:
        p.setFont(self._font)
        for i, ch in enumerate(_WORD):
            e = _out_cubic((self._t - self._births[i]) / _LETTER_ANIM)
            if e <= 0.0:
                continue
            p.setPen(QColor(*_TEXT, int(e * a)))
            dy = (1.0 - e) * 16.0   # rise into place
            p.drawText(QPointF(self._letter_x[i], self._baseline + dy), ch)
