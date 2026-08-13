from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QSizePolicy


class ElideLabel(QLabel):
    """QLabel that elides its text to fit the available width.

    Unlike a plain QLabel, it never forces the parent layout to grow:
    horizontal size policy is Ignored (minimum width 0), so the label
    shrinks with the window and the text is re-elided on every resize.
    The full text is kept and exposed via the tooltip.
    """

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        if text:
            self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 — Qt naming
        self._full = str(text)
        self.setToolTip(self._full)
        self._update_elide()

    def fullText(self) -> str:  # noqa: N802 — Qt naming
        return self._full

    def resizeEvent(self, ev) -> None:  # noqa: N802 — Qt naming
        super().resizeEvent(ev)
        self._update_elide()

    def _update_elide(self) -> None:
        width = max(0, self.contentsRect().width())
        elided = self.fontMetrics().elidedText(
            self._full, Qt.TextElideMode.ElideRight, width
        )
        super().setText(elided)
