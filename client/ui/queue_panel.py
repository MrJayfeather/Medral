from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QAbstractItemView,
    QPushButton, QMenu, QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QPoint
from PyQt6.QtGui import QAction


class QueuePanel(QWidget):
    remove_requested = pyqtSignal(int)       # index in queue
    move_requested   = pyqtSignal(int, int)  # from_index, to_index

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tracks:   list[dict] = []
        self._no_signal = False     # guard against recursive rowsMoved
        self._build_ui()

    # ── layout ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # header row
        hdr = QHBoxLayout()
        title = QLabel("QUEUE")
        title.setObjectName("sectionTitle")
        self._count = QLabel("")
        self._count.setStyleSheet("color:#7d8590; font-size:11px;")
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(self._count)
        root.addLayout(hdr)

        # list
        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        self._list.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._list.setSpacing(1)

        # detect internal-move drag-drop via model signal
        self._list.model().rowsMoved.connect(self._on_rows_moved)

        root.addWidget(self._list, 1)

    # ── public ────────────────────────────────────────────────────────────

    def update_state(self, state: dict) -> None:
        self._tracks = list(state.get("queue", []))
        self._rebuild()
        n = len(self._tracks)
        self._count.setText(f"{n} track{'s' if n != 1 else ''}" if n else "")

    # ── private ───────────────────────────────────────────────────────────

    def _rebuild(self) -> None:
        """Full list rebuild from self._tracks (preserves selection row)."""
        self._no_signal = True
        sel = self._list.currentRow()
        self._list.clear()

        for i, track in enumerate(self._tracks):
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 54))
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._list.addItem(item)

            row = _QueueRow(i, track)
            row.remove_clicked.connect(self._on_remove)
            self._list.setItemWidget(item, row)

        if 0 <= sel < self._list.count():
            self._list.setCurrentRow(sel)

        self._no_signal = False

    def _on_rows_moved(
        self,
        _src_parent, src_start: int, src_end: int,
        _dst_parent, dst_row: int,
    ) -> None:
        if self._no_signal:
            return
        from_idx = src_start
        # Qt inserts before dst_row, so if moving down the effective index is dst_row-1
        to_idx = (dst_row - 1) if dst_row > src_start else dst_row
        if from_idx == to_idx:
            return
        # Optimistic local reorder so widgets don't flicker while waiting for WS
        track = self._tracks.pop(from_idx)
        self._tracks.insert(to_idx, track)
        self._rebuild()
        self.move_requested.emit(from_idx, to_idx)

    def _on_remove(self, index: int) -> None:
        self.remove_requested.emit(index)

    def _context_menu(self, pos: QPoint) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        row = self._list.row(item)
        menu = QMenu(self)
        act_remove = menu.addAction("Remove from queue")
        act_up     = menu.addAction("Move up")
        act_down   = menu.addAction("Move down")

        act_up.setEnabled(row > 0)
        act_down.setEnabled(row < self._list.count() - 1)

        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen == act_remove:
            self.remove_requested.emit(row)
        elif chosen == act_up and row > 0:
            self.move_requested.emit(row, row - 1)
        elif chosen == act_down and row < self._list.count() - 1:
            self.move_requested.emit(row, row + 1)


# ── individual row widget ──────────────────────────────────────────────────

class _QueueRow(QWidget):
    remove_clicked = pyqtSignal(int)  # index

    def __init__(self, index: int, track: dict, parent=None) -> None:
        super().__init__(parent)
        self._idx = index

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 8, 0)
        lay.setSpacing(10)

        # index number
        num = QLabel(str(index + 1))
        num.setFixedWidth(22)
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num.setStyleSheet("color:#7d8590; font-size:11px;")
        lay.addWidget(num)

        # title + artist
        info = QVBoxLayout()
        info.setSpacing(2)

        title  = track.get("title",  "Unknown")
        artist = track.get("artist", "")
        dur    = int(track.get("duration") or 0)
        m, s   = divmod(dur, 60)

        t_lbl = QLabel(_elide(title, 52))
        t_lbl.setStyleSheet("font-size:13px; font-weight:500; color:#e6edf3;")
        t_lbl.setToolTip(title)
        info.addWidget(t_lbl)

        sub = QLabel(f"{_elide(artist, 30)}  •  {m}:{s:02d}")
        sub.setStyleSheet("font-size:11px; color:#7d8590;")
        info.addWidget(sub)

        lay.addLayout(info, 1)

        # remove button
        rm = QPushButton("✕")
        rm.setFixedSize(22, 22)
        rm.setStyleSheet(
            "QPushButton { background:transparent; color:#7d8590; border:none;"
            "              font-size:11px; border-radius:11px; }"
            "QPushButton:hover { color:#f85149; background:rgba(248,81,73,0.12); }"
        )
        rm.clicked.connect(lambda: self.remove_clicked.emit(self._idx))
        lay.addWidget(rm)


def _elide(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"
