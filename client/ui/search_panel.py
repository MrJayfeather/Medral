from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QLabel, QFrame, QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QKeyEvent


class SearchPanel(QWidget):
    """Search bar + collapsible top-5 results panel."""

    # emitted when user wants to search (show results)
    search_submitted = pyqtSignal(str)
    # emitted when user picks a result to play (webpage_url)
    play_requested   = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ── layout ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # ── search bar row ──
        bar = QHBoxLayout()
        bar.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "Search YouTube — song name, artist, or paste a URL…"
        )
        self._input.returnPressed.connect(self._on_submit)
        bar.addWidget(self._input, 1)

        self._btn = QPushButton("Search")
        self._btn.setObjectName("searchBtn")
        self._btn.setFixedWidth(88)
        self._btn.clicked.connect(self._on_submit)
        bar.addWidget(self._btn)

        root.addLayout(bar)

        # ── results area (hidden until results arrive) ──
        self._results_widget = QWidget()
        self._results_widget.setVisible(False)
        r_lay = QVBoxLayout(self._results_widget)
        r_lay.setContentsMargins(0, 2, 0, 0)
        r_lay.setSpacing(4)

        self._result_rows: list[_ResultRow] = []
        for _ in range(5):
            row = _ResultRow()
            row.play_clicked.connect(self._on_result_play)
            row.setVisible(False)
            r_lay.addWidget(row)
            self._result_rows.append(row)

        root.addWidget(self._results_widget)

    # ── public ────────────────────────────────────────────────────────────

    def show_results(self, tracks: list[dict]) -> None:
        has = bool(tracks)
        self._results_widget.setVisible(has)
        for i, row in enumerate(self._result_rows):
            if i < len(tracks):
                row.set_track(tracks[i])
                row.setVisible(True)
            else:
                row.setVisible(False)

    def clear(self) -> None:
        self._input.clear()
        self._results_widget.setVisible(False)

    # ── slots ─────────────────────────────────────────────────────────────

    def _on_submit(self) -> None:
        q = self._input.text().strip()
        if not q:
            return
        if q.startswith("http://") or q.startswith("https://"):
            self.play_requested.emit(q)
            self.clear()
        else:
            self.search_submitted.emit(q)

    def _on_result_play(self, url: str) -> None:
        self.play_requested.emit(url)
        self.clear()


# ── result row widget ──────────────────────────────────────────────────────

class _ResultRow(QFrame):
    play_clicked = pyqtSignal(str)  # webpage_url

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("searchResultRow")
        self._url = ""
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(12)

        # track info
        info = QVBoxLayout()
        info.setSpacing(2)

        self._title = QLabel()
        self._title.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #e6edf3;"
        )
        self._title.setMaximumWidth(500)
        info.addWidget(self._title)

        self._meta = QLabel()
        self._meta.setStyleSheet("font-size: 11px; color: #7d8590;")
        info.addWidget(self._meta)

        lay.addLayout(info, 1)

        # play button
        btn = QPushButton("▶")
        btn.setObjectName("resultPlayBtn")
        btn.setFixedSize(32, 32)
        btn.setToolTip("Add to queue")
        btn.clicked.connect(lambda: self.play_clicked.emit(self._url))
        lay.addWidget(btn)

    def set_track(self, track: dict) -> None:
        self._url   = track.get("webpage_url", "")
        title       = track.get("title",  "Unknown Title")
        artist      = track.get("artist", "Unknown Artist")
        dur         = int(track.get("duration") or 0)
        m, s        = divmod(dur, 60)

        self._title.setText(_elide(title, 60))
        self._title.setToolTip(title)
        self._meta.setText(f"{artist}  •  {m}:{s:02d}")


def _elide(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len - 1] + "…"
