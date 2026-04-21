import math
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QPointF, QRect
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QLinearGradient


class SplashScreen(QWidget):
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

        self._phase    = 0.0
        self._progress = 0.0
        self._alpha    = 255
        self._fading   = False

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        QTimer.singleShot(2000, self._start_fade)

    def _center(self) -> None:
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        self.move(
            geo.x() + (geo.width()  - self.width())  // 2,
            geo.y() + (geo.height() - self.height()) // 2,
        )

    def _start_fade(self) -> None:
        self._fading = True

    def _tick(self) -> None:
        self._phase = (self._phase + 0.025) % (math.pi * 200)
        if self._progress < 1.0:
            self._progress = min(1.0, self._progress + 0.006)
        if self._fading:
            self._alpha = max(0, self._alpha - 10)
            if self._alpha == 0:
                self._timer.stop()
                self.closed.emit()
                self.close()
                return
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2 - 18

        # Card background
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(14, 14, 26, self._alpha))
        p.drawRoundedRect(0, 0, w, h, 24, 24)

        # Subtle border glow
        pen = QPen(QColor(108, 99, 255, int(40 * self._alpha / 255)))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, w - 2, h - 2, 23, 23)

        # Pulsing rings
        for i in range(3):
            phase = self._phase + i * 2.09
            base_r = 62 + i * 28
            r = base_r + math.sin(phase) * 9
            alpha = int((78 - i * 22) * self._alpha / 255)
            ring_pen = QPen(QColor(108, 99, 255, alpha))
            ring_pen.setWidthF(1.5)
            p.setPen(ring_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)

        # Logo text
        font = QFont()
        font.setFamilies(["Syne", "Segoe UI", "SF Pro Display"])
        font.setPointSize(34)
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 5)
        p.setFont(font)
        p.setPen(QColor(232, 232, 245, self._alpha))
        logo_rect = QRect(0, int(cy) - 26, w, 52)
        p.drawText(logo_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, "MEDRAL")

        # Subtitle
        sub = QFont()
        sub.setFamilies(["DM Sans", "Segoe UI"])
        sub.setPointSize(10)
        p.setFont(sub)
        p.setPen(QColor(107, 107, 138, int(self._alpha * 0.8)))
        sub_rect = QRect(0, int(cy) + 34, w, 22)
        p.drawText(sub_rect, Qt.AlignmentFlag.AlignHCenter, "music for everyone")

        # Loading bar track
        bar_w, bar_h = 200, 3
        bar_x = (w - bar_w) // 2
        bar_y = h - 42
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(42, 42, 64, min(self._alpha, 140)))
        p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 2, 2)

        # Loading bar fill
        fill = int(bar_w * self._progress)
        if fill > 0:
            grad = QLinearGradient(bar_x, 0, bar_x + bar_w, 0)
            grad.setColorAt(0.0, QColor(108, 99, 255, self._alpha))
            grad.setColorAt(1.0, QColor(167, 139, 250, self._alpha))
            p.setBrush(grad)
            p.drawRoundedRect(bar_x, bar_y, fill, bar_h, 2, 2)

        p.end()
